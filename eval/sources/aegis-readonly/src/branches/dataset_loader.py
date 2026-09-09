import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
dataset_loader.py - Gercek video datasetleri icin PyTorch Dataset
"""

import os
import csv
import random
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'utils'))

try:
    from video_io import load_video
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'utils'))
    from video_io import load_video


# Bozuk veya cikarmak istedigimiz kaynaklar
SKIP_SOURCES = {"zeroscope"}

GENERATOR_TYPE_MAP = {
    "zeroscope": "t2v", "opensora": "t2v", "open_sora": "t2v",
    "latte": "t2v", "modelscope": "t2v", "morphstudio": "t2v",
    "hotshot": "t2v", "show_1": "t2v", "showone": "t2v",
    "lavie": "t2v", "videocrafter": "t2v", "crafter": "t2v",
    "sora": "t2v", "kling": "t2v", "runway": "t2v",
    "pika": "t2v", "gen2": "t2v",
    "i2vgen_xl": "i2v", "i2vgenxl": "i2v",
    "svd": "i2v", "seine": "i2v", "dynamicrafter": "i2v",
    "msrvtt": "real", "msr_vtt": "real", "msrvtt_youku": "real",
    "youku": "real", "kinetics": "real", "kinetics400": "real",
}

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".webm", ".mkv"}


def get_generator_type(name: str) -> str:
    s = name.lower().strip().replace("-", "_").replace(" ", "_")
    if s in GENERATOR_TYPE_MAP:
        return GENERATOR_TYPE_MAP[s]
    for key, val in GENERATOR_TYPE_MAP.items():
        if key in s or s in key:
            return val
    return "unknown"


def find_videos_recursive(directory: Path, max_depth: int = 4) -> list:
    videos = []
    def _search(path: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for item in path.iterdir():
                if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(item)
                elif item.is_dir():
                    _search(item, depth + 1)
        except PermissionError:
            pass
    _search(directory, 0)
    return videos


def build_index_from_dir(root: str) -> list:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Dataset koku bulunamadi: {root}")

    samples = []

    for split in ["real", "fake"]:
        split_dir = root / split
        if not split_dir.exists():
            print(f"  [UYARI] {split_dir} bulunamadi, atlaniyor")
            continue

        label = 0 if split == "real" else 1
        subdirs = [d for d in split_dir.iterdir() if d.is_dir()]

        if not subdirs:
            videos = find_videos_recursive(split_dir, max_depth=1)
            for vp in videos:
                samples.append({
                    "path": str(vp),
                    "label": label,
                    "source": split,
                    "type": "real" if label == 0 else "unknown",
                })
        else:
            for subdir in subdirs:
                source = subdir.name.lower()

                # Bozuk veya istenmeyen kaynaklari atla
                if source in SKIP_SOURCES:
                    print(f"  [ATLA] {source} (SKIP_SOURCES listesinde)")
                    continue

                gen_type = get_generator_type(source)
                if label == 0:
                    gen_type = "real"

                videos = find_videos_recursive(subdir, max_depth=3)
                for vp in videos:
                    samples.append({
                        "path": str(vp),
                        "label": label,
                        "source": source,
                        "type": gen_type,
                    })

                if videos:
                    print(f"  {split}/{source}: {len(videos)} video ({gen_type})")

    return samples


def save_index_to_csv(samples: list, output_path: str):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "label", "source", "type"])
        writer.writeheader()
        for s in samples:
            writer.writerow(s)
    print(f"  [index] {len(samples)} ornek -> {output_path}")


def load_index_from_csv(csv_path: str) -> list:
    samples = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["label"] = int(row["label"])
            samples.append(row)
    return samples


def split_index(
    samples: list,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    seed: int = 42,
) -> tuple:
    random.seed(seed)
    by_source = {}
    for s in samples:
        by_source.setdefault(s["source"], []).append(s)

    train, val, test = [], [], []
    for source, group in by_source.items():
        random.shuffle(group)
        n = len(group)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)
        train.extend(group[:n_train])
        val.extend(group[n_train:n_train + n_val])
        test.extend(group[n_train + n_val:])

    random.shuffle(train)
    random.shuffle(val)
    random.shuffle(test)
    return train, val, test


def build_synthetic_index(
    n_real: int = 20,
    n_fake: int = 20,
    output_dir: str = "/tmp/synthetic_videos",
) -> list:
    import cv2
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []

    for i in range(n_real):
        path = out_dir / f"real_{i:03d}.mp4"
        if not path.exists():
            _create_synthetic_video(str(path), realistic=True, seed=i)
        samples.append({"path": str(path), "label": 0,
                        "source": "synthetic_real", "type": "real"})

    for i in range(n_fake):
        path = out_dir / f"fake_{i:03d}.mp4"
        if not path.exists():
            _create_synthetic_video(str(path), realistic=False, seed=100 + i)
        samples.append({"path": str(path), "label": 1,
                        "source": "synthetic_fake", "type": "t2v"})

    return samples


def _create_synthetic_video(path: str, realistic: bool, seed: int):
    import cv2
    rng = np.random.RandomState(seed)
    h, w = 240, 320
    n_frames = 48
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, 24.0, (w, h))
    x, y = rng.randint(20, w - 20), rng.randint(20, h - 20)
    dx, dy = rng.choice([-3, -2, 2, 3]), rng.choice([-3, -2, 2, 3])
    for t in range(n_frames):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        if realistic:
            noise = rng.randint(0, 30, (h, w, 3), dtype=np.uint8)
            frame = noise
            tint = (t * 2) % 80
            frame[:, :, 0] = (frame[:, :, 0].astype(int) + tint).clip(0, 255).astype(np.uint8)
        else:
            frame[:, :, :] = 128
        cv2.circle(frame, (x, y), 15, (255, 200, 100), -1)
        x += dx + (rng.randint(-2, 3) if realistic else 0)
        y += dy + (rng.randint(-2, 3) if realistic else 0)
        if x < 20 or x > w - 20:
            dx = -dx
        if y < 20 or y > h - 20:
            dy = -dy
        out.write(frame)
    out.release()


class VideoForensicsDataset(Dataset):
    def __init__(
        self,
        samples: list,
        n_frames: int = 16,
        n_semantic: int = 8,
        height: int = 224,
        width: int = 224,
        skip_on_error: bool = True,
    ):
        self.samples = samples
        self.n_frames = n_frames
        self.n_semantic = n_semantic
        self.height = height
        self.width = width
        self.skip_on_error = skip_on_error

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        sample = self.samples[idx]
        try:
            bundle = load_video(
                sample["path"],
                n_frames=self.n_frames,
                n_semantic=self.n_semantic,
                height=self.height,
                width=self.width,
            )
        except Exception as e:
            if self.skip_on_error:
                next_idx = (idx + 1) % len(self.samples)
                return self.__getitem__(next_idx)
            raise

        return {
            "frames": bundle.frames_all,
            "frames_semantic": bundle.frames_semantic,
            "label": torch.tensor(sample["label"], dtype=torch.long),
            "source": sample["source"],
            "type": sample.get("type", "unknown"),
            "path": sample["path"],
        }


def collate_fn(batch: list) -> dict:
    return {
        "frames": torch.stack([b["frames"] for b in batch]),
        "frames_semantic": torch.stack([b["frames_semantic"] for b in batch]),
        "labels": torch.stack([b["label"] for b in batch]),
        "sources": [b["source"] for b in batch],
        "types": [b["type"] for b in batch],
        "paths": [b["path"] for b in batch],
    }


def build_dataloader(
    samples: list,
    batch_size: int = 4,
    shuffle: bool = True,
    num_workers: int = 4,
    **dataset_kwargs,
) -> DataLoader:
    ds = VideoForensicsDataset(samples, **dataset_kwargs)
    return DataLoader(
        ds,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=True,
        collate_fn=collate_fn,
        prefetch_factor=2 if num_workers > 0 else None,
        persistent_workers=num_workers > 0,
    )


if __name__ == "__main__":
    print("=" * 50)
    print("dataset_loader.py - Test")
    print("=" * 50)

    EXTRACT_DIR = f"{BASE_DIR}/datasets/genvideo/extracted"

    if Path(EXTRACT_DIR).exists():
        print(f"\nGercek dataset: {EXTRACT_DIR}")
        samples = build_index_from_dir(EXTRACT_DIR)
        n_real = sum(1 for s in samples if s["label"] == 0)
        n_fake = sum(1 for s in samples if s["label"] == 1)
        print(f"\nToplam: {len(samples)} | Real: {n_real} | Fake: {n_fake}")

        if samples:
            ds = VideoForensicsDataset(samples[:4], n_frames=16, n_semantic=8)
            item = ds[0]
            print(f"frames: {item['frames'].shape}")
            print(f"label:  {item['label'].item()}")
            print(f"source: {item['source']}")
    else:
        print("Gercek dataset yok, sentetik test...")
        samples = build_synthetic_index(n_real=4, n_fake=4)
        ds = VideoForensicsDataset(samples, n_frames=16, n_semantic=8)
        item = ds[0]
        print(f"frames: {item['frames'].shape}")

    print("\n✓ Test tamamlandi.")
