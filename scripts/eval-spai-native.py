#!/usr/bin/env python3
"""Development-only SPAI inference retaining native frames and official patch attention.

No score threshold is fitted here. Inputs outside declared resource bounds fail
explicitly; no implicit resize or center crop is permitted. Code is snapshotted
before model loading and the vendored model executes from that snapshot.
"""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import pathlib
import resource
import subprocess
import time

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def freeze_sources(output):
    snapshot = output.with_suffix(".source")
    snapshot.mkdir(parents=True, exist_ok=False)
    vendor_manifest = json.loads((ROOT / "eval/sources/spai-vendor-manifest.json").read_text())
    files = ["scripts/eval-spai-native.py", "scripts/eval-spai.py", "eval/sources/spai-vendor-manifest.json"]
    files += ["eval/vendor/spai/" + name for name in vendor_manifest["files"]]
    receipts = []
    for name in sorted(files):
        data = (ROOT / name).read_bytes()
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        receipts.append({"path": name, "sha256": digest(data)})
    # The existing hash-pinned safetensors are read once into memory. Model
    # executable code is copied; the large immutable weights need not be copied.
    weight_target = snapshot / "eval/vendor/spai/weights/model.safetensors"
    weight_target.parent.mkdir(parents=True, exist_ok=True)
    weight_target.symlink_to(ROOT / "eval/vendor/spai/weights/model.safetensors")
    (snapshot / "source-manifest.json").write_text(json.dumps(receipts, indent=2) + "\n")
    spec = importlib.util.spec_from_file_location("frozen_spai_helper", snapshot / "scripts/eval-spai.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    # The copied helper derives ROOT from its snapshot location and therefore
    # imports the snapshotted vendor modules and YAML, not live workspace code.
    if helper.ROOT != snapshot:
        raise ValueError("Frozen helper did not resolve the snapshot root")
    return helper, snapshot, receipts


def native_frames(path, count, max_dimension, max_pixels):
    raw_probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:stream_side_data=rotation:format=duration",
        "-of", "json", str(path),
    ], timeout=15)
    probe = json.loads(raw_probe)
    stream = probe["streams"][0]
    width, height = int(stream["width"]), int(stream["height"])
    duration = float(probe["format"]["duration"])
    if not 0 < duration <= 60:
        raise ValueError("Native-frame resource bound: duration must be greater than0 and at most60 seconds")
    if min(width, height) < 224 or max(width, height) > max_dimension or width * height > max_pixels:
        raise ValueError("Native-frame resource bound: dimensions outside declared bounds; no resize/crop fallback")
    if any(item.get("rotation", 0) != 0 for item in stream.get("side_data_list", [])):
        raise ValueError("Rotated input is outside this bounded study; no implicit orientation transform")
    expected = count * width * height * 3
    raw = subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1",
        "-i", str(path), "-vf", f"fps={count / duration}", "-frames:v", str(count),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], timeout=30)
    if len(raw) != expected:
        raise ValueError("Unexpected native-frame bytes or frame count")
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(count, height, width, 3)
    tensor = torch.from_numpy(frames.astype(np.float32).transpose(0, 3, 1, 2).copy()) / 255
    grid_patches = (height // 224) * (width // 224)
    return tensor, {"width": width, "height": height, "durationSeconds": duration,
                    "patchesPerFrame": grid_patches if grid_patches >= 4 else 5,
                    "fiveCropFallback": grid_patches < 4}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="eval/smoke-manifest.jsonl")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    parser.add_argument("--max-dimension", type=int, default=1024)
    parser.add_argument("--max-pixels", type=int, default=1024 * 1024)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.frames <= 16 or not 224 <= args.max_dimension <= 2048 or not 224 ** 2 <= args.max_pixels <= 2048 ** 2:
        raise ValueError("Requested frame/dimension bounds exceed the bounded evaluator")
    output = ROOT / args.output
    if output.exists():
        raise ValueError("Use a fresh output path")
    manifest_bytes = (ROOT / args.manifest).read_bytes()
    rows = [json.loads(line) for line in manifest_bytes.splitlines() if line]
    if any(row["split"] != "development" for row in rows):
        raise ValueError("This candidate study accepts development-only manifests")
    rows = rows[:args.limit]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Empty or duplicate candidate selection")
    output.parent.mkdir(parents=True, exist_ok=True)
    helper, snapshot, source_files = freeze_sources(output)
    torch.set_num_threads(4)
    model, source = helper.load_model(args.device)
    if model.img_patch_size != 224 or model.img_patch_stride != 224 or model.minimum_patches != 4:
        raise ValueError("Unexpected official patch extraction configuration")
    config = {
        "model": "mever-team/spai", "revision": source["revision"], "safetensorsSha256": helper.SAFE_SHA,
        "device": args.device, "fftDevice": "cpu", "frames": args.frames, "aggregation": "mean-logit",
        "preprocessing": "uniform-native-full-frame-rgb-unit-range-official-arbitrary-resolution-patch-attention",
        "sourceSnapshot": str(snapshot.relative_to(ROOT)), "sourceFingerprint": digest(json.dumps(source_files, sort_keys=True).encode()),
        "manifestSha256": digest(manifest_bytes), "maxDimension": args.max_dimension, "maxPixels": args.max_pixels,
        "minimumDimension": 224, "maxDurationSeconds": 60, "maxFileBytes": 20_000_000,
        "featureExtractionBatchSize": 8, "torchThreads": 4, "workers": 1,
        "torchVersion": torch.__version__, "torchvisionVersion": importlib.metadata.version("torchvision"),
        "scoreIsProbability": False,
    }
    errors = 0
    for index, row in enumerate(rows, 1):
        started = time.monotonic()
        result = {**row, "configuration": config}
        try:
            path = ROOT / row["path"]
            if path.stat().st_size > config["maxFileBytes"]:
                raise ValueError("Native-frame resource bound: file exceeds20MB")
            if digest(path.read_bytes()) != row["sha256"]:
                raise ValueError("Corpus hash mismatch")
            batch, receipt = native_frames(path, args.frames, args.max_dimension, args.max_pixels)
            batch = batch.to(args.device)
            with torch.inference_mode():
                scores = model([frame.unsqueeze(0) for frame in batch], feature_extraction_batch_size=8).float().cpu().flatten().tolist()
            if len(scores) != args.frames or not np.isfinite(scores).all():
                raise ValueError("Invalid native-frame model score count or value")
            result.update({"syntheticScore": float(np.mean(scores)), "frameScores": scores,
                           "scoreIsProbability": False, "framesAnalyzed": len(scores), "nativeFrameReceipt": receipt})
        except Exception as error:
            result.update({"error": str(error), "decision": "abstain"})
            errors += 1
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        # macOS reports ru_maxrss in bytes; preserve platform-specific units.
        result["processMaxRssBytesMacOS"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        with output.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"completed": index, "selected": len(rows), "id": row["id"], "elapsedMs": result["elapsedMs"], "error": result.get("error")}), flush=True)
        if errors >= 3:
            raise SystemExit("Three errors; stopping specialist study")
    (output.with_suffix(".receipt.json")).write_text(json.dumps({"configuration": config, "selected": len(rows),
        "errors": errors, "outputSha256": digest(output.read_bytes()), "sourceFiles": source_files}, indent=2) + "\n")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
