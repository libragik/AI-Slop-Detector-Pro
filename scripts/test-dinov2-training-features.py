#!/usr/bin/env python3
"""Offline encoding/cache contracts; no pretrained model or benchmark input."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


driver = load("training_feature_driver", "scripts/build-dinov2-training-features.py")
features = load("training_feature_extractor", "scripts/dinov2-temporal-features.py")


class Contracts(unittest.TestCase):
    def test_quality_window_and_resume_integrity(self):
        with tempfile.TemporaryDirectory(prefix="dinov2-driver-contract-", dir=ROOT / "eval/runs") as tmp:
            folder = Path(tmp)
            (folder / "media").mkdir()
            original = folder / "original.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=2",
                            "-an", "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p",
                            str(original)], check=True, timeout=30)
            row = {"id": "synthetic-contract", "path": str(original.relative_to(ROOT)), "sha256": driver.sha(original)}
            probe = features.probe_video(original)
            window = features.windows_for_probe(probe, mode="train", stable_parent_hash=row["sha256"])[0]
            generated = {}
            for quality in ("original", "mild", "severe"):
                media, receipt = driver.derivative(row, quality, folder)
                generated[quality] = (media, receipt)
                actual = features.probe_video(media)
                indices = features.select_indices(actual, window)
                self.assertEqual(len(indices), 8)
                self.assertEqual(len(set(indices)), 8)
                self.assertEqual(actual["frameCount"], 24 if quality == "severe" else 48)
                if quality != "original":
                    command = receipt["command"]
                    self.assertLess(command.index("-protocol_whitelist"), command.index("-i"))
                    self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file,pipe")
                    self.assertNotIn("-protocol_whitelist", receipt["arguments"])
                    self.assertNotIn("-noautorotate", command)
                    self.assertEqual(receipt["displayPolicy"], driver.DISPLAY_POLICY)
                    self.assertEqual(receipt["sourceDisplay"]["stream"]["sample_aspect_ratio"], "1:1")
                    self.assertIn("display_aspect_ratio", receipt["outputDisplay"]["stream"])
                self.assertEqual(driver.derivative(row, quality, folder), (media, receipt))
            media, receipt = generated["mild"]
            raw = media.read_bytes()
            media.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "receipt mismatch"):
                driver.derivative(row, "mild", folder)

    def test_memory_monitor(self):
        self.assertGreater(driver.process_tree_rss(os.getpid()), 0)

    def test_nested_session_watchdog_and_cumulative_budget(self):
        with tempfile.TemporaryDirectory(prefix="dinov2-watchdog-contract-") as tmp:
            pids = Path(tmp) / "pids.json"
            code = ("import json,os,subprocess,sys,time; "
                    "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True); "
                    "open(sys.argv[1],'w').write(json.dumps({'worker':os.getpid(),'nested':p.pid,'workerGroup':os.getpgrp(),'nestedGroup':os.getpgid(p.pid)})); "
                    "time.sleep(60)")
            sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
            try:
                result = driver.supervise([sys.executable, "-c", code, str(pids)], timeout_seconds=2,
                    prior_elapsed_seconds=1, memory_limit_bytes=1024 ** 3, poll_interval=.05)
                evidence = json.loads(pids.read_text())
                self.assertNotEqual(evidence["workerGroup"], evidence["nestedGroup"])
                self.assertEqual(result["stopReason"], "cumulative_wall_time_limit")
                self.assertIsNone(result["cleanupError"])
                self.assertNotEqual(result["exitCode"], 0)
                self.assertTrue({evidence["worker"], evidence["nested"]}.issubset(result["terminatedProcessIds"]))
                remaining = subprocess.run(["/bin/ps", "-p", str(evidence["nested"]), "-o", "state="],
                                           capture_output=True, text=True, timeout=3)
                self.assertTrue(not remaining.stdout.strip() or remaining.stdout.strip().startswith("Z"))
                self.assertIsNone(sentinel.poll(), "Unrelated process must remain running")
            finally:
                sentinel.terminate()
                sentinel.wait(timeout=3)
            with mock.patch.object(driver.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(ValueError, "exhausted"):
                    driver.supervise(["must-not-launch"], timeout_seconds=2,
                        prior_elapsed_seconds=2, memory_limit_bytes=1024)
                launch.assert_not_called()
            result = driver.supervise([sys.executable, "-c", "import time; time.sleep(10)"],
                                      timeout_seconds=2, memory_limit_bytes=1, poll_interval=.05)
            self.assertEqual(result["stopReason"], "process_tree_memory_limit")

    def test_cached_feature_rejects_changed_model_or_array(self):
        with tempfile.TemporaryDirectory(prefix="dinov2-cache-contract-") as tmp:
            path = Path(tmp) / "feature.npz"
            cls = np.zeros((8, 384), dtype=np.float32)
            np.savez(path, cls=cls)
            identity, contract = {"offlineFakeIdentity": True}, {"offlineFakeContract": True}
            base = {"mediaSha256": "a" * 64, "window": {"start": 0, "end": 2}}
            bindings = {"offlineFakeBindings": True}
            receipt = {"row": {**base, "featureSha256": driver.sha(path)}, "bindings": bindings,
                       "extraction": {"schemaVersion": 1, "status": "completed", "window": base["window"],
                         "model": identity, "modelFingerprint": features.digest(identity), "contract": contract,
                         "device": "mps", "featureShape": [8, 384], "featureDtype": "float32",
                         "clsBytesSha256": hashlib.sha256(cls.tobytes()).hexdigest(),
                         "source": {"sha256": base["mediaSha256"]},
                         "strictLoad": {"strict": True, "allTensorsFinite": True, "allLoadedTensorsEqual": True,
                                        "tensorElements": 22056576, "missingKeys": [], "unexpectedKeys": [], "mismatchedKeys": []},
                         "frames": [{"nativeIndex": i} for i in range(8)], "decoder": {"selectedFrameCount": 8}}}
            driver.validate_cached_feature(receipt, path, base, bindings, identity, contract)
            changed = json.loads(json.dumps(receipt))
            changed["extraction"]["model"] = {"anotherModel": True}
            with self.assertRaisesRegex(ValueError, "identity"):
                driver.validate_cached_feature(changed, path, base, bindings, identity, contract)
            cls[0, 0] = 1
            np.savez(path, cls=cls)
            receipt["row"]["featureSha256"] = driver.sha(path)
            with self.assertRaisesRegex(ValueError, "identity"):
                driver.validate_cached_feature(receipt, path, base, bindings, identity, contract)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Contracts)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"passed": result.wasSuccessful(), "testsRun": result.testsRun,
                      "pretrainedModelCalls": 0, "benchmarkInputs": 0,
                      "driverSha256": driver.sha(driver.__file__),
                      "featureModuleSha256": driver.sha(features.__file__)}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
