import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
preprocess_final.py - Final dataset (train.csv/val.csv) icin onisleme

Her videoyu okur, window sampling ile 16 frame cikarir,
(16, 3, 224, 224) float16 tensor olarak kaydeder.

TIMEOUT KORUMASI:
  Worker subprocess'leri icinde SIGALRM ile gercek bir zaman siniri var.
  Bir video isleme N saniyeden uzun surerse, o worker kendi icinde
  exception firlatip bir sonraki goreve gecer - pipeline asla kilitlenmez.
  Bu, ProcessPoolExecutor future-timeout'undan daha guvenilir, cunku
  gercekten o islemi (decord/cv2 cagrisini) kesintiye ugratir.

Kullanim:
    python3 preprocess_final.py --split train --num_workers 16
    python3 preprocess_final.py --split val --num_workers 16
"""

import os
import sys
import csv
import signal
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
UTILS_DIR = os.path.join(THIS_DIR, '..', 'utils')

sys.path.insert(0, THIS_DIR)
sys.path.insert(0, UTILS_DIR)

DATASET_DIR = Path(f'{BASE_DIR}/datasets/final_dataset')
OUTPUT_BASE = Path(f'{BASE_DIR}/datasets/final_dataset/preprocessed')

PER_VIDEO_TIMEOUT = 25  # saniye


class _VideoTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _VideoTimeout("video isleme zaman asimina ugradi")


def process_one(task):
    """
    Tek video isle - subprocess'te calisir.

    SIGALRM ile gercek timeout: PER_VIDEO_TIMEOUT saniye icinde
    bitmezse, signal handler bir exception firlatir ve bu worker
    bir sonraki goreve gecer. SIGALRM sadece Unix'te calisir,
    Linux sunucu ortaminda sorun olmaz.
    """
    path, label, source, difficulty, out_path, this_dir, utils_dir = task

    import sys, os
    if this_dir not in sys.path:
        sys.path.insert(0, this_dir)
    if utils_dir not in sys.path:
        sys.path.insert(0, utils_dir)

    # Bu worker process'inde alarm kur
    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(PER_VIDEO_TIMEOUT)

    try:
        from video_io import load_video, VideoQualityError
        import torch

        bundle = load_video(
            path,
            n_frames=16,
            n_semantic=8,
            height=224,
            width=224,
            sampling='window',
            target_dur=4.0,
            random_start=True,
            quality_filter=True,
        )
        tensor = bundle.frames_all.half()
        torch.save(tensor, out_path)
        return True, path

    except _VideoTimeout:
        return False, f"TIMEOUT: {path} ({PER_VIDEO_TIMEOUT}s asildi)"
    except VideoQualityError as e:
        return False, f"KALITE: {path}: {e}"
    except Exception as e:
        return False, f"{path}: {e}"
    finally:
        signal.alarm(0)  # alarmi iptal et
        signal.signal(signal.SIGALRM, old_handler)


def load_csv(csv_path: Path) -> list:
    samples = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['label'] = int(row['label'])
            samples.append(row)
    return samples


def save_csv(samples: list, csv_path: Path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['path', 'label', 'source', 'difficulty'])
        writer.writeheader()
        writer.writerows(samples)


def preprocess(split: str, num_workers: int):
    csv_path = DATASET_DIR / f'{split}.csv'
    if not csv_path.exists():
        print(f"HATA: {csv_path} bulunamadi.")
        return

    samples = load_csv(csv_path)
    print(f"[{split}] {len(samples)} ornek yuklendi")

    out_dir = OUTPUT_BASE / split
    out_dir.mkdir(parents=True, exist_ok=True)

    preprocessed_index = []
    tasks = []

    for i, s in enumerate(samples):
        out_name = f"{s['source']}_{i}.pt"
        out_path = out_dir / out_name

        preprocessed_index.append({
            'path':       str(out_path),
            'label':      s['label'],
            'source':     s['source'],
            'difficulty': s['difficulty'],
        })

        if not out_path.exists():
            tasks.append((
                s['path'], s['label'], s['source'], s['difficulty'],
                str(out_path), THIS_DIR, UTILS_DIR,
            ))

    already_done = len(samples) - len(tasks)
    print(f"  Zaten islenmis: {already_done} | Islenecek: {len(tasks)}")

    if tasks:
        success = fail = 0
        quality_fail = 0
        timeout_fail = 0

        # Not: max_tasks_per_child Python 3.11+ gerektirir, bu ortamda yok.
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(process_one, t): t for t in tasks}

            with tqdm(total=len(tasks), desc=f"Preprocess [{split}]") as pbar:
                for future in as_completed(futures):
                    ok, info = future.result()
                    if ok:
                        success += 1
                    else:
                        fail += 1
                        if 'KALITE' in info:
                            quality_fail += 1
                        elif 'TIMEOUT' in info:
                            timeout_fail += 1
                        if fail <= 15:
                            print(f"\n  [HATA] {info}")
                    pbar.update(1)
                    pbar.set_postfix(ok=success, fail=fail, timeout=timeout_fail)

        print(f"\n  Tamamlandi: {success} basarili, {fail} hatali "
              f"({quality_fail} kalite, {timeout_fail} timeout)")

    valid = [s for s in preprocessed_index if Path(s['path']).exists()]
    out_csv = out_dir / 'index.csv'
    save_csv(valid, out_csv)

    print(f"  Gecerli ornek: {len(valid)}")
    print(f"  Index kaydedildi: {out_csv}")

    if valid:
        total_gb = Path(valid[0]['path']).stat().st_size * len(valid) / 1e9
        print(f"  Tahmini disk kullanimi: ~{total_gb:.1f} GB")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['train', 'val'], required=True)
    parser.add_argument('--num_workers', type=int, default=16)
    args = parser.parse_args()
    preprocess(args.split, args.num_workers)
