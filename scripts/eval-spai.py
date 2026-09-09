#!/usr/bin/env python3
"""Bounded development evaluation of the official Apache-2 SPAI checkpoint.

Image-to-video adaptation: eight uniform native center crops, 256 pixels, mean
frame logits. FFT is performed on CPU, with the vision model on MPS by default.
No checkpoint config is executed. Restricted conversion allows only audited YACS
CfgNode and fails on any other unsupported global; inference uses safetensors.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

import numpy as np
import torch
from safetensors.torch import load_file, save_file
from yacs.config import CfgNode

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "eval/vendor/spai"
CHECKPOINT_SHA = "24159f27d7c8c2cd0cb6c4019189eb89ad0874a0d9d15f8dc9afd39ca9648a55"
SAFE_SHA = "2f713987c34dbbbddc5cc02e53d5990d77f15c66d814f9dff2194e2faeb35fd9"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare_sources():
    manifest = json.loads((ROOT / "eval/sources/spai-vendor-manifest.json").read_text())
    # Disable unused optional backbone downloads and plot exports. These edits
    # do not change the MFM model forward path selected by the official YAML.
    edits = {
        "spai/models/backbones.py": ("import clip\n", "# Evaluation adapter: optional CLIP path disabled.\nclip = None\n"),
        "spai/models/sid.py": ("from spai.utils import save_image_with_attention_overlay\n",
            "# Evaluation adapter: export-only plotting dependency disabled.\ndef save_image_with_attention_overlay(*args, **kwargs):\n    raise RuntimeError('Attention image exports disabled in this evaluation')\n"),
    }
    for name, expected in manifest["files"].items():
        path = VENDOR / name
        if not path.exists():
            url = f"https://raw.githubusercontent.com/mever-team/spai/{manifest['revision']}/{name}"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(1_000_001)
            if len(data) > 1_000_000 or digest(data) != expected:
                raise ValueError("Pinned SPAI source integrity/size mismatch")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        data = path.read_text()
        if name in edits:
            old, new = edits[name]
            original = data.replace(new, old)
            if digest(original.encode()) != expected:
                raise ValueError(f"Pinned SPAI original source mismatch: {name}")
            path.write_text(original.replace(old, new))
        elif digest(path.read_bytes()) != expected:
            raise ValueError(f"Pinned SPAI source mismatch: {name}")
    return manifest


def load_model(device):
    manifest = prepare_sources()
    safe_path = VENDOR / "weights/model.safetensors"
    if not safe_path.exists():
        checkpoint = VENDOR / "weights/ckpt_epoch_13.pth"
        if not checkpoint.exists() or digest(checkpoint.read_bytes()) != CHECKPOINT_SHA:
            raise ValueError("Expected the verified official SPAI checkpoint; see README download provenance")
        globals_used = torch.serialization.get_unsafe_globals_in_checkpoint(checkpoint)
        if globals_used != ["yacs.config.CfgNode"]:
            raise ValueError(f"Unexpected checkpoint globals: {globals_used}")
        with torch.serialization.safe_globals([CfgNode]):
            loaded = torch.load(checkpoint, map_location="cpu", weights_only=True)
        state = loaded["model"]
        if not isinstance(state, dict) or not all(isinstance(k, str) and isinstance(v, torch.Tensor) for k, v in state.items()):
            raise ValueError("Expected tensor-only model state")
        save_file({key: value.contiguous() for key, value in state.items()}, str(safe_path))
        del loaded, state
    if digest(safe_path.read_bytes()) != SAFE_SHA:
        raise ValueError("Converted SPAI safetensors integrity mismatch")
    sys.path.insert(0, str(VENDOR))
    from spai.config import get_custom_config
    from spai.models.sid import build_mf_vit
    from spai.models import filters
    # Fresh config from audited repository YAML, never the checkpoint's config.
    config = get_custom_config(str(VENDOR / "configs/spai.yaml"))
    if config.MODEL_WEIGHTS != "mfm":
        raise ValueError("Only the local MFM backbone is permitted")
    model = build_mf_vit(config)
    model.load_state_dict(load_file(str(safe_path)), strict=True)
    original_filter = filters.filter_image_frequencies
    if device == "mps":
        def cpu_fft(image, mask):
            return tuple(value.to(image.device) for value in original_filter(image.cpu(), mask.cpu()))
        filters.filter_image_frequencies = cpu_fft
    return model.eval().to(device), manifest


def frame_tensor(path, duration, count):
    vf = f"fps={count / duration},crop=min(iw\\,256):min(ih\\,256),pad=256:256:(ow-iw)/2:(oh-ih)/2"
    raw = subprocess.check_output(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
        "-vf", vf, "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], timeout=30)
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 256, 256, 3)
    if len(frames) != count:
        raise ValueError("Unexpected decoded frame count")
    return torch.from_numpy(frames.astype(np.float32).transpose(0, 3, 1, 2).copy()) / 255


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="eval/manifest.jsonl")
    parser.add_argument("--split", default="development", choices=["development", "calibration", "holdout"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--device", choices=["cpu", "mps"], default="mps")
    parser.add_argument("--output", default="eval/runs/spai-development.jsonl")
    args = parser.parse_args()
    if not 1 <= args.frames <= 16:
        raise ValueError("Frame count must be 1 through 16")
    output = ROOT / args.output
    if output.exists():
        raise ValueError("Use a fresh output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (ROOT / args.manifest).read_text().splitlines() if line]
    rows = [row for row in rows if row["split"] == args.split][:args.limit]
    torch.set_num_threads(4)
    model, source = load_model(args.device)
    config = {"model": "mever-team/spai", "revision": source["revision"], "safetensorsSha256": SAFE_SHA,
        "device": args.device, "fftDevice": "cpu", "frames": args.frames,
        "preprocessing": "uniform-native-center-crop256-five-spai-patches-rgb-unit-range",
        "aggregation": "mean-logit", "sourceSha256": digest(pathlib.Path(__file__).read_bytes()),
        "vendorManifestSha256": digest((ROOT / "eval/sources/spai-vendor-manifest.json").read_bytes())}
    errors = 0
    for index, row in enumerate(rows, 1):
        start = time.monotonic()
        result = {**row, "configuration": config}
        try:
            path = ROOT / row["path"]
            if digest(path.read_bytes()) != row["sha256"]:
                raise ValueError("Corpus hash mismatch")
            batch = frame_tensor(path, row["media"]["durationSeconds"], args.frames).to(args.device)
            with torch.inference_mode():
                scores = model([frame.unsqueeze(0) for frame in batch], feature_extraction_batch_size=8).float().cpu().flatten().tolist()
            result.update({"syntheticScore": float(np.mean(scores)), "frameScores": scores,
                "scoreIsProbability": False, "framesAnalyzed": len(scores)})
        except Exception as error:
            result["error"] = str(error)
            errors += 1
        result["elapsedMs"] = round((time.monotonic() - start) * 1000)
        with output.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
        print(json.dumps({"completed": index, "selected": len(rows), "id": row["id"], "elapsedMs": result["elapsedMs"], "error": result.get("error")}), flush=True)
        if errors >= 3:
            raise SystemExit("Three errors; stopping specialist experiment")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
