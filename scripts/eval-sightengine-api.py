#!/usr/bin/env python3
"""Single-use five-control diagnostic. Preparation and tests never need network."""
import argparse
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {"path": "eval/fixtures/sightengine-demo-diagnostic-v1.json",
          "sha256": "2b2934eb888db109df9def867bd7e13e9f5d01083e1d7a9021c7644ee9ae5825"}
API = {"endpoint": "https://api.sightengine.com/1.0/video/check-sync.json", "models": "genai",
       "intervalSeconds": .5, "threshold": .5, "positionUnit": "milliseconds"}
LIMITS = {"requests": 5, "operations": 500, "responseBytes": 1048576, "requestSeconds": 180,
          "minimumStartIntervalSeconds": 1}
COVERAGE = {"firstFrameMaxSeconds": .1, "maxGapSeconds": .6, "tailGapSeconds": .6}
REFS = ("sourceManifest", "originReceipt", "constructionReceipt", "frameLineage")
ENV_KEYS = ("SIGHTENGINE_API_USER", "SIGHTENGINE_API_SECRET")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def require(test, message):
    if not test:
        raise ValueError(message)


def path_in_eval(value, existing=True):
    p = (ROOT / value).resolve()
    require(p.is_relative_to(ROOT / "eval") and p != ROOT / "eval", "Path must stay inside eval")
    if existing:
        require(p.is_file(), "Missing input file")
    return p


def write_new(path, value):
    """Atomic exclusive publication; an interrupted run is never resumed."""
    p = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.link(temporary, p)
    finally:
        os.unlink(temporary)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def load_json_bytes(body):
    def pairs(values):
        out = {}
        for k, v in values:
            require(k not in out, "Duplicate JSON key")
            out[k] = v
        return out
    def constant(_):
        raise ValueError("Nonfinite JSON")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=constant)


def reservation(case):
    return 5 * (math.ceil(case["media"]["durationSeconds"] / .5) + 1)


def validate_fixture(path, for_run=False):
    p = path_in_eval(path)
    fixture = load_json_bytes(p.read_bytes())
    require(fixture.get("schemaVersion") == 1 and fixture.get("id") == "sightengine-api-diagnostic-v1",
            "Unexpected study identity")
    require(fixture.get("sourceFixture") == SOURCE and fixture.get("api") == API
            and fixture.get("limits") == LIMITS and fixture.get("coverage") == COVERAGE,
            "Fixed API recipe or bounds changed")
    source_path = path_in_eval(SOURCE["path"])
    require(sha(source_path) == SOURCE["sha256"], "Source fixture changed")
    original = load_json_bytes(source_path.read_bytes())
    cases = fixture["cases"]
    require(cases == original["cases"] and len(cases) == 5 and [r["order"] for r in cases] == [1,2,3,4,5],
            "The five original cases/order must remain byte-equivalent as JSON values")
    inputs = {SOURCE["path"]: sha(source_path)}
    for case in cases:
        media = path_in_eval(case["path"])
        require(sha(media) == case["sha256"] and media.stat().st_size == case["media"]["bytes"], "Media changed")
        require(finite(case["media"]["durationSeconds"]) and case["media"]["durationSeconds"] > 0, "Invalid duration")
        inputs[case["path"]] = sha(media)
        for key in REFS:
            if key in case:
                ref = case[key]; target = path_in_eval(ref["path"])
                require(sha(target) == ref["sha256"], "Source/provenance reference changed")
                inputs[ref["path"]] = ref["sha256"]
    require(sum(reservation(c) for c in cases) <= 500, "Nominal operation reservation exceeds limit")
    if for_run:
        require(fixture.get("frozen") is True and isinstance(fixture.get("frozenAt"), str)
                and fixture.get("runnerSha256") == sha(__file__), "Frozen fixture must pin this exact runner")
    return fixture, {"fixturePath": str(p.relative_to(ROOT)), "fixtureSha256": sha(p),
                     "runnerSha256": sha(__file__), "inputs": inputs,
                     "reservedNominalOperations": sum(reservation(c) for c in cases)}


def parse_response(body, case, secrets=()):
    """Persist allowlisted values only; arbitrary vendor fields/messages are discarded."""
    evidence = {"rawResponseSha256": hashlib.sha256(body).hexdigest(), "responseBytes": len(body),
                "frames": [], "issues": [], "request": {}, "schemaValid": False,
                "coverageComplete": False, "primaryDecision": None, "maximumValidScore": None,
                "secondaryAnyPositive": None, "mixedLocalizationPass": None}
    if len(body) > LIMITS["responseBytes"]:
        evidence["issues"].append("response_too_large"); return evidence
    try:
        value = load_json_bytes(body)
    except (ValueError, UnicodeError, TypeError):
        evidence["issues"].append("invalid_json"); return evidence
    if not isinstance(value, dict) or value.get("status") != "success":
        evidence["issues"].append("api_unsuccessful"); return evidence
    request = value.get("request")
    if isinstance(request, dict):
        identifier, timestamp, operations = request.get("id"), request.get("timestamp"), request.get("operations")
        if isinstance(identifier, str) and 0 < len(identifier) <= 256:
            evidence["request"]["id"] = "[redacted]" if any(s and s in identifier for s in secrets) else identifier
        else:
            evidence["issues"].append("missing_request_id")
        if finite(timestamp) and timestamp >= 0:
            evidence["request"]["timestamp"] = timestamp
        else:
            evidence["issues"].append("missing_request_timestamp")
        if type(operations) is int and operations >= 0:
            evidence["request"]["operations"] = operations
            if operations > reservation(case):
                evidence["issues"].append("operations_exceed_reservation")
        else:
            evidence["issues"].append("unknown_operations")
    else:
        evidence["issues"].append("missing_request_accounting")
    frames = value.get("data", {}).get("frames") if isinstance(value.get("data"), dict) else None
    if not isinstance(frames, list) or not frames:
        evidence["issues"].append("missing_frames"); return evidence
    if len(frames) > reservation(case) // 5:
        evidence["issues"].append("excess_frames")
    if evidence["request"].get("operations") != 5 * len(frames):
        evidence["issues"].append("operations_frame_count_mismatch")
    for index, frame in enumerate(frames):
        info = frame.get("info") if isinstance(frame, dict) else None
        kind = frame.get("type") if isinstance(frame, dict) else None
        raw_position = info.get("position") if isinstance(info, dict) else None
        position = raw_position / 1000 if finite(raw_position) else None
        score = kind.get("ai_generated") if isinstance(kind, dict) else None
        valid = finite(position) and 0 <= position < case["media"]["durationSeconds"] and finite(score) and 0 <= score <= 1
        evidence["frames"].append({"index": index, "rawPositionMilliseconds": raw_position if finite(raw_position) else None,
                                   "positionSeconds": position if finite(position) else None,
                                   "aiGenerated": score if finite(score) else None, "valid": valid})
        if not valid:
            evidence["issues"].append("invalid_frame_" + str(index))
    valid_frames = [f for f in evidence["frames"] if f["valid"]]
    if valid_frames:
        evidence["maximumValidScore"] = max(f["aiGenerated"] for f in valid_frames)
        evidence["secondaryAnyPositive"] = evidence["maximumValidScore"] >= .5
    evidence["schemaValid"] = not evidence["issues"]
    if not evidence["schemaValid"]:
        return evidence
    positions = [f["positionSeconds"] for f in evidence["frames"]]
    if positions[0] > .1:
        evidence["issues"].append("missing_start_coverage")
    if case["media"]["durationSeconds"] - positions[-1] > .6 + 1e-9:
        evidence["issues"].append("missing_tail_coverage")
    if any(b <= a or b - a > .6 + 1e-9 for a, b in zip(positions, positions[1:])):
        evidence["issues"].append("unordered_duplicate_or_gapped_coverage")
    evidence["coverageComplete"] = not evidence["issues"]
    if evidence["coverageComplete"]:
        evidence["primaryDecision"] = "ai" if evidence["secondaryAnyPositive"] else "not_ai"
    if case["sourceLabel"] == "mixed":
        positive = [f["positionSeconds"] for f in valid_frames if f["aiGenerated"] >= .5]
        evidence["mixedLocalizationPass"] = bool(positive) and all(3 <= p < 5 for p in positive)
    return evidence


def multipart(case, credentials):
    # Source filenames, labels, IDs, ancestry, and descriptions never go outbound.
    boundary = "sightengine-diagnostic-v1-boundary"
    chunks = []
    fields = {"models": "genai", "interval": "0.5", "api_user": credentials[0], "api_secret": credentials[1]}
    for name, value in fields.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="clip-{case["order"]:02d}.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode())
    media = path_in_eval(case["path"]).read_bytes()
    require(len(media) == case["media"]["bytes"] and hashlib.sha256(media).hexdigest() == case["sha256"],
            "Actual outbound media bytes differ from the pinned case")
    chunks.append(media)
    chunks.append((f"\r\n--{boundary}--\r\n").encode())
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


def remote_worker(fixture_path, order, ledger_path):
    fixture, binding = validate_fixture(fixture_path, for_run=True)
    ledger = load_json_bytes(path_in_eval(ledger_path).read_bytes())
    case = fixture["cases"][order-1]
    require(ledger.get("supervisorPid") == os.getppid() and ledger.get("status") == "submitting"
            and ledger.get("caseId") == case["id"] and ledger.get("fixtureSha256") == binding["fixtureSha256"]
            and ledger.get("mediaSha256") == case["sha256"], "Worker requires its live pre-submission ledger")
    claim = load_json_bytes(path_in_eval("eval/runs/sightengine-api-diagnostic-v1-execution.json").read_bytes())
    require(claim.get("fixtureSha256") == binding["fixtureSha256"]
            and path_in_eval(ledger_path).parent == path_in_eval(claim["outputPath"], existing=False),
            "Worker is not bound to the study's exclusive execution claim")
    credentials = tuple(os.environ.get(key, "") for key in ENV_KEYS)
    require(all(credentials), "Credentials are unavailable")
    body, content_type = multipart(case, credentials)
    connection = http.client.HTTPSConnection("api.sightengine.com", timeout=180, context=ssl.create_default_context())
    try:
        connection.request("POST", "/1.0/video/check-sync.json", body=body,
                           headers={"Content-Type": content_type, "Content-Length": str(len(body))})
        response = connection.getresponse()
        # http.client never follows redirects or automatically retries this POST.
        if response.status != 200:
            return {"kind": "http_error", "httpStatus": response.status, "operationsUnknown": True}
        raw = response.read(LIMITS["responseBytes"] + 1)
        return {"kind": "response", "httpStatus": 200, "evidence": parse_response(raw, case, credentials)}
    except Exception:
        # Exception messages and vendor error bodies could contain credentials.
        return {"kind": "transport_error", "operationsUnknown": True}
    finally:
        connection.close()


def execute_request(fixture_path, case, ledger_path):
    credentials = {key: os.environ[key] for key in ENV_KEYS}
    command = [sys.executable, str(Path(__file__).resolve()), "--fixture", fixture_path,
               "--worker-case", str(case["order"]), "--ledger", ledger_path, "--execute-api-requests"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=180,
                                env={"PATH": os.defpath, **credentials}, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"kind": "wall_timeout", "operationsUnknown": True}
    if result.returncode != 0:
        return {"kind": "worker_error", "operationsUnknown": True}
    try:
        return load_json_bytes(result.stdout)
    except (ValueError, UnicodeError, TypeError):
        return {"kind": "worker_error", "operationsUnknown": True}


def run_study(fixture_path, output, execute=False, requester=execute_request):
    require(execute, "Explicit --execute-api-requests is required")
    fixture, binding = validate_fixture(fixture_path, for_run=True)
    require(all(os.environ.get(key) for key in ENV_KEYS), "Both API credential environment variables are required")
    output = path_in_eval(output, existing=False); output.mkdir(parents=True, exist_ok=False)
    claim = ROOT / "eval/runs/sightengine-api-diagnostic-v1-execution.json"
    claim.parent.mkdir(parents=True, exist_ok=True)
    write_new(claim, {"fixtureSha256": binding["fixtureSha256"], "outputPath": str(output.relative_to(ROOT)),
                      "runnerSha256": binding["runnerSha256"], "claimedAt": now(), "resumable": False})
    write_new(output / "configuration.json", {**binding, "api": API, "limits": LIMITS, "coverage": COVERAGE})
    results, requests, reserved, reported, stop = [], 0, 0, 0, None
    last_completion = None
    for case in fixture["cases"]:
        base = {"order": case["order"], "id": case["id"], "mediaPath": case["path"], "mediaSha256": case["sha256"]}
        if stop:
            results.append({**base, "status": "not_attempted_due_to_stop", "stopReason": stop}); continue
        # Rehash all five media and provenance references immediately before every submission.
        try:
            _, current = validate_fixture(fixture_path, for_run=True)
            require(current == binding, "Inputs changed after run began")
        except Exception:
            stop = "input_integrity_failure"
            results.append({**base, "status": "not_attempted_due_to_stop", "stopReason": stop}); continue
        reserve = reservation(case)
        require(requests < 5 and reserved + reserve <= 500, "Submission/nominal-operation cap reached")
        if last_completion is not None:
            # A worker preflights media and establishes TLS after its intent.
            # Cool down after completion so variable startup cannot bunch POSTs.
            while (remaining := last_completion + 1 - time.monotonic()) > 0:
                time.sleep(min(1, remaining))
        intent_start = time.monotonic()
        requests += 1; reserved += reserve
        ledger = output / f"{case['order']:02d}.submitting.json"
        write_new(ledger, {**base, "caseId": case["id"], "status": "submitting", "startedAt": now(),
                          "fixtureSha256": binding["fixtureSha256"], "supervisorPid": os.getpid(),
                          "reservedNominalOperations": reserve, "cumulativeReservedNominalOperations": reserved,
                          "monotonicIntentStart": intent_start,
                          "requestNumber": requests, "outboundFilename": f"clip-{case['order']:02d}.mp4"})
        try:
            response = requester(fixture_path, case, str(ledger.relative_to(ROOT)))
        except Exception:
            response = {"kind": "worker_error", "operationsUnknown": True}
        last_completion = time.monotonic()
        evidence = response.get("evidence", {})
        operations = evidence.get("request", {}).get("operations")
        if type(operations) is int and operations >= 0:
            reported += operations
        if response.get("kind") != "response":
            stop = response.get("kind", "worker_error")
        elif not evidence.get("schemaValid"):
            stop = "schema_or_accounting_failure"
        elif not evidence.get("coverageComplete"):
            stop = "coverage_failure"
        elif reported > 500:
            stop = "reported_operation_limit"
        primary = evidence.get("primaryDecision") if not stop else None
        record = {**base, "status": "no_result" if stop else "completed", "response": response,
                  "primaryDecision": primary, "correct": primary == case["expectedPrimaryDecision"] if primary else None,
                  "transmissionMayBeUncertain": response.get("kind") != "response",
                  "monotonicRequesterCompletion": last_completion,
                  "stopReason": stop, "finishedAt": now()}
        write_new(output / f"{case['order']:02d}.result.json", record); results.append(record)
    interpretable = sum(r.get("primaryDecision") in ("ai", "not_ai") for r in results)
    mixed = next(r for r in results if r["order"] == 2)
    passed = interpretable == 5 and all(r.get("correct") is True for r in results) and mixed.get("response", {}).get("evidence", {}).get("mixedLocalizationPass") is True
    receipt = {**binding, "status": "passed" if passed else "failed" if not stop else "stopped",
               "submissionIntents": requests, "reservedNominalOperations": reserved,
               "reportedOperationsObserved": reported,
               "accountingMayBeIncomplete": any(r.get("status") == "no_result" and
                    (type(r.get("response", {}).get("evidence", {}).get("request", {}).get("operations")) is not int
                     or any("operations" in issue or "accounting" in issue for issue in r.get("response", {}).get("evidence", {}).get("issues", []))) for r in results),
               "completedPredictions": interpretable, "diagnosticPass": passed, "stopReason": stop,
               "results": results, "productValidation": False, "integrationPerformed": False,
               "scoreIsCalibratedProbability": False, "finishedAt": now()}
    write_new(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true"); mode.add_argument("--run", action="store_true")
    mode.add_argument("--worker-case", type=int, choices=range(1,6), help=argparse.SUPPRESS)
    parser.add_argument("--fixture", required=True); parser.add_argument("--output")
    parser.add_argument("--ledger", help=argparse.SUPPRESS)
    parser.add_argument("--execute-api-requests", action="store_true")
    args = parser.parse_args()
    if args.worker_case:
        require(args.execute_api_requests, "Explicit execution flag required")
        print(json.dumps(remote_worker(args.fixture, args.worker_case, args.ledger), allow_nan=False)); return 0
    require(args.output, "A fresh output directory is required")
    if args.prepare:
        _, binding = validate_fixture(args.fixture)
        output = path_in_eval(args.output, existing=False); output.mkdir(parents=True, exist_ok=False)
        receipt = {**binding, "status": "prepared", "networkRequests": 0, "api": API, "limits": LIMITS,
                   "coverage": COVERAGE, "preparedAt": now(), "productValidation": False}
        write_new(output / "preparation.json", receipt)
    else:
        receipt = run_study(args.fixture, args.output, args.execute_api_requests)
    print(json.dumps({"status": receipt["status"], "output": args.output})); return 0 if receipt["status"] in ("prepared", "passed") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # No arbitrary response, environment value, or multipart body reaches logs.
        print("Sightengine diagnostic stopped: local preflight or execution failure.", file=sys.stderr)
        raise SystemExit(1)
