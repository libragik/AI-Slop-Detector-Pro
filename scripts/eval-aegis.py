#!/usr/bin/env python3
"""Frozen development-only AEGIS benchmark: CPU, one centered window, one clip.

Upstream tensor computation is unmodified, including the FFT-axis behavior.
Only local, SHA-verified safetensors may initialize the complete model. Missing
weights or requested source frames are errors; there is no inference fallback.
"""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "eval/vendor/aegis"
RUNTIME = ROOT / "eval/vendor/aegis-runtime"
VENDOR_RECEIPT = ROOT / "eval/sources/aegis-vendor-manifest.json"
PROTOCOL = ROOT / "eval/AEGIS_EVALUATION_PROTOCOL.md"
REVISION = "d86a774fd971954a023e1cd00ed7ff5b2575e0d1"
PROTOCOL_SHA = "bde1f478fa3c2346cd8da014825f421f66376a31a4a88cbc6d216adc3987f171"
CONTROL_MANIFEST = ROOT / "eval/generated-origin-manifest.jsonl"
CONTROL_MANIFEST_SHA = "122b79147249eab01d06e0fbd0b33955fc86eb9479d8df1697fd123c480b8b55"
SMOKE_MANIFEST = ROOT / "eval/smoke-manifest.jsonl"
SMOKE_MANIFEST_SHA = "a73696821312e5e286d9b96906331129a36ed912f281389e0eae43cfb2c8909f"
TRANSFORMED_MANIFEST = ROOT / "eval/transformed-manifest.jsonl"
TRANSFORMED_MANIFEST_SHA = "a9a7b07a9e8513b753fb879e9e41154454d789a34c9fcf6edb7755e615db7fa1"
WEIGHTS_SHA = "c464af41b7528f18c1a3de748dde4dc5171aafaf8469c8848036ac45329ae474"
CONVERSION_RECEIPT = ROOT / "eval/sources/aegis-safe-conversion-receipt.json"
CONVERSION_RECEIPT_SHA = "6291fcea81af08892c6646bd5bb6f6e969de6fa7a2bf68722250b0faef7141e9"
SEED = 20260905


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def selection(manifest):
    if sha(CONTROL_MANIFEST) != CONTROL_MANIFEST_SHA or sha(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError("Preregistered control manifest or protocol changed")
    if sha(SMOKE_MANIFEST) != SMOKE_MANIFEST_SHA or sha(TRANSFORMED_MANIFEST) != TRANSFORMED_MANIFEST_SHA:
        raise ValueError("Preregistered original or transformed cohort changed")
    rows = read_rows(manifest)
    if not rows or any(row.get("split") != "development" for row in rows):
        raise ValueError("Only the registered development cohorts may be evaluated")
    selected = {row["id"]: row for row in rows}
    if len(selected) != len(rows):
        raise ValueError("Duplicate evaluation IDs")
    controls = read_rows(CONTROL_MANIFEST)
    originals = read_rows(SMOKE_MANIFEST)
    groups = {row["groupId"] for row in originals}
    original_ids = {row["id"] for row in originals}
    social = [row for row in read_rows(TRANSFORMED_MANIFEST)
              if row["groupId"] in groups and row["id"] not in original_ids]
    if len(controls) != 3 or len(originals) != 35 or len(social) != 70:
        raise ValueError("Unexpected registered cohort dimensions")
    cohorts = {"controls": controls, "originals": originals, "social": social,
               "originals-and-social": originals + social}
    for name, cohort in cohorts.items():
        registered = {row["id"]: row for row in cohort}
        if set(selected) == set(registered):
            for key, row in selected.items():
                if any(row.get(field) != registered[key].get(field)
                       for field in ("sha256", "groupId", "path", "label", "split")):
                    raise ValueError("Manifest does not match registered source identity")
            return rows, name, controls
    raise ValueError("Selection must be exactly three controls, 35 originals, 70 derivatives, or 105 paired files")


def freeze_sources(output, manifest):
    receipt = json.loads(VENDOR_RECEIPT.read_text())
    if receipt["revision"] != REVISION or not receipt["unchangedUpstreamSources"]:
        raise ValueError("Incorrect pinned upstream source receipt")
    snapshot = output.with_suffix(".source")
    snapshot.mkdir(parents=True, exist_ok=False)
    files = []
    for name, expected in receipt["files"].items():
        source = VENDOR / name
        if sha(source) != expected["sha256"]:
            raise ValueError(f"Official source hash mismatch: {name}")
        target = snapshot / "vendor" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files.append({"path": "vendor/" + name, "sha256": sha(target)})
    for source, name in [(Path(__file__), "eval-aegis.py"),
                         (VENDOR_RECEIPT, "vendor-manifest.json"),
                         (CONVERSION_RECEIPT, "weight-conversion-receipt.json"),
                         (PROTOCOL, "protocol.md"), (manifest, "manifest.jsonl")]:
        shutil.copyfile(source, snapshot / name)
        files.append({"path": name, "sha256": sha(snapshot / name)})
    (snapshot / "source-manifest.json").write_text(json.dumps(files, indent=2) + "\n")
    return snapshot, files


def runtime_modules():
    # The isolated timm release must not replace the older shared D3 runtime.
    if not (RUNTIME / "timm").is_dir():
        raise ValueError("Isolated timm==1.0.27 runtime has not been prepared")
    sys.path.insert(0, str(RUNTIME))
    import cv2
    import numpy as np
    import torch
    import timm
    from safetensors.torch import load_file
    if timm.__version__ != "1.0.27" or not Path(timm.__file__).resolve().is_relative_to(RUNTIME):
        raise ValueError("Exact isolated timm==1.0.27 is required")
    if not cv2.__version__.startswith("4.13.") or not Path(cv2.__file__).resolve().is_relative_to(RUNTIME):
        raise ValueError("An isolated, pinned OpenCV4.13 release is required")
    opencv_distribution = importlib.metadata.version("opencv-python")
    if opencv_distribution != "4.13.0.92":
        raise ValueError("Exact isolated opencv-python==4.13.0.92 is required")
    cv2.setNumThreads(1)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    random.seed(SEED)
    versions = {name: importlib.metadata.version(name) for name in
                ("torch", "torchvision", "numpy", "einops", "safetensors")}
    versions.update({"timm": timm.__version__, "opencv": cv2.__version__,
                     "opencvDistribution": opencv_distribution,
                     "python": sys.version.split()[0]})
    timm_files = [{"path": str(path.relative_to(RUNTIME)), "sha256": sha(path)}
                  for path in sorted((RUNTIME / "timm").rglob("*.py"))]
    return cv2, np, torch, timm, load_file, versions, timm_files


def load_model(snapshot, weights, torch, timm, load_file):
    branch_dir = snapshot / "vendor/src/branches"
    utils_dir = snapshot / "vendor/src/utils"
    sys.path.insert(0, str(utils_dir))
    sys.path.insert(0, str(branch_dir))
    pixel = importlib.import_module("pixel_branch")

    def architecture_only_dino():
        # Exact timm constructor arguments from upstream, with no checkpoint or
        # network access. The complete detector state replaces every tensor.
        return timm.create_model("vit_base_patch14_dinov2", pretrained=False,
                                 num_classes=0, global_pool="avg", img_size=224)

    pixel._load_dinov2_224 = architecture_only_dino
    detector = importlib.import_module("detector_model")
    video_io = importlib.import_module("video_io")
    for name in ("pixel_branch", "detector_model", "motion_branch", "consistency_branch", "video_io"):
        if not Path(sys.modules[name].__file__).resolve().is_relative_to(snapshot):
            raise ValueError("Model source escaped the immutable snapshot")
    model = detector.VideoForensicsDetector(freeze_dino=True).cpu().float()
    state = load_file(str(weights), device="cpu")
    expected = model.state_dict()
    if set(state) != set(expected):
        raise ValueError(f"Incomplete checkpoint: missing={len(set(expected)-set(state))}, unexpected={len(set(state)-set(expected))}")
    for name, tensor in state.items():
        if tensor.shape != expected[name].shape or tensor.dtype != expected[name].dtype:
            raise ValueError(f"Checkpoint tensor shape/dtype mismatch: {name}")
        if tensor.is_floating_point() and not torch.isfinite(tensor).all():
            raise ValueError(f"Nonfinite checkpoint tensor: {name}")
    model.load_state_dict(state, strict=True)
    if len(state) == 0 or not any(name.startswith("pixel_branch.dino.backbone.") for name in state):
        raise ValueError("Complete DINO backbone state was not supplied")
    receipt = {"strict": True, "tensorCount": len(state),
               "tensorElements": sum(t.numel() for t in state.values()),
               "parameters": sum(p.numel() for p in model.parameters()),
               "fullBackboneSupplied": True, "architectureOnlyInitialization": True}
    del state, expected
    model.eval()
    return model, video_io, receipt


def strict_frames(path, video_io, cv2, np):
    # Reuse official quality, centered-window indexing and normalization, while
    # refusing the stock decoder's fabricated frames when actual decoding fails.
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
        "stream=index,width,height:stream_side_data=rotation", "-of", "json", str(path),
    ], timeout=15))
    streams = probe.get("streams", [])
    if len(streams) != 1 or any(item.get("rotation", 0) != 0 for item in streams[0].get("side_data_list", [])):
        raise ValueError("Multiple video streams or rotated media are outside this bounded contract")
    meta = video_io.check_video_quality(str(path))
    if (max(meta["width"], meta["height"]) > 2048 or meta["duration"] > 120
            or meta["total_frames"] > 30000):
        raise ValueError("Input exceeds registered operational resource bounds")
    indices = video_io.window_sample(meta["total_frames"], 16, meta["fps"],
                                     target_dur=4.0, random_start=False)
    wanted = set(int(i) for i in indices)
    captured, times = {}, {}
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Unable to open video for strict decoding")
    try:
        index = 0
        while index <= max(wanted):
            ok, bgr = cap.read()
            if not ok:
                raise ValueError(f"Decode ended before requested frame {max(wanted)}; stopped at {index}")
            if index in wanted:
                if bgr.shape != (meta["height"], meta["width"], 3):
                    raise ValueError("Decoded native frame shape changed")
                captured[index] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                timestamp = float(cap.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                times[index] = timestamp if math.isfinite(timestamp) else None
            index += 1
    finally:
        cap.release()
    if set(captured) != wanted:
        raise ValueError("A requested source frame was not decoded")
    frames = np.stack([captured[int(i)] for i in indices])
    tensor = video_io.preprocess_frames(frames, height=224, width=224)
    if tuple(tensor.shape) != (16, 3, 224, 224):
        raise ValueError("Official preprocessing shape mismatch")
    receipt = {"metadata": meta, "ffprobeVideoStreams": streams,
               "sampling": "centered-four-second-window",
               "requestedFrameIndices": [int(i) for i in indices],
               "nominalSourceTimesSeconds": [float(i / meta["fps"]) for i in indices],
               "decoderTimesSeconds": [times[int(i)] for i in indices],
               "decoderTimestampCaveat": "OpenCV-reported timestamp; nominal index/fps also retained",
               "decodedUniqueIndices": sorted(captured),
               "duplicatedRequestedIndices": len(indices) - len(wanted),
               "nativeShape": list(frames.shape), "inputShape": [1, 16, 3, 224, 224],
               "rgbFrameSha256": [hashlib.sha256(frame.tobytes()).hexdigest() for frame in frames],
               "normalizedTensorSha256": hashlib.sha256(tensor.numpy().tobytes()).hexdigest(),
               "decoder": "OpenCV sequential RGB; strict unique requested frame coverage"}
    return tensor.unsqueeze(0), receipt


def validate_gate(path, controls, recipe_hash):
    if not path:
        raise ValueError("Successful three-control gate receipt is required before cohort inference")
    rows = read_rows(path)
    receipt = json.loads(Path(path).with_suffix(".receipt.json").read_text())
    if (receipt.get("completed") != 3 or receipt.get("errors") != 0
            or not receipt.get("safetensorsUnchanged") or receipt.get("outputSha256") != sha(path)):
        raise ValueError("Gate run is incomplete, changed, or has errors")
    indexed = {row["id"]: row for row in rows}
    if len(rows) != 3 or set(indexed) != {row["id"] for row in controls}:
        raise ValueError("Gate results do not match the three registered controls")
    for control in controls:
        result = indexed[control["id"]]
        positive = control["label"] in ("ai", "mixed")
        score = result.get("syntheticScore")
        if (result.get("error") or result["sha256"] != control["sha256"]
                or result["configuration"]["recipeFingerprint"] != recipe_hash
                or not isinstance(score, (int, float)) or not math.isfinite(score)
                or (score >= 0.5) != positive
                or result.get("decision") != ("ai" if positive else "not_ai")):
            raise ValueError("Known-origin control gate failed or used a different model recipe")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--gate-results")
    args = parser.parse_args()
    manifest, output, weights = (ROOT / value for value in (args.manifest, args.output, args.weights))
    if output.exists() or output.with_suffix(".receipt.json").exists():
        raise ValueError("Use a fresh output path; prior evidence is immutable")
    if weights.suffix != ".safetensors" or not weights.is_file():
        raise ValueError("An existing local safetensors model is required")
    if (args.weights_sha256 != WEIGHTS_SHA or sha(weights) != WEIGHTS_SHA
            or sha(CONVERSION_RECEIPT) != CONVERSION_RECEIPT_SHA):
        raise ValueError("Safetensors SHA-256 mismatch")
    rows, cohort, controls = selection(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot, source_files = freeze_sources(output, manifest)
    cv2, np, torch, timm, load_file, versions, timm_files = runtime_modules()
    recipe = {"model": "MusapYildiz/aegis-video-detector", "revision": REVISION,
              "safetensorsSha256": args.weights_sha256, "device": "cpu", "dtype": "float32",
              "batchSize": 1, "workers": 1, "torchThreads": 4, "torchInteropThreads": 1,
              "opencvThreads": 1, "seed": SEED, "frames": 16, "windowSeconds": 4,
              "randomStart": False, "threshold": 0.5, "comparator": ">=",
              "head": "main-fused", "upstreamFftShiftAllAxesPreserved": True,
              "scoreIsProbability": False, "confidence": None,
              "maxFileBytes": 50_000_000, "maxDimension": 2048, "maxDurationSeconds": 120,
              "maxTotalFrames": 30000, "perClipTimeoutSeconds": 120,
              "conversionReceiptSha256": CONVERSION_RECEIPT_SHA,
              "cohortReferenceSha256": {"controls": CONTROL_MANIFEST_SHA,
                                        "originals": SMOKE_MANIFEST_SHA,
                                        "transformed": TRANSFORMED_MANIFEST_SHA},
              "protocolSha256": PROTOCOL_SHA, "runtimeVersions": versions,
              "timmSourceFingerprint": fingerprint(timm_files),
              "sourceFingerprint": fingerprint([f for f in source_files if f["path"] != "manifest.jsonl"])}
    config = {**recipe, "recipeFingerprint": fingerprint(recipe),
              "manifestSha256": sha(manifest), "cohort": cohort}
    if cohort != "controls":
        validate_gate(ROOT / args.gate_results if args.gate_results else None, controls, config["recipeFingerprint"])
    receipt_path = output.with_suffix(".receipt.json")
    receipt = {"configuration": config, "sourceSnapshot": str(snapshot.relative_to(ROOT)),
               "sourceFiles": source_files, "timmSourceFiles": timm_files,
               "startedAtUnix": time.time(), "selected": len(rows), "completed": 0, "errors": 0}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    try:
        model, video_io, load_receipt = load_model(snapshot, weights, torch, timm, load_file)
    except Exception as error:
        receipt.update({"setupError": str(error), "setupErrorType": type(error).__name__,
                        "finishedAtUnix": time.time()})
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    receipt["modelLoading"] = load_receipt
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")

    def timeout_handler(signum, frame):
        raise TimeoutError("Per-clip operation exceeded120 seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    with output.open("x") as stream:
        for row in rows:
            started = time.monotonic()
            result = {**row, "configuration": config}
            signal.alarm(120)
            try:
                path = ROOT / row["path"]
                if path.stat().st_size > recipe["maxFileBytes"] or sha(path) != row["sha256"]:
                    raise ValueError("Input file size or SHA-256 failed validation")
                tensor, frame_receipt = strict_frames(path, video_io, cv2, np)
                result.update({"frameReceipt": frame_receipt, "framesDecoded": 16})
                if not torch.isfinite(tensor).all():
                    raise ValueError("Nonfinite preprocessed input")
                with torch.inference_mode():
                    outputs = model(tensor)
                values = {}
                for name, value in outputs.items():
                    if not isinstance(value, torch.Tensor) or not torch.isfinite(value).all():
                        raise ValueError(f"Invalid model output: {name}")
                    values[name] = value.detach().cpu().tolist()
                score = float(outputs["ai_probability"].item())
                logit = float(outputs["ai_logit"].item())
                if not 0 <= score <= 1 or abs(score - (1 / (1 + math.exp(-max(-700, min(700, logit)))))) > 1e-5:
                    raise ValueError("Main score/logit contract mismatch")
                result.update({"syntheticScore": score, "fusedLogit": logit,
                               "decision": "ai" if score >= 0.5 else "not_ai",
                               "scoreIsProbability": False, "framesAnalyzed": 16,
                               "frameReceipt": frame_receipt, "rawOutputs": values})
            except Exception as error:
                receipt["errors"] += 1
                result.update({"error": str(error), "errorType": type(error).__name__, "decision": "abstain"})
            finally:
                signal.alarm(0)
            result["elapsedMs"] = round((time.monotonic() - started) * 1000)
            result["processMaxRssBytesMacOS"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            stream.write(json.dumps(result, sort_keys=True) + "\n")
            stream.flush()
            receipt["completed"] += 1
            print(json.dumps({"id": row["id"], "completed": receipt["completed"],
                              "selected": len(rows), "elapsedMs": result["elapsedMs"],
                              "error": result.get("error")}), flush=True)
    receipt.update({"finishedAtUnix": time.time(), "outputSha256": sha(output),
                    "safetensorsUnchanged": sha(weights) == args.weights_sha256,
                    "runnerUnchanged": sha(Path(__file__)) == sha(snapshot / "eval-aegis.py")})
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["errors"] or not receipt["safetensorsUnchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
