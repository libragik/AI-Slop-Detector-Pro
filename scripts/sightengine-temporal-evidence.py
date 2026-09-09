#!/usr/bin/env python3
"""Research-only aggregation of local, normalized video sample evidence.

This module does not call a detector. Adjacent samples are correlated observations,
not independent corroboration. V1 is a prospectively fixed policy; changing its
constants requires a separately registered policy, not a CLI threshold override.
"""

import argparse
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path


DEFAULT_CONFIG = {
    "policyVersion": "sightengine-temporal-evidence-v1",
    "positionUnit": "seconds",
    "scoreThreshold": 0.5,
    "minimumPersistentSamples": 2,
    "maximumPositiveGapSeconds": 0.6,
    "declaredIntervalSeconds": 0.5,
    "coverage": {
        "firstFrameMaxSeconds": 0.1,
        "maximumGapSeconds": 0.6,
        "tailGapSeconds": 0.6,
    },
    "sequenceOrder": "received-order-no-sort-or-deduplication",
    "temporalInterpolation": False,
    "adjacentSamplesAreIndependent": False,
    "scoresAreCalibratedProbabilities": False,
    "insufficientForSubsecondExclusion": True,
}
_FIXED_CONFIG_JSON = json.dumps(DEFAULT_CONFIG, sort_keys=True, separators=(",", ":"))


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def policy_configuration(config=None):
    """Return a detached approved configuration and its canonical fingerprint."""
    serialized = canonical_json(json.loads(_FIXED_CONFIG_JSON) if config is None else config)
    if serialized != _FIXED_CONFIG_JSON:
        raise ValueError("Configuration differs from the fixed v1 research policy")
    return json.loads(serialized), hashlib.sha256(serialized.encode()).hexdigest()


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def decimal(value):
    return Decimal(str(value))


def aggregate_evidence(samples, *, duration_seconds, technical_complete,
                       declared_interval_seconds=None, config=None):
    """Aggregate received-order {positionSeconds, aiGenerated} observations.

    technical_complete must reflect successful transport, parsing and accounting
    by the caller. This component independently validates every sample and temporal
    coverage. An incomplete input can retain observations but cannot decide origin.
    """
    policy, fingerprint = policy_configuration(config)
    issues = []
    coverage_issues = []
    duration_valid = finite_number(duration_seconds) and duration_seconds > 0
    if not duration_valid:
        issues.append("duration_must_be_finite_and_positive")
    if technical_complete is not True:
        issues.append("caller_has_not_confirmed_technical_completion")
    interval_valid = (finite_number(declared_interval_seconds)
                      and declared_interval_seconds == policy["declaredIntervalSeconds"])
    if not interval_valid:
        issues.append("declared_sampling_interval_is_not_0.5_seconds")
    if not isinstance(samples, list):
        issues.append("samples_must_be_a_list")
        samples = []

    records = []
    for index, sample in enumerate(samples):
        problems = []
        position = sample.get("positionSeconds") if isinstance(sample, dict) else None
        score = sample.get("aiGenerated") if isinstance(sample, dict) else None
        if not isinstance(sample, dict):
            problems.append("sample_must_be_an_object")
        position_valid = (finite_number(position) and duration_valid
                          and 0 <= position < duration_seconds)
        score_valid = finite_number(score) and 0 <= score <= 1
        if not position_valid:
            problems.append("position_must_be_finite_and_in_video")
        if not score_valid:
            problems.append("score_must_be_finite_and_in_unit_interval")
        records.append({
            "index": index,
            "positionSeconds": position if finite_number(position) else None,
            "aiGenerated": score if finite_number(score) else None,
            "valid": position_valid and score_valid,
            "positive": score >= policy["scoreThreshold"] if position_valid and score_valid else None,
            "issues": problems,
        })
        if problems:
            issues.append(f"invalid_sample_at_index_{index}")

    # Invalid observations stay in this sequence and break a run. Never filter an
    # invalid/negative sample out and thereby join positives across it.
    candidates = []
    current = []
    for record in records:
        can_extend = (bool(current) and record["valid"] and record["positive"]
                      and current[-1]["index"] + 1 == record["index"]
                      and 0 < decimal(record["positionSeconds"]) - decimal(current[-1]["positionSeconds"])
                      <= decimal(policy["maximumPositiveGapSeconds"]))
        if current and not can_extend:
            candidates.append(current)
            current = []
        if record["valid"] and record["positive"]:
            current.append(record)
    if current:
        candidates.append(current)

    persistent = []
    isolated = []
    for run in candidates:
        if len(run) >= policy["minimumPersistentSamples"]:
            persistent.append({
                "sampleIndices": [sample["index"] for sample in run],
                "sampledPositionsSeconds": [sample["positionSeconds"] for sample in run],
                "sampleScores": [sample["aiGenerated"] for sample in run],
                "firstSampleSeconds": run[0]["positionSeconds"],
                "lastSampleSeconds": run[-1]["positionSeconds"],
                "extentMeaning": "sample_endpoints_only_not_a_continuous_AI_interval",
                "adjacentSamplesAreIndependent": False,
            })
        else:
            isolated.append({
                "sampleIndex": run[0]["index"],
                "positionSeconds": run[0]["positionSeconds"],
                "aiGenerated": run[0]["aiGenerated"],
                "status": "unresolved",
            })

    if not records:
        coverage_issues.append("no_samples")
    elif not all(record["valid"] for record in records):
        coverage_issues.append("invalid_samples_prevent_complete_coverage")
    if records and records[0]["valid"]:
        if decimal(records[0]["positionSeconds"]) > decimal(policy["coverage"]["firstFrameMaxSeconds"]):
            coverage_issues.append("initial_coverage_gap")
    if records and records[-1]["valid"] and duration_valid:
        if decimal(duration_seconds) - decimal(records[-1]["positionSeconds"]) > decimal(policy["coverage"]["tailGapSeconds"]):
            coverage_issues.append("terminal_coverage_gap")
    for previous, record in zip(records, records[1:]):
        if previous["valid"] and record["valid"]:
            gap = decimal(record["positionSeconds"]) - decimal(previous["positionSeconds"])
            if gap <= 0:
                coverage_issues.append(f"positions_not_strictly_increasing_at_index_{record['index']}")
            elif gap > decimal(policy["coverage"]["maximumGapSeconds"]):
                coverage_issues.append(f"coverage_gap_at_index_{record['index']}")

    complete = not issues and not coverage_issues
    if not complete:
        verdict = "inconclusive"
        reasons = ["Technical or sampling coverage requirements were not completed."]
    elif persistent:
        verdict = "persistent_ai_indicators"
        reasons = ["At least two consecutive positive sampled observations meet the fixed spacing rule."]
    elif isolated:
        verdict = "inconclusive"
        reasons = ["Isolated positive samples remain unresolved."]
    else:
        verdict = "no_clear_indicators"
        reasons = ["No positive samples were returned in the completed declared 2 Hz scan."]
    if isolated and "Isolated positive samples remain unresolved." not in reasons:
        reasons.append("Isolated positive samples remain unresolved.")
    reasons.append("Sampled evidence does not establish origin or exclude AI between samples, including subsecond inserts.")

    return {
        "schemaVersion": 1,
        "researchOnly": True,
        "configuration": policy,
        "policyFingerprint": fingerprint,
        "verdict": verdict,
        "reviewRequired": verdict == "inconclusive" or bool(isolated),
        "decisionReasons": reasons,
        "technicalComplete": complete,
        "callerTechnicalComplete": technical_complete is True,
        "technicalIssues": issues,
        "coverage": {
            "complete": complete,
            "durationSeconds": duration_seconds if duration_valid else None,
            "declaredIntervalSeconds": declared_interval_seconds if finite_number(declared_interval_seconds) else None,
            "issues": coverage_issues,
            "sampledPositionsSeconds": [record["positionSeconds"] for record in records if record["valid"]],
            "insufficientForSubsecondExclusion": True,
            "basis": "caller_declaration_and_returned_sample_positions_not_every_frame_inspection",
        },
        "persistentRuns": persistent,
        "isolatedAlerts": isolated,
        "sampleRecords": records,
        "notProofOfOrigin": True,
        "scoresAreCalibratedProbabilities": False,
        "adjacentSamplesAreIndependent": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Local JSON with samples, durationSeconds, technicalComplete, declaredIntervalSeconds")
    parser.add_argument("--output", type=Path, required=True, help="New local output file; never overwritten")
    args = parser.parse_args()
    data_bytes = args.input.read_bytes()
    data = json.loads(data_bytes, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Non-finite JSON constant: {value}")))
    if not isinstance(data, dict):
        raise ValueError("Input must be an object")
    result = aggregate_evidence(data.get("samples"), duration_seconds=data.get("durationSeconds"),
                                technical_complete=data.get("technicalComplete"),
                                declared_interval_seconds=data.get("declaredIntervalSeconds"),
                                config=data.get("configuration"))
    result["inputSha256"] = hashlib.sha256(data_bytes).hexdigest()
    result["aggregatorSha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8") as output:
        output.write(encoded)


if __name__ == "__main__":
    main()
