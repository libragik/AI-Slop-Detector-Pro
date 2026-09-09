#!/usr/bin/env python3
"""Synthetic contracts only: no detector calls or retained study predictions."""

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("sightengine-temporal-evidence.py")
SPEC = importlib.util.spec_from_file_location("temporal_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def samples(scores, positions=None):
    positions = [index / 2 for index in range(len(scores))] if positions is None else positions
    return [{"positionSeconds": position, "aiGenerated": score}
            for position, score in zip(positions, scores)]


def aggregate(records, duration=4, **changes):
    kwargs = {"duration_seconds": duration, "technical_complete": True,
              "declared_interval_seconds": 0.5}
    kwargs.update(changes)
    return MODULE.aggregate_evidence(records, **kwargs)


class EvidenceContracts(unittest.TestCase):
    def test_complete_no_hits_is_qualified_not_authentication(self):
        result = aggregate(samples([0] * 8))
        self.assertEqual(result["verdict"], "no_clear_indicators")
        self.assertTrue(result["coverage"]["complete"])
        self.assertTrue(result["coverage"]["insufficientForSubsecondExclusion"])
        self.assertTrue(result["notProofOfOrigin"])
        self.assertFalse(result["scoresAreCalibratedProbabilities"])
        self.assertIn("subsecond", " ".join(result["decisionReasons"]))

    def test_threshold_is_inclusive_and_preserves_score_bounds(self):
        result = aggregate(samples([0, 0.499999, 0.5, 1, 0, 0, 0, 0]))
        self.assertEqual(result["verdict"], "persistent_ai_indicators")
        self.assertEqual(result["persistentRuns"][0]["sampleIndices"], [2, 3])
        self.assertEqual(result["persistentRuns"][0]["sampleScores"], [0.5, 1])

    def test_isolated_positive_cannot_become_negative(self):
        result = aggregate(samples([0, 0, 1, 0, 0, 0, 0, 0]))
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertTrue(result["reviewRequired"])
        self.assertEqual(result["isolatedAlerts"][0]["status"], "unresolved")
        self.assertEqual(result["isolatedAlerts"][0]["positionSeconds"], 1)

    def test_persistent_and_isolated_are_both_retained(self):
        result = aggregate(samples([0, 1, 1, 0, 0, 1, 0, 0]))
        self.assertEqual(result["verdict"], "persistent_ai_indicators")
        self.assertEqual(result["persistentRuns"][0]["sampleIndices"], [1, 2])
        self.assertEqual(result["isolatedAlerts"][0]["sampleIndex"], 5)
        self.assertTrue(result["reviewRequired"])
        self.assertEqual(result["isolatedAlerts"][0]["status"], "unresolved")

    def test_disjoint_runs_are_never_merged(self):
        result = aggregate(samples([1, 1, 0, 1, 1, 1, 0, 0]))
        self.assertEqual([run["sampleIndices"] for run in result["persistentRuns"]], [[0, 1], [3, 4, 5]])
        self.assertEqual(result["persistentRuns"][1]["sampledPositionsSeconds"], [1.5, 2, 2.5])

    def test_negative_sample_breaks_run_without_interpolation(self):
        result = aggregate(samples([1, 0, 1], [0, 0.2, 0.4]), duration=0.8)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["persistentRuns"], [])
        self.assertEqual(len(result["isolatedAlerts"]), 2)

    def test_exact_gap_boundary_uses_decimal_positions(self):
        result = aggregate(samples([0, 1, 1, 0], [0, 0.6, 1.2, 1.8]), duration=2.4)
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(result["persistentRuns"][0]["sampledPositionsSeconds"], [0.6, 1.2])

    def test_gap_just_over_boundary_breaks_run_and_coverage(self):
        result = aggregate(samples([1, 1, 0], [0, 0.6000000001, 1]), duration=1.5)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["persistentRuns"], [])
        self.assertEqual(len(result["isolatedAlerts"]), 2)
        self.assertIn("coverage_gap_at_index_1", result["coverage"]["issues"])

    def test_zero_gap_cannot_corroborate_duplicate_observation(self):
        result = aggregate(samples([1, 1, 0], [0, 0, 0.5]), duration=1)
        self.assertEqual(result["persistentRuns"], [])
        self.assertEqual(len(result["isolatedAlerts"]), 2)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("positions_not_strictly_increasing_at_index_1", result["coverage"]["issues"])

    def test_reversed_positions_are_not_sorted_into_evidence(self):
        result = aggregate(samples([1, 1, 0], [0.5, 0, 0.8]), duration=1)
        self.assertEqual(result["persistentRuns"], [])
        self.assertEqual(result["coverage"]["sampledPositionsSeconds"], [0.5, 0, 0.8])
        self.assertEqual(result["verdict"], "inconclusive")

    def test_invalid_middle_record_is_not_filtered_then_joined(self):
        result = aggregate(samples([1, None, 1], [0, 0.2, 0.4]), duration=0.8)
        self.assertEqual(result["persistentRuns"], [])
        self.assertEqual([alert["sampleIndex"] for alert in result["isolatedAlerts"]], [0, 2])
        self.assertEqual(len(result["sampleRecords"]), 3)
        self.assertFalse(result["sampleRecords"][1]["valid"])

    def test_all_non_finite_out_of_range_boolean_or_missing_scores_abstain(self):
        for bad_score in [math.nan, math.inf, -math.inf, -0.01, 1.01, True, False, None, "0.99", {}, 10 ** 1000]:
            with self.subTest(score=str(bad_score)):
                result = aggregate(samples([bad_score] + [0] * 7))
                self.assertEqual(result["verdict"], "inconclusive")
                self.assertFalse(result["technicalComplete"])
                json.dumps(result, allow_nan=False)

    def test_non_finite_or_out_of_video_positions_abstain(self):
        for bad_position in [math.nan, math.inf, -math.inf, -0.1, 4, 4.1, True, None, "0", 10 ** 1000]:
            with self.subTest(position=str(bad_position)):
                records = samples([0] * 8)
                records[0]["positionSeconds"] = bad_position
                result = aggregate(records)
                self.assertEqual(result["verdict"], "inconclusive")
                json.dumps(result, allow_nan=False)

    def test_first_and_last_coverage_boundaries_inclusive(self):
        result = aggregate(samples([0] * 3, [0.1, 0.6, 1.1]), duration=1.7)
        self.assertEqual(result["verdict"], "no_clear_indicators")
        for positions, duration, issue in [([0.1000000001, 0.6, 1.1], 1.7, "initial_coverage_gap"),
                                           ([0.1, 0.6, 1.1], 1.7000000001, "terminal_coverage_gap")]:
            result = aggregate(samples([0] * 3, positions), duration=duration)
            self.assertEqual(result["verdict"], "inconclusive")
            self.assertIn(issue, result["coverage"]["issues"])

    def test_missing_interior_coverage_with_no_hits_cannot_be_negative(self):
        result = aggregate(samples([0] * 7, [0, 0.5, 1, 2, 2.5, 3, 3.5]))
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("coverage_gap_at_index_3", result["coverage"]["issues"])

    def test_partial_coverage_retains_supported_run_but_abstains(self):
        result = aggregate(samples([1, 1, 0], [1, 1.5, 2]))
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["persistentRuns"][0]["sampleIndices"], [0, 1])
        self.assertFalse(result["technicalComplete"])

    def test_caller_technical_failure_overrides_every_score_pattern(self):
        for scores in [[0] * 8, [1] * 8, [0, 0, 1, 0, 0, 0, 0, 0]]:
            for declaration in [False, None, 1, "true"]:
                with self.subTest(scores=scores, declaration=declaration):
                    result = aggregate(samples(scores), technical_complete=declaration)
                    self.assertEqual(result["verdict"], "inconclusive")
                    self.assertFalse(result["callerTechnicalComplete"])
        result = aggregate(samples([1] * 8), technical_complete=False)
        self.assertEqual(len(result["persistentRuns"][0]["sampleIndices"]), 8)

    def test_sampling_interval_is_an_explicit_required_declaration(self):
        for interval in [None, 0.1, 1, True, math.nan, "0.5"]:
            with self.subTest(interval=interval):
                result = aggregate(samples([0] * 8), declared_interval_seconds=interval)
                self.assertEqual(result["verdict"], "inconclusive")
                self.assertIn("declared_sampling_interval_is_not_0.5_seconds", result["technicalIssues"])

    def test_missing_or_empty_results_never_mean_negative(self):
        for records in [[], None, {}, ""]:
            with self.subTest(records=records):
                self.assertEqual(aggregate(records)["verdict"], "inconclusive")

    def test_duration_must_be_finite_positive_and_not_boolean(self):
        for duration in [0, -1, None, math.nan, math.inf, True, "4", 10 ** 1000]:
            with self.subTest(duration=duration):
                result = aggregate(samples([0] * 8), duration=duration)
                self.assertEqual(result["verdict"], "inconclusive")
                self.assertIn("duration_must_be_finite_and_positive", result["technicalIssues"])

    def test_correlated_samples_do_not_gain_probability_or_independence(self):
        result = aggregate(samples([0.99] * 8))
        self.assertEqual(result["persistentRuns"][0]["sampleScores"], [0.99] * 8)
        self.assertFalse(result["persistentRuns"][0]["adjacentSamplesAreIndependent"])
        self.assertFalse(result["adjacentSamplesAreIndependent"])
        self.assertFalse(result["scoresAreCalibratedProbabilities"])
        self.assertNotIn("probability", result)
        self.assertNotIn("confidence", result)
        self.assertEqual(result["persistentRuns"][0]["extentMeaning"],
                         "sample_endpoints_only_not_a_continuous_AI_interval")
        self.assertEqual(result["persistentRuns"][0]["lastSampleSeconds"], 3.5)

    def test_configuration_is_stable_detached_and_fingerprinted(self):
        policy, fingerprint = MODULE.policy_configuration()
        reversed_policy = dict(reversed(list(policy.items())))
        self.assertEqual(MODULE.policy_configuration(reversed_policy)[1], fingerprint)
        self.assertEqual(fingerprint, hashlib.sha256(MODULE.canonical_json(policy).encode()).hexdigest())
        policy["coverage"]["maximumGapSeconds"] = 5
        self.assertEqual(MODULE.policy_configuration()[0]["coverage"]["maximumGapSeconds"], 0.6)
        self.assertEqual(MODULE.policy_configuration()[1], fingerprint)

    def test_fixed_policy_rejects_threshold_or_other_post_hoc_override(self):
        for key, value in [("scoreThreshold", 0.99), ("minimumPersistentSamples", 3),
                           ("maximumPositiveGapSeconds", 1), ("policyVersion", "v2"),
                           ("adjacentSamplesAreIndependent", True)]:
            policy = copy.deepcopy(MODULE.DEFAULT_CONFIG)
            policy[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                aggregate(samples([0] * 8), config=policy)

    def test_cli_hashes_only_synthetic_input_and_refuses_output_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "synthetic.json"
            output_path = Path(directory) / "evidence.json"
            input_path.write_text(json.dumps({"samples": samples([0] * 8), "durationSeconds": 4,
                                             "technicalComplete": True, "declaredIntervalSeconds": 0.5}))
            command = [sys.executable, str(SCRIPT), "--input", str(input_path), "--output", str(output_path)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            output_bytes = output_path.read_bytes()
            result = json.loads(output_bytes)
            self.assertEqual(result["inputSha256"], hashlib.sha256(input_path.read_bytes()).hexdigest())
            self.assertEqual(result["aggregatorSha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
            self.assertEqual(result["verdict"], "no_clear_indicators")
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output_path.read_bytes(), output_bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
