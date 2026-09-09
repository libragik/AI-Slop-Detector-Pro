import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
build_calibration_set.py - Kalibrasyon icin validation seti hazirla

Kaynak 1: AEGIS Hard Test Set (parquet'ten keyframe'ler)
Kaynak 2: AIGVDBench kapalı kaynak modeller (extract edilmis .mp4)
Kaynak 3: GenVideo real videolar

Cikti: calibration_set.json
    Her ornek icin:
    - frames tensor yolu veya keyframe listesi
    - ground_truth label
    - kaynak/generator bilgisi
"""

import os
import sys
import json
import random
import torch
import numpy as np
import pandas as pd
from pathlib import Path
from PIL import Image
import io

THIS_DIR  = f'{BASE_DIR}/ai_video_detector/src/branches'
UTILS_DIR = f'{BASE_DIR}/ai_video_detector/src/utils'
sys.path.insert(0, THIS_DIR)
sys.path.insert(0, UTILS_DIR)

from detector_model import VideoForensicsDetector
from video_io import load_video

CHECKPOINT = f'{BASE_DIR}/checkpoints/phase1/checkpoint_best.pt'
OUTPUT_DIR = Path(f'{BASE_DIR}/datasets/calibration')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3,1,1)
IMAGENET_STD  = torch.tensor([0.229, 0.224, 0.225]).view(3,1,1)


def keyframes_to_tensor(keyframes, n=16, size=224):
    frames = []
    for kf in keyframes[:n]:
        if isinstance(kf, dict) and 'bytes' in kf:
            img = Image.open(io.BytesIO(kf['bytes'])).convert('RGB')
        elif isinstance(kf, Image.Image):
            img = kf.convert('RGB')
        else:
            img = Image.open(io.BytesIO(kf)).convert('RGB')
        img = img.resize((size, size))
        t = torch.from_numpy(np.array(img)).float() / 255.0
        t = t.permute(2, 0, 1)
        t = (t - IMAGENET_MEAN) / IMAGENET_STD
        frames.append(t)
    while len(frames) < n:
        frames.append(frames[-1])
    return torch.stack(frames[:n])


def collect_predictions(model, device):
    """
    Tum kaynaklardan prediction topla.
    Returns: list of {label, score, pixel_score, motion_score, disagreement, source}
    """
    results = []

    # ── Kaynak 1: AEGIS ──
    print("\n[1/3] AEGIS Hard Test Set...")
    aegis_dir = Path(f'{BASE_DIR}/datasets/aegis/data/')
    parquet_files = sorted(aegis_dir.glob('*.parquet'))

    if parquet_files:
        dfs = [pd.read_parquet(f) for f in parquet_files]
        df  = pd.concat(dfs, ignore_index=True)
        print(f"  {len(df)} ornek bulundu")

        for _, row in df.iterrows():
            meta      = json.loads(row['meta_data'])
            gt        = 1 if meta['ground_truth'] == 'ai' else 0
            generator = meta.get('generator', 'unknown')

            try:
                frames_t = keyframes_to_tensor(row['keyframes'])
                frames_t = frames_t.unsqueeze(0).to(device)

                with torch.no_grad():
                    out = model(frames_t)

                results.append({
                    'label':       gt,
                    'score':       out['ai_probability'].item(),
                    'pixel_score': out['pixel_prob'].item(),
                    'motion_score': out['motion_prob'].item(),
                    'disagreement': out['disagreement'].item(),
                    'source':      'aegis',
                    'generator':   generator,
                })
            except Exception as e:
                pass

        print(f"  {sum(1 for r in results if r['source']=='aegis')} ornek islendi")
    else:
        print("  AEGIS parquet bulunamadi, atlaniyor")

    # ── Kaynak 2: AIGVDBench ──
    print("\n[2/3] AIGVDBench kapalı kaynak modeller...")
    aigvd_base = Path(f'{BASE_DIR}/datasets/aigvdbench/extracted/fake/')

    aigvd_count = 0
    if aigvd_base.exists():
        for model_dir in aigvd_base.iterdir():
            if not model_dir.is_dir():
                continue
            videos = list(model_dir.glob('*.mp4'))
            sample = random.sample(videos, min(30, len(videos)))

            for vp in sample:
                try:
                    bundle   = load_video(str(vp), n_frames=16, n_semantic=8)
                    frames_t = bundle.frames_all.unsqueeze(0).to(device)

                    with torch.no_grad():
                        out = model(frames_t)

                    results.append({
                        'label':        1,
                        'score':        out['ai_probability'].item(),
                        'pixel_score':  out['pixel_prob'].item(),
                        'motion_score': out['motion_prob'].item(),
                        'disagreement': out['disagreement'].item(),
                        'source':       'aigvdbench',
                        'generator':    model_dir.name,
                    })
                    aigvd_count += 1
                except Exception:
                    pass

    print(f"  {aigvd_count} ornek islendi")

    # ── Kaynak 3: GenVideo Real ──
    print("\n[3/3] GenVideo real videolar...")
    real_dir = Path(f'{BASE_DIR}/datasets/genvideo/extracted/real/msrvtt_youku/Real/')

    real_count = 0
    if real_dir.exists():
        videos = list(real_dir.glob('*.mp4'))
        sample = random.sample(videos, min(100, len(videos)))

        for vp in sample:
            try:
                bundle   = load_video(str(vp), n_frames=16, n_semantic=8)
                frames_t = bundle.frames_all.unsqueeze(0).to(device)

                with torch.no_grad():
                    out = model(frames_t)

                results.append({
                    'label':        0,
                    'score':        out['ai_probability'].item(),
                    'pixel_score':  out['pixel_prob'].item(),
                    'motion_score': out['motion_prob'].item(),
                    'disagreement': out['disagreement'].item(),
                    'source':       'genvideo_real',
                    'generator':    'camera',
                })
                real_count += 1
            except Exception:
                pass

    print(f"  {real_count} ornek islendi")

    return results


def main():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Device: {device}")

    # Model yukle
    print("\nModel yukleniyor...")
    model = VideoForensicsDetector(freeze_dino=True).to(device)
    state = torch.load(CHECKPOINT, map_location=device, weights_only=False)
    model.load_state_dict(state['model_state'])
    model.eval()

    # Predictionlari topla
    results = collect_predictions(model, device)

    # Ozet
    n_real = sum(1 for r in results if r['label'] == 0)
    n_fake = sum(1 for r in results if r['label'] == 1)
    print(f"\nToplam: {len(results)} ornek | Real: {n_real} | Fake: {n_fake}")

    # Kaydet
    out_path = OUTPUT_DIR / 'calibration_predictions.json'
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Kaydedildi: {out_path}")

    # Hizli istatistik
    scores_real = [r['score'] for r in results if r['label'] == 0]
    scores_fake = [r['score'] for r in results if r['label'] == 1]
    if scores_real:
        print(f"\nReal skorlar:  mean={np.mean(scores_real):.3f}, std={np.std(scores_real):.3f}")
    if scores_fake:
        print(f"Fake skorlar:  mean={np.mean(scores_fake):.3f}, std={np.std(scores_fake):.3f}")

    # Mevcut accuracy
    correct = sum(1 for r in results if (r['score'] > 0.5) == bool(r['label']))
    print(f"Mevcut accuracy: {correct/len(results):.1%}")


if __name__ == '__main__':
    main()
