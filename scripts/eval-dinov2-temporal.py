#!/usr/bin/env python3
"""One frozen153-file development diagnostic; never a source-independent test."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import torch
from safetensors.torch import load_file

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    ("negative45", "eval/runs/aegis-shots-v1-negative-build/manifest.jsonl", "87c02fc0b447bb0a5cc9f39ca18bda788c773db6f8e145b88bd863b54eb4dc4f", 45),
    ("known3", "eval/generated-origin-manifest.jsonl", "122b79147249eab01d06e0fbd0b33955fc86eb9479d8df1697fd123c480b8b55", 3),
    ("benchmark105", "eval/aegis-development-manifest.jsonl", "b2bf057723c542e38a7f796785292300a00b52ba9d0ae02ffe98eb87a3d80dfa", 105),
)
TRAINING_GENERATORS = {"cogvideox", "easyanimate", "hunyuanvideo", "ltxvideo"}
QUALITIES = {"original": "original", "social_720p_crf28": "mild", "repost_360p_crf36_12fps_crop": "severe"}
HEADS = ("temporal", "appearance_control")
RESULT_SCHEMA = 2


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def evaluation_windows(duration):
    """Frozen two-second/one-second-stride plan; support checked per window."""
    require(finite_number(duration) and 0.5 <= duration <= 120 + 1e-6, "Unsupported diagnostic duration")
    if duration <= 2:
        windows = [{"start": 0.0, "end": duration}]
    else:
        starts = [float(i) for i in range(math.floor(duration - 2) + 1)]
        if abs(starts[-1] - (duration - 2)) > 1e-6:
            starts.append(duration - 2)
        windows = [{"start": start, "end": start + 2} for start in starts]
    require(len(windows) <= 128, "Diagnostic window cap exceeded")
    return windows


def error_record(error, stage):
    return {"stage": stage, "type": type(error).__name__, "message": str(error)[:1000]}


def check_error(value):
    return (isinstance(value, dict) and isinstance(value.get("type"), str)
            and isinstance(value.get("stage"), str) and isinstance(value.get("message"), str))


def artifact(path, expected_sha, root):
    relative = Path(path)
    require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe diagnostic artifact path")
    target = root / relative
    require(target.resolve().is_relative_to(root.resolve()) and not target.is_symlink(), "Diagnostic artifact escaped workspace")
    require(target.is_file() and sha(target) == expected_sha, "Diagnostic artifact hash mismatch")
    return target


def training_directory(value):
    path = Path(value)
    path = path if path.is_absolute() else ROOT / path
    resolved = path.resolve()
    require(resolved.is_relative_to((ROOT / "eval").resolve()) and resolved != (ROOT / "eval").resolve()
            and path.is_dir() and not path.is_symlink(), "Training must be an existing directory inside eval")
    return resolved


def derive_result(source, result, artifact_root=None):
    """Reconstruct coverage and decisions; saved ai/complete fields are ignored."""
    require(result.get("schemaVersion") == RESULT_SCHEMA and result.get("id") == source["id"]
            and result.get("sourceSha256") == source["sha256"] and result.get("cohort") == source["cohort"],
            "Diagnostic result/source identity mismatch")
    plan, records = result.get("windowPlan"), result.get("windows")
    require(isinstance(plan, list) and isinstance(records, list), "Missing diagnostic window plan/records")
    require(type(result.get("plannedWindows")) is int and result["plannedWindows"] == len(plan)
            and result.get("windowPlanSha256") == digest(plan), "Window plan count/hash mismatch")
    planning_error = result.get("planningError")
    if planning_error is not None:
        require(check_error(planning_error) and not plan and not records, "Malformed planning failure")
        return {"complete": False, "heads": {name: {"ai": None, "maximumLogit": None, "validWindows": 0} for name in HEADS},
                "failedWindows": 0, "planningFailed": True}
    require(plan == evaluation_windows(result.get("sourceDurationSeconds")), "Window plan differs from frozen cadence")
    require(len(records) == len(plan), "Missing or extra window execution record")
    probe = None
    if artifact_root is not None:
        probe = json.loads(artifact(result["probePath"], result["probeSha256"], artifact_root).read_text())
        require(probe.get("sha256") == source["sha256"] and probe.get("duration") == result["sourceDurationSeconds"], "Probe/source identity mismatch")
    valid = {name: [] for name in HEADS}
    complete = True
    failed = 0
    for index, (window, record) in enumerate(zip(plan, records)):
        require(type(record.get("index")) is int and record["index"] == index and record.get("window") == window,
                "Window missing, duplicated, reordered or changed")
        error, head_errors, logits = record.get("error"), record.get("headErrors"), record.get("logits")
        require(error is None or check_error(error), "Malformed window error")
        require(isinstance(head_errors, dict) and set(head_errors).issubset(HEADS)
                and all(check_error(e) for e in head_errors.values()), "Malformed per-head error")
        require(isinstance(logits, dict) and set(logits).issubset(HEADS)
                and all(finite_number(v) for v in logits.values()), "Invalid/nonfinite raw window logits")
        require(not (set(logits) & set(head_errors)), "Window head has both a score and error")
        require(error is None or (not logits and not head_errors), "Failed extraction has model scores")
        require(error is not None or set(logits) | set(head_errors) == set(HEADS), "Window has unexplained missing head score")
        window_complete = error is None and not head_errors and set(logits) == set(HEADS)
        complete &= window_complete
        failed += int(not window_complete)
        for name, value in logits.items():
            valid[name].append(value)
        if error is None:
            for key in ("featurePath", "featureSha256", "receiptPath", "receiptSha256"):
                require(isinstance(record.get(key), str) and bool(record[key]), "Completed extraction lacks retained feature/receipt reference")
            if artifact_root is not None:
                feature = artifact(record["featurePath"], record["featureSha256"], artifact_root)
                receipt = json.loads(artifact(record["receiptPath"], record["receiptSha256"], artifact_root).read_text())
                require(receipt.get("window") == window and receipt.get("source", {}).get("sha256") == source["sha256"]
                        and receipt.get("featureSha256") == record["featureSha256"], "Feature receipt identity mismatch")
                require(Path(receipt.get("featurePath", "")).resolve() == feature.resolve(), "Receipt points to another feature file")
                with np.load(feature, allow_pickle=False) as saved:
                    require(saved.files == ["cls"], "Unexpected diagnostic feature payload")
                    cls = saved["cls"]
                    require(cls.shape == (8, 384) and cls.dtype == np.float32 and np.isfinite(cls).all()
                            and hashlib.sha256(cls.tobytes()).hexdigest() == receipt.get("clsBytesSha256"), "Diagnostic feature array/receipt mismatch")
                frames = receipt.get("frames", [])
                available = [i for i, timestamp in enumerate(probe["timestamps"]) if window["start"] <= timestamp < window["end"]]
                require(len(available) >= 8 and len(frames) == 8, "Unsupported retained sampling")
                indices = [available[i * (len(available) - 1) // 7] for i in range(8)]
                require([f.get("nativeIndex") for f in frames] == indices
                        and [f.get("timestamp") for f in frames] == [probe["timestamps"][i] for i in indices], "Recorded samples differ from frozen native-index selection")
    heads = {}
    for name in HEADS:
        maximum = max(valid[name]) if valid[name] else None
        decision = True if maximum is not None and maximum >= 0 else False if complete else None
        heads[name] = {"maximumLogit": maximum, "ai": decision, "validWindows": len(valid[name]), "coverageIncomplete": not complete}
    return {"complete": complete, "heads": heads, "failedWindows": failed, "planningFailed": False}


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


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def diagnostic_rows():
    rows = []
    for cohort, file, expected, count in MANIFESTS:
        if sha(ROOT / file) != expected:
            raise ValueError("Diagnostic source manifest changed")
        subset = [json.loads(line) for line in (ROOT / file).read_text().splitlines() if line]
        if len(subset) != count or any(r["split"] != "development" for r in subset):
            raise ValueError("Unexpected diagnostic allocation")
        for row in subset:
            rows.append({**row, "cohort": cohort, "expectedAi": row["label"] in ("ai", "mixed")})
    if len({r["id"] for r in rows}) != 153 or len({r["sha256"] for r in rows}) != 153:
        raise ValueError("Duplicate diagnostic identity")
    if sum(not r["expectedAi"] for r in rows) != 82:
        raise ValueError("Unexpected negative target count")
    return rows


def summarize(rows, results, artifact_root=None):
    if rows != diagnostic_rows():
        raise ValueError("Summary source allocation differs from the exact frozen153 manifests")
    if len(results) != len(rows) or [r["id"] for r in results] != [r["id"] for r in rows]:
        raise ValueError("Diagnostic rows missing, duplicated or reordered")
    derived = [derive_result(source, result, artifact_root) for source, result in zip(rows, results)]
    summary = {"files": len(rows), "sourceIndependenceEstablished": False,
               "productValidation": False, "resultSchemaVersion": RESULT_SCHEMA,
               "retainedArtifactHashesVerified": artifact_root is not None,
               "decisionDerivation": "Finite raw per-window logits, maximum >=0; saved ai/complete flags ignored. Any missing coverage fails the study gate.",
               "planningFailures": sum(r["planningFailed"] for r in derived),
               "failedWindows": sum(r["failedWindows"] for r in derived), "heads": {}}
    for head in HEADS:
        counts = {"negative45": {"correct": 0, "total": 45}, "known3": {"correct": 0, "total": 3},
                  "authorReal": {"correct": 0, "total": 36}, "technicalComplete": 0,
                  "positiveWithIncompleteCoverage": 0, "undetermined": 0,
                  "allAi": {q: {"detected": 0, "total": 23} for q in QUALITIES.values()},
                  "outsideTrainingFoldersAi": {q: {"detected": 0, "total": 19} for q in QUALITIES.values()}}
        observed = {"authorReal": 0, "negative45": 0, "known3": 0,
                    "allAi": {q: 0 for q in QUALITIES.values()},
                    "outsideTrainingFoldersAi": {q: 0 for q in QUALITIES.values()}}
        for source, result in zip(rows, derived):
            completed = result["complete"]
            decision = result["heads"][head]["ai"]
            counts["positiveWithIncompleteCoverage"] += int(decision is True and not completed)
            counts["undetermined"] += int(decision is None)
            if completed and type(decision) is bool:
                counts["technicalComplete"] += 1
            correct = type(decision) is bool and decision == source["expectedAi"]
            cohort = source["cohort"]
            if cohort in ("negative45", "known3"):
                observed[cohort] += 1
                counts[cohort]["correct"] += int(correct)
            elif not source["expectedAi"]:
                observed["authorReal"] += 1
                counts["authorReal"]["correct"] += int(correct)
            else:
                q = QUALITIES[source["transformation"]]
                observed["allAi"][q] += 1
                counts["allAi"][q]["detected"] += int(correct)
                if source["generator"] not in TRAINING_GENERATORS:
                    observed["outsideTrainingFoldersAi"][q] += 1
                    counts["outsideTrainingFoldersAi"][q]["detected"] += int(correct)
        if (observed["negative45"] != 45 or observed["known3"] != 3 or observed["authorReal"] != 36
                or any(v != 23 for v in observed["allAi"].values())
                or any(v != 19 for v in observed["outsideTrainingFoldersAi"].values())):
            raise ValueError("Frozen gate denominators differ from actual source metadata")
        gates = {"complete": counts["technicalComplete"] == 153,
                 "knownOriginRegressions": counts["known3"]["correct"] == 3,
                 "documentedNegatives": counts["negative45"]["correct"] == 45,
                 "authorRealNegatives": counts["authorReal"]["correct"] == 36,
                 "allAiPerQuality": all(c["detected"] >= 19 for c in counts["allAi"].values()),
                 "outsideTrainingFoldersPerQuality": all(c["detected"] >= 16 for c in counts["outsideTrainingFoldersAi"].values())}
        summary["heads"][head] = {"counts": counts, "gates": gates, "passesDiagnostic": all(gates.values())}
    summary["candidatePassesDiagnostic"] = summary["heads"]["temporal"]["passesDiagnostic"]
    summary["decision"] = "eligible_for_separate_independent_evaluation" if summary["candidatePassesDiagnostic"] else "reject_candidate_no_threshold_rescue"
    negative_increases = 0
    outside_net = 0
    mixed_positive = False
    paired_changes = []
    for source, result in zip(rows, derived):
        a, b = result["heads"]["temporal"]["ai"], result["heads"]["appearance_control"]["ai"]
        if type(a) is not bool or type(b) is not bool:
            continue
        if a != b:
            paired_changes.append({"id": source["id"], "expectedAi": source["expectedAi"], "temporal": a, "appearance_control": b})
        if not source["expectedAi"]:
            negative_increases += int(a and not b)
        if source["cohort"] == "benchmark105" and source["expectedAi"] and source["generator"] not in TRAINING_GENERATORS:
            outside_net += int(a) - int(b)
        if source["id"] == "10a7c358371f29ddd7acb538":
            mixed_positive = a
    summary["pairedReference"] = {"changedDecisions": paired_changes,
        "netAdditionalOutsideFolderAiAcross57QualityCases": outside_net,
        "newNegativeFalseFlags": negative_increases,
        "renderedMixedDetected": mixed_positive,
        "descriptiveTemporalBenefitGate": outside_net >= 6 and negative_increases == 0 and mixed_positive
            and all(summary["heads"][name]["counts"]["technicalComplete"] == 153 for name in summary["heads"]),
        "independentSignificanceTest": False, "controlMayReplaceCandidate": False}
    return summary


def verify_training_supervision(training, identity):
    running = sorted(training.glob("training-watchdog-???.running.json"))
    terminals = sorted(training.glob("training-watchdog-???.json"))
    require(bool(running) and len(running) == len(terminals), "Training lacks its final successful supervisor terminal")
    prior, bindings = 0.0, []
    for index, (start_path, end_path) in enumerate(zip(running, terminals), 1):
        require(start_path.name == f"training-watchdog-{index:03d}.running.json"
                and end_path.name == f"training-watchdog-{index:03d}.json", "Training supervisor sequence changed")
        start, end = json.loads(start_path.read_text()), json.loads(end_path.read_text())
        supervision = end.get("supervision", {})
        elapsed = supervision.get("elapsedSeconds")
        require(start.get("identity") == identity == end.get("identity") and end.get("runningReceiptSha256") == sha(start_path)
                and finite_number(elapsed) and elapsed >= 0 and start.get("priorElapsedSeconds") == prior
                and supervision.get("priorElapsedSeconds") == prior and end.get("cumulativeElapsedSeconds") == prior + elapsed
                and start.get("wallTimeLimitSeconds") == supervision.get("wallTimeLimitSeconds") == 1800
                and start.get("memoryLimitBytes") == supervision.get("memoryLimitBytes") == 8 * 1024**3,
                "Training supervisor identity/budget mismatch")
        if index == len(running):
            require(end.get("status") == "completed" and end.get("completionPublished") is True
                    and supervision.get("exitCode") == 0 and supervision.get("stopReason") is None
                    and supervision.get("cleanupError") is None
                    and finite_number(supervision.get("peakProcessTreeRssBytes"))
                    and 0 <= supervision["peakProcessTreeRssBytes"] <= 8 * 1024**3 and prior + elapsed <= 1800,
                    "Completed training was not a successful bounded supervised run")
        else:
            require(end.get("status") == "failed" and end.get("completionPublished") is False,
                    "Training resumed after a purported completed run")
        prior += elapsed
        bindings.append({"runningPath": str(start_path.relative_to(ROOT)), "runningSha256": sha(start_path),
                         "terminalPath": str(end_path.relative_to(ROOT)), "terminalSha256": sha(end_path)})
    return bindings


def load_final_heads(trainer, protocol, protocol_path, training, features_path):
    complete_path, configuration_path = training / "complete.json", training / "configuration.json"
    complete = json.loads(complete_path.read_text())
    configuration = json.loads(configuration_path.read_text())
    expected_configuration = {"protocolSha256": sha(protocol_path), "featureManifestSha256": sha(features_path),
                              "trainingSourceSha256": protocol["sourceHashes"]["scripts/train-dinov2-temporal.py"],
                              "heads": trainer.HEAD_CONFIG, "training": trainer.TRAINING_CONFIG,
                              "torch": torch.__version__, "numpy": np.__version__}
    require(configuration == expected_configuration, "Training configuration/cache/head recipe changed")
    fingerprint = trainer.digest(configuration)
    require(complete.get("complete") is True and type(complete.get("epochs")) is int and complete["epochs"] == 20
            and complete.get("fingerprint") == fingerprint and set(complete.get("heads", {})) == set(HEADS)
            and complete.get("internalDevelopmentRows") == 768, "Not the completed fixed-epoch candidate")
    supervision = verify_training_supervision(training, {
        "protocolSha256": configuration["protocolSha256"], "featureManifestSha256": configuration["featureManifestSha256"],
        "trainingSourceSha256": configuration["trainingSourceSha256"],
        "driverSha256": protocol["sourceHashes"][protocol["featureDriverPath"]]})
    # Full training-cache validation is read-only; no model forward or refitting.
    _, cache_rows, arrays = trainer.load_cache(features_path, protocol, sha(protocol_path))
    require(len(cache_rows) == 6912, "Completed training cache differs from fixed cohort")
    del arrays, cache_rows
    epoch_path, state_path = training / "epoch-20.json", training / "state-20.pt"
    epoch = json.loads(epoch_path.read_text())
    require(epoch.get("epoch") == 20 and epoch.get("fingerprint") == fingerprint
            and epoch.get("stateFile") == state_path.name and sha(state_path) == epoch.get("stateSha256"), "Final epoch receipt/state mismatch")
    heads, optimizers = trainer.make_heads()
    require(trainer.restore_state(state_path, epoch["stateSha256"], heads, optimizers, fingerprint) == 20,
            "Final export is not epoch20")
    state = trainer.read_state(state_path, epoch["stateSha256"], fingerprint)
    record = state["epochRecord"]
    require(isinstance(record, dict) and epoch == {**record, "fingerprint": fingerprint,
                                                 "stateFile": state_path.name, "stateSha256": epoch["stateSha256"]},
            "Epoch receipt and saved training record differ")
    whole = trainer.TRAINING_CONFIG["wholeRealPerEpoch"] + trainer.TRAINING_CONFIG["wholeAiPerEpoch"]
    ai_splices = trainer.TRAINING_CONFIG["realAiFeatureSplicesPerEpoch"]
    real_splices = trainer.TRAINING_CONFIG["realRealFeatureSplicesPerEpoch"]
    examples = whole + ai_splices + real_splices
    require(set(record) == {"epoch", "examples", "exampleTypes", "averageTrainingLoss"}
            and record["examples"] == examples and record["exampleTypes"] == {
                "whole": whole, "real_ai_feature_splice": ai_splices, "real_real_feature_splice": real_splices}
            and set(record["averageTrainingLoss"]) == set(HEADS)
            and all(finite_number(v) and v >= 0 for v in record["averageTrainingLoss"].values()), "Final epoch accounting differs from fixed training recipe")
    expected_steps = 20 * math.ceil(examples / trainer.TRAINING_CONFIG["batchSize"])
    for optimizer in optimizers.values():
        require(all(float(s["step"]) == expected_steps for s in optimizer.state.values()), "Optimizer update count is not twenty complete epochs")
    for name, head in heads.items():
        exported = complete["heads"][name]
        path = trainer.checked_file(exported["path"], exported["sha256"])
        require(path == training.resolve() / (name + ".safetensors")
                and exported.get("parameters") == sum(p.numel() for p in head.parameters()), "Final head identity/count changed")
        actual, expected = load_file(str(path), device="cpu"), head.state_dict()
        require(set(actual) == set(expected) and all(actual[k].dtype == expected[k].dtype
                and actual[k].shape == expected[k].shape and torch.equal(actual[k], expected[k]) for k in expected),
                "Exported head differs from strictly restored epoch20 state")
        head.eval().requires_grad_(False)
    binding = {"trainingCompletePath": str(complete_path.relative_to(ROOT)), "trainingCompleteSha256": sha(complete_path),
               "trainingConfigurationSha256": sha(configuration_path), "trainingFingerprint": fingerprint,
               "featureManifestPath": str(features_path.relative_to(ROOT)), "featureManifestSha256": sha(features_path),
               "epochReceiptPath": str(epoch_path.relative_to(ROOT)), "epochReceiptSha256": sha(epoch_path),
               "epochStatePath": str(state_path.relative_to(ROOT)), "epochStateSha256": sha(state_path),
               "epoch": 20, "optimizerUpdatesPerParameter": expected_steps, "headFiles": complete["heads"],
               "trainingSupervision": supervision,
               "allExportedTensorsEqualRestoredState": True}
    return heads, binding


def validate_loaded_backbone(model, loaded, protocol, feature_module):
    identity = protocol["featureIdentity"]
    require(protocol.get("featureDevice") == "mps" and loaded.get("device") == "mps", "Diagnostic feature device differs from frozen MPS")
    require(loaded.get("identity") == identity == feature_module.runtime_identity()
            and loaded.get("fingerprint") == feature_module.digest(identity), "Loaded backbone/runtime identity mismatch")
    backbone = protocol["backbone"]
    require(identity["assets"]["model.safetensors"]["sha256"] == backbone["weightsSha256"]
            and sha(ROOT / backbone["modelDirectory"] / "model.safetensors") == backbone["weightsSha256"], "Loaded backbone weight identity mismatch")
    contract_path = ROOT / backbone["contractPath"]
    require(sha(contract_path) == backbone["contractSha256"], "Backbone contract changed")
    contract = feature_module.validate_contract(contract_path)
    require(loaded.get("contract") == contract and loaded.get("load") == json.loads(contract_path.read_text())["load"], "Strict backbone load/contract mismatch")
    require(model._feature_identity == identity and model._feature_load_receipt == loaded["load"]
            and model._feature_contract == contract and model._feature_device == "mps", "Actual model attributes differ from loaded receipt")
    parameters = list(model.parameters())
    require(bool(parameters) and all(p.device.type == "mps" and p.dtype == torch.float32 and not p.requires_grad for p in parameters),
            "Actual backbone parameters are not frozen MPS FP32")
    policy = identity["policy"]
    require(policy["windowSeconds"] == 2.0 and policy["evaluationStrideSeconds"] == 1.0
            and policy["framesPerWindow"] == 8 and policy["limits"]["windows"] == 128, "Frozen sampling policy differs from evaluator")


def run_case(row, artifacts, feature_module, model, processor, heads, loaded):
    started = time.monotonic()
    item = {"schemaVersion": RESULT_SCHEMA, "id": row["id"], "cohort": row["cohort"], "sourceSha256": row["sha256"],
            "expectedAi": row["expectedAi"], "sourceDurationSeconds": None,
            "planningError": None, "plannedWindows": 0, "windowPlan": [], "windowPlanSha256": digest([]), "windows": []}
    try:
        require(sha(ROOT / row["path"]) == row["sha256"], "Diagnostic source media changed")
        probe = feature_module.probe_video(ROOT / row["path"])
        require(probe["sha256"] == row["sha256"], "Probe source hash differs from fixed row")
        windows = evaluation_windows(probe["duration"])
        probe_path = artifacts / "probe.json"
        write_json(probe_path, probe)
        item.update(sourceDurationSeconds=probe["duration"], plannedWindows=len(windows), windowPlan=windows,
                    windowPlanSha256=digest(windows), probePath=str(probe_path.relative_to(ROOT)), probeSha256=sha(probe_path))
    except Exception as error:
        item["planningError"] = error_record(error, "probe_and_plan")
        windows = []
    for index, window in enumerate(windows):
        record = {"index": index, "window": window, "error": None, "headErrors": {}, "logits": {}}
        try:
            # One invocation per planned window. No replay after partial failure.
            # The frozen extract_window alias lacks a probe argument. Its public
            # singleton implementation provides identical semantics with reuse.
            extracted = feature_module.extract_windows(ROOT / row["path"], [window], model, processor, "mps", probe=probe)
            require(len(extracted) == 1, "Single-window extractor returned a different count")
            cls, receipt = extracted[0]
            require(receipt["window"] == window and receipt["source"]["sha256"] == row["sha256"]
                    and receipt["model"] == loaded["identity"] and receipt["modelFingerprint"] == loaded["fingerprint"]
                    and receipt["device"] == "mps" and receipt["strictLoad"] == loaded["load"]
                    and receipt["contract"] == loaded["contract"], "Window feature receipt differs from frozen source/backbone")
            path = artifacts / f"window-{index:03d}.npz"
            feature_module.save_features(path, cls, receipt)
            receipt_path = path.with_suffix(".receipt.json")
            record.update(featurePath=str(path.relative_to(ROOT)), featureSha256=sha(path),
                          receiptPath=str(receipt_path.relative_to(ROOT)), receiptSha256=sha(receipt_path),
                          sampleTimestamps=[f["timestamp"] for f in receipt["frames"]],
                          sampledKnownInsertFrames=sum(3 <= f["timestamp"] < 5 for f in receipt["frames"])
                          if row["id"] == "10a7c358371f29ddd7acb538" else None)
        except Exception as error:
            record["error"] = error_record(error, "extract_and_save")
        else:
            for name, head in heads.items():
                try:
                    with torch.inference_mode():
                        logit = float(head(torch.from_numpy(cls[None]))[0])
                    require(finite_number(logit), "Nonfinite diagnostic head logit")
                    record["logits"][name] = logit
                except Exception as error:
                    record["headErrors"][name] = error_record(error, "head:" + name)
        item["windows"].append(record)
        write_json(artifacts / f"window-{index:03d}.result.json", record)
    derived = derive_result(row, item)
    item.update(complete=derived["complete"], heads=derived["heads"], failedWindows=derived["failedWindows"],
                error=item["planningError"] or ({"type": "IncompleteCoverage", "stage": "windows", "message": "One or more prescribed windows/heads failed"} if not derived["complete"] else None),
                elapsedSeconds=time.monotonic() - started)
    return item


def run(args):
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text())
    if protocol.get("frozen") is not True:
        raise ValueError("Frozen full training/diagnostic recipe required")
    for name, expected in protocol["sourceHashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError("Frozen source changed: " + name)
    trainer = load_module("diagnostic_trainer", "scripts/train-dinov2-temporal.py")
    feature_module = load_module("diagnostic_features", "scripts/dinov2-temporal-features.py")
    if protocol["heads"] != trainer.HEAD_CONFIG or protocol["training"] != trainer.TRAINING_CONFIG:
        raise ValueError("Protocol/head mismatch")
    training, features_path = training_directory(args.training), trainer.checked_path(args.features)
    heads, training_binding = load_final_heads(trainer, protocol, protocol_path, training, features_path)
    rows = diagnostic_rows()
    require(protocol["diagnostics"]["manifests"] == [dict(cohort=c, path=p, sha256=s, count=n) for c, p, s, n in MANIFESTS]
            and protocol["diagnostics"]["thresholdLogit"] == 0.0
            and protocol["diagnostics"]["expectedFiles"] == 153, "Frozen diagnostic identity/threshold differs")
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=False)
    (output / "artifacts").mkdir()
    (output / "source").mkdir()
    for file in protocol["sourceHashes"]:
        shutil.copyfile(ROOT / file, output / "source" / Path(file).name)
    shutil.copyfile(protocol_path, output / "source/protocol.json")
    run_configuration = {"protocolSha256": sha(protocol_path), "training": training_binding,
                         "diagnosticManifests": MANIFESTS, "resultSchemaVersion": RESULT_SCHEMA,
                         "candidate": "temporal", "control": "appearance_control", "thresholdLogit": 0.0,
                         "scoreIsProbability": False, "sourceSha256": sha(__file__)}
    write_json(output / "configuration.json", run_configuration)
    backbone = protocol["backbone"]
    if sha(ROOT / backbone["contractPath"]) != backbone["contractSha256"]:
        raise ValueError("Backbone contract changed")
    model, processor, loaded = feature_module.load_backbone(ROOT / backbone["modelDirectory"],
                                        device="mps", contract_receipt=ROOT / backbone["contractPath"])
    validate_loaded_backbone(model, loaded, protocol, feature_module)
    write_json(output / "loaded-backbone.json", loaded)
    results = []
    for row in rows:
        artifacts = output / "artifacts" / row["id"]
        artifacts.mkdir()
        item = run_case(row, artifacts, feature_module, model, processor, heads, loaded)
        write_json(artifacts / "result.json", item)
        with (output / "results.jsonl").open("a") as f:
            f.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
            f.flush()
        results.append(item)
        print(json.dumps({"completed": len(results), "of": len(rows), "id": row["id"],
                          "completeCoverage": item["complete"], "error": item["error"]}), flush=True)
    validate_loaded_backbone(model, loaded, protocol, feature_module)
    require(sha(protocol_path) == run_configuration["protocolSha256"], "Protocol changed during diagnostic")
    for file, expected in protocol["sourceHashes"].items():
        require(sha(ROOT / file) == expected, "Frozen diagnostic source changed")
    summary = summarize(rows, results, artifact_root=ROOT)
    summary["resultsSha256"] = sha(output / "results.jsonl")
    write_json(output / "summary.json", summary)
    return 0 if summary["candidatePassesDiagnostic"] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--training", required=True)
    parser.add_argument("--features", required=True, help="The exact completed feature-cache manifest used for training")
    parser.add_argument("--output", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(run(args))
    driver = load_module("diagnostic_supervisor", "scripts/build-dinov2-training-features.py")
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    receipt = driver.supervise(command, timeout_seconds=3600, memory_limit_bytes=8 * 1024 ** 3)
    output = ROOT / args.output
    if output.exists():
        write_json(output / "watchdog.json", receipt)
    print(json.dumps({"diagnosticWatchdog": receipt}), flush=True)
    raise SystemExit(receipt["exitCode"] or (1 if receipt["stopReason"] else 0))


if __name__ == "__main__":
    main()
