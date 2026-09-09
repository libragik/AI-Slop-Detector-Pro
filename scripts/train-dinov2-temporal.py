#!/usr/bin/env python3
"""Fixed development experiment on cached DINOv2 CLS features.

Both heads are trained once. The appearance head is a control, never a fallback.
Feature splices and video labels are weak supervision, not pixel-origin truth.
No detector probability or product validation is established by this program.
"""
import argparse
from collections import Counter
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import time
from types import SimpleNamespace

import numpy as np
import torch
from safetensors.torch import load_file, save_file

ROOT = Path(__file__).resolve().parents[1]
SEED = 2026090503
QUALITIES = ("original", "mild", "severe")
GENERATORS = ("cogvideox", "easyanimate", "hunyuanvideo", "ltxvideo")
HEAD_CONFIG = {
    "frames": 8, "embeddingDimensions": 384, "hiddenDimensions": 128,
    "activation": "GELU", "normalization": "LayerNorm-per-frame",
    "temporalInput": "cls-and-absolute-next-difference-final-zero",
    "appearanceControlInput": "cls-and-zero-difference-same-shape-and-initialization",
    "pooling": "maximum-frame-logit", "thresholdLogit": 0.0,
    "scoreIsProbability": False,
}
TRAINING_CONFIG = {
    "seed": SEED, "epochs": 20, "batchSize": 64,
    "optimizer": "AdamW", "learningRate": 0.001, "weightDecay": 0.0001,
    "betas": [0.9, 0.999], "epsilon": 1e-8,
    "wholeRealPerEpoch": 3072, "wholeAiPerEpoch": 3072,
    "realAiFeatureSplicesPerEpoch": 3072, "realRealFeatureSplicesPerEpoch": 3072,
    "spliceFrames": 2, "qualities": list(QUALITIES),
    "device": "cpu", "dtype": "float32", "threads": 4,
    "checkpointSelection": "fixed-final-epoch-only", "earlyStopping": False,
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic_new(path, writer):
    """Publish a complete file exclusively; never replace prior run evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".pending-", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        writer(temporary)
        with temporary.open("rb") as f:
            os.fsync(f.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    body = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    atomic_new(path, lambda temporary: temporary.write_text(body))


def write_matching_json(path, value):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Existing transaction receipt differs: " + str(path))
    else:
        write_json(path, value)


def checked_path(value, area="eval"):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing artifact path")
    path = (ROOT / value).resolve()
    if not path.is_relative_to((ROOT / area).resolve()) or not path.is_file():
        raise ValueError("Artifact is outside its registered workspace area: " + value)
    return path


def checked_file(value, expected, area="eval"):
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("Missing artifact SHA-256")
    path = checked_path(value, area)
    if sha(path) != expected:
        raise ValueError("Artifact hash mismatch: " + value)
    return path


def metadata_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def media_hashes(value):
    """Known input identities only; never read prediction files to fit a model."""
    found = set()
    if isinstance(value, list):
        for item in value:
            found.update(media_hashes(item))
    elif isinstance(value, dict):
        if isinstance(value.get("path"), str) and value["path"].lower().endswith((".mp4", ".mov", ".mkv")):
            if isinstance(value.get("sha256"), str):
                found.add(value["sha256"])
        if isinstance(value.get("cgiSourceSha256"), str):
            found.add(value["cgiSourceSha256"])
        for item in value.values():
            found.update(media_hashes(item))
    return found


def validate_acquisition(protocol):
    acquisition = protocol["acquisition"]
    files = {kind: checked_file(acquisition[kind + "Path"], acquisition[kind + "Sha256"])
             for kind in ("manifest", "completion", "fixture")}
    fixture = json.loads(files["fixture"].read_text())
    completion = json.loads(files["completion"].read_text())
    parents = [json.loads(line) for line in files["manifest"].read_text().splitlines() if line.strip()]
    expected_counts = {"train": {"real": 1024, "ai": 1024, "aiPerGenerator": 256},
                       "internal_development": {"real": 128, "ai": 128, "aiPerGenerator": 32}, "total": 2304}
    acquisition_script = "scripts/acquire-genbuster-training-subset.py"
    if (fixture.get("frozen") is not True or not isinstance(fixture.get("frozenAt"), str)
            or fixture.get("counts") != expected_counts
            or fixture.get("acquisitionScriptSha256") != protocol["sourceHashes"].get(acquisition_script)
            or completion.get("schemaVersion") != 1 or completion.get("complete") is not True
            or completion.get("records") != 2304 or completion.get("uniqueContentHashes") != 2304
            or completion.get("counts") != expected_counts
            or completion.get("fixtureSha256") != acquisition["fixtureSha256"]
            or completion.get("scriptSha256") != fixture.get("acquisitionScriptSha256")
            or completion.get("manifestPath") != acquisition["manifestPath"]
            or completion.get("manifestSha256") != acquisition["manifestSha256"]
            or completion.get("sourceUrl") != fixture.get("sourceUrl")
            or completion.get("archiveBytes") != fixture.get("archiveBytes")):
        raise ValueError("Acquisition fixture/completion does not bind the frozen cohort")
    # This function only recomputes the pinned ZIP-index selection; it does not
    # download members, decode media, or perform any model operation.
    acquisition_module = metadata_module(
        checked_file(acquisition_script, fixture["acquisitionScriptSha256"], "scripts"), "dinov2_acquisition_validation")
    if acquisition_module.load_frozen(files["fixture"], acquisition["fixtureSha256"], root=ROOT) != fixture:
        raise ValueError("Acquisition differs from deterministic frozen selection")
    excluded = set(fixture["excludedKnownMediaSha256"])
    if any(re.fullmatch(r"[0-9a-f]{64}", x) is None for x in excluded):
        raise ValueError("Malformed known-media exclusion identity")
    known = set()
    for name, expected in fixture["inputSha256"].items():
        path = checked_file(name, expected)
        if name.endswith(".jsonl"):
            value = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        elif name.endswith(".json"):
            value = json.loads(path.read_text())
        else:
            continue
        known.update(media_hashes(value))
    if not known.issubset(excluded) or completion.get("excludedKnownMediaHashes") != len(excluded):
        raise ValueError("Acquisition omitted a known benchmark/control identity exclusion")
    entries = fixture["entries"]
    if len(parents) != 2304 or len(entries) != 2304:
        raise ValueError("Exact 2304 acquired parents required")
    ids, paths, contents, members, allocation = set(), set(), set(), set(), Counter()
    for parent, entry in zip(parents, entries):
        if any(parent.get(key) != value for key, value in entry.items()):
            raise ValueError("Acquisition manifest changed a frozen entry or its order")
        if (parent["id"] != parent["parentId"] or parent["id"] in ids
                or parent["archiveMember"] in members
                or parent["sha256"] in contents or parent["sha256"] in excluded
                or parent.get("acquisitionFixtureSha256") != acquisition["fixtureSha256"]):
            raise ValueError("Acquired parent duplication, overlap, or fixture mismatch")
        path = checked_file(parent["path"], parent["sha256"])
        if (path in paths or type(parent["bytes"]) is not int
                or path.stat().st_size != parent["bytes"]
                or parent["bytes"] != parent["zip"]["uncompressedBytes"]):
            raise ValueError("Acquired media path or byte census changed")
        ids.add(parent["id"]); paths.add(path); contents.add(parent["sha256"]); members.add(parent["archiveMember"])
        allocation[(parent["split"], parent["label"], parent["generator"])] += 1
    expected_allocation = Counter()
    for split, real, per_generator in (("train", 1024, 256), ("internal_development", 128, 32)):
        expected_allocation[(split, "real", None)] = real
        for generator in GENERATORS:
            expected_allocation[(split, "ai", generator)] = per_generator
    if allocation != expected_allocation or completion.get("actualUncompressedBytes") != sum(x["bytes"] for x in parents):
        raise ValueError("Acquisition class/generator quotas or byte total changed")
    return parents


def setup_runtime():
    if torch.__version__ != "2.8.0" or np.__version__ != "2.2.6":
        raise ValueError("Pinned Torch2.8.0 and NumPy2.2.6 runtime required")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(SEED)
    random.seed(SEED)
    np.random.seed(SEED)


class Head(torch.nn.Module):
    def __init__(self, temporal):
        super().__init__()
        self.temporal = temporal
        width = 768
        self.layers = torch.nn.Sequential(
            torch.nn.LayerNorm(width), torch.nn.Linear(width, 128),
            torch.nn.GELU(), torch.nn.Linear(128, 1),
        )

    def inputs(self, cls):
        if cls.ndim != 3 or cls.shape[1:] != (8, 384):
            raise ValueError("Expected batch of eight384-dimensional CLS embeddings")
        if not self.temporal:
            return torch.cat((cls, torch.zeros_like(cls)), dim=-1)
        # Compute after feature splicing; never carry old donor/host differences.
        delta = torch.cat(((cls[:, 1:] - cls[:, :-1]).abs(), torch.zeros_like(cls[:, :1])), dim=1)
        return torch.cat((cls, delta), dim=-1)

    def forward(self, cls):
        return self.layers(self.inputs(cls)).squeeze(-1).amax(dim=1)


def make_heads():
    heads = {}
    optimizers = {}
    for name in ("temporal", "appearance_control"):
        torch.manual_seed(SEED)
        heads[name] = Head(name == "temporal").float().cpu()
        optimizers[name] = torch.optim.AdamW(
            heads[name].parameters(), lr=0.001, betas=(0.9, 0.999), eps=1e-8,
            weight_decay=0.0001, foreach=False, fused=False,
        )
    return heads, optimizers


def feature_recipe(protocol, protocol_sha):
    for name, expected in protocol["sourceHashes"].items():
        checked_file(name, expected, "scripts")
    module_path = protocol["featureModulePath"]
    driver_path = protocol["featureDriverPath"]
    if module_path != "scripts/dinov2-temporal-features.py" or driver_path != "scripts/build-dinov2-training-features.py":
        raise ValueError("Unexpected feature implementation")
    module = metadata_module(checked_file(module_path, protocol["sourceHashes"][module_path], "scripts"),
                             "dinov2_feature_validation")
    driver = metadata_module(checked_file(driver_path, protocol["sourceHashes"][driver_path], "scripts"),
                             "dinov2_driver_validation")
    if protocol.get("qualityRecipes") != driver.QUALITY_RECIPES:
        raise ValueError("Frozen quality recipes differ from the driver")
    identity = module.runtime_identity()  # Metadata only: no backbone load.
    if protocol["featureIdentity"] != identity or protocol["featureDevice"] not in ("cpu", "mps"):
        raise ValueError("Frozen feature runtime identity changed")
    backbone = protocol["backbone"]
    if backbone["weightsSha256"] != identity["assets"]["model.safetensors"]["sha256"]:
        raise ValueError("Protocol does not pin the official backbone")
    checked_file(str(Path(backbone["modelDirectory"]) / "model.safetensors"), backbone["weightsSha256"])
    contract_path = checked_file(backbone["contractPath"], backbone["contractSha256"])
    # Checks already stored synthetic CPU/MPS arrays and strict-load evidence;
    # validate_contract performs no model forward or media decode.
    contract = module.validate_contract(contract_path)
    return {"protocolSha256": protocol_sha,
            "acquisitionManifestSha256": protocol["acquisition"]["manifestSha256"],
            "backboneSha256": backbone["weightsSha256"],
            "featureModuleSha256": protocol["sourceHashes"][module_path],
            "driverSha256": protocol["sourceHashes"][driver_path]}, contract


def validate_extraction(extraction, row, parent, cls, protocol, contract, original_duration):
    identity = protocol["featureIdentity"]
    load = extraction.get("strictLoad", {})
    if (extraction.get("schemaVersion") != 1 or extraction.get("status") != "completed"
            or extraction.get("window") != row["window"]
            or extraction.get("model") != identity or extraction.get("modelFingerprint") != digest(identity)
            or extraction.get("contract") != contract
            or load != json.loads(checked_path(contract["path"]).read_text())["load"]
            or extraction.get("device") != protocol["featureDevice"]
            or extraction.get("featureShape") != [8, 384] or extraction.get("featureDtype") != "float32"
            or extraction.get("clsBytesSha256") != hashlib.sha256(cls.tobytes()).hexdigest()
            or not all(load.get(k) is True for k in ("strict", "allTensorsFinite", "allLoadedTensorsEqual"))
            or load.get("tensorElements") != 22056576 or type(load.get("tensorCount")) is not int
            or load["tensorCount"] <= 0
            or any(load.get(k) != [] for k in ("missingKeys", "unexpectedKeys", "mismatchedKeys"))):
        raise ValueError("Feature extraction lacks matching complete model/input evidence")
    source = extraction["source"]
    media = checked_path(row["mediaPath"])
    if (checked_path(source["path"]) != media or source["sha256"] != row["mediaSha256"]
            or source["bytes"] != media.stat().st_size):
        raise ValueError("Extraction source does not match the receipted media")
    duration = source["duration"]
    if type(duration) not in (float, int) or not math.isfinite(duration) or not .5 <= duration <= 120 + 1e-6:
        raise ValueError("Extraction duration is unsupported")
    if row["quality"] == "original":
        original_duration = duration
    if original_duration is None:
        raise ValueError("Original feature receipt must precede its derivatives")
    length = min(2.0, original_duration)
    fraction = int(hashlib.sha256(("dinov2-window-v1:" + parent["sha256"]).encode()).hexdigest()[:16], 16) / 2**64
    start = round(fraction * max(0.0, original_duration - length), 9)
    if row["window"] != {"start": start, "end": start + length} or start + length > duration + 1e-6:
        raise ValueError("Feature window differs from the frozen original-parent interval")
    frames = extraction["frames"]
    if not isinstance(frames, list) or len(frames) != 8:
        raise ValueError("Exactly eight native sample receipts required")
    indices, times = [], []
    for frame in frames:
        index, timestamp = frame["nativeIndex"], frame["timestamp"]
        if (type(index) is not int or not 0 <= index < source["frameCount"]
                or type(timestamp) not in (int, float) or not math.isfinite(timestamp)
                or not start <= timestamp < start + length
                or frame["nativeShape"] != [source["height"], source["width"], 3]
                or not math.isclose(frame["absoluteTimestamp"], timestamp + source["ptsOrigin"], abs_tol=1e-6)
                or any(re.fullmatch(r"[0-9a-f]{64}", frame[k]) is None
                       for k in ("rgbSha256", "preprocessedFP32Sha256"))):
            raise ValueError("Invalid native sampled-frame evidence")
        indices.append(index); times.append(timestamp)
    if (len(set(indices)) != 8 or indices != sorted(indices)
            or any(a >= b for a, b in zip(times, times[1:]))
            or extraction["decoder"].get("selectedFrameCount") != 8
            or len(extraction["decoder"].get("actualDecodedTimestamps", [])) != 8
            or any(not math.isclose(t, frames[i]["absoluteTimestamp"], abs_tol=.001, rel_tol=0)
                   for i, t in enumerate(extraction["decoder"]["actualDecodedTimestamps"]))):
        raise ValueError("Repeated, unordered, or incomplete sampled frames")
    return original_duration


def validate_construction(construction, row, parent, protocol):
    if row["quality"] == "original":
        if (construction != {"original": True, "parentSha256": parent["sha256"]}
                or row["mediaPath"] != parent["path"] or row["mediaSha256"] != parent["sha256"]):
            raise ValueError("Original feature media differs from its acquired parent")
        return
    recipe = protocol["qualityRecipes"][row["quality"]]
    arguments = ["-map", "0:v:0", "-an", "-vf", recipe["filter"], "-crf", recipe["crf"],
                 "-c:v", "libx264", "-preset", "veryfast", "-threads", "2", "-pix_fmt", "yuv420p",
                 "-map_metadata", "-1", "-movflags", "+faststart"]
    if (construction.get("parentId") != parent["id"] or construction.get("parentSha256") != parent["sha256"]
            or construction.get("quality") != row["quality"] or construction.get("path") != row["mediaPath"]
            or construction.get("sha256") != row["mediaSha256"]
            or construction.get("bytes") != checked_path(row["mediaPath"]).stat().st_size
            or construction.get("arguments") != arguments
            or construction.get("driverSha256") != protocol["sourceHashes"][protocol["featureDriverPath"]]):
        raise ValueError("Feature media construction differs from the frozen quality recipe")


def load_cache(path, protocol, protocol_sha):
    bindings, contract = feature_recipe(protocol, protocol_sha)
    parents = validate_acquisition(protocol)
    document = json.loads(Path(path).read_text())
    rows = document["rows"]
    if (document.get("complete") is not True or len(rows) != 2304 * 3
            or any(document.get(k) != v for k, v in bindings.items())
            or document.get("sourceHashes") != protocol["sourceHashes"]
            or document.get("featureDevice") != protocol["featureDevice"]):
        raise ValueError("Exactly6912 complete planned feature rows required")
    seen_features, seen_receipts, seen_ids = set(), set(), set()
    arrays = []
    original_duration = None
    for i, row in enumerate(rows):
        parent, quality = parents[i // 3], QUALITIES[i % 3]
        expected_id = hashlib.sha256((parent["id"] + "|dinov2-feature-v1|" + quality).encode()).hexdigest()[:24]
        if (row["parentId"] != parent["id"] or row["quality"] != quality or row["id"] != expected_id
                or any(row[k] != parent[k] for k in ("split", "label", "generator"))
                or row["sourceSha256"] != parent["sha256"] or row["id"] in seen_ids):
            raise ValueError("Feature allocation/identity/order differs from the acquired parent set")
        file = checked_file(row["featurePath"], row["featureSha256"])
        receipt_path = checked_file(row["receiptPath"], row["receiptSha256"])
        if file != Path(path).resolve().parent / "features" / (expected_id + ".npz") or receipt_path != file.with_suffix(".json"):
            raise ValueError("Feature paths differ from the driver's deterministic output layout")
        checked_file(row["mediaPath"], row["mediaSha256"])
        if file in seen_features or receipt_path in seen_receipts:
            raise ValueError("Feature or wrapper path reused for another parent/quality")
        seen_features.add(file); seen_receipts.add(receipt_path); seen_ids.add(row["id"])
        receipt = json.loads(receipt_path.read_text())
        base_row = {k: v for k, v in row.items() if k not in ("receiptPath", "receiptSha256")}
        if receipt.get("row") != base_row or receipt.get("bindings") != bindings:
            raise ValueError("Feature wrapper does not bind the exact cache row and recipe")
        with np.load(file, allow_pickle=False) as archive:
            if archive.files != ["cls"]:
                raise ValueError("Feature archive must contain only cls")
            cls = archive["cls"]
            if cls.dtype != np.float32 or cls.shape != (8, 384) or not np.isfinite(cls).all():
                raise ValueError("Invalid or nonfinite CLS features")
            arrays.append(cls.copy())
        validate_construction(receipt["mediaConstruction"], row, parent, protocol)
        original_duration = validate_extraction(receipt["extraction"], row, parent, cls, protocol, contract,
                                                None if quality == "original" else original_duration)
    return document, rows, np.stack(arrays)


def epoch_examples(rows, epoch):
    """Every train parent/quality has one whole example; each real also hosts two splices."""
    rng = np.random.default_rng(SEED + epoch)
    examples = [(i, None, None, int(row["label"] == "ai"), "whole")
                for i, row in enumerate(rows) if row["split"] == "train"]
    for quality in QUALITIES:
        real = sorted((i for i, r in enumerate(rows) if r["split"] == "train" and
                       r["quality"] == quality and r["label"] == "real"), key=lambda i: rows[i]["parentId"])
        ai = sorted((i for i, r in enumerate(rows) if r["split"] == "train" and
                     r["quality"] == quality and r["label"] == "ai"), key=lambda i: rows[i]["parentId"])
        if len(real) != len(ai) or len(real) < 2:
            raise ValueError("Balanced same-quality train parents required")
        ai_donors = rng.permutation(ai)
        offset = int(rng.integers(1, len(real)))
        for j, host in enumerate(real):
            start = int(rng.integers(0, 7))
            examples.append((host, int(ai_donors[j]), start, 1, "real_ai_feature_splice"))
            examples.append((host, real[(j + offset) % len(real)], start, 0, "real_real_feature_splice"))
    return [examples[int(i)] for i in rng.permutation(len(examples))]


def make_batch(features, examples):
    x = np.stack([features[item[0]] for item in examples])
    for i, (_, donor, start, _, _) in enumerate(examples):
        if donor is not None:
            x[i, start:start + 2] = features[donor, start:start + 2]
    labels = torch.tensor([item[3] for item in examples], dtype=torch.float32)
    return torch.from_numpy(x), labels


def train_epoch(heads, optimizers, rows, features, epoch, batch_size=64, deadline=None):
    examples = epoch_examples(rows, epoch)
    totals = {name: 0.0 for name in heads}
    counts = {}
    for item in examples:
        counts[item[4]] = counts.get(item[4], 0) + 1
    for head in heads.values():
        head.train()
    for start in range(0, len(examples), batch_size):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Training invocation budget reached before next batch")
        batch = examples[start:start + batch_size]
        x, y = make_batch(features, batch)
        for name, head in heads.items():
            optimizers[name].zero_grad(set_to_none=True)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(head(x), y)
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite loss")
            loss.backward()
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in head.parameters()):
                raise ValueError("Missing/nonfinite gradient")
            optimizers[name].step()
            if any(not torch.isfinite(p).all() for p in head.parameters()):
                raise ValueError("Nonfinite updated parameter")
            totals[name] += float(loss.detach()) * len(batch)
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Training invocation budget reached after batch")
    return {"epoch": epoch + 1, "examples": len(examples), "exampleTypes": counts,
            "averageTrainingLoss": {k: v / len(examples) for k, v in totals.items()}}


def safe_tree(value):
    if isinstance(value, torch.Tensor):
        return value.device.type == "cpu" and (not value.is_floating_point() or bool(torch.isfinite(value).all()))
    if isinstance(value, dict):
        return all(type(k) in (str, int) and safe_tree(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return all(safe_tree(v) for v in value)
    return value is None or type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))


def save_state(path, heads, optimizers, next_epoch, fingerprint, epoch_record=None):
    state = {"schemaVersion": 2, "nextEpoch": next_epoch, "fingerprint": fingerprint,
             "epochRecord": epoch_record,
             "heads": {k: h.state_dict() for k, h in heads.items()},
             "optimizers": {k: o.state_dict() for k, o in optimizers.items()}}
    if not safe_tree(state):
        raise ValueError("State contains unsupported values")
    atomic_new(path, lambda temporary: torch.save(state, temporary))
    return sha(path)


def read_state(path, expected_sha, fingerprint):
    if sha(path) != expected_sha:
        raise ValueError("Training-state hash mismatch")
    state = torch.load(path, map_location="cpu", weights_only=True)
    if (not safe_tree(state) or set(state) != {"schemaVersion", "nextEpoch", "fingerprint", "epochRecord", "heads", "optimizers"}
            or state.get("schemaVersion") != 2 or state.get("fingerprint") != fingerprint):
        raise ValueError("Unexpected restricted training-state schema")
    if type(state["nextEpoch"]) is not int or not 0 <= state["nextEpoch"] <= 20:
        raise ValueError("Invalid resume epoch")
    return state


def restore_state(path, expected_sha, heads, optimizers, fingerprint):
    state = read_state(path, expected_sha, fingerprint)
    if set(state["heads"]) != set(heads) or set(state["optimizers"]) != set(optimizers):
        raise ValueError("Training-state head mismatch")
    for name in heads:
        expected = heads[name].state_dict()
        supplied = state["heads"][name]
        if (set(supplied) != set(expected)
                or any(supplied[k].shape != expected[k].shape or supplied[k].dtype != expected[k].dtype for k in expected)):
            raise ValueError("Training-state head tensor contract changed")
        groups = state["optimizers"][name].get("param_groups", [])
        initial_groups = optimizers[name].state_dict()["param_groups"]
        if len(groups) != len(initial_groups) or any(g != initial for g, initial in zip(groups, initial_groups)):
            raise ValueError("Resume optimizer recipe changed")
        optimizer_state = state["optimizers"][name].get("state", {})
        parameters = list(heads[name].parameters())
        parameter_ids = [index for group in groups for index in group["params"]]
        if state["nextEpoch"] > 0:
            if set(optimizer_state) != set(parameter_ids):
                raise ValueError("Resume lost optimizer state for a trained parameter")
            steps = []
            for index, parameter in zip(parameter_ids, parameters):
                value = optimizer_state[index]
                if (set(value) != {"step", "exp_avg", "exp_avg_sq"}
                        or any(not isinstance(value[key], torch.Tensor) or value[key].shape != parameter.shape
                               or value[key].dtype != parameter.dtype for key in ("exp_avg", "exp_avg_sq"))
                        or not isinstance(value["step"], torch.Tensor) or value["step"].ndim != 0
                        or float(value["step"]) <= 0 or not float(value["step"]).is_integer()):
                    raise ValueError("Resume optimizer tensor/step schema changed")
                steps.append(float(value["step"]))
            if len(set(steps)) != 1:
                raise ValueError("Resume optimizer parameters have inconsistent step counts")
        heads[name].load_state_dict(state["heads"][name], strict=True)
        optimizers[name].load_state_dict(state["optimizers"][name])
    return state["nextEpoch"]


def recover_epochs(output, heads, optimizers, fingerprint):
    """Recover a fully published orphan state; never overwrite it or refit it."""
    output = Path(output)
    found = {int(p.stem.split("-")[1]) for pattern in ("state-??.pt", "epoch-??.json") for p in output.glob(pattern)}
    if not found:
        return 0
    if found != set(range(1, max(found) + 1)) or max(found) > 20:
        raise ValueError("Training checkpoint sequence has a gap or extra epoch")
    for epoch in sorted(found):
        state_path = output / f"state-{epoch:02d}.pt"
        receipt_path = output / f"epoch-{epoch:02d}.json"
        if not state_path.is_file():
            raise ValueError("Epoch receipt lacks its saved state")
        observed_sha = sha(state_path)
        state = read_state(state_path, observed_sha, fingerprint)
        record = state["epochRecord"]
        if (state["nextEpoch"] != epoch or not isinstance(record, dict) or record.get("epoch") != epoch
                or set(record) != {"epoch", "examples", "exampleTypes", "averageTrainingLoss"}
                or type(record["examples"]) is not int or record["examples"] <= 0
                or set(record["averageTrainingLoss"]) != set(heads)
                or not safe_tree(record)):
            raise ValueError("Orphan checkpoint lacks a complete matching epoch record")
        count = record["examples"]
        if (count % 4 or record["exampleTypes"] != {"whole": count // 2, "real_ai_feature_splice": count // 4,
                                                   "real_real_feature_splice": count // 4}
                or any(type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0
                       for loss in record["averageTrainingLoss"].values())):
            raise ValueError("Orphan checkpoint has invalid epoch accounting")
        committed = {**record, "fingerprint": fingerprint, "stateFile": state_path.name, "stateSha256": observed_sha}
        if receipt_path.exists():
            if json.loads(receipt_path.read_text()) != committed:
                raise ValueError("Committed epoch receipt and restricted state differ")
        else:
            # Validate both model and optimizer before making an orphan reachable.
            restore_state(state_path, observed_sha, heads, optimizers, fingerprint)
            write_json(receipt_path, committed)
            write_matching_json(output / f"recovered-{epoch:02d}.json",
                                {"recoveredAtomicOrphanState": True, "stateFile": state_path.name,
                                 "stateSha256": observed_sha, "epoch": epoch, "fingerprint": fingerprint})
    latest = max(found)
    last = output / f"state-{latest:02d}.pt"
    return restore_state(last, sha(last), heads, optimizers, fingerprint)


def export_head(path, head):
    expected = {k: t.contiguous() for k, t in head.state_dict().items()}
    if Path(path).exists():
        actual = load_file(str(path), device="cpu")
        if set(actual) != set(expected) or any(actual[k].dtype != expected[k].dtype or actual[k].shape != expected[k].shape
                                               or not torch.equal(actual[k], expected[k]) for k in expected):
            raise ValueError("Previously exported head differs from final checkpoint")
    else:
        atomic_new(path, lambda temporary: save_file(expected, str(temporary)))
    return sha(path)


def head_scores(heads, features):
    result = {name: [] for name in heads}
    with torch.inference_mode():
        for name, head in heads.items():
            head.eval()
            for start in range(0, len(features), 64):
                logits = head(torch.from_numpy(features[start:start + 64]))
                if not torch.isfinite(logits).all():
                    raise ValueError("Nonfinite evaluation logits")
                result[name].extend(float(x) for x in logits)
    return result


def train(args):
    protocol_path = checked_path(args.protocol)
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("frozen") is not True or protocol.get("heads") != HEAD_CONFIG or protocol.get("training") != TRAINING_CONFIG:
        raise ValueError("Complete frozen protocol with exact head/training recipe required")
    source_sha = sha(__file__)
    if protocol["sourceHashes"].get("scripts/train-dinov2-temporal.py") != source_sha:
        raise ValueError("Training source changed after freeze")
    features_path = checked_path(args.features)
    protocol_sha = sha(protocol_path)
    document, rows, features = load_cache(features_path, protocol, protocol_sha)
    configuration = {"protocolSha256": sha(protocol_path), "featureManifestSha256": sha(ROOT / args.features),
                     "trainingSourceSha256": source_sha, "heads": HEAD_CONFIG, "training": TRAINING_CONFIG,
                     "torch": torch.__version__, "numpy": np.__version__}
    fingerprint = digest(configuration)
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / "eval").resolve()):
        raise ValueError("Training output must stay in the evaluation workspace")
    heads, optimizers = make_heads()
    next_epoch = 0
    if (output / "configuration.json").exists():
        if not args.resume or (output / "complete.json").exists():
            raise ValueError("Use a fresh output or explicitly resume an incomplete identical run")
        initial = json.loads((output / "configuration.json").read_text())
        if initial != configuration:
            raise ValueError("Cannot resume changed configuration")
        next_epoch = recover_epochs(output, heads, optimizers, fingerprint)
    else:
        if output.exists() and any(p.name != ".training-supervisor.lock" and
                                   re.fullmatch(r"training-watchdog-[0-9]{3}(\.running)?\.json", p.name) is None
                                   for p in output.iterdir()):
            raise ValueError("Uninitialized output contains unrecognized prior artifacts")
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "configuration.json", configuration)
    started = time.monotonic()
    deadline = started + 1800
    for epoch in range(next_epoch, 20):
        if time.monotonic() - started > 1800:
            raise TimeoutError("1800-second training budget reached before next epoch")
        record = train_epoch(heads, optimizers, rows, features, epoch, deadline=deadline)
        state_name = f"state-{epoch + 1:02d}.pt"
        state_sha = save_state(output / state_name, heads, optimizers, epoch + 1, fingerprint, epoch_record=record)
        committed = {**record, "fingerprint": fingerprint, "stateFile": state_name, "stateSha256": state_sha}
        write_json(output / f"epoch-{epoch + 1:02d}.json", committed)
        print(json.dumps(committed, sort_keys=True), flush=True)
    head_files = {}
    for name, head in heads.items():
        target = output / (name + ".safetensors")
        head_files[name] = {"path": str(target.relative_to(ROOT)), "sha256": export_head(target, head),
                            "parameters": sum(p.numel() for p in head.parameters())}
    indices = [i for i, row in enumerate(rows) if row["split"] == "internal_development"]
    scores = head_scores(heads, features[indices])
    internal_rows = [{**rows[index], "logits": {name: scores[name][j] for name in heads},
                      "scoreIsProbability": False} for j, index in enumerate(indices)]
    write_matching_json(output / "internal-development.json", {"usedForCheckpointOrThresholdSelection": False,
                "sourceIndependenceEstablished": False, "rows": internal_rows})
    if sha(protocol_path) != protocol_sha or sha(features_path) != configuration["featureManifestSha256"]:
        raise ValueError("Frozen protocol/cache manifest changed during training")
    for name, expected in protocol["sourceHashes"].items():
        checked_file(name, expected, "scripts")
    write_json(output / "complete.json", {"complete": True, "fingerprint": fingerprint,
                "epochs": 20, "heads": head_files, "internalDevelopmentRows": len(internal_rows),
                "elapsedThisInvocationSeconds": time.monotonic() - started,
                "productValidation": False, "diagnosticsStillRequired": True})


def supervised_training(args):
    """Hard owned-tree cap; incomplete journals never reset a spent budget."""
    protocol_path = checked_path(args.protocol)
    protocol = json.loads(protocol_path.read_text())
    limits = protocol.get("resourceLimits", {})
    if (protocol.get("frozen") is not True or limits.get("headTrainingSeconds") != 1800
            or limits.get("headTrainingTreeRssBytes") != 8 * 1024**3):
        raise ValueError("Frozen1800-second/8GiB head-training limits required")
    driver_path = protocol["featureDriverPath"]
    driver = metadata_module(checked_file(driver_path, protocol["sourceHashes"][driver_path], "scripts"),
                             "dinov2_training_supervisor")
    if protocol["sourceHashes"].get("scripts/train-dinov2-temporal.py") != sha(__file__):
        raise ValueError("Training supervisor source differs from freeze")
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / "eval").resolve()):
        raise ValueError("Training output must stay inside eval")
    if output.exists() and not args.resume:
        raise ValueError("Existing run requires explicit identical-run resume")
    if (output / "complete.json").exists():
        raise ValueError("Training is complete; do not rerun or choose another checkpoint")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".training-supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        running_files = sorted(output.glob("training-watchdog-???.running.json"))
        completed_files = sorted(output.glob("training-watchdog-???.json"))
        if len(running_files) != len(completed_files):
            raise ValueError("Unfinished supervisor journal: retain evidence and inspect the prior owned run")
        prior = 0.0
        identity = {"protocolSha256": sha(protocol_path), "featureManifestSha256": sha(checked_path(args.features)),
                    "trainingSourceSha256": sha(__file__),
                    "driverSha256": protocol["sourceHashes"][driver_path]}
        for i, (running_path, completed_path) in enumerate(zip(running_files, completed_files), 1):
            if running_path.name != f"training-watchdog-{i:03d}.running.json" or completed_path.name != f"training-watchdog-{i:03d}.json":
                raise ValueError("Supervisor journal sequence changed")
            started_record = json.loads(running_path.read_text())
            completed = json.loads(completed_path.read_text())
            elapsed = completed.get("supervision", {}).get("elapsedSeconds")
            if (started_record.get("identity") != identity or completed.get("identity") != identity
                    or completed.get("runningReceiptSha256") != sha(running_path)
                    or type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0
                    or completed["supervision"].get("priorElapsedSeconds") != prior
                    or started_record.get("priorElapsedSeconds") != prior
                    or completed.get("cumulativeElapsedSeconds") != prior + elapsed
                    or started_record.get("wallTimeLimitSeconds") != 1800
                    or started_record.get("memoryLimitBytes") != 8 * 1024**3
                    or completed["supervision"].get("wallTimeLimitSeconds") != 1800
                    or completed["supervision"].get("memoryLimitBytes") != 8 * 1024**3
                    or completed.get("status") not in ("completed", "failed")):
                raise ValueError("Prior supervision identity or elapsed budget changed")
            prior += elapsed
        if prior >= 1800:
            raise ValueError("Cumulative head-training budget is exhausted")
        number = len(running_files) + 1
        running_path = output / f"training-watchdog-{number:03d}.running.json"
        started_record = {"status": "running", "identity": identity, "priorElapsedSeconds": prior,
                          "supervisorPid": os.getpid(), "startedAt": datetime.now(timezone.utc).isoformat(),
                          "wallTimeLimitSeconds": 1800, "memoryLimitBytes": 8 * 1024**3}
        write_json(running_path, started_record)
        command = [sys.executable, str(Path(__file__).resolve()), "train", "--protocol", args.protocol,
                   "--features", args.features, "--output", args.output, "--worker", "--supervision",
                   str(running_path.relative_to(ROOT))]
        if args.resume:
            command.append("--resume")
        receipt = driver.supervise(command, timeout_seconds=1800, memory_limit_bytes=8 * 1024**3,
                                   prior_elapsed_seconds=prior)
        success = receipt["exitCode"] == 0 and not receipt["stopReason"] and (output / "complete.json").is_file()
        completed = {"status": "completed" if success else "failed",
                     "identity": identity, "runningReceiptSha256": sha(running_path), "supervision": receipt,
                     "cumulativeElapsedSeconds": prior + receipt["elapsedSeconds"],
                     "completionPublished": (output / "complete.json").is_file(),
                     "finishedAt": datetime.now(timezone.utc).isoformat()}
        write_json(output / f"training-watchdog-{number:03d}.json", completed)
        print(json.dumps({"trainingWatchdog": completed}), flush=True)
        return 0 if success else (receipt["exitCode"] or 1)


def supervision_contract():
    """Exercise journal accounting with fake workers and a real short watchdog."""
    global ROOT, metadata_module
    saved_root, saved_loader = ROOT, metadata_module
    driver = saved_loader(saved_root / "scripts/build-dinov2-training-features.py", "head_contract_real_supervisor")
    actual = driver.supervise([sys.executable, "-c", "import time; time.sleep(30)"],
                              timeout_seconds=.25, memory_limit_bytes=8 * 1024**3,
                              prior_elapsed_seconds=.15, poll_interval=.02)
    assert actual["stopReason"] == "cumulative_wall_time_limit" and actual["exitCode"] != 0
    assert actual["priorElapsedSeconds"] == .15 and actual["elapsedSeconds"] < 3
    checks = ["real-owned-child-hard-timeout-with-prior-budget"]
    with tempfile.TemporaryDirectory(prefix="dinov2-supervision-contract-") as temporary:
        try:
            ROOT = Path(temporary).resolve()
            (ROOT / "scripts").mkdir(); (ROOT / "eval").mkdir()
            driver_path = ROOT / "scripts/driver.py"; driver_path.write_text("# synthetic driver identity\n")
            features_path = ROOT / "eval/features.json"; features_path.write_text("{}")
            protocol_path = ROOT / "eval/protocol.json"
            write_json(protocol_path, {"frozen": True, "resourceLimits": {"headTrainingSeconds": 1800,
                       "headTrainingTreeRssBytes": 8 * 1024**3}, "featureDriverPath": "scripts/driver.py",
                       "sourceHashes": {"scripts/driver.py": sha(driver_path),
                                        "scripts/train-dinov2-temporal.py": sha(__file__)}})
            calls = []
            def fake_supervise(command, **kwargs):
                calls.append((command, kwargs))
                return {"elapsedSeconds": 900.0, "priorElapsedSeconds": kwargs["prior_elapsed_seconds"],
                        "exitCode": 1, "stopReason": None, "wallTimeLimitSeconds": 1800,
                        "memoryLimitBytes": 8 * 1024**3}
            metadata_module = lambda *_: SimpleNamespace(supervise=fake_supervise)
            args = SimpleNamespace(protocol="eval/protocol.json", features="eval/features.json",
                                   output="eval/training", resume=False)
            with contextlib.redirect_stdout(io.StringIO()):
                assert supervised_training(args) == 1
                first_sha = sha(ROOT / "eval/training/training-watchdog-001.json")
                args.resume = True
                assert supervised_training(args) == 1
            assert [x[1]["prior_elapsed_seconds"] for x in calls] == [0, 900]
            assert sha(ROOT / "eval/training/training-watchdog-001.json") == first_sha
            assert calls[0][0][2] == "train" and "--worker" in calls[0][0] and "--resume" in calls[1][0]
            try:
                supervised_training(args)
                raise AssertionError("Exhausted cumulative training budget was reset")
            except ValueError:
                pass
            assert len(calls) == 2
            checks.append("resume-cumulative-budget-and-evidence-preservation")
            args.output = "eval/interrupted"; args.resume = True
            interrupted = ROOT / args.output; interrupted.mkdir()
            write_json(interrupted / "training-watchdog-001.running.json", {"status": "running"})
            try:
                supervised_training(args)
                raise AssertionError("Unknown prior resource consumption was discarded")
            except ValueError:
                pass
            assert len(calls) == 2
            checks.append("unfinished-supervisor-journal-fails-closed")
            args.output = "eval/changed-input"; args.resume = False
            with contextlib.redirect_stdout(io.StringIO()):
                supervised_training(args)
            features_path.write_text('{"changed":true}')
            args.resume = True
            try:
                supervised_training(args)
                raise AssertionError("Changed cache identity was accepted for resume")
            except ValueError:
                pass
            assert len(calls) == 3
            checks.append("supervision-binds-cache-identity")
        finally:
            ROOT, metadata_module = saved_root, saved_loader
    return checks


def cache_contract():
    """Full-size artificial metadata/CLS cache; no videos or backbone are opened.

    External acquisition/runtime validators are stubbed only inside this toy
    workspace. Their real implementations have separate pinned contracts.
    The trainer's acquisition, row, media, wrapper, array, and extraction
    validators below are exercised without stubbing their checks.
    """
    global ROOT, feature_recipe
    saved_root, saved_recipe = ROOT, feature_recipe
    checks = []
    with tempfile.TemporaryDirectory(prefix="dinov2-cache-contract-") as temporary:
        try:
            ROOT = Path(temporary)
            for directory in ("scripts", "eval/parents", "eval/cache/features", "eval/cache/media"):
                (ROOT / directory).mkdir(parents=True)
            script_name = "scripts/acquire-genbuster-training-subset.py"
            script = ROOT / script_name
            script.write_text("import json\nfrom pathlib import Path\ndef load_frozen(path, expected, root):\n    return json.loads(Path(path).read_text())\n")
            source_sha = sha(script)
            known_sha = hashlib.sha256(b"excluded synthetic source").hexdigest()
            known_path = ROOT / "eval/known.json"
            known_path.write_text(json.dumps({"path": "eval/known.mp4", "sha256": known_sha}))
            counts = {"train": {"real": 1024, "ai": 1024, "aiPerGenerator": 256},
                      "internal_development": {"real": 128, "ai": 128, "aiPerGenerator": 32}, "total": 2304}
            parents, entries = [], []
            for split, real_count, per_generator in (("train", 1024, 256), ("internal_development", 128, 32)):
                for generator in (None, *GENERATORS):
                    for number in range(real_count if generator is None else per_generator):
                        identifier = hashlib.sha256(f"{split}-{generator}-{number}".encode()).hexdigest()
                        media = ROOT / "eval/parents" / (identifier + ".mp4")
                        media.write_bytes(identifier.encode())  # Deliberately not a video.
                        entry = {"id": identifier, "parentId": identifier, "split": split,
                                 "label": "real" if generator is None else "ai", "generator": generator,
                                 "path": str(media.relative_to(ROOT)), "archiveMember": identifier + ".mp4",
                                 "zip": {"uncompressedBytes": media.stat().st_size}}
                        entries.append(entry)
                        parents.append({**entry, "sha256": sha(media), "bytes": media.stat().st_size})
            fixture = {"frozen": True, "frozenAt": "2026-09-05T00:00:00+00:00", "counts": counts,
                       "acquisitionScriptSha256": source_sha, "sourceUrl": "synthetic-offline-fixture",
                       "archiveBytes": 123, "excludedKnownMediaSha256": [known_sha],
                       "inputSha256": {"eval/known.json": sha(known_path)}, "entries": entries}
            fixture_path = ROOT / "eval/fixture.json"; write_json(fixture_path, fixture)
            fixture_sha = sha(fixture_path)
            parents = [{**p, "acquisitionFixtureSha256": fixture_sha} for p in parents]
            manifest_path = ROOT / "eval/parents.jsonl"
            manifest_path.write_text("".join(json.dumps(p) + "\n" for p in parents))
            completion = {"schemaVersion": 1, "complete": True, "records": 2304, "counts": counts,
                          "fixtureSha256": fixture_sha, "scriptSha256": source_sha,
                          "sourceUrl": fixture["sourceUrl"], "archiveBytes": 123,
                          "manifestPath": "eval/parents.jsonl", "manifestSha256": sha(manifest_path),
                          "uniqueContentHashes": 2304, "excludedKnownMediaHashes": 1,
                          "actualUncompressedBytes": sum(p["bytes"] for p in parents)}
            completion_path = ROOT / "eval/completion.json"; write_json(completion_path, completion)
            acquisition = {key: value for kind, path in (("fixture", fixture_path), ("manifest", manifest_path),
                                                        ("completion", completion_path))
                           for key, value in ((kind + "Path", str(path.relative_to(ROOT))), (kind + "Sha256", sha(path)))}
            load = {"strict": True, "allTensorsFinite": True, "allLoadedTensorsEqual": True,
                    "tensorElements": 22056576, "tensorCount": 1,
                    "missingKeys": [], "unexpectedKeys": [], "mismatchedKeys": []}
            contract_path = ROOT / "eval/contract.json"; write_json(contract_path, {"load": load})
            contract = {"path": str(contract_path), "sha256": sha(contract_path), "fingerprint": "synthetic"}
            bindings = {"protocolSha256": "synthetic-protocol", "acquisitionManifestSha256": sha(manifest_path),
                        "backboneSha256": "synthetic-backbone", "featureModuleSha256": "synthetic-feature-source",
                        "driverSha256": "synthetic-driver"}
            protocol = {"acquisition": acquisition, "sourceHashes": {script_name: source_sha,
                        "scripts/build-dinov2-training-features.py": "synthetic-driver"},
                        "featureDriverPath": "scripts/build-dinov2-training-features.py",
                        "featureIdentity": {"testOnly": True}, "featureDevice": "cpu",
                        "qualityRecipes": {q: {"filter": "synthetic-filter", "crf": "28"} for q in ("mild", "severe")}}
            feature_recipe = lambda *_: (bindings, contract)
            cls = np.zeros((8, 384), dtype=np.float32)
            cls_sha = hashlib.sha256(cls.tobytes()).hexdigest()
            shared = ROOT / "eval/cls.npz"; np.savez(shared, cls=cls)
            rows = []
            for parent in parents:
                for quality in QUALITIES:
                    identifier = hashlib.sha256((parent["id"] + "|dinov2-feature-v1|" + quality).encode()).hexdigest()[:24]
                    feature = ROOT / "eval/cache/features" / (identifier + ".npz")
                    os.link(shared, feature)  # Unique paths, legitimate equal synthetic values.
                    receipt_path = feature.with_suffix(".json")
                    media = ROOT / parent["path"]
                    if quality != "original":
                        media = ROOT / "eval/cache/media" / (identifier + ".mp4")
                        media.write_bytes((parent["id"] + quality).encode())
                    row = {"id": identifier, "parentId": parent["id"], "split": parent["split"],
                           "label": parent["label"], "generator": parent["generator"], "quality": quality,
                           "sourceSha256": parent["sha256"], "mediaPath": str(media.relative_to(ROOT)),
                           "mediaSha256": sha(media), "featurePath": str(feature.relative_to(ROOT)),
                           "featureSha256": sha(feature), "window": {"start": 0.0, "end": 2.0}}
                    frames = [{"nativeIndex": i, "timestamp": i / 8, "absoluteTimestamp": i / 8,
                               "rgbSha256": cls_sha, "preprocessedFP32Sha256": cls_sha, "nativeShape": [224, 224, 3]}
                              for i in (0, 2, 4, 6, 8, 10, 12, 15)]
                    extraction = {"schemaVersion": 1, "status": "completed", "window": row["window"],
                                  "model": protocol["featureIdentity"], "modelFingerprint": digest(protocol["featureIdentity"]),
                                  "strictLoad": load, "contract": contract, "device": "cpu", "featureShape": [8, 384],
                                  "featureDtype": "float32", "clsBytesSha256": cls_sha, "frames": frames,
                                  "decoder": {"selectedFrameCount": 8, "actualDecodedTimestamps": [f["timestamp"] for f in frames]},
                                  "source": {"path": str(media), "sha256": sha(media), "bytes": media.stat().st_size,
                                             "duration": 2.0, "frameCount": 16, "width": 224, "height": 224, "ptsOrigin": 0}}
                    construction = {"original": True, "parentSha256": parent["sha256"]}
                    if quality != "original":
                        construction = {"parentId": parent["id"], "parentSha256": parent["sha256"], "quality": quality,
                                        "path": row["mediaPath"], "sha256": row["mediaSha256"], "bytes": media.stat().st_size,
                                        "driverSha256": "synthetic-driver", "arguments": ["-map", "0:v:0", "-an", "-vf",
                                        "synthetic-filter", "-crf", "28", "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
                                        "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "+faststart"]}
                    write_json(receipt_path, {"row": row, "bindings": bindings, "extraction": extraction,
                                              "mediaConstruction": construction})
                    rows.append({**row, "receiptPath": str(receipt_path.relative_to(ROOT)), "receiptSha256": sha(receipt_path)})
            cache_path = ROOT / "eval/cache/manifest.json"
            document = {**bindings, "complete": True, "sourceHashes": protocol["sourceHashes"], "featureDevice": "cpu", "rows": rows}
            cache_path.write_text(json.dumps(document))
            _, _, arrays = load_cache(cache_path, protocol, "synthetic-protocol")
            assert arrays.shape == (6912, 8, 384)
            checks.append("full-2304-parent-6912-row-synthetic-cache-accepted")
            del arrays
            for key, wrong in (("generator", "unregistered"), ("sourceSha256", known_sha),
                               ("parentId", parents[1]["id"]), ("split", "internal_development"),
                               ("featurePath", rows[1]["featurePath"]), ("receiptPath", rows[1]["receiptPath"])):
                previous = rows[0][key]; rows[0][key] = wrong
                cache_path.write_text(json.dumps(document))
                try:
                    load_cache(cache_path, protocol, "synthetic-protocol")
                    raise AssertionError("Cache mutation was accepted: " + key)
                except ValueError:
                    checks.append("cache-rejects-" + key)
                rows[0][key] = previous
            cache_path.write_text(json.dumps(document))
            first_receipt = ROOT / rows[0]["receiptPath"]
            original_receipt = json.loads(first_receipt.read_text())
            for key, wrong in (("device", "mps"), ("clsBytesSha256", known_sha), ("status", "failed")):
                altered = json.loads(json.dumps(original_receipt)); altered["extraction"][key] = wrong
                first_receipt.write_text(json.dumps(altered)); rows[0]["receiptSha256"] = sha(first_receipt)
                cache_path.write_text(json.dumps(document))
                try:
                    load_cache(cache_path, protocol, "synthetic-protocol")
                    raise AssertionError("Extraction mutation was accepted: " + key)
                except ValueError:
                    checks.append("extraction-rejects-" + key)
            assert len(checks) == 10
        finally:
            ROOT, feature_recipe = saved_root, saved_recipe
    return checks


def contract():
    """Offline synthetic-feature contracts; no video, backbone, or benchmark input."""
    rng = np.random.default_rng(90210)
    rows = []
    arrays = []
    for label in ("real", "ai"):
        for parent in range(2):
            for quality in QUALITIES:
                rows.append({"parentId": f"toy-{label}-{parent}", "label": label,
                             "quality": quality, "split": "train"})
                arrays.append(rng.normal(size=(8, 384)).astype(np.float32))
    features = np.stack(arrays)
    original = features.copy()
    x, labels = make_batch(features, [(0, 6, 3, 1, "toy")])
    assert np.array_equal(features, original), "Splicing mutated source cache"
    assert np.array_equal(x.numpy()[0, 3:5], features[6, 3:5])
    head = Head(True)
    differences = head.inputs(x)[0, :, 384:]
    assert torch.equal(differences[:-1], (x[0, 1:] - x[0, :-1]).abs())
    assert torch.count_nonzero(differences[-1]) == 0
    assert torch.equal(head(x), head.layers(head.inputs(x)).squeeze(-1).max(dim=1).values)
    examples = epoch_examples(rows, 0)
    assert len(examples) == 24 and sum(e[3] for e in examples) == 12
    for host, donor, start, label, kind in examples:
        assert rows[host]["split"] == "train"
        if donor is not None:
            assert rows[donor]["quality"] == rows[host]["quality"] and donor != host
            assert 0 <= start <= 6
    heads, optimizers = make_heads()
    assert all(torch.equal(v, heads["appearance_control"].state_dict()[k])
               for k, v in heads["temporal"].state_dict().items()), "Reference initialization differs"
    assert torch.count_nonzero(heads["appearance_control"].inputs(x)[:, :, 384:]) == 0
    initial = {name: {k: v.clone() for k, v in head.state_dict().items()} for name, head in heads.items()}
    first = train_epoch(heads, optimizers, rows, features, 0, batch_size=8)
    assert all(any(not torch.equal(initial[name][k], v) for k, v in h.state_dict().items()) for name, h in heads.items())
    with tempfile.TemporaryDirectory(prefix="dinov2-head-contract-") as tmp:
        state = Path(tmp) / "state.pt"
        expected = save_state(state, heads, optimizers, 1, "toy-contract")
        resumed, resumed_optimizers = make_heads()
        assert restore_state(state, expected, resumed, resumed_optimizers, "toy-contract") == 1
        train_epoch(heads, optimizers, rows, features, 1, batch_size=8)
        train_epoch(resumed, resumed_optimizers, rows, features, 1, batch_size=8)
        assert all(torch.equal(value, resumed[name].state_dict()[key]) for name, head in heads.items()
                   for key, value in head.state_dict().items()), "Save/resume diverged"
        for name, h in heads.items():
            sf = Path(tmp) / (name + ".safetensors")
            save_file(h.state_dict(), str(sf))
            restored = Head(name == "temporal")
            restored.load_state_dict(load_file(str(sf)), strict=True)
            assert torch.equal(restored(x), h(x)), "Safe export changed scores"
        # A crash after state publication but before its JSON receipt must
        # restore that epoch, not repeat its optimizer updates or overwrite it.
        orphan_dir = Path(tmp) / "orphan"; orphan_dir.mkdir()
        orphan = orphan_dir / "state-01.pt"
        first_heads, first_optimizers = make_heads()
        restore_state(state, expected, first_heads, first_optimizers, "toy-contract")
        orphan_sha = save_state(orphan, first_heads, first_optimizers, 1, "toy-orphan", epoch_record=first)
        recovered, recovered_optimizers = make_heads()
        assert recover_epochs(orphan_dir, recovered, recovered_optimizers, "toy-orphan") == 1
        assert sha(orphan) == orphan_sha and (orphan_dir / "epoch-01.json").is_file()
        assert json.loads((orphan_dir / "recovered-01.json").read_text())["recoveredAtomicOrphanState"] is True
        assert all(torch.equal(value, recovered[name].state_dict()[key]) for name, h in first_heads.items()
                   for key, value in h.state_dict().items())
        assert recover_epochs(orphan_dir, recovered, recovered_optimizers, "toy-orphan") == 1
        for expected_hash, fingerprint in (("0" * 64, "toy-orphan"), (orphan_sha, "wrong-recipe")):
            try:
                restore_state(orphan, expected_hash, recovered, recovered_optimizers, fingerprint)
                raise AssertionError("Mismatched resume identity was accepted")
            except ValueError:
                pass
        altered = read_state(orphan, orphan_sha, "toy-orphan")
        altered["optimizers"]["temporal"]["param_groups"][0]["lr"] = .5
        wrong = Path(tmp) / "wrong-optimizer.pt"; torch.save(altered, wrong)
        try:
            restore_state(wrong, sha(wrong), recovered, recovered_optimizers, "toy-orphan")
            raise AssertionError("Resume silently changed the optimizer recipe")
        except ValueError:
            pass
        for name, h in heads.items():
            artifact = Path(tmp) / ("export-" + name + ".safetensors")
            before = export_head(artifact, h)
            assert export_head(artifact, h) == before
        try:
            train_epoch(heads, optimizers, rows, features, 2, deadline=time.monotonic() - 1)
            raise AssertionError("Expired training budget was ignored")
        except TimeoutError:
            pass
        invalid = features.copy(); invalid[:] = np.nan
        try:
            train_epoch(heads, optimizers, rows, invalid, 2)
            raise AssertionError("Nonfinite synthetic inputs were trained")
        except ValueError:
            pass
    cache_checks = cache_contract()
    supervision_checks = supervision_contract()
    print(json.dumps({"passed": True, "syntheticFeatureOnly": True,
        "checks": ["cache-not-mutated", "splice-differences-recomputed", "last-difference-zero",
                   "max-pooling", "class-and-quality-balance", "finite-gradients-and-updates",
                   "bitwise-save-resume", "safetensors-score-equivalence", "matched-reference-initialization",
                   "orphan-state-recovery-without-overwrite", "resume-hash-recipe-optimizer-guards",
                   "idempotent-final-export", "batch-deadline", "nonfinite-training-rejected", *cache_checks,
                   *supervision_checks],
        "parameters": {name: sum(p.numel() for p in h.parameters()) for name, h in heads.items()},
        "sourceSha256": sha(__file__), "torch": torch.__version__, "numpy": np.__version__}))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("contract")
    p = sub.add_parser("train")
    p.add_argument("--protocol", required=True)
    p.add_argument("--features", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--supervision", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.mode == "contract":
        setup_runtime()
        contract()
    elif args.worker:
        running = json.loads(checked_path(args.supervision).read_text())
        if (running.get("status") != "running" or running.get("supervisorPid") != os.getppid()
                or running.get("identity", {}).get("trainingSourceSha256") != sha(__file__)
                or running.get("identity", {}).get("protocolSha256") != sha(checked_path(args.protocol))):
            raise ValueError("Head-training worker requires its live supervisor journal")
        setup_runtime()
        train(args)
    else:
        raise SystemExit(supervised_training(args))


if __name__ == "__main__":
    main()
