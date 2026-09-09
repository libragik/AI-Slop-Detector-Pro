#!/usr/bin/env python3
"""Synthetic logits/state/arrays only; no pretrained model or media inference."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch
from safetensors.torch import save_file, load_file


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


E = module("evaluator_contract", "eval-dinov2-temporal.py")
T = module("trainer_binding_contract", "train-dinov2-temporal.py")


def result(row, duration=2.0):
    plan = E.evaluation_windows(duration)
    logit = 1.0 if row["expectedAi"] else -1.0
    windows = [{"index": i, "window": w, "error": None, "headErrors": {},
                "logits": {name: logit for name in E.HEADS}, "featurePath": "synthetic.npz", "receiptPath": "synthetic.json",
                "featureSha256": "0" * 64, "receiptSha256": "0" * 64} for i, w in enumerate(plan)]
    return {"schemaVersion": 2, "id": row["id"], "sourceSha256": row["sha256"], "cohort": row["cohort"],
            "sourceDurationSeconds": duration, "windowPlan": plan, "plannedWindows": len(plan),
            "windowPlanSha256": E.digest(plan), "planningError": None, "windows": windows,
            "complete": True, "error": None, "heads": {name: {"ai": row["expectedAi"]} for name in E.HEADS}}


def failed_window(window):
    return {"index": window["index"], "window": window["window"], "error": {"stage": "extract", "type": "RuntimeError", "message": "synthetic failure"}, "headErrors": {}, "logits": {}}


class Metrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = E.diagnostic_rows()  # Metadata only, never prediction/feature reads.

    def perfect(self):
        return [result(row) for row in self.rows]

    def test_perfect_raw_logits_and_inclusive_zero(self):
        records = self.perfect()
        self.assertTrue(E.summarize(self.rows, records)["candidatePassesDiagnostic"])
        ai = next(i for i, r in enumerate(self.rows) if r["expectedAi"])
        records[ai]["windows"][0]["logits"]["temporal"] = 0.0
        self.assertTrue(E.derive_result(self.rows[ai], records[ai])["heads"]["temporal"]["ai"])

    def test_saved_booleans_and_maxima_cannot_override_raw_evidence(self):
        records = self.perfect()
        for r in records:
            r["complete"] = False
            r["error"] = {"madeUp": True}
            r["heads"] = {name: {"ai": False, "maximumLogit": -999} for name in E.HEADS}
        self.assertTrue(E.summarize(self.rows, records)["candidatePassesDiagnostic"])
        records[0]["complete"] = True
        records[0]["windows"][0]["logits"]["temporal"] = 1.0  # first fixed source is negative
        summary = E.summarize(self.rows, records)
        self.assertFalse(summary["candidatePassesDiagnostic"])
        self.assertEqual(summary["heads"]["temporal"]["counts"]["negative45"]["correct"], 44)

    def test_missing_duplicate_reordered_or_wrong_source_ids_reject(self):
        for mutation in ("missing", "duplicate", "order", "source", "row-metadata"):
            with self.subTest(mutation=mutation):
                records, rows = self.perfect(), copy.deepcopy(self.rows)
                if mutation == "missing": records.pop()
                if mutation == "duplicate": records[-1] = records[0]
                if mutation == "order": records[0], records[1] = records[1], records[0]
                if mutation == "source": records[0]["sourceSha256"] = "f" * 64
                if mutation == "row-metadata": rows[0]["expectedAi"] = True
                with self.assertRaises(ValueError): E.summarize(rows, records)

    def test_window_count_order_plan_and_finite_raw_contracts(self):
        row = self.rows[0]
        for mutation in ("missing", "duplicate", "order", "index", "count", "plan", "nan", "inf", "bool", "missing-head"):
            r = result(row, 3.0)
            if mutation == "missing": r["windows"].pop()
            if mutation == "duplicate": r["windows"][1] = copy.deepcopy(r["windows"][0])
            if mutation == "order": r["windows"].reverse()
            if mutation == "index": r["windows"][0]["index"] = True
            if mutation == "count": r["plannedWindows"] = 1
            if mutation == "plan": r["windowPlan"][0]["end"] = 1.0
            if mutation == "nan": r["windows"][0]["logits"]["temporal"] = float("nan")
            if mutation == "inf": r["windows"][0]["logits"]["temporal"] = float("inf")
            if mutation == "bool": r["windows"][0]["logits"]["temporal"] = True
            if mutation == "missing-head": del r["windows"][0]["logits"]["temporal"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): E.derive_result(row, r)

    def test_partial_positive_retained_partial_negative_abstains_and_gate_fails(self):
        records = self.perfect(); index = next(i for i, r in enumerate(self.rows) if r["expectedAi"])
        records[index] = result(self.rows[index], 3.0)
        records[index]["windows"][1] = failed_window(records[index]["windows"][1])
        records[index]["complete"] = True
        derived = E.derive_result(self.rows[index], records[index])
        self.assertIs(derived["heads"]["temporal"]["ai"], True)
        summary = E.summarize(self.rows, records)
        self.assertFalse(summary["candidatePassesDiagnostic"])
        self.assertEqual(summary["heads"]["temporal"]["counts"]["technicalComplete"], 152)
        self.assertEqual(summary["heads"]["temporal"]["counts"]["positiveWithIncompleteCoverage"], 1)
        records[index]["windows"][0]["logits"] = {name: -1. for name in E.HEADS}
        self.assertIsNone(E.derive_result(self.rows[index], records[index])["heads"]["temporal"]["ai"])

    def test_head_failure_and_planning_failure_cannot_be_clean_negative(self):
        row = self.rows[0]; r = result(row)
        r["windows"][0]["logits"].pop("appearance_control")
        r["windows"][0]["headErrors"]["appearance_control"] = {"type": "ValueError", "stage": "head", "message": "synthetic"}
        self.assertIsNone(E.derive_result(row, r)["heads"]["temporal"]["ai"])
        r.update(windowPlan=[], plannedWindows=0, windows=[], windowPlanSha256=E.digest([]),
                 planningError={"type": "ValueError", "stage": "probe", "message": "synthetic"})
        self.assertFalse(E.derive_result(row, r)["complete"])

    def test_outside_folder_gate_cannot_be_hidden_by_overall_recall(self):
        records = self.perfect()
        outside_kept = {q: 0 for q in E.QUALITIES}
        for row, r in zip(self.rows, records):
            if row["cohort"] == "benchmark105" and row["expectedAi"] and row["generator"] not in E.TRAINING_GENERATORS:
                q = row["transformation"]; outside_kept[q] += 1
                if outside_kept[q] > 15:
                    r["windows"][0]["logits"]["temporal"] = -1.0
        gates = E.summarize(self.rows, records)["heads"]["temporal"]["gates"]
        self.assertTrue(gates["allAiPerQuality"])
        self.assertFalse(gates["outsideTrainingFoldersPerQuality"])

    def test_window_plan_duration_limits_and_fractional_tail(self):
        self.assertEqual(E.evaluation_windows(3.5), [{"start": 0., "end": 2.}, {"start": 1., "end": 3.}, {"start": 1.5, "end": 3.5}])
        self.assertEqual(len(E.evaluation_windows(120)), 119)
        for duration in (0.49, 121, float("nan"), True):
            with self.assertRaises(ValueError): E.evaluation_windows(duration)


class WindowExecution(unittest.TestCase):
    def test_each_singleton_window_once_continue_after_middle_error_and_retain_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(E, "ROOT", Path(temporary)):
            root = Path(temporary); source = root / "synthetic.bin"; source.write_bytes(b"not a video")
            row = {"id": "synthetic", "path": "synthetic.bin", "sha256": E.sha(source), "cohort": "synthetic", "expectedAi": True}
            timestamps = [i / 24 for i in range(96)]
            probe = {"sha256": row["sha256"], "duration": 4., "timestamps": timestamps}
            loaded = {"identity": {"synthetic": True}, "fingerprint": "synthetic", "load": {}, "contract": {}}
            calls, forwards = [], []
            def extract(path, windows, model, processor, device, probe):
                self.assertEqual(len(windows), 1); calls.append(windows[0])
                if windows[0]["start"] == 1: raise RuntimeError("retained middle-window failure")
                w = windows[0]; available = [i for i, t in enumerate(timestamps) if w["start"] <= t < w["end"]]
                indices = [available[i * (len(available) - 1) // 7] for i in range(8)]
                cls = np.zeros((8, 384), np.float32)
                rec = {"window": w, "source": {"sha256": row["sha256"]}, "model": loaded["identity"], "modelFingerprint": "synthetic",
                       "strictLoad": {}, "contract": {}, "device": "mps", "clsBytesSha256": __import__('hashlib').sha256(cls.tobytes()).hexdigest(),
                       "frames": [{"nativeIndex": i, "timestamp": timestamps[i]} for i in indices]}
                return [(cls, rec)]
            def save(path, cls, receipt):
                with path.open("xb") as f: np.savez(f, cls=cls)
                E.write_json(path.with_suffix(".receipt.json"), dict(receipt, featurePath=str(path), featureSha256=E.sha(path)))
            def head(value):
                forwards.append(value.shape); return torch.tensor([1.])
            f = SimpleNamespace(probe_video=lambda p: probe, extract_windows=extract, save_features=save)
            artifacts = root / "artifacts"; artifacts.mkdir()
            r = E.run_case(row, artifacts, f, None, None, {name: head for name in E.HEADS}, loaded)
            self.assertEqual(len(calls), 3); self.assertEqual(len(forwards), 4)
            self.assertEqual([w["index"] for w in r["windows"]], [0, 1, 2])
            self.assertIn("middle-window", r["windows"][1]["error"]["message"])
            self.assertFalse(r["complete"]); self.assertTrue(r["heads"]["temporal"]["ai"])
            self.assertTrue((artifacts / "window-002.npz").exists())
            self.assertFalse(E.derive_result(row, r, artifact_root=root)["complete"])
            (artifacts / "window-002.npz").write_bytes(b"corrupt")
            with self.assertRaises(ValueError): E.derive_result(row, r, artifact_root=root)


class FinalBinding(unittest.TestCase):
    def test_training_directory_accepts_directory_and_rejects_file_or_escape(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(E, "ROOT", Path(temporary)):
            root = Path(temporary); training = root / "eval/training"; training.mkdir(parents=True)
            regular = root / "eval/file.json"; regular.write_text("{}")
            outside = root / "outside"; outside.mkdir()
            link = root / "eval/link"; link.symlink_to(training, target_is_directory=True)
            self.assertEqual(E.training_directory("eval/training"), training.resolve())
            self.assertEqual(E.training_directory(str(training)), training.resolve())
            for path in (regular, outside, link, root / "eval/missing", root / "eval", "eval/../outside"):
                with self.subTest(path=str(path)), self.assertRaises(ValueError):
                    E.training_directory(str(path))

    def build(self, root):
        training = root / "eval/training"; training.mkdir(parents=True)
        features = root / "eval/features.json"; features.write_text('{"synthetic":true}')
        protocol = {"sourceHashes": {"scripts/train-dinov2-temporal.py": E.sha(T.__file__), "scripts/driver.py": "d" * 64}, "featureDriverPath": "scripts/driver.py"}
        protocol_path = root / "eval/protocol.json"; E.write_json(protocol_path, protocol)
        configuration = {"protocolSha256": E.sha(protocol_path), "featureManifestSha256": E.sha(features),
                         "trainingSourceSha256": E.sha(T.__file__), "heads": T.HEAD_CONFIG, "training": T.TRAINING_CONFIG,
                         "torch": torch.__version__, "numpy": np.__version__}
        E.write_json(training / "configuration.json", configuration); fingerprint = T.digest(configuration)
        heads, optimizers = T.make_heads()
        # Synthetic optimizer state only: no forward, backward, or training step.
        for name, optimizer in optimizers.items():
            for p in heads[name].parameters():
                optimizer.state[p] = {"step": torch.tensor(3840.), "exp_avg": torch.zeros_like(p), "exp_avg_sq": torch.zeros_like(p)}
        record = {"epoch": 20, "examples": 12288, "exampleTypes": {"whole": 6144, "real_ai_feature_splice": 3072, "real_real_feature_splice": 3072},
                  "averageTrainingLoss": {name: 0.5 for name in E.HEADS}}
        state_sha = T.save_state(training / "state-20.pt", heads, optimizers, 20, fingerprint, record)
        E.write_json(training / "epoch-20.json", dict(record, fingerprint=fingerprint, stateFile="state-20.pt", stateSha256=state_sha))
        exported = {}
        for name, head in heads.items():
            path = training / (name + ".safetensors")
            exported[name] = {"path": str(path.relative_to(root)), "sha256": T.export_head(path, head), "parameters": sum(p.numel() for p in head.parameters())}
        E.write_json(training / "complete.json", {"complete": True, "epochs": 20, "fingerprint": fingerprint, "heads": exported, "internalDevelopmentRows": 768})
        identity = {key: configuration[key] for key in ("protocolSha256", "featureManifestSha256", "trainingSourceSha256")}; identity["driverSha256"] = "d" * 64
        started = {"identity": identity, "priorElapsedSeconds": 0., "wallTimeLimitSeconds": 1800, "memoryLimitBytes": 8 * 1024**3}
        E.write_json(training / "training-watchdog-001.running.json", started)
        E.write_json(training / "training-watchdog-001.json", {"identity": identity, "status": "completed", "completionPublished": True,
                     "runningReceiptSha256": E.sha(training / "training-watchdog-001.running.json"), "cumulativeElapsedSeconds": 1.,
                     "supervision": dict(started, elapsedSeconds=1., exitCode=0, stopReason=None, cleanupError=None, peakProcessTreeRssBytes=1000)})
        return protocol, protocol_path, training, features

    def test_final_epoch_cache_config_export_and_supervisor_bindings(self):
        for mutation in (None, "export", "cache", "config", "state", "epoch", "missing-watchdog", "failed-watchdog"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(E, "ROOT", root), patch.object(T, "ROOT", root), patch.object(T, "load_cache", return_value=({}, [None] * 6912, None)):
                    protocol, pp, training, features = self.build(root)
                    if mutation == "export":
                        path = training / "temporal.safetensors"; weights = load_file(str(path)); weights[next(iter(weights))] += 1
                        save_file(weights, str(path)); done = json.loads((training / "complete.json").read_text()); done["heads"]["temporal"]["sha256"] = E.sha(path)
                        (training / "complete.json").write_text(json.dumps(done))
                    if mutation == "cache": features.write_text('{"changed":true}')
                    if mutation == "config":
                        path = training / "configuration.json"; c = json.loads(path.read_text()); c["heads"]["thresholdLogit"] = 99; path.write_text(json.dumps(c))
                    if mutation == "state":
                        path = training / "state-20.pt"; path.write_bytes(path.read_bytes() + b"changed")
                    if mutation == "epoch":
                        path = training / "epoch-20.json"; c = json.loads(path.read_text()); c["examples"] = 1; path.write_text(json.dumps(c))
                    if mutation == "missing-watchdog": (training / "training-watchdog-001.json").unlink()
                    if mutation == "failed-watchdog":
                        path = training / "training-watchdog-001.json"; c = json.loads(path.read_text()); c["status"] = "failed"; path.write_text(json.dumps(c))
                    if mutation is None:
                        heads, binding = E.load_final_heads(T, protocol, pp, training, features)
                        self.assertTrue(binding["allExportedTensorsEqualRestoredState"])
                        self.assertEqual(binding["optimizerUpdatesPerParameter"], 3840)
                        self.assertEqual(set(heads), set(E.HEADS))
                    else:
                        with self.assertRaises(ValueError): E.load_final_heads(T, protocol, pp, training, features)

    def test_loaded_backbone_identity_device_weights_and_actual_parameters(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(E, "ROOT", Path(temporary)):
            root = Path(temporary); models = root / "eval/models"; models.mkdir(parents=True)
            weight = models / "model.safetensors"; weight.write_bytes(b"synthetic identity fixture; never loaded")
            contract_path = root / "eval/contract.json"; E.write_json(contract_path, {"load": {"strict": True}})
            identity = {"assets": {"model.safetensors": {"sha256": E.sha(weight)}}, "policy": {
                "windowSeconds": 2., "evaluationStrideSeconds": 1., "framesPerWindow": 8, "limits": {"windows": 128}}}
            contract = {"path": str(contract_path), "sha256": E.sha(contract_path)}
            protocol = {"featureIdentity": identity, "featureDevice": "mps", "backbone": {
                "modelDirectory": "eval/models", "weightsSha256": E.sha(weight), "contractPath": "eval/contract.json", "contractSha256": E.sha(contract_path)}}
            loaded = {"identity": identity, "fingerprint": E.digest(identity), "device": "mps", "load": {"strict": True}, "contract": contract}
            parameters = [SimpleNamespace(device=SimpleNamespace(type="mps"), dtype=torch.float32, requires_grad=False)]
            model = SimpleNamespace(_feature_identity=identity, _feature_load_receipt=loaded["load"], _feature_contract=contract,
                                    _feature_device="mps", parameters=lambda: parameters)
            feature_module = SimpleNamespace(runtime_identity=lambda: identity, digest=E.digest, validate_contract=lambda p: contract)
            E.validate_loaded_backbone(model, loaded, protocol, feature_module)
            for key, value in [("identity", {}), ("device", "cpu"), ("fingerprint", "wrong"), ("load", {})]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    E.validate_loaded_backbone(model, dict(loaded, **{key: value}), protocol, feature_module)
            parameters[0].device.type = "cpu"
            with self.assertRaises(ValueError): E.validate_loaded_backbone(model, loaded, protocol, feature_module)
            parameters[0].device.type = "mps"
            weight.write_bytes(b"changed")
            with self.assertRaises(ValueError): E.validate_loaded_backbone(model, loaded, protocol, feature_module)


if __name__ == "__main__":
    unittest.main(verbosity=2)
