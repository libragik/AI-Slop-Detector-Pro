#!/usr/bin/env python3
"""Evaluate the Apache-2 SAFE image checkpoint on sampled video frames.

Official model and preprocessing are audited, pinned below. Image-to-video
adaptation: eight uniform frames, native-resolution center crop 256, mean logits.
The emitted score is a ranking statistic, not a calibrated video probability.
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import time
import urllib.request

import numpy as np
import torch
from safetensors.torch import load_file, save_file

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVISION = "4e998724651b227def64f5be0cd60c0aa1552c35"
BASE = f"https://raw.githubusercontent.com/Ouxiang-Li/SAFE/{REVISION}/"
FILES = {
    "models/resnet.py": "f0d3956e8586f0c122a06f2b674799f21b82d65690b3460b06e15679ae7be528",
    "checkpoint/checkpoint-best.pth": "b3f5ecfb46a154ed553aaaf4bf3ba59182310726ddb0cbb1fe42bd0e22d2f20e",
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_model(device):
    vendor = ROOT / "eval/vendor/safe"
    for name, expected in FILES.items():
        path = vendor / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(BASE + name, timeout=30) as response:
                data = response.read(20_000_001)
            if len(data) > 20_000_000 or digest(data) != expected:
                raise ValueError("Pinned SAFE download failed integrity/size check")
            path.write_bytes(data)
        if digest(path.read_bytes()) != expected:
            raise ValueError(f"Pinned SAFE source/checkpoint hash mismatch: {name}")
    # Never permit general pickle execution. The original restricted load must
    # be a tensor-only model dictionary; subsequent inference uses safetensors.
    state = torch.load(vendor / "checkpoint/checkpoint-best.pth", map_location="cpu", weights_only=True)["model"]
    if not all(isinstance(key, str) and isinstance(value, torch.Tensor) for key, value in state.items()):
        raise ValueError("Expected a tensor-only state dictionary")
    safe_path = vendor / "checkpoint/model.safetensors"
    save_file({key: value.contiguous() for key, value in state.items()}, str(safe_path))
    spec = importlib.util.spec_from_file_location("audited_safe_resnet", vendor / "models/resnet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.resnet50(pretrained=False)
    model.load_state_dict(load_file(str(safe_path)), strict=True)
    return model.eval().to(device), digest(safe_path.read_bytes())


def frames(path, duration, count):
    vf = f"fps={count / duration},crop=min(iw\\,256):min(ih\\,256),pad=256:256:(ow-iw)/2:(oh-ih)/2"
    raw = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(path), "-vf", vf, "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=30)
    images = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 256, 256, 3)
    if len(images) != count:
        raise ValueError(f"Expected {count} frames, decoded {len(images)}")
    return torch.from_numpy(images.astype(np.float32).transpose(0, 3, 1, 2).copy()) / 255


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="eval/manifest.jsonl")
    parser.add_argument("--split", default="development", choices=["development", "calibration", "holdout"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", default="eval/runs/safe-development.jsonl")
    parser.add_argument("--device", choices=["mps", "cpu"], default="mps")
    parser.add_argument("--frames", type=int, default=8)
    args = parser.parse_args()
    if args.frames < 1 or args.frames > 32:
        raise ValueError("Frame count must be 1 through 32")
    rows = [json.loads(line) for line in (ROOT / args.manifest).read_text().splitlines() if line]
    rows = [row for row in rows if row["split"] == args.split][:args.limit]
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Use a fresh output path")
    model, weights_sha = load_model(args.device)
    torch.set_num_threads(4)
    config = {"model": "Ouxiang-Li/SAFE", "revision": REVISION, "checkpointSha256": FILES["checkpoint/checkpoint-best.pth"],
        "safetensorsSha256": weights_sha, "device": args.device, "frames": args.frames,
        "preprocessing": "uniform-center-crop256-rgb-unit-range", "aggregation": "mean-logit-difference",
        "sourceSha256": digest(pathlib.Path(__file__).read_bytes())}
    errors = 0
    for index, row in enumerate(rows, 1):
        start = time.monotonic()
        result = {**row, "configuration": config}
        try:
            path = ROOT / row["path"]
            if digest(path.read_bytes()) != row["sha256"]:
                raise ValueError("Corpus hash mismatch")
            batch = frames(path, row["media"]["durationSeconds"], args.frames).to(args.device)
            with torch.inference_mode():
                logits = model(batch).float().cpu()
            scores = (logits[:, 1] - logits[:, 0]).tolist()
            result.update({"syntheticScore": float(np.mean(scores)), "frameScores": scores,
                "scoreIsProbability": False, "framesAnalyzed": len(scores)})
        except Exception as error:
            errors += 1
            result["error"] = str(error)
        result["elapsedMs"] = round((time.monotonic() - start) * 1000)
        with output.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"completed": index, "selected": len(rows), "id": row["id"], "error": result.get("error")}), flush=True)
        if errors >= 3:
            raise SystemExit("Three errors; stopping specialist experiment")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
