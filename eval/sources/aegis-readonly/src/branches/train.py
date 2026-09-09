import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
train.py - Faz 2 Egitim Scripti (Pixel + Motion + Consistency Branch)

final_dataset/preprocessed/{train,val}/index.csv kullanir.
extra_test.csv (Sora subset) ve AEGIS Hard Test Set bu scriptte
ASLA kullanilmaz - onlar ayri, egitim-sonrasi degerlendirme icindir.

Kullanim:
    CUDA_VISIBLE_DEVICES=4 python3 train.py \
        --epochs 20 --batch_size 16 --pos_weight 1.0

    # Kesintiye ugrarsa devam etmek icin:
    CUDA_VISIBLE_DEVICES=4 python3 train.py \
        --epochs 20 --batch_size 16 --resume /path/to/checkpoint_last.pt
"""

import os
import sys
import csv
import time
import argparse
import json
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import roc_auc_score, f1_score, accuracy_score
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector_model import VideoForensicsDetector


# ─────────────────────────────────────────────
# Onislenmis .pt Dataset (final_dataset formati)
# ─────────────────────────────────────────────

class PreprocessedDataset(Dataset):
    """
    final_dataset/preprocessed/{split}/index.csv'den yukler.
    Her satir: path, label, source, difficulty
    Her .pt dosyasi: (16, 3, 224, 224) float16 tensor.
    """

    def __init__(self, samples: list):
        self.samples = samples

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        s = self.samples[idx]
        try:
            frames = torch.load(s["path"], weights_only=True).float()  # float16 -> float32
        except Exception:
            next_idx = (idx + 1) % len(self.samples)
            return self.__getitem__(next_idx)

        return {
            "frames":     frames,
            "label":      torch.tensor(s["label"], dtype=torch.long),
            "source":     s["source"],
            "difficulty": s.get("difficulty", "unknown"),
            "path":       s["path"],
        }


def preprocessed_collate(batch: list) -> dict:
    return {
        "frames":      torch.stack([b["frames"] for b in batch]),
        "labels":      torch.stack([b["label"]  for b in batch]),
        "sources":     [b["source"]     for b in batch],
        "difficulties":[b["difficulty"] for b in batch],
        "paths":       [b["path"]       for b in batch],
    }


def load_split_index(final_dataset_dir: str, split: str) -> list:
    """
    final_dataset/preprocessed/{split}/index.csv'den yukler.
    Bu dosya preprocess_final.py tarafindan uretilir ve sadece
    GERCEKTEN var olan .pt dosyalarini icerir (bozuk/timeout videolar
    zaten elenmis).
    """
    csv_path = Path(final_dataset_dir) / split / "index.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Index bulunamadi: {csv_path}\n"
            f"Once preprocess_final.py --split {split} calistirilmali."
        )

    samples = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["label"] = int(row["label"])
            if Path(row["path"]).exists():
                samples.append(row)
    return samples


# ─────────────────────────────────────────────
# Metrik hesaplama
# ─────────────────────────────────────────────

def compute_metrics(all_labels, all_probs, threshold: float = 0.5) -> dict:
    all_labels = np.array(all_labels)
    all_probs  = np.array(all_probs)
    all_preds  = (all_probs >= threshold).astype(int)

    auc = roc_auc_score(all_labels, all_probs) if len(np.unique(all_labels)) > 1 else 0.0
    f1  = f1_score(all_labels, all_preds, zero_division=0)
    acc = accuracy_score(all_labels, all_preds)

    tp = ((all_preds == 1) & (all_labels == 1)).sum()
    fp = ((all_preds == 1) & (all_labels == 0)).sum()
    fn = ((all_preds == 0) & (all_labels == 1)).sum()
    tn = ((all_preds == 0) & (all_labels == 0)).sum()

    recall    = tp / (tp + fn + 1e-8)
    precision = tp / (tp + fp + 1e-8)
    fpr       = fp / (fp + tn + 1e-8)  # false positive rate - AEGIS sorunuyla ilgili kritik metrik

    return {
        "auc": float(auc), "f1": float(f1),
        "accuracy": float(acc),
        "recall": float(recall), "precision": float(precision),
        "fpr": float(fpr),
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
    }


# ─────────────────────────────────────────────
# Egitim dongusu
# ─────────────────────────────────────────────

def train_one_epoch(model, loader, optimizer, device, epoch, pos_weight, log_interval=50) -> dict:
    model.train()
    total_loss = 0.0
    fusion_losses, pixel_losses, motion_losses, consistency_losses = [], [], [], []
    pm_losses, pc_losses, mc_losses = [], [], []
    all_labels, all_probs = [], []
    t0 = time.time()

    for step, batch in enumerate(loader):
        frames = batch["frames"].to(device, non_blocking=True)
        labels = batch["labels"].to(device, non_blocking=True)

        optimizer.zero_grad()
        outputs = model(frames)
        losses  = model.compute_loss(outputs, labels, pos_weight=pos_weight)
        losses["total"].backward()

        nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad],
            max_norm=1.0,
        )
        optimizer.step()

        total_loss += losses["total"].item()
        fusion_losses.append(losses["fusion"].item())
        pixel_losses.append(losses["pixel"].item())
        motion_losses.append(losses["motion"].item())
        consistency_losses.append(losses["consistency"].item())
        pm_losses.append(losses["pixel_motion"].item())
        pc_losses.append(losses["pixel_consistency"].item())
        mc_losses.append(losses["motion_consistency"].item())

        all_labels.extend(labels.cpu().numpy().tolist())
        all_probs.extend(outputs["ai_probability"].detach().cpu().numpy().tolist())

        if (step + 1) % log_interval == 0:
            elapsed = time.time() - t0
            avg_loss = total_loss / (step + 1)
            speed = (step + 1) / elapsed
            eta = (len(loader) - step - 1) / speed
            print(
                f"  Epoch {epoch} | Step {step+1}/{len(loader)} | "
                f"Loss: {avg_loss:.4f} | "
                f"F:{np.mean(fusion_losses):.3f} "
                f"P:{np.mean(pixel_losses):.3f} "
                f"M:{np.mean(motion_losses):.3f} "
                f"C:{np.mean(consistency_losses):.3f} | "
                f"PM:{np.mean(pm_losses):.3f} "
                f"PC:{np.mean(pc_losses):.3f} "
                f"MC:{np.mean(mc_losses):.3f} | "
                f"{speed:.1f} batch/s | ETA:{eta/60:.1f}dk"
            )

    metrics = compute_metrics(all_labels, all_probs)
    metrics["loss"]               = total_loss / len(loader)
    metrics["fusion_loss"]        = float(np.mean(fusion_losses))
    metrics["pixel_loss"]         = float(np.mean(pixel_losses))
    metrics["motion_loss"]        = float(np.mean(motion_losses))
    metrics["consistency_loss"]   = float(np.mean(consistency_losses))
    metrics["pixel_motion_loss"]      = float(np.mean(pm_losses))
    metrics["pixel_consistency_loss"] = float(np.mean(pc_losses))
    metrics["motion_consistency_loss"] = float(np.mean(mc_losses))
    return metrics


@torch.no_grad()
def evaluate(model, loader, device, pos_weight) -> dict:
    model.eval()
    total_loss = 0.0
    all_labels, all_probs = [], []
    all_pixel, all_motion, all_consistency, all_disagree = [], [], [], []
    source_stats = {}

    for batch in loader:
        frames = batch["frames"].to(device, non_blocking=True)
        labels = batch["labels"].to(device, non_blocking=True)

        outputs = model(frames)
        losses  = model.compute_loss(outputs, labels, pos_weight=pos_weight)

        total_loss += losses["total"].item()
        all_labels.extend(labels.cpu().numpy().tolist())
        all_probs.extend(outputs["ai_probability"].cpu().numpy().tolist())
        all_pixel.extend(outputs["pixel_prob"].cpu().numpy().tolist())
        all_motion.extend(outputs["motion_prob"].cpu().numpy().tolist())
        all_consistency.extend(outputs["consistency_prob"].cpu().numpy().tolist())
        all_disagree.extend(outputs["disagreement"].cpu().numpy().tolist())

        for src, lbl, prob in zip(
            batch["sources"],
            labels.cpu().tolist(),
            outputs["ai_probability"].cpu().tolist()
        ):
            if src not in source_stats:
                source_stats[src] = {"labels": [], "probs": []}
            source_stats[src]["labels"].append(lbl)
            source_stats[src]["probs"].append(prob)

    metrics = compute_metrics(all_labels, all_probs)
    metrics["loss"]             = total_loss / len(loader)
    metrics["avg_disagreement"] = float(np.mean(all_disagree))
    metrics["pixel_metrics"]        = compute_metrics(all_labels, all_pixel)
    metrics["motion_metrics"]       = compute_metrics(all_labels, all_motion)
    metrics["consistency_metrics"]  = compute_metrics(all_labels, all_consistency)

    source_aucs = {}
    source_fprs = {}
    for src, data in source_stats.items():
        if len(np.unique(data["labels"])) > 1:
            source_aucs[src] = float(roc_auc_score(data["labels"], data["probs"]))
        # FPR sadece real (label=0) iceren kaynaklar icin anlamli
        labels_arr = np.array(data["labels"])
        if (labels_arr == 0).all():
            preds = (np.array(data["probs"]) >= 0.5).astype(int)
            fp = (preds == 1).sum()
            source_fprs[src] = float(fp / len(preds))
    metrics["source_aucs"] = source_aucs
    metrics["source_fprs"] = source_fprs
    return metrics


# ─────────────────────────────────────────────
# Checkpoint
# ─────────────────────────────────────────────

def save_checkpoint(model, optimizer, epoch, metrics, save_dir, is_best=False):
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    epochs_dir = save_dir / "epochs"
    epochs_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "epoch": epoch,
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "metrics": metrics,
    }
    torch.save(state, save_dir / "checkpoint_last.pt")

    # Her epoch'un kendi dosyasi - ileride "epoch N'de model nasil davraniyordu"
    # diye geriye donup analiz edebilmek icin. Disk maliyeti: ~37MB x epoch sayisi.
    torch.save(state, epochs_dir / f"checkpoint_epoch{epoch:03d}.pt")

    if is_best:
        torch.save(state, save_dir / "checkpoint_best.pt")
        print(f"  -> En iyi model: AUC={metrics.get('auc', 0):.4f} FPR={metrics.get('fpr', 0):.4f}")


def load_checkpoint(path, model, optimizer=None, device=torch.device("cpu")) -> int:
    state = torch.load(path, map_location=device, weights_only=False)
    model.load_state_dict(state["model_state"])
    if optimizer and "optimizer_state" in state:
        optimizer.load_state_dict(state["optimizer_state"])
    epoch = state.get("epoch", 0)
    metrics = state.get("metrics", {})
    print(f"  Checkpoint yuklendi: epoch={epoch}, AUC={metrics.get('auc', 0):.4f}")
    return epoch


# ─────────────────────────────────────────────
# Ana egitim
# ─────────────────────────────────────────────

def train(args):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n{'='*60}")
    print(f"Video Forensics Detector - Faz 2 Egitim (Pixel+Motion+Consistency)")
    print(f"{'='*60}")
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"GPU:    {torch.cuda.get_device_name(0)}")
        print(f"VRAM:   {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    print(f"pos_weight: {args.pos_weight}  (1.0 = notr, veri seti zaten dengeli ~1:1.26)")

    # ── Veri ──
    print(f"\nVeri yukleniyor: {args.final_dataset_dir}")
    train_s = load_split_index(args.final_dataset_dir, "train")
    val_s   = load_split_index(args.final_dataset_dir, "val")

    n_real_tr = sum(1 for s in train_s if s["label"] == 0)
    n_fake_tr = sum(1 for s in train_s if s["label"] == 1)
    n_real_val = sum(1 for s in val_s if s["label"] == 0)
    n_fake_val = sum(1 for s in val_s if s["label"] == 1)

    print(f"  Train: {len(train_s)}  (Real: {n_real_tr} | Fake: {n_fake_tr})")
    print(f"  Val:   {len(val_s)}  (Real: {n_real_val} | Fake: {n_fake_val})")
    print(f"  NOT: extra_test.csv ve AEGIS bu egitimde KULLANILMIYOR (veri sizintisi onlemi)")

    train_ds = PreprocessedDataset(train_s)
    val_ds   = PreprocessedDataset(val_s)

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.num_workers, pin_memory=True, collate_fn=preprocessed_collate,
        prefetch_factor=4 if args.num_workers > 0 else None,
        persistent_workers=args.num_workers > 0, drop_last=True,
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=args.num_workers, pin_memory=True, collate_fn=preprocessed_collate,
        prefetch_factor=4 if args.num_workers > 0 else None,
        persistent_workers=args.num_workers > 0,
    )

    # ── Model ──
    print(f"\nModel hazirlaniyor (Pixel + Motion + Consistency Branch)...")
    model = VideoForensicsDetector(freeze_dino=True).to(device)
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Egitilir parametre: {n_trainable:,}")

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr, weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs, eta_min=args.lr * 0.01,
    )

    start_epoch = 0
    if args.resume:
        start_epoch = load_checkpoint(args.resume, model, optimizer, device)

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    history  = []
    best_auc = 0.0

    print(f"\nEgitim: {args.epochs} epoch | batch={args.batch_size} | lr={args.lr}")
    print(f"Checkpoint: {save_dir}\n")

    for epoch in range(start_epoch + 1, args.epochs + 1):
        t_epoch = time.time()
        print(f"\n{'-'*55}")
        print(f"Epoch {epoch}/{args.epochs}  lr={scheduler.get_last_lr()[0]:.2e}")

        train_m = train_one_epoch(
            model, train_loader, optimizer, device, epoch, args.pos_weight,
            log_interval=max(1, min(50, len(train_loader) // 5)),
        )
        val_m = evaluate(model, val_loader, device, args.pos_weight)
        scheduler.step()

        epoch_time = time.time() - t_epoch
        print(f"\n  TRAIN | Loss:{train_m['loss']:.4f} AUC:{train_m['auc']:.4f} "
              f"F1:{train_m['f1']:.4f} Acc:{train_m['accuracy']:.4f}")
        print(f"  VAL   | Loss:{val_m['loss']:.4f} AUC:{val_m['auc']:.4f} "
              f"F1:{val_m['f1']:.4f} Acc:{val_m['accuracy']:.4f} "
              f"FPR:{val_m['fpr']:.4f} DisAgr:{val_m['avg_disagreement']:.4f}")

        pm = val_m["pixel_metrics"]
        mm = val_m["motion_metrics"]
        cm = val_m["consistency_metrics"]
        print(f"  PIXEL       | AUC:{pm['auc']:.4f} F1:{pm['f1']:.4f} FPR:{pm['fpr']:.4f}")
        print(f"  MOTION      | AUC:{mm['auc']:.4f} F1:{mm['f1']:.4f} FPR:{mm['fpr']:.4f}")
        print(f"  CONSISTENCY | AUC:{cm['auc']:.4f} F1:{cm['f1']:.4f} FPR:{cm['fpr']:.4f}")

        if val_m["source_aucs"]:
            print(f"  Kaynak AUC:")
            for src, auc in sorted(val_m["source_aucs"].items()):
                print(f"    {src}: {auc:.4f}")
        if val_m["source_fprs"]:
            print(f"  Kaynak FPR (sadece real kaynaklar):")
            for src, fpr in sorted(val_m["source_fprs"].items()):
                print(f"    {src}: {fpr:.4f}")

        print(f"  Sure: {epoch_time:.0f}s")

        is_best = val_m["auc"] > best_auc
        if is_best:
            best_auc = val_m["auc"]
        save_checkpoint(model, optimizer, epoch, val_m, str(save_dir), is_best)

        history.append({"epoch": epoch, "train": train_m, "val": val_m})
        with open(save_dir / "history.json", "w") as f:
            json.dump(history, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Egitim tamamlandi. En iyi Val AUC: {best_auc:.4f}")
    print(f"\nSiradaki adim: ablation_eval.py ile 7 kombinasyonu test et,")
    print(f"sonra AEGIS Hard Test Set + extra_test.csv (Sora) ile capraz dogrulama yap.")


# ─────────────────────────────────────────────
# Argparse
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--final_dataset_dir", type=str,
                        default=f"{BASE_DIR}/datasets/final_dataset/preprocessed",
                        help="train/ ve val/ alt klasorlerini iceren ana dizin")
    parser.add_argument("--epochs",          type=int,   default=20)
    parser.add_argument("--batch_size",      type=int,   default=16)
    parser.add_argument("--lr",              type=float, default=1e-4)
    parser.add_argument("--num_workers",     type=int,   default=8)
    parser.add_argument("--pos_weight",      type=float, default=1.0,
                        help="BCE pos_weight. Varsayilan 1.0 (notr). "
                             "Veri seti zaten dengeli (~1:1.26), bu degeri "
                             "degistirmek amac fonksiyonunu degerlendirme "
                             "metrigiyle (FPR) karistirir - sadece ayri bir "
                             "hyperparameter deneyinde degistirin.")
    parser.add_argument("--save_dir",        type=str,
                        default=f"{BASE_DIR}/checkpoints/phase2",
                        help="Faz 1 checkpoint'ini bozmamak icin ayri klasor")
    parser.add_argument("--resume",          type=str,   default=None)

    args = parser.parse_args()
    train(args)
