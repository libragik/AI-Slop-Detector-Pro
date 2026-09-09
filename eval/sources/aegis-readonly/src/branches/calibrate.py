import os
# Kendi sunucunda calistirmak icin: export AEGIS_BASE_DIR=/senin/yolun
BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")

"""
calibrate.py - Temperature Scaling + Uncertainty Threshold

Adim 1: Temperature Scaling
    Modelin logit'lerini T ile bolerek kalibrasyon sagla
    ECE (Expected Calibration Error) minimize et

Adim 2: Uncertainty Threshold
    Branch disagreement > threshold ise UNCERTAIN karar ver
    Threshold'u F1 score'u koruyarak false positive azaltacak sekilde sec

Adim 3: Sonuclari gorsellestir ve kaydet
"""

import json
import numpy as np
from pathlib import Path
from scipy.optimize import minimize_scalar
from scipy.special import expit as sigmoid
from scipy.special import logit

DATA_PATH = Path(f'{BASE_DIR}/datasets/calibration/calibration_predictions.json')
OUTPUT_DIR = Path(f'{BASE_DIR}/datasets/calibration')


# ─────────────────────────────────────────────
# Metrikler
# ─────────────────────────────────────────────

def expected_calibration_error(labels, probs, n_bins=10):
    """ECE hesapla — dusuk = iyi kalibre."""
    bins = np.linspace(0, 1, n_bins + 1)
    ece  = 0.0
    n    = len(labels)

    for i in range(n_bins):
        mask = (probs >= bins[i]) & (probs < bins[i+1])
        if mask.sum() == 0:
            continue
        acc  = labels[mask].mean()
        conf = probs[mask].mean()
        ece += mask.sum() / n * abs(acc - conf)

    return ece


def compute_metrics(labels, probs, threshold=0.5):
    preds = (probs >= threshold).astype(int)
    tp = ((preds == 1) & (labels == 1)).sum()
    fp = ((preds == 1) & (labels == 0)).sum()
    fn = ((preds == 0) & (labels == 1)).sum()
    tn = ((preds == 0) & (labels == 0)).sum()

    acc       = (tp + tn) / len(labels)
    precision = tp / (tp + fp + 1e-8)
    recall    = tp / (tp + fn + 1e-8)
    f1        = 2 * precision * recall / (precision + recall + 1e-8)
    fpr       = fp / (fp + tn + 1e-8)  # false positive rate

    return {
        'accuracy':  float(acc),
        'precision': float(precision),
        'recall':    float(recall),
        'f1':        float(f1),
        'fpr':       float(fpr),
        'tp': int(tp), 'fp': int(fp), 'fn': int(fn), 'tn': int(tn),
    }


# ─────────────────────────────────────────────
# Temperature Scaling
# ─────────────────────────────────────────────

def find_temperature(labels, scores):
    """
    En iyi T degerini bul.
    logit(score) / T -> sigmoid -> kalibre prob
    """
    # Skorlari logit uzayina cevir (0/1 edge case'lerden kac)
    scores_clipped = np.clip(scores, 1e-6, 1 - 1e-6)
    logits = logit(scores_clipped)

    def ece_loss(T):
        if T <= 0:
            return 1.0
        calibrated = sigmoid(logits / T)
        return expected_calibration_error(labels, calibrated)

    result = minimize_scalar(ece_loss, bounds=(0.1, 5.0), method='bounded')
    return result.x


# ─────────────────────────────────────────────
# Uncertainty Threshold
# ─────────────────────────────────────────────

def find_uncertainty_threshold(labels, scores, disagreements):
    """
    En iyi disagreement threshold bul.
    
    Hedef:
    - UNCERTAIN dediklerini dogru karardan cikar
    - Kalan kararlarda false positive rate'i dusur
    - Recall'u fazla dusurme (fake'leri kacirma)
    """
    best_threshold  = 0.3
    best_score      = -1

    for thresh in np.arange(0.1, 0.7, 0.02):
        # Belirli olanlar: disagreement < thresh
        certain_mask = disagreements < thresh
        certain_n    = certain_mask.sum()

        if certain_n < 50:  # Cok az ornek kalirsa gecme
            continue

        certain_labels = labels[certain_mask]
        certain_scores = scores[certain_mask]

        m = compute_metrics(certain_labels, certain_scores)

        # Skor: FPR'yi dusur, F1'i koru
        # FPR azalmasi onemli, recall fazla dusmemeli
        score = (1 - m['fpr']) * 0.6 + m['f1'] * 0.4

        if score > best_score:
            best_score     = score
            best_threshold = thresh

    return best_threshold


# ─────────────────────────────────────────────
# Ana kalibrasyon
# ─────────────────────────────────────────────

def main():
    # Veriyi yukle
    if not DATA_PATH.exists():
        print(f"HATA: {DATA_PATH} bulunamadi.")
        print("Once build_calibration_set.py calistir.")
        return

    with open(DATA_PATH) as f:
        data = json.load(f)

    labels       = np.array([d['label']       for d in data])
    scores       = np.array([d['score']        for d in data])
    disagreements = np.array([d['disagreement'] for d in data])
    generators   = [d.get('generator', 'unknown') for d in data]

    print(f"Veri: {len(data)} ornek | Real: {(labels==0).sum()} | Fake: {(labels==1).sum()}")

    # ── Adim 1: Mevcut durum ──
    print("\n" + "="*55)
    print("MEVCUT DURUM (kalibrasyonsuz)")
    print("="*55)
    m_before = compute_metrics(labels, scores)
    ece_before = expected_calibration_error(labels, scores)
    print(f"Accuracy:  {m_before['accuracy']:.1%}")
    print(f"F1:        {m_before['f1']:.3f}")
    print(f"FPR:       {m_before['fpr']:.3f}  (gercek videoların yanlış AI sayılma oranı)")
    print(f"ECE:       {ece_before:.4f}  (kalibrasyon hatası, dusuk=iyi)")

    # Kaynak bazinda breakdown
    print("\nKaynak bazinda:")
    for src in ['aegis', 'aigvdbench', 'genvideo_real']:
        mask = np.array([d['source'] == src for d in data])
        if mask.sum() == 0:
            continue
        m = compute_metrics(labels[mask], scores[mask])
        print(f"  {src:<20}: Acc={m['accuracy']:.1%} FPR={m['fpr']:.3f}")

    # Generator bazinda
    print("\nGenerator bazinda (AEGIS):")
    for gen in ['camera', 'kling', 'sora']:
        mask = np.array([d.get('generator') == gen for d in data])
        if mask.sum() == 0:
            continue
        m = compute_metrics(labels[mask], scores[mask])
        print(f"  {gen:<15}: N={mask.sum()} Acc={m['accuracy']:.1%} FPR={m['fpr']:.3f}")

    # ── Adim 2: Temperature Scaling ──
    print("\n" + "="*55)
    print("ADIM 1: TEMPERATURE SCALING")
    print("="*55)

    T = find_temperature(labels, scores)
    print(f"Bulunan T: {T:.4f}")

    scores_clipped = np.clip(scores, 1e-6, 1 - 1e-6)
    logits         = logit(scores_clipped)
    cal_scores     = sigmoid(logits / T)

    m_after  = compute_metrics(labels, cal_scores)
    ece_after = expected_calibration_error(labels, cal_scores)

    print(f"\nKalibre sonrasi:")
    print(f"Accuracy:  {m_after['accuracy']:.1%}  (once: {m_before['accuracy']:.1%})")
    print(f"F1:        {m_after['f1']:.3f}  (once: {m_before['f1']:.3f})")
    print(f"FPR:       {m_after['fpr']:.3f}  (once: {m_before['fpr']:.3f})")
    print(f"ECE:       {ece_after:.4f}  (once: {ece_before:.4f})")

    # ── Adim 3: Uncertainty Threshold ──
    print("\n" + "="*55)
    print("ADIM 2: UNCERTAINTY THRESHOLD")
    print("="*55)

    unc_threshold = find_uncertainty_threshold(labels, cal_scores, disagreements)
    print(f"Bulunan threshold: {unc_threshold:.2f}")

    certain_mask   = disagreements < unc_threshold
    uncertain_mask = disagreements >= unc_threshold
    uncertain_n    = uncertain_mask.sum()

    print(f"UNCERTAIN olarak isaretlenen: {uncertain_n} ({uncertain_n/len(data):.1%})")

    if certain_mask.sum() > 0:
        m_certain = compute_metrics(labels[certain_mask], cal_scores[certain_mask])
        print(f"\nKesin karar verilen {certain_mask.sum()} ornek:")
        print(f"  Accuracy: {m_certain['accuracy']:.1%}")
        print(f"  F1:       {m_certain['f1']:.3f}")
        print(f"  FPR:      {m_certain['fpr']:.3f}  (once: {m_before['fpr']:.3f})")

    # ── Sonuclari kaydet ──
    calibration_params = {
        'temperature': float(T),
        'uncertainty_threshold': float(unc_threshold),
        'metrics_before': {
            'accuracy': m_before['accuracy'],
            'f1': m_before['f1'],
            'fpr': m_before['fpr'],
            'ece': float(ece_before),
        },
        'metrics_after_temp': {
            'accuracy': m_after['accuracy'],
            'f1': m_after['f1'],
            'fpr': m_after['fpr'],
            'ece': float(ece_after),
        },
        'uncertain_rate': float(uncertain_n / len(data)),
    }

    out_path = OUTPUT_DIR / 'calibration_params.json'
    with open(out_path, 'w') as f:
        json.dump(calibration_params, f, indent=2)

    print(f"\nKalibrasyon parametreleri kaydedildi: {out_path}")
    print(json.dumps(calibration_params, indent=2))


if __name__ == '__main__':
    main()
