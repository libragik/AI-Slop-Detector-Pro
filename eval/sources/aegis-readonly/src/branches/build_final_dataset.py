import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
build_final_dataset.py - Final veri seti olusturma

Tum kaynaklardan ornekleme yapar, train/val split olusturur,
AEGIS + GenVidBench Sora'yi ayri "extra_test" olarak tutar (asla egitimde kullanilmaz).

Kullanim:
    python3 build_final_dataset.py
"""

import os
import csv
import random
import shutil
from pathlib import Path

random.seed(42)

# ─────────────────────────────────────────────
# Yapilandirma
# ─────────────────────────────────────────────

BASE = Path(f'{BASE_DIR}')
OUT_DIR = BASE / 'datasets' / 'final_dataset'
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Her kaynaktan kac video alinacak ve zorluk seviyesi
FAKE_SOURCES = [
    # (path, n_target, difficulty, label_name)
    (BASE / 'datasets/genvidbench/extracted/fake/ms',              2000, 'easy',   'modelscope'),
    (BASE / 'datasets/genvidbench/extracted/fake/t2vz',             2000, 'easy',   't2vz'),
    (BASE / 'datasets/genvideo/extracted/fake/OpenSora',            2000, 'easy',   'opensora_old'),

    (BASE / 'datasets/genvidbench/extracted/fake/pika',             1500, 'medium', 'pika_new'),
    (BASE / 'datasets/genvideo/extracted/fake/pika',                1000, 'medium', 'pika_old'),
    (BASE / 'datasets/genvidbench/extracted/fake/vc2',              2000, 'medium', 'videocrafter2'),
    (BASE / 'datasets/genvidbench/extracted/fake/svd',              1500, 'medium', 'svd_new'),
    (BASE / 'datasets/genvideo/extracted/fake/SVD',                 1000, 'medium', 'svd_old'),
    (BASE / 'datasets/genvidbench/extracted/fake/cogvideo',         2000, 'medium', 'cogvideo'),
    (BASE / 'datasets/genvidbench/extracted/fake/mora',             1500, 'medium', 'mora'),
    (BASE / 'datasets/genvideo/extracted/fake/SEINE',               1500, 'medium', 'seine_old'),
    (BASE / 'datasets/genvideo/extracted/fake/Latte',               2000, 'medium', 'latte_old'),

    (BASE / 'datasets/genvidbench/extracted/fake/veo3',             1350, 'hard',   'veo3'),
    (BASE / 'datasets/genvidbench/raw/local/kling',                  420, 'hard',   'kling'),
    (BASE / 'datasets/aigvdbench/extracted/fake/Gen2',               100, 'hard',   'gen2'),
    (BASE / 'datasets/aigvdbench/extracted/fake/Luma',               100, 'hard',   'luma'),
]

REAL_SOURCES = [
    (BASE / 'datasets/kinetics400/videos',                         15000, 'real', 'kinetics400'),
    (BASE / 'datasets/genvidbench/extracted/real/hd_vg_130m',        8000, 'real', 'hd_vg_130m'),
    (BASE / 'datasets/genvideo/extracted/real/msrvtt_youku/Real',    4500, 'real', 'msrvtt_youku'),
]

# Test'e ayrilacaklar (egitimde ASLA kullanilmaz)
EXTRA_TEST_SOURCES = [
    (BASE / 'datasets/genvidbench/raw/local/sora',  'fake', 'sora_genvidbench'),
]
# AEGIS zaten parquet formatinda, ayri ele alinacak (zaten test ettik)


# ─────────────────────────────────────────────
# Yardimci fonksiyonlar
# ─────────────────────────────────────────────

def find_videos(path: Path, max_depth: int = 4) -> list:
    """Bir klasor altindaki tum mp4 dosyalarini bul."""
    if not path.exists():
        return []
    videos = []
    def _search(p, depth):
        if depth > max_depth:
            return
        try:
            for item in p.iterdir():
                if item.is_file() and item.suffix.lower() == '.mp4':
                    videos.append(item)
                elif item.is_dir():
                    _search(item, depth + 1)
        except PermissionError:
            pass
    _search(path, 0)
    return videos


def sample_videos(path: Path, n_target: int) -> list:
    """Bir klasorden n_target kadar rastgele video sec."""
    videos = find_videos(path)
    if not videos:
        print(f"  [UYARI] {path} - video bulunamadi")
        return []
    n = min(n_target, len(videos))
    selected = random.sample(videos, n)
    return selected


# ─────────────────────────────────────────────
# Ana islem
# ─────────────────────────────────────────────

def build():
    print("=" * 60)
    print("FINAL VERI SETI OLUSTURMA")
    print("=" * 60)

    all_samples = []  # [{'path', 'label', 'source', 'difficulty'}]

    # ── FAKE kaynaklar ──
    print("\n[FAKE] Kaynaklar isleniyor...")
    fake_total = 0
    for path, n_target, difficulty, name in FAKE_SOURCES:
        videos = sample_videos(path, n_target)
        for v in videos:
            all_samples.append({
                'path':       str(v),
                'label':      1,
                'source':     name,
                'difficulty': difficulty,
            })
        fake_total += len(videos)
        print(f"  {name:<20} ({difficulty:<6}): {len(videos):>6} / {n_target}")

    print(f"\n  FAKE TOPLAM: {fake_total}")

    # ── REAL kaynaklar ──
    print("\n[REAL] Kaynaklar isleniyor...")
    real_total = 0
    for path, n_target, difficulty, name in REAL_SOURCES:
        videos = sample_videos(path, n_target)
        for v in videos:
            all_samples.append({
                'path':       str(v),
                'label':      0,
                'source':     name,
                'difficulty': difficulty,
            })
        real_total += len(videos)
        print(f"  {name:<20} ({difficulty:<6}): {len(videos):>6} / {n_target}")

    print(f"\n  REAL TOPLAM: {real_total}")
    print(f"\n  GENEL TOPLAM: {fake_total + real_total}")
    print(f"  Oran (fake:real): 1:{real_total/max(fake_total,1):.2f}")

    # ── Train/Val split (stratified by source) ──
    print("\n[SPLIT] Train/Val ayriliyor...")
    by_source = {}
    for s in all_samples:
        by_source.setdefault(s['source'], []).append(s)

    train, val = [], []
    for source, group in by_source.items():
        random.shuffle(group)
        n_val = max(1, int(len(group) * 0.1))
        val.extend(group[:n_val])
        train.extend(group[n_val:])

    random.shuffle(train)
    random.shuffle(val)

    print(f"  Train: {len(train)}")
    print(f"  Val:   {len(val)}")

    # ── Extra Test (asla egitimde kullanilmaz) ──
    print("\n[EXTRA TEST] Ayri test seti olusturuluyor...")
    extra_test = []
    for path, label_name, name in EXTRA_TEST_SOURCES:
        videos = find_videos(path)
        label = 1 if label_name == 'fake' else 0
        for v in videos:
            extra_test.append({
                'path':       str(v),
                'label':      label,
                'source':     name,
                'difficulty': 'test_only',
            })
        print(f"  {name:<20}: {len(videos)} video (TEST ICIN, EGITIME GIRMEZ)")

    # ── CSV'lere kaydet ──
    def save_csv(samples, filename):
        out_path = OUT_DIR / filename
        with open(out_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['path', 'label', 'source', 'difficulty'])
            writer.writeheader()
            writer.writerows(samples)
        print(f"  Kaydedildi: {out_path} ({len(samples)} ornek)")

    print("\n[KAYIT] CSV dosyalari yaziliyor...")
    save_csv(train, 'train.csv')
    save_csv(val, 'val.csv')
    save_csv(extra_test, 'extra_test.csv')

    # ── Zorluk dagilimi ozeti ──
    print("\n[OZET] Zorluk dagilimi (train):")
    diff_count = {}
    for s in train:
        diff_count[s['difficulty']] = diff_count.get(s['difficulty'], 0) + 1
    for d, c in sorted(diff_count.items()):
        print(f"  {d:<10}: {c:>6} ({c/len(train)*100:.1f}%)")

    print("\n" + "=" * 60)
    print("TAMAMLANDI")
    print("=" * 60)
    print(f"\nNot: AEGIS Hard Test Set ayri tutuluyor (zaten parquet formatinda).")
    print(f"Egitim komutu icin train.csv ve val.csv kullanin.")


if __name__ == '__main__':
    build()
