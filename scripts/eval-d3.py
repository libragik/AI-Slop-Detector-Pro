#!/usr/bin/env python3
"""Local D3 temporal-feature candidate; emits scores, never calibrated probabilities.

Adapted from the MIT D3 implementation, commit c798fbc57fe0c4198d63a73732c2c0f9e4b4816c.
See eval/sources/D3-LICENSE.txt. Differences: deterministic center window instead of
random window; raw decoded frames instead of intermediate JPEG files; MPS/CPU.
This is an evaluation candidate, not claimed exact reproduction of paper metrics.
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "eval/models/hf"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import torch
from huggingface_hub import snapshot_download
from transformers import XCLIPVisionModel

MODEL = "microsoft/xclip-base-patch16"
REVISION = "d6184e3fd8780d04c85d0f1eabe5f94bf44d98f6"


def frame_tensor(path, duration, color):
    start = max(0, (duration - 2) / 2)
    vf = "fps=8,crop=if(gt(iw\\,ih)\\,trunc(iw*0.8/2)*2\\,iw):if(gt(iw\\,ih)\\,ih\\,trunc(ih*0.8/2)*2),scale=224:224"
    raw = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(start), "-i", str(path), "-t", "2", "-vf", vf,
        "-frames:v", "16", "-f", "rawvideo", "-pix_fmt", color + "24", "pipe:1"], timeout=30)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 224, 224, 3)
    count = 16 if len(frames) >= 16 else 8
    if len(frames) < count:
        raise ValueError("D3 requires at least eight frames in the sampled window")
    frames = frames[:count].astype(np.float32) / 255
    # The official D3 loader uses cv2.imread without BGR->RGB, followed by this
    # ImageNet normalization. Keep BGR default; --color rgb is an explicit ablation.
    frames = (frames - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
    return torch.from_numpy(frames.transpose(0, 3, 1, 2).copy()), start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="eval/manifest.jsonl")
    parser.add_argument("--split", default="development", choices=["development", "calibration", "holdout"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", default="eval/runs/d3-development.jsonl")
    parser.add_argument("--color", choices=["bgr", "rgb"], default="bgr")
    parser.add_argument("--device", choices=["auto", "cpu", "mps"], default="auto")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    device = "mps" if args.device == "auto" and torch.backends.mps.is_available() else "cpu" if args.device == "auto" else args.device
    rows = [json.loads(line) for line in (ROOT / args.manifest).read_text().splitlines() if line]
    rows = [row for row in rows if row["split"] == args.split][:args.limit]
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    configuration = {"model": MODEL, "revision": REVISION, "device": device, "color": args.color,
                     "window": "center-two-seconds-eight-fps", "sourceSha256": source_hash}
    completed = set()
    if output.exists():
        if not args.resume:
            raise RuntimeError("Output already exists; use a new run path or --resume")
        for row in map(json.loads, output.read_text().splitlines()):
            if row.get("configuration") != configuration:
                raise RuntimeError("Cannot resume changed D3 configuration")
            if not row.get("error"):
                completed.add(row["id"])
    snapshot = snapshot_download(MODEL, revision=REVISION, allow_patterns=["config.json", "model.safetensors", "README.md"])
    model = XCLIPVisionModel.from_pretrained(snapshot, use_safetensors=True, trust_remote_code=False,
        local_files_only=True).eval().to(device)
    torch.set_num_threads(4)
    errors = 0
    for index, row in enumerate(rows, 1):
        if row["id"] in completed:
            continue
        start = time.monotonic()
        result = {**row, "configuration": configuration}
        try:
            path = ROOT / row["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise RuntimeError("Corpus file hash mismatch")
            frames, window_start = frame_tensor(path, row["media"]["durationSeconds"], args.color)
            with torch.inference_mode():
                features = model(frames.to(device)).pooler_output.float()
                distances = torch.linalg.vector_norm(features[1:] - features[:-1], dim=-1)
                second_order = distances[1:] - distances[:-1]
                raw = float(torch.std(second_order).cpu())
            # Official AP evaluation uses 1-y_true (real=positive). Larger D3
            # standard deviation therefore points toward real; negate for AI rank.
            result.update({"d3Raw": raw, "syntheticScore": -raw, "scoreIsProbability": False,
                           "framesAnalyzed": len(frames), "windowStartSeconds": window_start,
                           "windowEndSeconds": window_start + len(frames) / 8})
        except Exception as error:
            errors += 1
            result["error"] = str(error)
        result["elapsedMs"] = round((time.monotonic() - start) * 1000)
        with output.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"completed": index, "selected": len(rows), "id": row["id"],
                          "elapsedMs": result["elapsedMs"], "error": result.get("error")}), flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
