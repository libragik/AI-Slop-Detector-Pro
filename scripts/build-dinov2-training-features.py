#!/usr/bin/env python3
"""Build the frozen training feature cache; no head fitting or diagnostic input.

Original, mild and severe each retain their acquired training parent. Quality
transforms reproduce the previously declared local compression simulations.
Every source file, actual sample, feature file and executable is receipted.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FEATURE_SCRIPT = ROOT / "scripts/dinov2-temporal-features.py"
QUALITY_RECIPES = {
    "mild": {"filter": "scale='min(720,iw)':-2,fps=24", "crf": "28"},
    "severe": {"filter": "crop=trunc(iw*0.85/2)*2:trunc(ih*0.85/2)*2,scale='min(360,iw)':-2,fps=12,drawbox=x=0:y=0:w=iw:h=ih*0.08:color=black@0.8:t=fill", "crf": "36"},
}
DERIVATIVE_PREFIX = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                     "-protocol_whitelist", "file,pipe", "-i"]
DISPLAY_POLICY = {
    "derivative": "FFmpeg default autorotation remains enabled; no added rotation or SAR correction.",
    "featureExtraction": "Frozen decoder disables autorotation; probe rejects declared nonzero rotation.",
    "geometry": "Record stored dimensions and SAR/DAR; raw stored pixels do not establish matched display geometry.",
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def process_inventory():
    raw = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,rss=,lstart="], timeout=3).decode()
    result = {}
    for line in raw.splitlines():
        if line.strip():
            pid, parent, rss, started = line.split(maxsplit=3)
            result[int(pid)] = (int(parent), int(rss) * 1024, started)
    return result


def owned_processes(pid, inventory, tracked=None):
    # Start identity prevents a formerly owned PID from selecting a reused PID.
    descendants = {p for p, started in (tracked or {}).items()
                   if p in inventory and inventory[p][2] == started}
    if pid in inventory and (not tracked or pid not in tracked or inventory[pid][2] == tracked[pid]):
        descendants.add(pid)
    while True:
        expanded = descendants | {child for child, (parent, _, _) in inventory.items() if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    return {p: inventory[p][2] for p in descendants}


def process_tree_rss(pid):
    inventory = process_inventory()
    return sum(inventory[p][1] for p in owned_processes(pid, inventory))


def terminate_owned_processes(pid, tracked):
    # Freeze each observed parent before another census, so nested-session
    # children cannot be lost when their parent is killed/reparented.
    stopped, signalled = set(), []
    try:
        for _ in range(8):
            inventory = process_inventory()
            tracked = owned_processes(pid, inventory, tracked)
            pending = set(tracked) - stopped
            if not pending:
                break
            for child in sorted(pending):
                try:
                    os.kill(child, signal.SIGSTOP)
                    stopped.add(child)
                except ProcessLookupError:
                    pass
        else:
            raise RuntimeError("Owned process tree did not stabilize during cleanup")
    finally:
        # Recheck identity immediately before signalling; no process-group
        # assumption, because the decoder creates its own session.
        inventory = process_inventory()
        for child, started in sorted(tracked.items(), reverse=True):
            if child in inventory and inventory[child][2] == started:
                try:
                    os.kill(child, signal.SIGKILL)
                    signalled.append(child)
                except ProcessLookupError:
                    pass
    return signalled


def supervise(command, *, timeout_seconds, memory_limit_bytes, prior_elapsed_seconds=0, poll_interval=.2):
    """Run one owned tree; cumulative budget includes previous invocation receipts."""
    if (not 0 <= prior_elapsed_seconds < timeout_seconds or memory_limit_bytes <= 0
            or not 0 < poll_interval <= 1):
        raise ValueError("Invalid or exhausted supervision budget")
    child = subprocess.Popen(command, start_new_session=True)
    began, peak_rss, stop_reason, tracked = time.monotonic(), 0, None, {}
    killed, cleanup_error = [], None
    try:
        while child.poll() is None:
            inventory = process_inventory()
            tracked = owned_processes(child.pid, inventory, tracked)
            peak_rss = max(peak_rss, sum(inventory[p][1] for p in tracked))
            if time.monotonic() - began + prior_elapsed_seconds > timeout_seconds:
                stop_reason = "cumulative_wall_time_limit"
            elif peak_rss > memory_limit_bytes:
                stop_reason = "process_tree_memory_limit"
            if stop_reason:
                break
            time.sleep(poll_interval)
    except (subprocess.SubprocessError, ValueError, OSError):
        stop_reason = "resource_monitor_failed"
    except BaseException as exc:
        stop_reason = "supervisor_interrupted:" + type(exc).__name__
    finally:
        # Also reap tracked descendants after a normal or failed worker exit.
        try:
            killed = terminate_owned_processes(child.pid, tracked)
        except Exception as exc:
            cleanup_error = type(exc).__name__ + ": " + str(exc)
            stop_reason = stop_reason or "resource_cleanup_failed"
            if child.poll() is None:
                child.kill()
        child.wait(timeout=5)
    return {"elapsedSeconds": time.monotonic() - began, "priorElapsedSeconds": prior_elapsed_seconds,
            "peakProcessTreeRssBytes": peak_rss, "exitCode": child.returncode,
            "stopReason": stop_reason, "wallTimeLimitSeconds": timeout_seconds,
            "memoryLimitBytes": memory_limit_bytes, "terminatedProcessIds": killed,
            "cleanupError": cleanup_error}


def verify_sources(protocol):
    if protocol.get("frozen") is not True or protocol.get("qualityRecipes") != QUALITY_RECIPES:
        raise ValueError("Frozen exact quality recipe required")
    for name, expected in protocol["sourceHashes"].items():
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT / "scripts") or sha(path) != expected:
            raise ValueError("Frozen executable changed: " + name)
    acquisition = protocol["acquisition"]
    for kind in ("manifest", "completion", "fixture"):
        if sha(ROOT / acquisition[kind + "Path"]) != acquisition[kind + "Sha256"]:
            raise ValueError("Acquisition " + kind + " hash mismatch")
    rows = [json.loads(line) for line in (ROOT / acquisition["manifestPath"]).read_text().splitlines() if line]
    if len(rows) != 2304 or len({r["id"] for r in rows}) != 2304 or len({r["sha256"] for r in rows}) != 2304:
        raise ValueError("Exact unique acquired parent set required")
    for row in rows:
        if row["id"] != row["parentId"] or row["split"] not in ("train", "internal_development"):
            raise ValueError("Invalid acquired parent allocation")
        path = ROOT / row["path"]
        if not path.resolve().is_relative_to(ROOT / "eval") or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Acquired parent identity changed")
    return rows


def display_metadata(path):
    command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
               "-show_entries", "stream=width,height,sample_aspect_ratio,display_aspect_ratio:stream_tags=rotate:stream_side_data=rotation",
               "-of", "json", str(path)]
    result = subprocess.run(command, check=True, capture_output=True, timeout=15)
    if len(result.stdout) > 65536 or len(result.stderr) > 65536:
        raise ValueError("Display metadata exceeds bounded receipt size")
    raw = json.loads(result.stdout)
    if len(raw.get("streams", [])) != 1:
        raise ValueError("One display-metadata video stream required")
    return {"command": command, "stream": raw["streams"][0],
            "probeSha256": hashlib.sha256(result.stdout).hexdigest()}


def derivative(row, quality, output):
    original = ROOT / row["path"]
    if quality == "original":
        return original, {"original": True, "parentSha256": row["sha256"]}
    recipe = QUALITY_RECIPES[quality]
    identifier = hashlib.sha256((row["id"] + "|dinov2-training-v1|" + quality).encode()).hexdigest()[:24]
    target = output / "media" / (identifier + ".mp4")
    receipt_path = output / "media" / (identifier + ".json")
    arguments = ["-map", "0:v:0", "-an", "-vf", recipe["filter"], "-crf", recipe["crf"],
                 "-c:v", "libx264", "-preset", "veryfast", "-threads", "2", "-pix_fmt", "yuv420p",
                 "-map_metadata", "-1", "-movflags", "+faststart"]
    command = [*DERIVATIVE_PREFIX, str(original), *arguments, str(target)]
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt["parentSha256"] != row["sha256"] or receipt["arguments"] != arguments
                or receipt.get("command") != command or receipt.get("displayPolicy") != DISPLAY_POLICY
                or receipt.get("driverSha256") != sha(__file__) or sha(target) != receipt["sha256"]):
            raise ValueError("Existing derivative receipt mismatch")
        return target, receipt
    if target.exists():
        raise ValueError("Unreceipted derivative exists; preserve and inspect before resuming")
    source_display = display_metadata(original)
    subprocess.run(command, check=True, capture_output=True, timeout=90)
    if not 0 < target.stat().st_size <= 50_000_000:
        raise ValueError("Derivative size outside50000000-byte extractor bound")
    receipt = {"parentId": row["id"], "parentSha256": row["sha256"], "quality": quality,
               "path": relative(target), "sha256": sha(target), "bytes": target.stat().st_size,
               "arguments": arguments, "command": command, "driverSha256": sha(__file__),
               "displayPolicy": DISPLAY_POLICY,
               "sourceDisplay": source_display, "outputDisplay": display_metadata(target),
               "note": "Local encoding simulation, not an actual platform reupload."}
    write_json(receipt_path, receipt)
    return target, receipt


def validate_cached_feature(receipt, feature_path, base, bindings, identity, contract):
    if receipt.get("row") != {**base, "featureSha256": sha(feature_path)} or receipt.get("bindings") != bindings:
        raise ValueError("Cached feature receipt is not the same input and recipe")
    with np.load(feature_path, allow_pickle=False) as data:
        if data.files != ["cls"]:
            raise ValueError("Cached feature archive must contain only cls")
        cls = data["cls"]
        if cls.shape != (8, 384) or cls.dtype != np.float32 or not np.isfinite(cls).all():
            raise ValueError("Cached feature shape/dtype/finiteness mismatch")
    extraction = receipt.get("extraction", {})
    load = extraction.get("strictLoad", {})
    if (extraction.get("schemaVersion") != 1 or extraction.get("status") != "completed"
            or extraction.get("window") != base["window"] or extraction.get("model") != identity
            or extraction.get("modelFingerprint") != hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            or extraction.get("contract") != contract or extraction.get("device") != "mps"
            or extraction.get("featureShape") != [8, 384] or extraction.get("featureDtype") != "float32"
            or extraction.get("clsBytesSha256") != hashlib.sha256(cls.tobytes()).hexdigest()
            or extraction.get("source", {}).get("sha256") != base["mediaSha256"]
            or not all(load.get(k) is True for k in ("strict", "allTensorsFinite", "allLoadedTensorsEqual"))
            or load.get("tensorElements") != 22056576
            or any(load.get(k) != [] for k in ("missingKeys", "unexpectedKeys", "mismatchedKeys"))):
        raise ValueError("Cached extraction identity or complete-load evidence changed")
    frames = extraction.get("frames", [])
    if (len(frames) != 8 or len({f.get("nativeIndex") for f in frames}) != 8
            or extraction.get("decoder", {}).get("selectedFrameCount") != 8):
        raise ValueError("Cached extraction lacks eight distinct native frames")


def build(args):
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text())
    rows = verify_sources(protocol)
    protocol_sha = sha(protocol_path)
    output = ROOT / args.output
    configuration = {"protocolSha256": protocol_sha, "sourceHashes": protocol["sourceHashes"],
                     "acquisitionManifestSha256": protocol["acquisition"]["manifestSha256"],
                     "backboneSha256": protocol["backbone"]["weightsSha256"],
                     "featureModuleSha256": sha(FEATURE_SCRIPT), "driverSha256": sha(__file__),
                     "featureDevice": "mps", "rowsExpected": 6912}
    if output.exists():
        if not args.resume or (output / "manifest.json").exists():
            raise ValueError("Use a new feature directory or resume an identical incomplete run")
        if json.loads((output / "configuration.json").read_text()) != configuration:
            raise ValueError("Cannot resume a changed extraction recipe")
    else:
        output.mkdir(parents=True)
        (output / "media").mkdir()
        (output / "features").mkdir()
        write_json(output / "configuration.json", configuration)
        snapshot = output / "source"
        snapshot.mkdir()
        for name in protocol["sourceHashes"]:
            shutil.copyfile(ROOT / name, snapshot / Path(name).name)
        shutil.copyfile(protocol_path, snapshot / "protocol.json")
    spec = importlib.util.spec_from_file_location("dinov2_features", FEATURE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    backbone = protocol["backbone"]
    contract = ROOT / backbone["contractPath"]
    if sha(contract) != backbone["contractSha256"]:
        raise ValueError("Backbone numerical contract changed")
    identity = module.runtime_identity()
    if (protocol.get("featureIdentity") != identity or protocol.get("featureDevice") != "mps"
            or backbone["weightsSha256"] != identity["assets"]["model.safetensors"]["sha256"]):
        raise ValueError("Frozen backbone/runtime/device does not match the feature implementation")
    model, processor, load_receipt = module.load_backbone(ROOT / backbone["modelDirectory"], device="mps", contract_receipt=contract)
    feature_rows = []
    started = time.monotonic()
    for parent_index, row in enumerate(rows):
        if time.monotonic() - started > 7200:
            raise TimeoutError("Two-hour extraction invocation budget reached between parents")
        original_probe = module.probe_video(ROOT / row["path"])
        window = module.windows_for_probe(original_probe, mode="train", stable_parent_hash=row["sha256"])[0]
        for quality in ("original", "mild", "severe"):
            identifier = hashlib.sha256((row["id"] + "|dinov2-feature-v1|" + quality).encode()).hexdigest()[:24]
            feature_path = output / "features" / (identifier + ".npz")
            receipt_path = output / "features" / (identifier + ".json")
            media_path, media_receipt = derivative(row, quality, output)
            base = {"id": identifier, "parentId": row["id"], "split": row["split"],
                    "label": row["label"], "generator": row["generator"], "quality": quality,
                    "sourceSha256": row["sha256"], "mediaPath": relative(media_path),
                    "mediaSha256": sha(media_path), "featurePath": relative(feature_path), "window": window}
            bindings = {"protocolSha256": protocol_sha,
                        "acquisitionManifestSha256": configuration["acquisitionManifestSha256"],
                        "backboneSha256": backbone["weightsSha256"],
                        "featureModuleSha256": configuration["featureModuleSha256"],
                        "driverSha256": configuration["driverSha256"]}
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                validate_cached_feature(receipt, feature_path, base, bindings, identity, load_receipt["contract"])
            else:
                if feature_path.exists():
                    raise ValueError("Unreceipted feature exists; preserve and inspect before resuming")
                cls, extraction = module.extract_window(media_path, window, model, processor, "mps")
                if cls.shape != (8, 384) or cls.dtype != np.float32 or not np.isfinite(cls).all():
                    raise ValueError("Unexpected feature shape, dtype or nonfinite value")
                with feature_path.open("xb") as f:
                    np.savez(f, cls=cls)
                receipt = {"row": {**base, "featureSha256": sha(feature_path)}, "bindings": bindings,
                           "mediaConstruction": media_receipt, "extraction": extraction,
                           "labelQualification": "Publisher whole-video weak label; sampled window origin is not independently verified."}
                validate_cached_feature(receipt, feature_path, base, bindings, identity, load_receipt["contract"])
                write_json(receipt_path, receipt)
            feature_rows.append({**receipt["row"], "receiptPath": relative(receipt_path), "receiptSha256": sha(receipt_path)})
        if (parent_index + 1) % 16 == 0 or parent_index == len(rows) - 1:
            print(json.dumps({"parentsComplete": parent_index + 1, "parentsTotal": len(rows),
                              "featuresComplete": len(feature_rows), "elapsedSeconds": time.monotonic() - started}), flush=True)
    if len(feature_rows) != 6912:
        raise ValueError("Incomplete extraction")
    write_json(output / "manifest.json", {**configuration, "complete": True, "rows": feature_rows,
                "elapsedThisInvocationSeconds": time.monotonic() - started,
                "trainingPerformed": False, "productValidation": False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        build(args)
        return
    output = ROOT / args.output
    old_receipts = list(output.glob("watchdog-*.json")) if output.exists() else []
    spent = sum(json.loads(p.read_text())["elapsedSeconds"] for p in old_receipts)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    receipt = supervise(command, timeout_seconds=7200, memory_limit_bytes=8 * 1024 ** 3,
                        prior_elapsed_seconds=spent)
    receipt["driverSha256"] = sha(__file__)
    if output.exists():
        write_json(output / f"watchdog-{len(old_receipts) + 1:03d}.json", receipt)
    print(json.dumps({"featureWatchdog": receipt}), flush=True)
    if receipt["stopReason"] or receipt["exitCode"]:
        raise SystemExit(receipt["exitCode"] if receipt["exitCode"] > 0 else 1)


if __name__ == "__main__":
    main()
