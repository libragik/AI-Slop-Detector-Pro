#!/usr/bin/env python3
"""Bounded prospective sample-evidence screen; no score tuning or automatic retry."""
import argparse
import hashlib
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/eval-sightengine-api.py"
HELPER_SHA = "b953a1dd11f3f2b5bf81f3c9d7819466fed1d98c7defeb234e0439c82ca852be"
AGGREGATOR = ROOT / "scripts/sightengine-temporal-evidence.py"
AGGREGATOR_SHA = "527b15281583255c975c60b7f8f3b44981c2a6744a6ab4af514bc61b667a7453"
MANIFEST_SHA = "1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7"
RESPONSE_CAP = 1048576


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def validate(manifest_path):
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("Only the prospectively frozen screen is authorized by this runner")
    if sha(HELPER) != HELPER_SHA or sha(AGGREGATOR) != AGGREGATOR_SHA:
        raise ValueError("Pinned implementation changed")
    helper = module(HELPER, "sightengine_contract")
    aggregator = module(AGGREGATOR, "temporal_policy")
    manifest = json.loads(manifest_path.read_bytes())
    candidate = manifest["candidate"]
    if sha(ROOT / candidate["path"]) != candidate["sha256"]:
        raise ValueError("Candidate policy reference changed")
    if manifest.get("policy", {}).get("aggregatorSha256") != AGGREGATOR_SHA or manifest["policy"].get("policyFingerprint") != aggregator.policy_configuration()[1]:
        raise ValueError("Manifest does not bind the implemented temporal policy")
    if manifest.get("limits", {}).get("maxReservedOperations") != 3000:
        raise ValueError("Manifest operation cap differs")
    cases = manifest["cases"]
    if not 1 <= len(cases) <= 30 or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Invalid bounded case list")
    if len({case["sha256"] for case in cases}) != len(cases):
        raise ValueError("Duplicate media bytes")
    total = 0
    for case in cases:
        path = (ROOT / case["path"]).resolve()
        if not path.is_relative_to(ROOT / "eval") or sha(path) != case["sha256"]:
            raise ValueError("Media path or hash mismatch")
        duration = case["media"]["durationSeconds"]
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or not 0 < duration < 60:
            raise ValueError("Unsupported duration")
        if path.stat().st_size != case["media"]["bytes"] or not 0 < path.stat().st_size <= 50_000_000:
            raise ValueError("Media byte limit/mismatch")
        total += helper.reservation(case)
    if total > 3000:
        raise ValueError("Operation reservation exceeds screen cap")
    return manifest, helper, aggregator, total


def worker(args):
    manifest, helper, _, _ = validate(args.manifest)
    if not 0 <= args.worker < len(manifest["cases"]):
        raise ValueError("Invalid worker case index")
    case = manifest["cases"][args.worker]
    claim = json.loads((args.output / "execution.json").read_bytes())
    if claim["manifestSha256"] != sha(args.manifest) or claim["runnerSha256"] != sha(__file__):
        raise ValueError("Execution binding mismatch")
    global_claim = json.loads((ROOT / "eval/runs" / f"sightengine-screen-{MANIFEST_SHA}-execution.json").read_bytes())
    intent = json.loads((args.output / f"intent-{args.worker:02d}.json").read_bytes())
    if (global_claim != claim or claim["output"] != str(args.output) or claim["supervisorPid"] != os.getppid()
            or intent["index"] != args.worker or intent["id"] != case["id"] or intent["mediaSha256"] != case["sha256"]):
        raise ValueError("Worker is not attached to its active submission intent")
    credentials = tuple(os.environ.get(key, "") for key in ("SIGHTENGINE_API_USER", "SIGHTENGINE_API_SECRET"))
    if not all(credentials):
        return {"kind": "credentials_unavailable", "operationsUnknown": False}
    # Avoid the original five-control parser's study-specific label/localization branch.
    wire_case = {**case, "order": args.worker + 1, "sourceLabel": "unknown"}
    body, content_type = helper.multipart(wire_case, credentials)
    write_new(args.output / f"worker-{args.worker:02d}.json", {"startedAt": now(), "mediaSha256": case["sha256"]})
    connection = http.client.HTTPSConnection("api.sightengine.com", timeout=175, context=ssl.create_default_context())
    try:
        connection.request("POST", "/1.0/video/check-sync.json", body=body,
                           headers={"Content-Type": content_type, "Content-Length": str(len(body))})
        response = connection.getresponse()
        if response.status != 200:
            return {"kind": "http_error", "httpStatus": response.status, "operationsUnknown": True}
        raw = response.read(RESPONSE_CAP + 1)
        return {"kind": "response", "evidence": helper.parse_response(raw, wire_case, credentials)}
    except Exception:
        return {"kind": "transport_error", "operationsUnknown": True}
    finally:
        connection.close()


def interpret_response(response, case, aggregator):
    response = response if isinstance(response, dict) else {"kind": "worker_error", "operationsUnknown": True}
    evidence = response.get("evidence", {})
    evidence = evidence if isinstance(evidence, dict) else {}
    reported = evidence.get("request", {}).get("operations")
    complete = (response.get("kind") == "response" and evidence.get("schemaValid") is True
                and evidence.get("coverageComplete") is True and type(reported) is int)
    temporal = aggregator.aggregate_evidence(evidence.get("frames", []), duration_seconds=case["media"]["durationSeconds"],
                                             technical_complete=complete, declared_interval_seconds=0.5)
    return complete and temporal["technicalComplete"], temporal, reported


def run(args):
    manifest, helper, aggregator, reserved = validate(args.manifest)
    if not all(os.environ.get(key) for key in ("SIGHTENGINE_API_USER", "SIGHTENGINE_API_SECRET")):
        raise ValueError("Sightengine credentials missing")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_hash = sha(args.manifest)
    plan = {"manifestPath": str(args.manifest.relative_to(ROOT)), "manifestSha256": manifest_hash,
            "output": str(args.output), "supervisorPid": os.getpid(),
            "runnerSha256": sha(__file__), "aggregatorSha256": AGGREGATOR_SHA, "helperSha256": HELPER_SHA,
            "policyFingerprint": aggregator.policy_configuration()[1], "startedAt": now(),
            "reservedOperations": reserved, "maximumReservedOperations": 3000,
            "maximumRequests": len(manifest["cases"]), "automaticRetries": 0}
    # A claim keyed to the exact manifest also prevents rerunning into a different output directory.
    write_new(ROOT / "eval/runs" / f"sightengine-screen-{manifest_hash}-execution.json", plan)
    write_new(args.output / "execution.json", plan)
    write_new(args.output / "manifest.json", manifest)
    results = []
    operations = 0
    stop = None
    for index, case in enumerate(manifest["cases"]):
        if stop:
            results.append({"id": case["id"], "status": "not_attempted", "reason": stop})
            continue
        if index:
            time.sleep(1)  # after previous request completion
        intent = {"index": index, "id": case["id"], "mediaSha256": case["sha256"], "startedAt": now()}
        write_new(args.output / f"intent-{index:02d}.json", intent)
        started = time.monotonic()
        command = [sys.executable, str(Path(__file__).resolve()), "--manifest", str(args.manifest),
                   "--output", str(args.output), "--worker", str(index)]
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180,
                                       env={key: os.environ.get(key, "") for key in ("PATH", "SIGHTENGINE_API_USER", "SIGHTENGINE_API_SECRET")})
            response = helper.load_json_bytes(completed.stdout) if completed.returncode == 0 and len(completed.stdout) <= RESPONSE_CAP else {"kind": "worker_error", "operationsUnknown": True}
        except subprocess.TimeoutExpired:
            response = {"kind": "wall_timeout", "operationsUnknown": True}
        except Exception:
            response = {"kind": "worker_error", "operationsUnknown": True}
        complete, temporal, reported = interpret_response(response, case, aggregator)
        if type(reported) is int:
            operations += reported
        if not complete or type(reported) is not int or operations > reserved:
            stop = "Technical completion or operation accounting failed; no further calls"
            complete = False
        result = {**intent, "status": "completed" if complete else "stopped", "elapsedSeconds": time.monotonic() - started,
                  "response": response, "temporal": temporal, "reportedOperationsObserved": operations,
                  "accountingMayBeIncomplete": not complete,
                  "transmissionMayBeUncertain": response.get("kind") not in ("response", "credentials_unavailable")}
        write_new(args.output / f"case-{index:02d}.json", result)
        results.append(result)
        print(json.dumps({"completed": index + 1, "total": len(manifest["cases"]), "id": case["id"],
                          "status": result["status"], "decision": temporal["verdict"], "operations": operations}), flush=True)
    receipt = {**plan, "completedAt": now(), "results": results, "stopReason": stop,
               "reportedOperationsObserved": operations, "status": "stopped" if stop else "completed",
               "accuracyClaim": None, "qualification": "Apply prospectively specified gates; publisher labels and reused parents are not independent proof of origin."}
    write_new(args.output / "receipt.json", receipt)
    return 1 if stop else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", type=int)
    args = parser.parse_args()
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    if args.worker is not None:
        print(json.dumps(worker(args), allow_nan=False))
        return 0
    return run(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Prospective screen stopped before further submissions; provider error text omitted.", file=sys.stderr)
        raise SystemExit(1)
