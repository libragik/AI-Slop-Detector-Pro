#!/usr/bin/env python3
"""Receipt-backed, offline Wan generation; never a detector accuracy test.

The supervisor enforces a frozen plan, prerequisite receipts, one process tree,
single-use output directories, and wall-time / sampled RSS limits. The worker
loads only hash-verified local safetensors using explicit built-in classes.
"""
import argparse
import atexit
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"
REVISION = "0fad780a534b6463e45facd96134c9f345acfa5b"
MODEL_PATH = "eval/models/wan2.1-t2v-1.3b-diffusers"
LOCK_PATH = "eval/wan-requirements.lock"
PUBLISHER_PATH = "eval/sources/wan-model-publisher-manifest.json"
CRITICAL_SOURCES = (
    "diffusers/pipelines/wan/pipeline_wan.py",
    "diffusers/models/transformers/transformer_wan.py",
    "diffusers/models/autoencoders/autoencoder_kl_wan.py",
    "diffusers/schedulers/scheduling_unipc_multistep.py",
    "diffusers/models/modeling_utils.py",
    "transformers/models/umt5/modeling_umt5.py",
    "transformers/models/t5/tokenization_t5.py",
    "transformers/tokenization_utils_tokenizers.py",
    "transformers/modeling_utils.py",
)
MODEL_BYTES = 28_928_887_859
MAX_RSS = 64 * 1024**3
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_XET": "1", "TOKENIZERS_PARALLELISM": "false",
    "HF_ENABLE_PARALLEL_LOADING": "false", "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4",
    "OPENBLAS_NUM_THREADS": "4", "VECLIB_MAXIMUM_THREADS": "4",
    "NUMEXPR_NUM_THREADS": "4", "PYTHONNOUSERSITE": "1",
}
RUN_FIELDS = {"id", "stage", "prompt", "negativePrompt", "seed", "height", "width",
              "numFrames", "numInferenceSteps", "guidanceScale", "flowShift", "fps",
              "maxSequenceLength", "device", "dtype", "threads", "timeoutSeconds",
              "maxRssBytes", "outputDir"}


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    # Every artifact is write-once. A failed attempt retains its partial output.
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def checked_json(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or "") or digest(path) != expected:
        raise ValueError(f"Required SHA-256 pin does not match: {Path(path).name}")
    return json.loads(Path(path).read_text())


def safe_relative(root, name):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Expected a contained relative path")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes its registered directory")
    return target


def runtime_receipt(root, lock):
    if Path(sys.prefix).resolve() != (root / "eval/.venv-wan").resolve():
        raise ValueError("Run with the isolated eval/.venv-wan interpreter")
    expected = dict(re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", lock.read_text(), re.M))
    normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
    expected = {normalize(k): v for k, v in expected.items()}
    distributions = {normalize(d.metadata["Name"]): d for d in importlib.metadata.distributions()}
    installed = {k: d.version for k, d in distributions.items()}
    if not expected or installed != expected:
        raise ValueError("Installed distributions differ from the complete dependency lock")
    records = {}
    for name, distribution in sorted(distributions.items()):
        files = [p for p in distribution.files or []
                 if len(p.parts) == 2 and str(p).endswith(".dist-info/RECORD")]
        if len(files) != 1:
            raise ValueError(f"Missing installation RECORD: {name}")
        records[name] = {"version": distribution.version,
                         "installationRecordSha256": digest(distribution.locate_file(files[0]))}
    site = root / "eval/.venv-wan/lib/python3.12/site-packages"
    sources = [{"path": name, "sha256": digest(site / name)} for name in CRITICAL_SOURCES]
    return {"python": sys.version, "pythonExecutable": sys.executable,
            "platform": platform.platform(), "architecture": platform.machine(),
            "requirementsLockSha256": digest(lock), "packages": records, "criticalSources": sources}


def validate_run(run):
    if set(run) != RUN_FIELDS:
        raise ValueError("Run fields must match the documented frozen-plan schema exactly")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run["id"]):
        raise ValueError("Invalid run ID")
    if run["stage"] not in ("contract", "normal"):
        raise ValueError("Only the runtime contract and registered normal recipe are supported")
    for key in ("prompt", "negativePrompt"):
        if not isinstance(run[key], str) or len(run[key]) > 8000:
            raise ValueError("Invalid frozen text prompt")
    if not run["prompt"].strip():
        raise ValueError("A fixed nonempty text-only prompt is required")
    if type(run["seed"]) is not int or not 0 <= run["seed"] < 2**32:
        raise ValueError("Seed must be a fixed unsigned 32-bit integer")
    common = {"guidanceScale": 5.0, "flowShift": 3.0, "fps": 16,
              "maxSequenceLength": 512, "device": "cpu", "dtype": "float32",
              "threads": 4, "maxRssBytes": MAX_RSS}
    recipe = ({"height": 128, "width": 128, "numFrames": 9,
               "numInferenceSteps": 2, "timeoutSeconds": 600}
              if run["stage"] == "contract" else
              {"height": 480, "width": 832, "numFrames": 81,
               "numInferenceSteps": 50, "timeoutSeconds": 1800})
    if any(run[k] != value for k, value in (common | recipe).items()):
        raise ValueError("Recipe differs from the bounded CPU reference contract")
    if not isinstance(run["outputDir"], str) or not run["outputDir"].startswith("eval/runs/"):
        raise ValueError("Output must be a new directory under eval/runs")


def validate_loading_info(component, info):
    # No unexplained missing keys, implicit random parameters, adapters, or
    # mismatched shapes. Known tied-weight omissions must be handled by the
    # library's documented model rules, not a broad allowlist here.
    allowed = {"missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"}
    if not isinstance(info, dict) or set(info) - allowed or any(info.values()):
        raise ValueError(f"Nonempty or unfamiliar loading report for {component}: {info}")


def normalize_run(raw, plan):
    """Map the frozen study's API-style keys; never fill missing model settings."""
    mapping = {"negative_prompt": "negativePrompt", "num_frames": "numFrames",
               "num_inference_steps": "numInferenceSteps", "guidance_scale": "guidanceScale",
               "max_sequence_length": "maxSequenceLength"}
    run = {mapping.get(k, k): v for k, v in raw.items() if k != "purpose"}
    purpose = raw.get("purpose")
    if purpose not in ("technical-contract-excluded-from-evaluation", "evaluation-parent"):
        raise ValueError("Unknown frozen generation purpose")
    run["stage"] = "contract" if purpose == "technical-contract-excluded-from-evaluation" else "normal"
    scheduler = plan.get("wanScheduler", {})
    expected = {"class": "UniPCMultistepScheduler", "usePinnedModelConfig": True,
                "flow_shift": 3.0, "prediction_type": "flow_prediction", "use_flow_sigmas": True,
                "solver_order": 2, "solver_type": "bh2", "num_train_timesteps": 1000}
    if scheduler != expected:
        raise ValueError("Frozen plan must retain the exact published scheduler")
    run["flowShift"] = scheduler["flow_shift"]
    validate_run(run)
    return run


def validate_prerequisites(plan, plan_sha, protocol_sha, gate, acquisition, contract, run):
    if plan.get("schemaVersion") != 1 or plan.get("frozen") is not True:
        raise ValueError("Generation plan must be explicitly frozen")
    if plan.get("modelId") != MODEL_ID or plan.get("revision") != REVISION:
        raise ValueError("Plan model identity mismatch")
    if gate.get("status") != "passed" or gate.get("generationPlanSha256") != plan_sha:
        raise ValueError("A successful negative gate bound to this generation plan is required")
    if gate.get("evaluationProtocolSha256") != protocol_sha:
        raise ValueError("Negative gate does not match the frozen evaluation protocol")
    if not {"negative-45", "veo-30"}.issubset(set(gate.get("completedStages", []))):
        raise ValueError("Both negative and Veo detector gates must pass before Wan loading")
    if acquisition.get("modelRevision", acquisition.get("revision")) != REVISION:
        raise ValueError("Acquisition receipt model revision mismatch")
    if run["stage"] == "normal":
        if not contract or contract.get("status") != "succeeded":
            raise ValueError("Normal generation requires a successful runtime contract")
        if contract.get("generationPlanSha256") != plan_sha or contract.get("stage") != "contract":
            raise ValueError("Runtime contract belongs to another plan or stage")
        if contract.get("evaluationProtocolSha256") != protocol_sha:
            raise ValueError("Runtime contract protocol mismatch")
        if contract.get("eligibleAsEvaluationControl") is not False:
            raise ValueError("Runtime contract was incorrectly marked as an evaluation control")
    validate_run(run)


def verify_component_state(component, model_dir, name, torch):
    from safetensors import safe_open
    header = {}
    for path in sorted((model_dir / name).glob("*.safetensors")):
        with safe_open(str(path), framework="pt", device="cpu") as handle:
            for key in handle.keys():
                if key in header:
                    raise ValueError("Duplicate checkpoint tensor key across shards")
                view = handle.get_slice(key)
                header[key] = {"shape": tuple(view.get_shape()), "dtype": view.get_dtype()}
    state = component.state_dict()
    # Official UMT5 stores shared.weight once; the published Transformers class
    # declares encoder.embed_tokens.weight -> shared.weight as an intentional
    # tie. Require actual storage identity, not a guessed missing-key exception.
    intentional_ties = {}
    if name == "text_encoder":
        tied, original = "encoder.embed_tokens.weight", "shared.weight"
        if original not in header or tied in header or tied not in state:
            raise ValueError("Unexpected UMT5 serialized embedding contract")
        if state[tied].data_ptr() != state[original].data_ptr():
            raise ValueError("UMT5 embedding alias is not actually tied after loading")
        intentional_ties[tied] = original
    if set(header) != set(state) - set(intentional_ties):
        raise ValueError(f"Serialized and runtime state keys do not match: {name}")
    for key, expected in header.items():
        if expected["shape"] != tuple(state[key].shape) or expected["dtype"] != "F32" or state[key].dtype != torch.float32:
            raise ValueError(f"Serialized tensor shape/dtype mismatch: {name}/{key}")
    return {"serializedTensorCount": len(header), "runtimeStateKeyCount": len(state),
            "verifiedIntentionalTies": intentional_ties}


def verify_local_files(model_dir, publisher, acquisition):
    if publisher.get("model") != MODEL_ID or publisher.get("revision") != REVISION:
        raise ValueError("Publisher manifest model mismatch")
    entries = publisher["files"]
    if len(entries) != 19 or sum(entry["size"] for entry in entries) != MODEL_BYTES:
        raise ValueError("Publisher manifest has incomplete required files")
    records = acquisition.get("records", acquisition.get("files"))
    if not isinstance(records, list):
        raise ValueError("Acquisition receipt must contain one record per required file")
    records_by_path = {r["path"]: r for r in records}
    wanted = {e["rfilename"] for e in entries}
    if len(records_by_path) != len(records) or set(records_by_path) != wanted:
        raise ValueError("Acquisition receipt is incomplete or contains unexpected files")
    actual = {str(p.relative_to(model_dir)) for p in model_dir.rglob("*") if p.is_file()}
    if actual != wanted or any(p.is_symlink() for p in model_dir.rglob("*")):
        raise ValueError("Model directory must contain exactly the 19 verified regular files")
    verified = []
    for entry in entries:
        name = entry["rfilename"]
        path = safe_relative(model_dir, name)
        record = records_by_path[name]
        if record.get("success") is not True or path.stat().st_size != entry["size"]:
            raise ValueError(f"Incomplete model acquisition: {name}")
        sha = digest(path)
        if record.get("sha256") != sha or record.get("bytes") != entry["size"]:
            raise ValueError(f"Acquisition file hash/length mismatch: {name}")
        if "lfs" in entry:
            if sha != entry["lfs"]["sha256"]:
                raise ValueError(f"Publisher LFS hash mismatch: {name}")
        else:
            raw = path.read_bytes()
            blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            if blob != entry["blobId"]:
                raise ValueError(f"Publisher git-blob identity mismatch: {name}")
        stat = path.stat()
        verified.append({"path": name, "sha256": sha, "bytes": stat.st_size,
                         "mtimeNs": stat.st_mtime_ns, "inode": stat.st_ino})
    return verified


def configure_worker():
    os.environ.update(OFFLINE_ENV)
    # HF flags and local_files_only are complemented by an audit guard. This
    # process may not create an internet connection or resolve a remote host.
    def no_network(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo"}:
            raise RuntimeError("Network access is disabled in the generation worker")
    sys.addaudithook(no_network)
    import numpy as np
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    # Safetensors is mandatory even if a library accidentally enters a legacy
    # loader. Never permit pickle-backed torch.load in this worker.
    def no_pickle(*args, **kwargs):
        raise RuntimeError("Pickle-backed torch.load is disabled")
    torch.load = no_pickle
    return np, torch


def load_pipeline(model_dir, torch):
    from diffusers import AutoencoderKLWan, WanPipeline, WanTransformer3DModel, UniPCMultistepScheduler
    from transformers import UMT5EncoderModel, T5TokenizerFast
    expected_index = {"scheduler": ["diffusers", "UniPCMultistepScheduler"],
                      "text_encoder": ["transformers", "UMT5EncoderModel"],
                      "tokenizer": ["transformers", "T5TokenizerFast"],
                      "transformer": ["diffusers", "WanTransformer3DModel"],
                      "vae": ["diffusers", "AutoencoderKLWan"]}
    index = json.loads((model_dir / "model_index.json").read_text())
    if index.get("_class_name") != "WanPipeline" or any(index.get(k) != v for k, v in expected_index.items()):
        raise ValueError("Unexpected pipeline architecture")
    reports, components = {}, {}
    for name, cls in (("text_encoder", UMT5EncoderModel), ("transformer", WanTransformer3DModel),
                      ("vae", AutoencoderKLWan)):
        print(json.dumps({"event": "loading_component", "component": name}), flush=True)
        kwargs = dict(local_files_only=True, use_safetensors=True, output_loading_info=True,
                      ignore_mismatched_sizes=False, disable_mmap=False)
        if name == "text_encoder":
            kwargs.update(dtype=torch.float32, trust_remote_code=False, weights_only=True,
                          device_map="cpu", use_kernels=False)
        else:
            # Explicit built-in classes have no remote-code dispatch mechanism.
            kwargs.update(torch_dtype=torch.float32, low_cpu_mem_usage=True)
        component, info = cls.from_pretrained(str(model_dir / name), **kwargs)
        validate_loading_info(name, info)
        component.eval()
        count = 0
        for parameter in component.parameters():
            if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
                raise ValueError(f"Unexpected parameter device/dtype: {name}")
            if not torch.isfinite(parameter).all().item():
                raise ValueError(f"Nonfinite model parameters: {name}")
            count += parameter.numel()
        if not count:
            raise ValueError("Empty model component")
        state_contract = verify_component_state(component, model_dir, name, torch)
        reports[name] = {"loadingInfo": {key: sorted(value) for key, value in info.items()}, "parameters": count,
                         "stateContract": state_contract,
                         "class": f"{cls.__module__}.{cls.__name__}"}
        components[name] = component
    tokenizer = T5TokenizerFast.from_pretrained(str(model_dir / "tokenizer"),
                                                local_files_only=True, trust_remote_code=False)
    scheduler = UniPCMultistepScheduler.from_pretrained(str(model_dir / "scheduler"), local_files_only=True)
    scheduler_expected = {"flow_shift": 3.0, "prediction_type": "flow_prediction", "use_flow_sigmas": True,
                          "solver_order": 2, "solver_type": "bh2", "num_train_timesteps": 1000}
    if any(scheduler.config.get(k) != v for k, v in scheduler_expected.items()):
        raise ValueError("Published UniPC 480p scheduler config mismatch")
    pipe = WanPipeline(tokenizer=tokenizer, scheduler=scheduler, **components).to("cpu")
    pipe.set_progress_bar_config(disable=True)
    reports["schedulerConfig"] = dict(scheduler.config)
    reports["tokenizerClass"] = f"{type(tokenizer).__module__}.{type(tokenizer).__name__}"
    return pipe, reports


def finite_tensor(tensor, torch, label):
    if not isinstance(tensor, torch.Tensor) or not tensor.is_floating_point() or not torch.isfinite(tensor).all().item():
        raise ValueError(f"Nonfinite or invalid {label}")


def perform_generation(pipe, run, out, np, torch):
    import random
    random.seed(run["seed"])
    np.random.seed(run["seed"])
    torch.manual_seed(run["seed"])
    generator = torch.Generator(device="cpu").manual_seed(run["seed"])
    events = []
    decode_info = {}
    original_decode = pipe.vae.decode

    def checked_decode(*args, **kwargs):
        result = original_decode(*args, **kwargs)
        tensor = result[0]
        finite_tensor(tensor, torch, "unclamped VAE decode")
        decode_info.update(shape=list(tensor.shape), minimum=tensor.min().item(), maximum=tensor.max().item())
        return result

    pipe.vae.decode = checked_decode

    def step_callback(pipeline, step, timestep, tensors):
        latent = tensors["latents"]
        finite_tensor(latent, torch, "denoised latent")
        record = {"event": "denoising_step", "step": step, "timestep": float(timestep),
                  "elapsedSeconds": time.monotonic() - started, "latentShape": list(latent.shape),
                  "latentSha256": hashlib.sha256(latent.detach().contiguous().numpy().tobytes()).hexdigest()}
        events.append(record)
        print(json.dumps(record, allow_nan=False), flush=True)
        return tensors

    # Record exact tokenization as well as raw text. No prompt expansion or image
    # input is accepted; no external embeddings may replace the text encoder.
    from diffusers.pipelines.wan.pipeline_wan import prompt_clean
    tokens = {}
    for key in ("prompt", "negativePrompt"):
        cleaned = prompt_clean(run[key])
        encoding = pipe.tokenizer(cleaned, padding="max_length", max_length=512,
                                  truncation=True, add_special_tokens=True,
                                  return_attention_mask=True, return_tensors="pt")
        untruncated = pipe.tokenizer(cleaned, truncation=False, add_special_tokens=True)["input_ids"]
        if len(untruncated) > 512:
            raise ValueError("Frozen prompt would be silently truncated")
        tokens[key] = {"cleanedText": cleaned, "inputIds": encoding.input_ids.tolist(),
                       "attentionMask": encoding.attention_mask.tolist()}
    write_json(out / "tokenization.json", tokens)
    started = time.monotonic()
    with torch.inference_mode():
        frames = pipe(prompt=run["prompt"], negative_prompt=run["negativePrompt"],
                      height=run["height"], width=run["width"], num_frames=run["numFrames"],
                      num_inference_steps=run["numInferenceSteps"], guidance_scale=5.0,
                      max_sequence_length=512, num_videos_per_prompt=1,
                      generator=generator, output_type="np", return_dict=True,
                      callback_on_step_end=step_callback,
                      callback_on_step_end_tensor_inputs=["latents"]).frames
    duration = time.monotonic() - started
    expected = (1, run["numFrames"], run["height"], run["width"], 3)
    if frames.shape != expected or not np.isfinite(frames).all() or frames.min() < 0 or frames.max() > 1:
        raise ValueError("Generated video has invalid shape/range/nonfinite pixels")
    if len(events) != run["numInferenceSteps"] or not decode_info:
        raise ValueError("Pipeline did not complete every registered step and decode")
    # Preserve the pre-encoding result. NPY contains numerical arrays only.
    with (out / "frames-float32.npy").open("xb") as stream:
        np.save(stream, frames.astype(np.float32, copy=False), allow_pickle=False)
    pixels = np.rint(frames[0] * 255).astype(np.uint8)
    raw_path = out / "frames-rgb24.raw"
    with raw_path.open("xb") as stream:
        stream.write(pixels.tobytes())
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("A local ffmpeg executable is required to preserve the video")
    version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True, timeout=10).stdout
    command = [ffmpeg, "-nostdin", "-n", "-hide_banner", "-loglevel", "error", "-threads", "4",
               "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f'{run["width"]}x{run["height"]}',
               "-framerate", str(run["fps"]), "-i", str(raw_path), "-an", "-c:v", "libx264",
               "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-threads", "4",
               "-movflags", "+faststart", str(out / "video.mp4")]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return {"generationSeconds": duration, "outputShape": list(frames.shape), "finite": True,
            "unclampedDecode": decode_info, "steps": events, "encodingCommand": command,
            "ffmpegVersion": version, "ffmpegSha256": digest(ffmpeg),
            "artifacts": [{"path": p.name, "sha256": digest(p), "bytes": p.stat().st_size}
                          for p in (out / "tokenization.json", out / "frames-float32.npy", raw_path, out / "video.mp4")]}


def worker(job_path):
    job = json.loads(job_path.read_text())
    out = job_path.parent.parent
    started = time.monotonic()
    try:
        root = Path(job["root"])
        for item in job["snapshotFiles"]:
            if digest(job_path.parent / item["name"]) != item["sha256"]:
                raise ValueError("Frozen source/receipt snapshot drift")
        np, torch = configure_worker()
        if runtime_receipt(root, job_path.parent / "requirements.lock") != job["runtime"]:
            raise ValueError("Installed runtime/source changed after supervisor snapshot")
        model_dir = root / MODEL_PATH
        publisher = json.loads((job_path.parent / "publisher.json").read_text())
        acquisition = json.loads((job_path.parent / "acquisition.json").read_text())
        print(json.dumps({"event": "verifying_local_files"}), flush=True)
        verified = verify_local_files(model_dir, publisher, acquisition)
        write_json(out / "verified-model-files.json", verified)
        pipe, loading = load_pipeline(model_dir, torch)
        write_json(out / "component-loading.json", loading)
        loaded = time.monotonic()
        result = perform_generation(pipe, job["run"], out, np, torch)
        for record in verified:
            stat = (model_dir / record["path"]).stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (record["bytes"], record["mtimeNs"], record["inode"]):
                raise ValueError("Model file changed during generation")
        result.update(status="succeeded", loadingAndVerificationSeconds=loaded-started,
                      workerSeconds=time.monotonic()-started)
        write_json(out / "worker-result.json", result)
        return 0
    except BaseException as error:
        write_json(out / "worker-error.json", {"status": "failed", "errorType": type(error).__name__,
                                              "message": str(error), "workerSeconds": time.monotonic()-started})
        traceback.print_exc()
        return 1


def stop_process_tree(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def supervise(command, env, out, timeout_seconds, max_rss):
    import psutil
    start = time.monotonic()
    peak = 0
    failure = None
    with (out / "worker.log").open("x") as log, (out / "resource-samples.jsonl").open("x") as samples:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        tracked = psutil.Process(process.pid)
        def interrupted(signum, frame):
            raise KeyboardInterrupt(f"Supervisor interrupted by signal {signum}")
        previous_handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - start
                rss = 0
                try:
                    members = [tracked] + tracked.children(recursive=True)
                    for member in members:
                        try:
                            rss += member.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    pass
                peak = max(peak, rss)
                samples.write(json.dumps({"seconds": elapsed, "processTreeRssBytes": rss}) + "\n")
                samples.flush()
                if elapsed > timeout_seconds or rss > max_rss:
                    failure = "wall_time_limit" if elapsed > timeout_seconds else "rss_limit"
                    stop_process_tree(process)
                    break
                time.sleep(0.25)
        except KeyboardInterrupt:
            failure = "supervisor_interrupted"
            stop_process_tree(process)
        except Exception as error:
            failure = "supervisor_error:" + type(error).__name__
            stop_process_tree(process)
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
        code = process.wait(timeout=5)
    return {"exitCode": code, "resourceFailure": failure, "wallSeconds": time.monotonic()-start,
            "peakSampledProcessTreeRssBytes": peak, "samplingIntervalSeconds": 0.25,
            "limitType": "supervisor polling; transient allocation overshoot is possible"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-runtime", action="store_true", help="Imports and dependency verification only; no forward calls")
    parser.add_argument("--output", type=Path, help="New receipt directory for --check-runtime")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--evaluation-protocol", type=Path)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--gate-receipt", type=Path)
    parser.add_argument("--gate-sha256")
    parser.add_argument("--acquisition-receipt", type=Path)
    parser.add_argument("--acquisition-sha256")
    parser.add_argument("--contract-receipt", type=Path)
    parser.add_argument("--contract-sha256")
    parser.add_argument("--run-id")
    parser.add_argument("--_worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._worker:
        return worker(args._worker)
    lock = ROOT / LOCK_PATH
    runtime = runtime_receipt(ROOT, lock)
    if args.check_runtime:
        if not args.output:
            parser.error("--check-runtime requires a new --output directory")
        args.output.mkdir(parents=True, exist_ok=False)
        configure_worker()
        from diffusers import WanPipeline, WanTransformer3DModel, AutoencoderKLWan, UniPCMultistepScheduler
        from transformers import UMT5EncoderModel, T5TokenizerFast
        runtime.update(status="imports_passed", modelLoaded=False, forwardCalls=0,
                       classes=[cls.__name__ for cls in (WanPipeline, WanTransformer3DModel, AutoencoderKLWan,
                                                        UniPCMultistepScheduler, UMT5EncoderModel, T5TokenizerFast)])
        write_json(args.output / "runtime.json", runtime)
        print(json.dumps({"status": "imports_passed", "modelLoaded": False, "forwardCalls": 0}))
        return 0
    for name in ("plan", "plan_sha256", "evaluation_protocol", "protocol_sha256", "gate_receipt",
                 "gate_sha256", "acquisition_receipt", "acquisition_sha256", "run_id"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required before full checkpoint loading")
    plan = checked_json(args.plan, args.plan_sha256)
    if digest(args.evaluation_protocol) != args.protocol_sha256:
        raise ValueError("Evaluation protocol SHA mismatch")
    gate = checked_json(args.gate_receipt, args.gate_sha256)
    acquisition = checked_json(args.acquisition_receipt, args.acquisition_sha256)
    contract = checked_json(args.contract_receipt, args.contract_sha256) if args.contract_receipt else None
    runs = [normalize_run(raw, plan) for raw in plan.get("runs", [])]
    if len({r["id"] for r in runs}) != len(runs) or len(runs) != 3:
        raise ValueError("Plan must contain exactly one contract and two distinct normal runs")
    if sum(r["stage"] == "contract" for r in runs) != 1 or sum(r["stage"] == "normal" for r in runs) != 2:
        raise ValueError("Unexpected stage allocation")
    for run in runs:
        validate_run(run)
    normal = [r for r in runs if r["stage"] == "normal"]
    if normal[0]["seed"] == normal[1]["seed"] or normal[0]["prompt"] == normal[1]["prompt"]:
        raise ValueError("Normal runs need two predeclared distinct prompts and seeds")
    matches = [r for r in runs if r["id"] == args.run_id]
    if len(matches) != 1:
        raise ValueError("Requested run is absent from the frozen plan")
    run = matches[0]
    validate_prerequisites(plan, args.plan_sha256, args.protocol_sha256, gate, acquisition, contract, run)
    if run["stage"] == "normal":
        for previous in normal[:normal.index(run)]:
            previous_path = safe_relative(ROOT, previous["outputDir"]) / "receipt.json"
            if not previous_path.exists():
                raise ValueError("Normal runs must execute in registered order")
            previous_receipt = json.loads(previous_path.read_text())
            if (previous_receipt.get("status") != "succeeded" or
                    previous_receipt.get("generationPlanSha256") != args.plan_sha256 or
                    previous_receipt.get("run") != previous):
                raise ValueError("Earlier generation failed or belongs to another plan; abort the fixed study")
    for path, key in ((Path(__file__), "scriptSha256"), (lock, "requirementsLockSha256"),
                      (ROOT / PUBLISHER_PATH, "publisherManifestSha256")):
        if digest(path) != plan.get(key):
            raise ValueError(f"Frozen plan source pin mismatch: {key}")
    (ROOT / "eval/runs").mkdir(parents=True, exist_ok=True)
    process_lock = (ROOT / "eval/runs/.wan-generation.lock").open("a")
    try:
        fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        process_lock.close()
        raise ValueError("Another Wan generation supervisor is active")
    atexit.register(process_lock.close)
    out = safe_relative(ROOT, run["outputDir"])
    out.mkdir(parents=True, exist_ok=False)
    source = out / "source"
    source.mkdir()
    to_copy = [(Path(__file__), "eval-generate-wan.py"), (lock, "requirements.lock"),
               (ROOT / PUBLISHER_PATH, "publisher.json"), (args.plan, "plan.json"),
               (args.evaluation_protocol, "evaluation-protocol.md"), (args.gate_receipt, "negative-gate.json"),
               (args.acquisition_receipt, "acquisition.json")]
    if args.contract_receipt:
        to_copy.append((args.contract_receipt, "contract-receipt.json"))
    snapshots = []
    for original, name in to_copy:
        shutil.copyfile(original, source / name)
        snapshots.append({"name": name, "sha256": digest(source / name)})
    site = ROOT / "eval/.venv-wan/lib/python3.12/site-packages"
    for entry in runtime["criticalSources"]:
        name = "runtime-source/" + entry["path"]
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(site / entry["path"], target)
        if digest(target) != entry["sha256"]:
            raise ValueError("Runtime source changed while taking its snapshot")
        snapshots.append({"name": name, "sha256": digest(target)})
    write_json(source / "job.json", {"root": str(ROOT), "run": run, "snapshotFiles": snapshots, "runtime": runtime})
    write_json(out / "runtime.json", runtime)
    env = os.environ.copy()
    env.update(OFFLINE_ENV)
    env.pop("PYTHONPATH", None)
    try:
        result = supervise([sys.executable, str(source / "eval-generate-wan.py"), "--_worker", str(source / "job.json")],
                           env, out, run["timeoutSeconds"], run["maxRssBytes"])
    except Exception as error:
        result = {"exitCode": None, "resourceFailure": "supervisor_setup_error",
                  "errorType": type(error).__name__, "message": str(error)}
    worker_file = out / "worker-result.json"
    completed = json.loads(worker_file.read_text()) if worker_file.exists() else None
    succeeded = result["exitCode"] == 0 and not result["resourceFailure"] and completed and completed.get("status") == "succeeded"
    output_record = ({"path": str((out / "video.mp4").relative_to(ROOT)),
                      "sha256": digest(out / "video.mp4")} if succeeded else None)
    receipt = {"schemaVersion": 1, "status": "succeeded" if succeeded else "failed", "stage": run["stage"],
               "eligibleAsEvaluationControl": run["stage"] == "normal" and bool(succeeded),
               "generationSlot": run["id"], "inputMedia": [], "output": output_record,
               "completedAt": datetime.now(timezone.utc).isoformat(), "run": run,
               "generationPlanSha256": args.plan_sha256, "evaluationProtocolSha256": args.protocol_sha256,
               "negativeGateReceiptSha256": args.gate_sha256, "acquisitionReceiptSha256": args.acquisition_sha256,
               "contractReceiptSha256": args.contract_sha256, "modelId": MODEL_ID, "modelRevision": REVISION,
               "scriptSha256": digest(source / "eval-generate-wan.py"), "requirementsLockSha256": digest(source / "requirements.lock"),
               "runtimeReceiptSha256": digest(out / "runtime.json"), "resourceMonitoring": result,
               "workerResultSha256": digest(worker_file) if worker_file.exists() else None,
               "failurePolicy": "Preserve failed output; abort study; no replacement or silent retry."}
    write_json(out / "receipt.json", receipt)
    if succeeded and run["stage"] == "normal":
        write_json(out / "parent-receipt.json", {
            "schemaVersion": 1, "status": "completed", "generationSlot": run["id"],
            "generationPlanSha256": args.plan_sha256, "evaluationProtocolSha256": args.protocol_sha256,
            "inputMedia": [], "modelId": MODEL_ID, "modelRevision": REVISION,
            "output": output_record,
            "rawGenerationReceipt": {"path": str((out / "receipt.json").relative_to(ROOT)),
                                     "sha256": digest(out / "receipt.json")},
        })
    print(json.dumps({"status": receipt["status"], "runId": run["id"], "resourceMonitoring": result}))
    return 0 if succeeded else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "failed", "errorType": type(error).__name__, "message": str(error)}), file=sys.stderr)
        raise SystemExit(1)
