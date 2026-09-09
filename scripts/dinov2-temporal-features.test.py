"""Offline contracts: no pretrained weights, model construction or model forwards."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("dinov2_features", Path(__file__).with_name("dinov2-temporal-features.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class FeatureContracts(unittest.TestCase):
    def test_import_has_no_model_modules(self):
        # Separate fresh interpreter also guards against other tests importing Torch.
        result = subprocess.run([sys.executable, "-c", "import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('f',{str(Path(M.__file__).resolve())!r});"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "assert 'torch' not in sys.modules and 'transformers' not in sys.modules"], check=True)
        self.assertEqual(result.returncode, 0)

    def test_identity_json_roundtrip(self):
        value = M.runtime_identity()
        self.assertEqual(value, json.loads(json.dumps(value)))

    def test_pinned_preprocessor_matches_pil_recipe(self):
        import numpy as np
        from PIL import Image
        from transformers import BitImageProcessor
        config = json.loads((M.ROOT/"eval/sources/dinov2-training-backbone/hf-preprocessor_config.json").read_text())
        processor = BitImageProcessor(**config)
        for image in M.synthetic_images():
            crop = M.crop_receipt(image.width, image.height)
            resized = image.convert("RGB").resize(tuple(crop["resized"]), Image.Resampling.BICUBIC)
            x, y, w, h = crop["cropXYWH"]
            expected = np.asarray(resized.crop((x,y,x+w,y+h))).astype(np.float32)/255
            expected = (expected-np.array(config["image_mean"], dtype=np.float32))/np.array(config["image_std"], dtype=np.float32)
            actual = processor(images=image, return_tensors="np")["pixel_values"][0]
            self.assertEqual(actual.shape, (3,224,224))
            self.assertLessEqual(float(np.max(np.abs(actual-expected.transpose(2,0,1)))), 1e-6)

    def test_training_window_reused(self):
        probe = {"duration": 9, "timestamps": [i/24 for i in range(216)]}
        window = M.windows_for_probe(probe, "train", "a"*64)
        self.assertEqual(window, M.windows_for_probe(probe, "train", "a"*64))
        derivative = {"duration": 8.99, "originalDuration": 9,
                      "timestamps": [i/30 for i in range(269)]}
        self.assertEqual(window, M.windows_for_probe(derivative, "train", "a"*64))
        self.assertNotEqual(window, M.windows_for_probe(probe, "train", "b"*64))

    def test_evaluation_tail_and_coverage(self):
        probe = {"duration": 5.25, "timestamps": [i/24 for i in range(126)]}
        windows = M.windows_for_probe(probe, "evaluation", "a"*64)
        self.assertEqual(windows[-1], {"start": 3.25, "end": 5.25})
        self.assertEqual(windows[0]["start"], 0)
        for a, b in zip(windows, windows[1:]):
            self.assertLessEqual(b["start"], a["end"])
        for window in windows:
            indexes = M.select_indices(probe, window)
            self.assertEqual(len(set(indexes)), 8)
            self.assertTrue(all(window["start"] <= probe["timestamps"][i] < window["end"] for i in indexes))

    def test_short_and_sparse_failures(self):
        with self.assertRaises(ValueError):
            M.windows_for_probe({"duration": .49, "timestamps": []}, "evaluation", "a"*64)
        with self.assertRaises(ValueError):
            M.windows_for_probe({"duration": 2, "timestamps": [i/3 for i in range(6)]}, "evaluation", "a"*64)
        p = {"duration": .5, "timestamps": [i/16 for i in range(8)]}
        self.assertEqual(M.windows_for_probe(p, "evaluation", "a"*64), [{"start": 0., "end": .5}])

    def test_no_network_guard(self):
        original = socket.getaddrinfo
        with M.offline():
            with self.assertRaises(RuntimeError):
                socket.getaddrinfo("example.com", 443)
        self.assertIs(socket.getaddrinfo, original)

    def test_watchdog_and_byte_caps(self):
        with self.assertRaises(TimeoutError):
            M.bounded_process([sys.executable, "-c", "import time;time.sleep(20)"], .1, 100)
        with self.assertRaises(ValueError):
            M.bounded_process([sys.executable, "-c", "print('x'*1000)"], 2, 10)

    def test_missing_checkpoint_rejected_before_model_import(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                M.validate_assets(root)
            with self.assertRaises(ValueError):
                M.load_backbone(root)

    def test_native_decoder_and_tamper(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as root:
            clip = Path(root)/"fixture.mkv"
            # Lossless RGB with 18 distinct native frames at 8fps; not dataset media.
            frames = []
            for i in range(18):
                frame = np.empty((64, 96, 3), dtype=np.uint8)
                frame[..., 0] = i*11
                frame[..., 1] = np.arange(96, dtype=np.uint8)
                frame[..., 2] = np.arange(64, dtype=np.uint8)[:, None]
                frames.append(frame)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", "96x64", "-r", "8", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
                str(clip)], input=b"".join(f.tobytes() for f in frames), check=True, timeout=10)
            probe = M.probe_video(clip)
            self.assertEqual(probe["frameCount"], 18)
            self.assertAlmostEqual(probe["duration"], 2.25)
            indexes = M.select_indices(probe, {"start": .25, "end": 2.25})
            found = {}
            receipt = M.decode_selected(probe, indexes, lambda i, rgb: found.update({i: rgb.copy()}))
            self.assertEqual(set(found), set(indexes))
            self.assertEqual(receipt["selectedFrameCount"], 8)
            for i, rgb in found.items():
                self.assertTrue(np.array_equal(rgb, frames[i]))
            forged = dict(probe, absoluteTimestamps=[t+.01 for t in probe["absoluteTimestamps"]])
            with self.assertRaises(ValueError):
                M.decode_selected(forged, indexes, lambda *args: None)
            clip.write_bytes(clip.read_bytes()+b"changed")
            with self.assertRaises(ValueError):
                M.decode_selected(probe, indexes, lambda *args: None)

    def test_safe_feature_roundtrip_and_immutable_receipt(self):
        import numpy as np
        cls = np.arange(8*384, dtype=np.float32).reshape(8, 384)
        receipt = {"clsBytesSha256": hashlib.sha256(cls.tobytes()).hexdigest()}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"feature.npz"
            M.save_features(path, cls, receipt)
            with np.load(path, allow_pickle=False) as data:
                self.assertEqual(data.files, ["cls"])
                self.assertTrue(np.array_equal(data["cls"], cls))
            with self.assertRaises(FileExistsError):
                M.save_features(path, cls, receipt)
            with self.assertRaises(ValueError):
                M.save_features(Path(root)/"bad.npz", cls.astype(np.float64), receipt)

    def test_agreement_threshold_is_fixed(self):
        import numpy as np
        cpu = np.ones((2,384), dtype=np.float32)
        self.assertTrue(M._agreement(cpu, cpu)["passed"])
        self.assertFalse(M._agreement(cpu, cpu+np.float32(.002))["passed"])
        changed = cpu.copy(); changed[0,0] += .004
        self.assertFalse(M._agreement(cpu, changed)["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
