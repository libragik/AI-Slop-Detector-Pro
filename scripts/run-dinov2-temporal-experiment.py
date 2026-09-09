#!/usr/bin/env python3
"""Run the frozen extraction, fitting, and diagnostic stages in order."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "eval/fixtures/dinov2-temporal-protocol-v1.json"
OUTPUT = ROOT / "eval/runs/dinov2-temporal-experiment-v1"
FEATURES = "eval/runs/dinov2-training-features-v1"
TRAINING = "eval/runs/dinov2-temporal-training-v1"
DIAGNOSTIC = "eval/runs/dinov2-temporal-diagnostic-v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(name, value):
    with (OUTPUT / name).open("x") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main():
    protocol_path = ROOT / PROTOCOL
    protocol_hash = sha(protocol_path)
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("frozen") is not True:
        raise ValueError("The complete experiment must be frozen before launch")
    own_name = str(Path(__file__).resolve().relative_to(ROOT))
    if protocol["sourceHashes"].get(own_name) != sha(__file__):
        raise ValueError("Launcher is not bound to the frozen protocol")
    stages = [
        ("features", ["scripts/build-dinov2-training-features.py", "--protocol", PROTOCOL,
                      "--output", FEATURES], ROOT / FEATURES / "manifest.json"),
        ("training", ["scripts/train-dinov2-temporal.py", "train", "--protocol", PROTOCOL,
                      "--features", FEATURES + "/manifest.json", "--output", TRAINING],
         ROOT / TRAINING / "complete.json"),
        ("diagnostic", ["scripts/eval-dinov2-temporal.py", "--protocol", PROTOCOL,
                        "--features", FEATURES + "/manifest.json", "--training", TRAINING,
                        "--output", DIAGNOSTIC], ROOT / DIAGNOSTIC / "summary.json"),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=False)
    for name, arguments, completion in stages:
        if sha(protocol_path) != protocol_hash:
            raise ValueError("Protocol changed between stages")
        for source, expected in protocol["sourceHashes"].items():
            if sha(ROOT / source) != expected:
                raise ValueError("Frozen source changed: " + source)
        command = [sys.executable, *arguments]
        running = {"stage": name, "protocolSha256": protocol_hash, "command": command,
                   "startedAt": datetime.now(timezone.utc).isoformat()}
        record(name + ".running.json", running)
        print(json.dumps({"experimentStageStarted": name}), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        terminal = {**running, "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "exitCode": result.returncode,
                    "completionPath": str(completion.relative_to(ROOT)),
                    "completionSha256": sha(completion) if completion.is_file() else None}
        record(name + ".terminal.json", terminal)
        print(json.dumps({"experimentStageFinished": terminal}), flush=True)
        if result.returncode or not completion.is_file():
            return result.returncode if result.returncode > 0 else 1
    record("complete.json", {"allStagesCompleted": True, "protocolSha256": protocol_hash,
                             "productValidation": False, "integrationPerformed": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
