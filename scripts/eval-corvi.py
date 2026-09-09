#!/usr/bin/env python3
"""Local development-only video adaptation of official Corvi ICASSP2023 weights.

Preserves the official full native RGB frame, ImageNet normalization and mean
spatial logit. Eight uniformly sampled frame logits are averaged for video QA;
that temporal adaptation is not an official or validated video detector.
Inference loads verified safetensors only and executes copied, pinned source.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import pathlib
import shutil
import subprocess
import time

import numpy as np
import torch
from PIL import Image
from safetensors.torch import load_file

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "eval/vendor/corvi"
SAFE_SHA = "8b7c1a9f463746dc6cf2fda33036b4ad0c48bc82fe3ef503d26c91162563e66a"
SAFE_PATH = VENDOR / "weights/Grag2021_latent/model_epoch_best.safetensors"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def freeze_sources(output):
    receipt_path = ROOT / "eval/sources/corvi-source-verification.json"
    receipt = json.loads(receipt_path.read_text())
    frozen = output.with_suffix(".source")
    frozen.mkdir()
    for name, entry in receipt["verifiedFiles"].items():
        source = VENDOR / name
        if sha(source) != entry["sha256"]:
            raise ValueError(f"Official source integrity mismatch: {name}")
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(__file__, frozen / "eval-corvi.py")
    shutil.copyfile(receipt_path, frozen / "source-verification.json")
    return frozen, receipt


def decode_native_frames(path, count):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-show_format", "-of", "json", str(path)], timeout=15))
    stream = probe["streams"][0]
    width, height = stream["width"], stream["height"]
    duration = float(probe["format"]["duration"])
    if not (0 < duration <= 120 and 0 < width <= 1536 and 0 < height <= 1536):
        raise ValueError("Native image exceeds this bounded experiment; refusing implicit resize/crop")
    raw = subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-noautorotate",
        "-i", str(path), "-map", "0:v:0", "-vf", f"fps={count / duration}",
        "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=30)
    expected_bytes = count * width * height * 3
    if len(raw) != expected_bytes:
        raise ValueError("Unexpected native decoded frame dimensions/count")
    return np.frombuffer(raw, dtype=np.uint8).reshape(count, height, width, 3), duration


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    args = parser.parse_args()
    if args.frames != 8:
        raise ValueError("This fixed development experiment uses eight frames")
    if args.device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS requested but unavailable; no implicit device fallback")
    manifest = ROOT / args.manifest
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line]
    if not 1 <= len(rows) <= 35 or any(row["split"] != "development" for row in rows):
        raise ValueError("Only one through 35 existing development clips are authorized")
    output = ROOT / args.output
    if output.exists():
        raise ValueError("Use a fresh output path; existing evidence is preserved")
    if sha(SAFE_PATH) != SAFE_SHA:
        raise ValueError("Verified safetensors required; checkpoint loading is unavailable")
    output.parent.mkdir(parents=True, exist_ok=True)
    frozen, source = freeze_sources(output)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    architecture = load_module(frozen / "test_code/networks/resnet_mod.py", "corvi_frozen_architecture")
    normalization = load_module(frozen / "test_code/normalization.py", "corvi_frozen_normalization")
    model = architecture.resnet50(pretrained=False, num_classes=1, gap_size=1, stride0=1)
    model.load_state_dict(load_file(str(SAFE_PATH), device="cpu"), strict=True)
    model.eval().to(args.device)
    transforms = normalization.get_list_norm("resnet")
    configuration = {
        "model": "grip-unina/DMimageDetection:Grag2021_latent", "revision": source["revision"],
        "safetensorsSha256": SAFE_SHA, "device": args.device, "threads": 4, "frames": 8,
        "architecture": "resnet50-num_classes1-gap_size1-stride0_1",
        "preprocessing": "native-full-frame-rgb-imagenet-normalization-no-resize-no-crop",
        "spatialAggregation": "mean-logit", "temporalAggregation": "mean-frame-logit",
        "publishedImageDecision": "logit > 0 means synthetic", "threshold": 0,
        "videoAdaptationValidated": False, "scoreIsProbability": False,
        "runnerSha256": sha(frozen / "eval-corvi.py"),
        "sourceReceiptSha256": sha(frozen / "source-verification.json"),
        "manifestSha256": sha(manifest), "torchVersion": torch.__version__,
    }
    plan = {"startedAtUnix": time.time(), "configuration": configuration,
            "sourceSnapshot": str(frozen.relative_to(ROOT)), "selected": len(rows)}
    plan_path = output.with_suffix(".receipt.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    errors = 0
    for index, row in enumerate(rows, 1):
        start = time.monotonic()
        result = {**row, "configuration": configuration}
        try:
            path = ROOT / row["path"]
            if sha(path) != row["sha256"]:
                raise ValueError("Corpus hash mismatch")
            frames, duration = decode_native_frames(path, args.frames)
            scores, shapes, map_shapes = [], [], []
            with torch.inference_mode():
                for frame in frames:
                    tensor = Image.fromarray(frame).convert("RGB")
                    for transform in transforms:
                        tensor = transform(tensor)
                    if tuple(tensor.shape) != (3, frame.shape[0], frame.shape[1]):
                        raise ValueError("Full-frame preprocessing contract violated")
                    score_map = model(tensor.unsqueeze(0).to(args.device))
                    if score_map.ndim != 4 or tuple(score_map.shape[:2]) != (1, 1):
                        raise ValueError("Unexpected official spatial score output")
                    scores.append(float(score_map.mean().item()))
                    shapes.append(list(tensor.shape))
                    map_shapes.append(list(score_map.shape))
            if len(scores) != 8 or not all(math.isfinite(score) for score in scores):
                raise ValueError("Invalid frame logits")
            score = float(np.mean(scores))
            result.update({"syntheticScore": score, "frameScores": scores,
                "decision": "ai" if score > 0 else "not_ai", "scoreIsProbability": False,
                "framesAnalyzed": len(scores), "inputFrameShapes": shapes,
                "outputScoreMapShapes": map_shapes, "durationSecondsVerified": duration})
        except Exception as error:
            errors += 1
            result["error"] = str(error)
        result["elapsedMs"] = round((time.monotonic() - start) * 1000)
        with output.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"completed": index, "selected": len(rows), "id": row["id"],
            "elapsedMs": result["elapsedMs"], "error": result.get("error")}), flush=True)
        if errors:
            break
    plan.update({"finishedAtUnix": time.time(), "completed": index, "errors": errors,
        "safetensorsUnchanged": sha(SAFE_PATH) == SAFE_SHA,
        "runnerUnchanged": sha(pathlib.Path(__file__)) == configuration["runnerSha256"]})
    plan["elapsedSeconds"] = plan["finishedAtUnix"] - plan["startedAtUnix"]
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
