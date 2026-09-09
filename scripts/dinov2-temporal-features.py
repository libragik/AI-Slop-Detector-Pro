#!/usr/bin/env python3
"""Auditable DINOv2 frame features. Import is metadata-only; no implicit downloads.

Public API: load_backbone, probe_video, windows_for_probe, extract_window,
extract_windows, save_features. Labels never enter inference. The CLI's acquire
and contract commands are explicit actions, never triggered by extraction.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "facebook/dinov2-small"
REVISION = "ed25f3a31f01632728cabb09d1542f84ab7b0056"
ASSETS = {
    "model.safetensors": (88249960, "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"),
    "config.json": (547, "1809f83e3bdb1609a501a610ad4a742f4fd8ae44d72ca4aa0df52d1f2ac8628d"),
    "preprocessor_config.json": (436, "14e780d86fa1861f8751f868d7f45425b5feb55c38ca26f152ca5097ab30f828"),
}
VERSIONS = {"torch": "2.8.0", "torchvision": "0.23.0", "transformers": "4.57.6",
            "safetensors": "0.8.0", "Pillow": "12.3.0", "numpy": "2.2.6"}
TRANSFORMER_FILES = {
    "models/dinov2/modeling_dinov2.py": "e1376e0decc4cf3fd60042a17464a4118f1802a4e1ca2af4496c211fabb6d34b",
    "models/dinov2/configuration_dinov2.py": "d36d05e792619389f06e9cf17c3c738bbecfa1efb93a9b8667e7fe9b11036058",
    "models/bit/image_processing_bit.py": "4375facc5a89b1ed31aaefc74181f516a07d9cd292e7c7e26798ff17e728a96d",
}
LIMITS = {"sourceBytes": 50_000_000, "nativePixels": 16_000_000,
          "nativeFrames": 30000, "durationSeconds": 120, "windows": 128,
          "probeSeconds": 45, "decodeSeconds": 180, "probeBytes": 8 * 1024**2,
          "stderrBytes": 2 * 1024**2, "modelBatchFrames": 2}
POLICY = {"version": "dinov2-temporal-features-v1", "windowSeconds": 2.0,
          "evaluationStrideSeconds": 1.0, "minimumSeconds": 0.5,
          "framesPerWindow": 8, "sampling": "floor-linspace-native-index-inclusive",
          "windowMembership": "start <= normalized frame PTS < end",
          "preprocess": "pinned slow BitImageProcessor: RGB,bicubic short256,center224,ImageNet",
          "embedding": "final-layernorm CLS pooler_output,384,FP32",
          "attention": "eager", "torchThreads": 4, "torchInteropThreads": 1,
          "agreementMaxAbsolute": 3e-3, "agreementRelativeL2": 1e-3,
          "limits": LIMITS}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


SOURCE_SHA = sha(__file__)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    """Exclusive immutable receipt; partial writes cannot replace prior evidence."""
    path = Path(path)
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temp.open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(temp, path)
    finally:
        temp.unlink()


@contextmanager
def offline():
    """Explicitly block networking during imports, load, preprocessing and forwards."""
    env = {key: os.environ.get(key) for key in
           ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY")}
    original = [(socket, "getaddrinfo", socket.getaddrinfo),
                (socket, "create_connection", socket.create_connection),
                (socket.socket, "connect", socket.socket.connect),
                (socket.socket, "connect_ex", socket.socket.connect_ex)]
    def denied(*args, **kwargs):
        raise RuntimeError("Network access prohibited in local feature extraction")
    try:
        for key in env:
            os.environ[key] = "1"
        for obj, name, _ in original:
            setattr(obj, name, denied)
        yield
    finally:
        for obj, name, fn in original:
            setattr(obj, name, fn)
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def runtime_identity():
    if sha(__file__) != SOURCE_SHA:
        raise RuntimeError("Feature source changed after module import")
    actual = {name: importlib.metadata.version(name) for name in VERSIONS}
    if actual != VERSIONS:
        raise RuntimeError(f"Runtime version mismatch: {actual}")
    dist = importlib.metadata.distribution("transformers")
    for name, expected in TRANSFORMER_FILES.items():
        if sha(dist.locate_file("transformers/" + name)) != expected:
            raise RuntimeError(f"Audited runtime source changed: {name}")
    media_tools = {}
    for name in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(name)
        if not resolved:
            raise RuntimeError(f"Missing media executable: {name}")
        media_tools[name] = {"path": str(Path(resolved).resolve()), "sha256": sha(resolved)}
    return {"versions": actual, "python": sys.version.split()[0], "mediaTools": media_tools,
            "sourceSha256": SOURCE_SHA, "transformersSourceHashes": TRANSFORMER_FILES,
            "policy": POLICY, "model": MODEL_ID, "revision": REVISION,
            "assets": {name: {"bytes": value[0], "sha256": value[1]}
                       for name, value in ASSETS.items()}}


def validate_assets(model_dir):
    root = Path(model_dir).resolve()
    for name, (size, expected) in ASSETS.items():
        p = root / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size != size or sha(p) != expected:
            raise ValueError(f"Missing or mismatched pinned asset: {name}")
    allowed = set(ASSETS) | {"acquisition.json", "supervisor.json", "README.md", "LICENSE"}
    if any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in root.iterdir()):
        raise ValueError("Unexpected local model assets")
    return root


def acquire_backbone(output_dir):
    """Explicit standalone acquisition only, exact publisher bytes, no model load."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    receipt = {"startedAt": now(), "status": "failed", "model": MODEL_ID,
               "revision": REVISION, "sourceSha256": SOURCE_SHA, "files": []}
    try:
        for name, (size, expected) in ASSETS.items():
            url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
            temp = root / (name + ".partial")
            start = time.monotonic()
            h, count = hashlib.sha256(), 0
            with urllib.request.urlopen(url, timeout=30) as r, temp.open("xb") as f:
                if r.status != 200:
                    raise RuntimeError("Non-successful acquisition response")
                while True:
                    chunk = r.read(min(1024**2, size + 1 - count))
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > size or time.monotonic() - start > 180:
                        raise RuntimeError("Acquisition byte/time bound exceeded")
                    f.write(chunk)
                    h.update(chunk)
                f.flush()
                os.fsync(f.fileno())
            if count != size or h.hexdigest() != expected:
                raise RuntimeError("Publisher asset hash or size mismatch")
            temp.rename(root / name)
            receipt["files"].append({"name": name, "url": url, "bytes": count,
                                     "sha256": h.hexdigest()})
        # Already audited license/card, copied without another network dependency.
        for source, name in [("meta-LICENSE", "LICENSE"), ("hf-README.md", "README.md")]:
            data = (ROOT / "eval/sources/dinov2-training-backbone" / source).read_bytes()
            (root / name).write_bytes(data)
        receipt["status"] = "completed"
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt["finishedAt"] = now()
        write_json(root / "acquisition.json", receipt)
    return receipt


def _load_backbone(model_dir, device):
    identity = runtime_identity()
    root = validate_assets(model_dir)
    if device not in ("cpu", "mps"):
        raise ValueError("Only CPU or MPS FP32 is registered")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1":
        raise RuntimeError("Silent MPS CPU fallback is forbidden")
    with offline():
        import numpy as np
        import torch
        from safetensors.torch import load_file
        from transformers import BitImageProcessor, Dinov2Config, Dinov2Model
        torch.set_num_threads(4)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.manual_seed(20260905)
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS is unavailable; no fallback")
        config = Dinov2Config.from_pretrained(root, local_files_only=True)
        config._attn_implementation = "eager"
        model = Dinov2Model(config).cpu().float()
        state = load_file(str(root / "model.safetensors"), device="cpu")
        expected = model.state_dict()
        if set(state) != set(expected) or not state:
            raise RuntimeError("Incomplete backbone checkpoint keys")
        for key, tensor in state.items():
            if tensor.shape != expected[key].shape or tensor.dtype != expected[key].dtype:
                raise RuntimeError(f"Backbone tensor shape/dtype mismatch: {key}")
            if not torch.isfinite(tensor).all().item():
                raise RuntimeError(f"Nonfinite backbone tensor: {key}")
        model.load_state_dict(state, strict=True)
        if sum(t.numel() for t in state.values()) != 22056576:
            raise RuntimeError("Wrong complete-backbone element census")
        if any(not torch.equal(model.state_dict()[k], v) for k, v in state.items()):
            raise RuntimeError("Loaded tensor differs from supplied checkpoint")
        load_receipt = {"strict": True, "allTensorsFinite": True,
                        "allLoadedTensorsEqual": True, "tensorCount": len(state),
                        "tensorElements": sum(t.numel() for t in state.values()),
                        "missingKeys": [], "unexpectedKeys": [], "mismatchedKeys": []}
        del state, expected
        model.requires_grad_(False).eval().to(device)
        processor = BitImageProcessor.from_pretrained(root, local_files_only=True)
        processor._feature_settings = json.loads((root / "preprocessor_config.json").read_text())
    model._feature_identity = identity
    model._feature_load_receipt = load_receipt
    model._feature_device = device
    model._feature_contract = None
    return model, processor, {"identity": identity, "fingerprint": digest(identity),
                              "load": load_receipt, "device": device}


def synthetic_images():
    import numpy as np
    from PIL import Image
    images = []
    for height, width, phase in [(320, 480, 0), (480, 320, 71)]:
        y, x = np.indices((height, width), dtype=np.uint32)
        rgb = np.stack(((3*x + y + phase) % 256, (x + 5*y + phase) % 256,
                        ((x//11 + y//13) % 2)*255), axis=-1).astype(np.uint8)
        images.append(Image.fromarray(rgb))
    return images


def _forward(images, model, processor, device):
    import numpy as np
    import torch
    if device != model._feature_device or next(model.parameters()).device.type != device:
        raise ValueError("Model device identity mismatch")
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("Backbone must remain frozen in evaluation mode")
    for name, expected in processor._feature_settings.items():
        if name == "image_processor_type":
            continue
        if getattr(processor, name) != expected:
            raise ValueError(f"Pinned preprocessing changed: {name}")
    with offline(), torch.inference_mode():
        inputs = processor(images=images, return_tensors="pt")["pixel_values"]
        if inputs.shape != (len(images), 3, 224, 224) or inputs.dtype != torch.float32:
            raise RuntimeError("Preprocessor shape/dtype mismatch")
        pre_hashes = [hashlib.sha256(t.numpy().tobytes()).hexdigest() for t in inputs]
        result = model(pixel_values=inputs.to(device)).pooler_output
        if device == "mps":
            torch.mps.synchronize()
        cls = result.cpu().numpy().astype(np.float32, copy=False)
    if cls.shape != (len(images), 384) or not np.isfinite(cls).all():
        raise RuntimeError("Invalid/nonfinite CLS features")
    return cls, pre_hashes


def _agreement(cpu, mps):
    import numpy as np
    if cpu.shape != (2, 384) or mps.shape != cpu.shape or not np.isfinite([cpu, mps]).all():
        raise ValueError("Invalid synthetic contract arrays")
    delta = cpu.astype(np.float64) - mps.astype(np.float64)
    absolute = float(np.max(np.abs(delta)))
    relative = float(np.linalg.norm(delta) / max(np.linalg.norm(cpu.astype(np.float64)), 1e-12))
    return {"maxAbsolute": absolute, "relativeL2": relative,
            "passed": absolute <= 3e-3 and relative <= 1e-3}


def run_runtime_contract(model_dir, output_dir):
    import numpy as np
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"schemaVersion": 1, "startedAt": now(), "status": "failed",
               "identity": runtime_identity(), "limits": {"maxAbsolute": 3e-3, "relativeL2": 1e-3},
               "inputKind": "two deterministic synthetic RGB images; not evaluation media"}
    try:
        images = synthetic_images()
        receipt["imageHashes"] = [hashlib.sha256(im.tobytes()).hexdigest() for im in images]
        cpu_model, processor, loaded = _load_backbone(model_dir, "cpu")
        cpu, pre = _forward(images, cpu_model, processor, "cpu")
        receipt["load"] = loaded["load"]
        receipt["preprocessedHashes"] = pre
        cpu_model.to("mps")
        cpu_model._feature_device = "mps"
        mps, mps_pre = _forward(images, cpu_model, processor, "mps")
        if pre != mps_pre:
            raise RuntimeError("CPU/MPS inputs differed")
        with (out / "outputs.npz").open("xb") as f:
            np.savez(f, cpu=cpu, mps=mps)
        receipt["outputs"] = {"path": str((out / "outputs.npz").resolve()),
                              "sha256": sha(out / "outputs.npz")}
        receipt["agreement"] = _agreement(cpu, mps)
        if not receipt["agreement"]["passed"]:
            raise RuntimeError("Frozen CPU/MPS agreement gate failed")
        receipt["status"] = "passed"
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt["finishedAt"] = now()
        receipt["fingerprint"] = digest(receipt["identity"])
        write_json(out / "contract.json", receipt)
    return receipt


def validate_contract(path):
    import numpy as np
    p = Path(path)
    receipt = json.loads(p.read_text())
    expected = runtime_identity()
    if (receipt.get("status") != "passed" or receipt.get("identity") != expected
            or receipt.get("fingerprint") != digest(expected)):
        raise ValueError("Missing/stale/failed synthetic runtime contract")
    loaded = receipt.get("load", {})
    if (not all(loaded.get(k) is True for k in ("strict", "allTensorsFinite", "allLoadedTensorsEqual"))
            or loaded.get("tensorElements") != 22056576 or loaded.get("tensorCount", 0) <= 0
            or any(loaded.get(k) != [] for k in ("missingKeys", "unexpectedKeys", "mismatchedKeys"))
            or receipt.get("limits") != {"maxAbsolute": 3e-3, "relativeL2": 1e-3}
            or receipt.get("imageHashes") != [hashlib.sha256(im.tobytes()).hexdigest() for im in synthetic_images()]):
        raise ValueError("Incomplete synthetic load/input/limit evidence")
    output = Path(receipt["outputs"]["path"])
    if sha(output) != receipt["outputs"]["sha256"]:
        raise ValueError("Runtime contract outputs changed")
    with np.load(output, allow_pickle=False) as data:
        if (set(data.files) != {"cpu", "mps"} or data["cpu"].dtype != np.float32
                or data["mps"].dtype != np.float32
                or not _agreement(data["cpu"], data["mps"])["passed"]
                or receipt.get("agreement") != _agreement(data["cpu"], data["mps"])):
            raise ValueError("Saved runtime outputs fail frozen agreement")
    return {"path": str(p.resolve()), "sha256": sha(p), "fingerprint": digest(expected)}


def load_backbone(model_dir, device="cpu", contract_receipt=None):
    if contract_receipt is None:
        raise ValueError("A successful synthetic runtime contract is required before media extraction")
    contract = validate_contract(contract_receipt)
    model, processor, receipt = _load_backbone(model_dir, device)
    model._feature_contract = contract
    receipt["contract"] = contract
    return model, processor, receipt


def _kill(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)


def bounded_process(command, timeout, stdout_limit, stderr_limit=65536, callback=None):
    """Drain both pipes, bound memory/time; optional streaming stdout consumer."""
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True, stdin=subprocess.DEVNULL)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "out")
    selector.register(proc.stderr, selectors.EVENT_READ, "err")
    buffers = {"out": bytearray(), "err": bytearray()}
    counts = {"out": 0, "err": 0}
    start = time.monotonic()
    try:
        while selector.get_map():
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"Subprocess exceeded {timeout}s")
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                kind = key.data
                counts[kind] += len(chunk)
                if counts[kind] > (stdout_limit if kind == "out" else stderr_limit):
                    raise ValueError(f"Subprocess {kind} byte cap exceeded")
                if kind == "out" and callback:
                    callback(chunk)
                else:
                    buffers[kind].extend(chunk)
        code = proc.wait(timeout=max(1, timeout-(time.monotonic()-start)))
        if code != 0:
            raise RuntimeError(f"Subprocess failed ({code}): {bytes(buffers['err'])[-2000:].decode(errors='replace')}")
        return bytes(buffers["out"]), bytes(buffers["err"])
    finally:
        _kill(proc)
        selector.close()
        proc.stdout.close()
        proc.stderr.close()


def probe_video(path):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > LIMITS["sourceBytes"]:
        raise ValueError("Missing source or 50 MB source bound exceeded")
    command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v", "-show_streams", "-show_format",
               "-show_frames", "-show_entries",
               "stream=index,width,height,duration,time_base:stream_tags=rotate:stream_side_data=rotation:"
               "format=duration:frame=best_effort_timestamp_time,pkt_duration_time,width,height", "-of", "json", str(path)]
    data, _ = bounded_process(command, LIMITS["probeSeconds"], LIMITS["probeBytes"])
    raw = json.loads(data)
    streams, frames = raw.get("streams", []), raw.get("frames", [])
    if len(streams) != 1 or not 8 <= len(frames) <= LIMITS["nativeFrames"]:
        raise ValueError("Exactly one video stream and 8–30000 timestamped native frames required")
    stream = streams[0]
    w, h = int(stream["width"]), int(stream["height"])
    if min(w, h) <= 0 or w*h > LIMITS["nativePixels"]:
        raise ValueError("Invalid native size or 16 MP bound exceeded")
    if (float(stream.get("tags", {}).get("rotate", 0)) != 0
            or any(float(x.get("rotation", 0)) != 0 for x in stream.get("side_data_list", []))):
        raise ValueError("Rotation requires an explicitly audited input conversion")
    pts = [float(f["best_effort_timestamp_time"]) for f in frames]
    if (not all(math.isfinite(t) for t in pts) or any(b <= a for a, b in zip(pts, pts[1:]))
            or any((int(f["width"]), int(f["height"])) != (w, h) for f in frames)):
        raise ValueError("Missing/nonmonotonic timestamps or changing native frame dimensions")
    # The frame timeline defines video length, excluding unrelated audio duration.
    last_duration = float(frames[-1].get("pkt_duration_time", 0))
    if not math.isfinite(last_duration) or last_duration <= 0:
        last_duration = pts[-1] - pts[-2]
    duration = pts[-1] - pts[0] + last_duration
    if not 0.5 <= duration <= 120 + 1e-6:
        raise ValueError("Video duration outside 0.5–120 seconds")
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
            "width": w, "height": h, "duration": duration, "ptsOrigin": pts[0],
            "timestamps": [t-pts[0] for t in pts], "absoluteTimestamps": pts,
            "frameCount": len(frames), "probeSha256": hashlib.sha256(data).hexdigest(),
            "command": command, "lastFrameDuration": last_duration}


def windows_for_probe(probe, mode, stable_parent_hash):
    if not re.fullmatch(r"[0-9a-f]{64}", stable_parent_hash):
        raise ValueError("Stable original SHA-256 is required for window identity")
    duration = float(probe["duration"])
    if not math.isfinite(duration) or not 0.5 <= duration <= 120+1e-6:
        raise ValueError("Unsupported video duration")
    if mode == "train":
        # Caller supplies the original duration, so derivatives use identical bounds.
        original = float(probe.get("originalDuration", duration))
        if not 0.5 <= original <= 120+1e-6:
            raise ValueError("Unsupported original duration")
        length = min(2.0, original)
        fraction = int(hashlib.sha256(("dinov2-window-v1:"+stable_parent_hash).encode()).hexdigest()[:16], 16)/2**64
        start = round(fraction * max(0.0, original-length), 9)
        windows = [{"start": start, "end": start+length}]
    elif mode == "evaluation":
        if duration <= 2:
            windows = [{"start": 0.0, "end": duration}]
        else:
            starts = [float(i) for i in range(math.floor(duration-2)+1)]
            if abs(starts[-1]-(duration-2)) > 1e-6:
                starts.append(duration-2)
            windows = [{"start": s, "end": s+2} for s in starts]
    else:
        raise ValueError("Mode must be train or evaluation")
    if len(windows) > LIMITS["windows"]:
        raise ValueError("Window count bound exceeded")
    for win in windows:
        select_indices(probe, win)
    return windows


def select_indices(probe, window):
    start, end = float(window["start"]), float(window["end"])
    if (not math.isfinite(start+end) or start < 0 or not 0.5 <= end-start <= 2.0+1e-6
            or end > float(probe["duration"])+1e-6):
        raise ValueError("Window outside supported source coverage")
    available = [i for i, pts in enumerate(probe["timestamps"]) if start <= pts < end]
    if len(available) < 8:
        raise ValueError("Window has fewer than eight distinct native frames")
    indexes = [available[(i*(len(available)-1))//7] for i in range(8)]
    if len(set(indexes)) != 8:
        raise ValueError("Native sampling produced duplicate frame indexes")
    return indexes


def crop_receipt(width, height):
    # Same aspect-preserving integer output sizes as the pinned slow processor.
    rw, rh = ((int(256*width/height), 256) if width >= height else (256, int(256*height/width)))
    left, top = (rw-224)//2, (rh-224)//2
    return {"native": [width, height], "resized": [rw, rh],
            "cropXYWH": [left, top, 224, 224],
            "resizedAreaFractionRetained": 224*224/(rw*rh),
            "note": "Center crop discards borders; resampling mixes source pixels. No every-pixel coverage claim."}


def decode_selected(probe, indexes, consume):
    """Decode selected RGB frames once; verify actual showinfo PTS and dimensions."""
    import numpy as np
    indexes = sorted(set(indexes))
    if not indexes or len(indexes) > LIMITS["windows"]*8:
        raise ValueError("Invalid selected-frame count")
    if sha(probe["path"]) != probe["sha256"]:
        raise ValueError("Input changed since probe")
    expression = "+".join(f"eq(n\\,{i})" for i in indexes)
    command = ["ffmpeg", "-nostdin", "-v", "info", "-threads", "1", "-filter_threads", "1", "-noautorotate",
               "-protocol_whitelist", "file,pipe",
               "-copyts", "-i", probe["path"], "-map", "0:v:0", "-an", "-sn", "-dn",
               "-vf", f"select={expression},showinfo", "-fps_mode", "passthrough",
               "-pix_fmt", "rgb24", "-threads", "1", "-f", "rawvideo", "pipe:1"]
    frame_bytes = probe["width"]*probe["height"]*3
    pending, done = bytearray(), 0
    def chunk(data):
        nonlocal done
        pending.extend(data)
        while len(pending) >= frame_bytes:
            if done >= len(indexes):
                raise ValueError("Decoder returned extra selected frames")
            raw = bytes(pending[:frame_bytes])
            del pending[:frame_bytes]
            rgb = np.frombuffer(raw, dtype=np.uint8).reshape(probe["height"], probe["width"], 3)
            consume(indexes[done], rgb)
            done += 1
    _, stderr = bounded_process(command, LIMITS["decodeSeconds"],
                                 frame_bytes*len(indexes), LIMITS["stderrBytes"], chunk)
    if pending or done != len(indexes):
        raise ValueError("Truncated/missing selected RGB frames")
    observed = []
    for line in stderr.decode(errors="replace").splitlines():
        if "showinfo" in line and re.search(r"\bn:\s*\d+", line):
            pts = re.search(r"\bpts_time:([^\s]+)", line)
            size = re.search(r"\bs:(\d+)x(\d+)", line)
            if pts and size:
                observed.append((float(pts[1]), int(size[1]), int(size[2])))
    if len(observed) != len(indexes):
        raise ValueError("Decoder timestamp count does not match selected RGB frames")
    for index, (pts, w, h) in zip(indexes, observed):
        # ffmpeg showinfo decimal formatting has bounded rounding at <=120 seconds.
        if abs(pts-probe["absoluteTimestamps"][index]) > 0.001 or (w, h) != (probe["width"], probe["height"]):
            raise ValueError("Decoder timestamps/dimensions differ from ffprobe selection")
    if sha(probe["path"]) != probe["sha256"]:
        raise ValueError("Source changed while decoding")
    return {"command": command, "showinfoSha256": hashlib.sha256(stderr).hexdigest(),
            "selectedFrameCount": done, "verifiedTimestampToleranceSeconds": .001,
            "actualDecodedTimestamps": [x[0] for x in observed]}


def extract_windows(path, windows, model, processor, device, probe=None):
    import numpy as np
    from PIL import Image
    if model._feature_contract is None or model._feature_identity != runtime_identity():
        raise ValueError("Media extraction requires matching model/runtime contract")
    validate_contract(model._feature_contract["path"])
    if not windows or len(windows) > LIMITS["windows"]:
        raise ValueError("Invalid requested window count")
    probe = probe or probe_video(path)
    if Path(path).resolve() != Path(probe["path"]).resolve():
        raise ValueError("Probe belongs to another path")
    groups = [select_indices(probe, win) for win in windows]
    selected = sorted({i for group in groups for i in group})
    features, frame_receipts, batch = {}, {}, []
    def flush():
        if not batch:
            return
        values, hashes = _forward([im for _, im, _ in batch], model, processor, device)
        for (index, im, rgb_sha), feat, pre_sha in zip(batch, values, hashes):
            features[index] = feat.copy()
            frame_receipts[index] = {"nativeIndex": index, "timestamp": probe["timestamps"][index],
                                     "absoluteTimestamp": probe["absoluteTimestamps"][index],
                                     "rgbSha256": rgb_sha, "preprocessedFP32Sha256": pre_sha,
                                     "nativeShape": [im.height, im.width, 3]}
        batch.clear()
    def consume(index, rgb):
        batch.append((index, Image.fromarray(rgb), hashlib.sha256(rgb.tobytes()).hexdigest()))
        if len(batch) >= LIMITS["modelBatchFrames"]:
            flush()
    decoded = decode_selected(probe, selected, consume)
    flush()
    # No feature artifacts are returned until all frame/PTS/decode checks succeed.
    results = []
    for window, indexes in zip(windows, groups):
        cls = np.stack([features[i] for i in indexes]).astype(np.float32)
        receipt = {"schemaVersion": 1, "status": "completed", "createdAt": now(),
                   "window": window, "source": {k: probe[k] for k in
                    ("path", "sha256", "bytes", "width", "height", "duration", "frameCount", "ptsOrigin", "probeSha256")},
                   "frames": [frame_receipts[i] for i in indexes], "decoder": decoded,
                   "crop": crop_receipt(probe["width"], probe["height"]),
                   "model": model._feature_identity, "modelFingerprint": digest(model._feature_identity),
                   "strictLoad": model._feature_load_receipt, "contract": model._feature_contract,
                   "device": device, "featureShape": [8, 384], "featureDtype": "float32",
                   "clsBytesSha256": hashlib.sha256(cls.tobytes()).hexdigest()}
        results.append((cls, receipt))
    return results


def extract_window(path, window, model, processor, device):
    return extract_windows(path, [window], model, processor, device)[0]


def save_features(path, cls, receipt):
    import numpy as np
    path = Path(path)
    if cls.shape != (8, 384) or cls.dtype != np.float32 or not np.isfinite(cls).all():
        raise ValueError("Features must be finite FP32 cls[8,384]")
    if hashlib.sha256(cls.tobytes()).hexdigest() != receipt["clsBytesSha256"]:
        raise ValueError("Receipt and feature array differ")
    with path.open("xb") as f:
        np.savez(f, cls=cls)
    with np.load(path, allow_pickle=False) as data:
        if data.files != ["cls"] or not np.array_equal(data["cls"], cls):
            raise ValueError("Feature safenpz roundtrip mismatch")
    completed = dict(receipt, featurePath=str(path.resolve()), featureSha256=sha(path))
    write_json(path.with_suffix(".receipt.json"), completed)
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="action", required=True)
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--model-dir", required=True)
    contract = sub.add_parser("contract")
    contract.add_argument("--model-dir", required=True)
    contract.add_argument("--output-dir", required=True)
    extract = sub.add_parser("extract")
    for name in ("model-dir", "contract-receipt", "source", "source-sha256", "original-sha256", "output-dir"):
        extract.add_argument("--"+name, required=True)
    extract.add_argument("--original-duration", type=float)
    extract.add_argument("--mode", choices=["train", "evaluation"], required=True)
    extract.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    args = parser.parse_args()
    if not args.worker:
        return supervised_cli(args)
    if args.action == "acquire":
        result = acquire_backbone(args.model_dir)
    elif args.action == "contract":
        result = run_runtime_contract(args.model_dir, args.output_dir)
    else:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=False)
        try:
            if sha(args.source) != args.source_sha256:
                raise ValueError("Source does not match caller's pinned file identity")
            probe = probe_video(args.source)
            if args.mode == "train":
                if args.original_duration is None:
                    raise ValueError("Training requires the common original duration")
                probe["originalDuration"] = args.original_duration
            windows = windows_for_probe(probe, args.mode, args.original_sha256)
            model, processor, _ = load_backbone(args.model_dir, args.device, args.contract_receipt)
            values = extract_windows(args.source, windows, model, processor, args.device, probe=probe)
            saved = [save_features(out/f"window-{i:03d}.npz", cls, rec)
                     for i, (cls, rec) in enumerate(values)]
            result = {"status": "completed", "sourceSha256": args.source_sha256,
                      "originalSha256": args.original_sha256, "mode": args.mode,
                      "sourceSha": SOURCE_SHA, "windows": len(saved),
                      "featureReceipts": [{"path": str(out/f"window-{i:03d}.receipt.json"),
                                           "sha256": sha(out/f"window-{i:03d}.receipt.json")}
                                          for i in range(len(saved))]}
            write_json(out/"extraction.json", result)
        except Exception as exc:
            write_json(out/"failure.json", {"status": "failed", "at": now(),
                       "type": type(exc).__name__, "message": str(exc), "sourceSha256": SOURCE_SHA})
            raise
    print(json.dumps(result, allow_nan=False))


def process_tree(pid):
    """Read-only process census; restrict monitoring/signals to this owned child tree."""
    raw = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss="], timeout=3).decode()
    rows = [tuple(map(int, line.split())) for line in raw.splitlines() if line.strip()]
    owned = {pid}
    for _ in rows:
        added = {p for p, parent, _ in rows if parent in owned} - owned
        if not added:
            break
        owned |= added
    return owned, sum(rss*1024 for p, _, rss in rows if p in owned)


def supervised_cli(args):
    """CLI hard watchdog includes all ffmpeg children. Import callers need one too."""
    timeout = {"acquire": 300, "contract": 600, "extract": 1200}[args.action]
    cap = 8 * 1024**3
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", *sys.argv[1:]],
                            start_new_session=True)
    start, peak, failure, owned = time.monotonic(), 0, None, {proc.pid}
    try:
        while proc.poll() is None:
            owned, rss = process_tree(proc.pid)
            peak = max(peak, rss)
            if rss > cap or time.monotonic()-start > timeout:
                failure = "RSS limit exceeded" if rss > cap else "Wall time limit exceeded"
                break
            time.sleep(.2)
    except BaseException as exc:
        failure = f"Supervisor stopped: {type(exc).__name__}"
    finally:
        if failure or proc.poll() is None:
            for pid in sorted(owned, reverse=True):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        code = proc.wait(timeout=5)
        out = Path(args.model_dir if args.action == "acquire" else args.output_dir)
        if out.is_dir():
            write_json(out/"supervisor.json", {"status": "failed" if failure or code else "completed",
                       "sourceSha256": SOURCE_SHA, "peakTreeRSSBytes": peak,
                       "wallSeconds": time.monotonic()-start, "exitCode": code,
                       "failure": failure, "timeoutSeconds": timeout, "RSSLimitBytes": cap,
                       "scope": "this explicit command child process and descendants"})
    if failure or code:
        raise SystemExit(code if code > 0 else 1)


if __name__ == "__main__":
    main()
