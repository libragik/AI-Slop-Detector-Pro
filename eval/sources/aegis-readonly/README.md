# AEGIS — AI-Generated Video Detection System
## Proje Özeti

Tamamen yapay zeka tarafından üretilmiş videoları (Sora, Veo, Kling, Runway vb.) gerçek kamera videolarından ayırt eden bir tespit sistemi. **Deepfake/yüz değiştirme değil**, baştan sona sentetik video üretimi tespiti.

---

## Repo Yapısı

```
ai_video_detector/
  README.md              Bu dosya
  download_dataset.py    GenVideo-100K seçici indirme scripti
  src/
    branches/             Model kodu + veri/eğitim/analiz pipeline'ı (bkz. Kod Dosyaları)
    utils/video_io.py     Video okuma/decode yardımcıları
  benchmark_scripts/      Diğer 6 modelin public inference scriptleri (bkz. ilgili bölüm)
  results/phase2/         Yayınlanan analiz çıktıları — json/csv/md/png (bkz. Analiz Çıktıları)

  # .gitignore ile dışlanan, sadece sunucuda bulunan klasörler:
  checkpoints/            Model ağırlıkları (.pt) + ham analiz çıktıları (results/'a kopyalanan kaynak)
                          .pt dosyaları GitHub'da değil, Hugging Face Hub'da yayınlanıyor —
                          bkz. Checkpoint bölümü
  datasets/               Tüm video/tensor verisi
  other_models/           6 rakip modelin tam kodu (lisans/boyut nedeniyle yayınlanmıyor)
```

Sunucuya özel mutlak yollar (`/kullanici_yedek/musap.yildiz/...`) kod içinde
`AEGIS_BASE_DIR` ortam değişkeni ile parametrize edilmiş
(`BASE_DIR = os.environ.get("AEGIS_BASE_DIR", "/kullanici_yedek/musap.yildiz")`).
Kendi sunucunuzda çalıştırmak için `export AEGIS_BASE_DIR=/senin/yolun` yeterli.

---

## Kullanım

Bu bölüm, sistemi baştan kurup çalıştırmak için gereken adımları özetler.

### 1) Ortam Kurulumu

```bash
# Python 3.10 ile test edildi
python3 -m venv venv && source venv/bin/activate

# torch/torchvision CUDA sürümüne göre ayrı kurulmalı, ör:
pip install torch==2.5.0 torchvision==0.20.0 --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt

export AEGIS_BASE_DIR=/senin/yolun      # datasets/ ve checkpoints/ hangi kökte olacak
```

`checkpoints/` (model ağırlıkları) ve `datasets/` (video/tensor verisi) repoya dahil
değil (gitignore'lu, boyut nedeniyle) — bunları ayrıca temin edip `$AEGIS_BASE_DIR`
altına yerleştirmeniz gerekiyor. DINOv2 ağırlıkları ilk çalıştırmada `torch.hub` /
`timm` üzerinden otomatik indiriliyor (internet erişimi gerekir).

### 2) Tek Video / Klasör Analizi (en hızlı deneme yolu)

```bash
cd src/branches

# Tek video
python3 inference.py \
  --video /path/to/video.mp4 \
  --checkpoint $AEGIS_BASE_DIR/checkpoints/phase2/checkpoint_best.pt \
  --output_json sonuc.json

# Bir klasördeki tüm videolar
python3 inference.py \
  --dir /path/to/video_folder/ \
  --checkpoint $AEGIS_BASE_DIR/checkpoints/phase2/checkpoint_best.pt \
  --output_json sonuclar.json

# --device auto (varsayılan) cuda varsa otomatik kullanır; --device cpu ile zorlanabilir
```

**Dikkat:** `inference.py`'nin `--checkpoint` varsayılanı `checkpoints/phase1/...` (eski,
Faz 1) — güncel/en iyi modeli (Faz 2, Epoch 7, Val AUC=0.998) kullanmak için yukarıdaki
gibi **her zaman phase2 checkpoint'ini elle belirtin**.

Çıktıda ana `ai_probability`'nin yanında 6 alt-kombinasyon skoru da (pixel/motion/
consistency tekil + PM/PC/MC ikili) rapor edilir.

### 3) Eğitim

```bash
cd src/branches
python3 train.py \
  --final_dataset_dir $AEGIS_BASE_DIR/datasets/final_dataset/preprocessed \
  --epochs 20 --batch_size 16 --lr 1e-4 \
  --save_dir $AEGIS_BASE_DIR/checkpoints/phase2
  # --resume $AEGIS_BASE_DIR/checkpoints/phase2/checkpoint_last.pt ile kaldığı yerden devam eder
```

`--final_dataset_dir` altında `train/index.csv` ve `val/index.csv` (ön-işlenmiş `.pt`
tensörlere işaret eden) bulunmalı — bunlar `preprocess_final.py` ile üretilir
(bkz. Veri hazırlama pipeline'ı).

### 4) Değerlendirme / Analiz Pipeline'ı (çalıştırma sırası)

Aşağıdaki sıra izlenirse her adım bir öncekinin çıktısını kullanır; skorlar bir kere
kaydedildikten sonra tekrar inference çalıştırmaya gerek kalmaz.

```bash
cd src/branches

# 1. Ham skorları kaydet (7 kombinasyon × seçilen kaynak)
python3 save_scores.py --source all --checkpoint $AEGIS_BASE_DIR/checkpoints/phase2/checkpoint_best.pt

# 2. Ablation metrikleri (timing + bellek dahil)
python3 ablation_eval.py --source aegis_raw

# 3. Val-optimal threshold analizi (kaydedilmiş skorlardan, inference gerektirmez)
python3 threshold_tuning.py
python3 threshold_tuning_ablation.py

# 4. Branch disagreement / korelasyon / kalibrasyon
python3 branch_analysis.py --source aegis_raw
python3 calibration_analysis.py --source aegis_raw

# 5. Bizim model + 5 rakip modelin tüm test setlerinde karşılaştırması
python3 build_full_comparison.py
```

### 5) Diğer Modellerle Karşılaştırma

```bash
cd benchmark_scripts

# 1. Test klasöründen ground-truth manifest üret
python3 build_manifest.py --root $AEGIS_BASE_DIR/datasets/aegis_full/videos/test_data \
  --output manifest.csv

# 2. Her modelin kendi inference scriptini çalıştır (model ağırlıkları ayrıca temin edilmeli)
python3 infer_busterx.py --model_path /path/to/busterx_weights \
  --video_dir $AEGIS_BASE_DIR/datasets/aegis_full/videos/test_data --output busterx_results.csv
# infer_cocovideo.py / infer_ivyfake.py / infer_videoveritas.py / skyra_model_engine_hf.py
# için de benzer şekilde --video_dir ve --output kullanılır

# 3. Sonuçları manifest ile birleştirip metrik hesapla
python3 compute_metrics.py --manifest manifest.csv \
  --result busterx_results.csv --output comparison_report.csv
```

---

## Mimari (Faz 2 — Aktif)

```
Video (B, 16, 3, 224, 224)
  ├── Pixel Branch       → DINOv2 (frozen) + LNP + FFT → 512d
  ├── Motion Branch      → LightFlowNet + TemporalTransformer → 512d
  └── Consistency Branch → DINOv2 embedding + velocity + acceleration
                           + speed (||v||) + jerk (||a||) → Transformer → 256d
       ↓
  TripleFusion → ai_probability
  + 6 ek head: 3 tekil (pixel/motion/consistency) + 3 ikili (PM/PC/MC)
  → 7 kombinasyonlu ablation desteği
```

**Eğitilebilir parametre:** 9,231,883 (DINOv2 85M frozen)
**Model boyutu:** 379.8 MB RAM, 453.8 MB disk, peak GPU 2.19 GB

---

## Checkpoint

Model ağırlıkları (`.pt`) boyut nedeniyle GitHub'da değil, **Hugging Face Hub**'da:
**https://huggingface.co/MusapYildiz/aegis-video-detector** (public — best + last + tüm epoch 1-20)

```bash
# Tek dosya indirme
pip install huggingface_hub
python3 -c "
from huggingface_hub import hf_hub_download
path = hf_hub_download('MusapYildiz/aegis-video-detector', 'checkpoint_best.pt',
                        local_dir='\$AEGIS_BASE_DIR/checkpoints/phase2')
print(path)
"

# Tüm repoyu (best+last+epochs, ~9.2 GB) indirme
hf download MusapYildiz/aegis-video-detector --local-dir $AEGIS_BASE_DIR/checkpoints/phase2
```

```
En iyi: checkpoint_best.pt — Epoch 7/20, Val AUC=0.9980, Val FPR=0.0218
Son:    checkpoint_last.pt — Epoch 20/20 (eğitim sonu, en iyi epoch değil)
Tüm epochlar: epochs/checkpoint_epoch00N.pt (1-20)
Geçmiş (sunucuda): $AEGIS_BASE_DIR/checkpoints/phase2/history.json
```

**Epoch seçim notu:** Val loss kriteri ile epoch 3-4 daha iyi (overfitting epoch 5'te başlıyor), ama Val AUC ve GenBuster'da epoch 7 daha dengeli. Epoch 4 AEGIS AUC'de en yüksek (0.901) ama FPR'de kötü.

---

## Veri Seti (Faz 2)

```
Toplam: 49,370 video → 43,857 train + 4,908 val
Preprocessed: $AEGIS_BASE_DIR/datasets/final_dataset/preprocessed/
  train/index.csv  (43,857 satır)
  val/index.csv    (4,908 satır)

FAKE (~21,870): ModelScope, T2VZ, OpenSora, Pika, VC2, SVD, CogVideo,
                Mora, SEINE, Latte, Veo3, Kling, Gen2, Luma
REAL (~27,500): Kinetics-400 (15K), HD-VG-130M (8K), MSR-VTT/Youku (4.5K)
Format: .pt tensor (16, 3, 224, 224) float16
```

### Eğitim Verisini Nereden İndirebilirsin

`build_final_dataset.py`'deki `FAKE_SOURCES`/`REAL_SOURCES` yollarına bakılırsa veri iki
farklı toplama/döneme ait: `datasets/genvidbench/` (daha yeni, "GenVidBench" akademik
benchmark'ı) ve `datasets/genvideo/` (daha eski, ModelScope "GenVideo-100K"/DeMamba seti —
zaten `download_dataset.py` ile bu repoda indirilebiliyor). Aynı üreticinin (ör. Pika, SVD)
iki kaynaktan da örneği var (`_new`/`_old` etiketli) — birebir aynı 43,857 satırı
reprodüklemek için ikisi de gerekiyor.

| Klasör | Kaynak | İndirme |
|---|---|---|
| `genvidbench/extracted/fake/{ms,t2vz,pika,vc2,svd,cogvideo,mora}` + `.../real/hd_vg_130m` | GenVidBench | `hf download jian-0/GenVidBench --repo-type dataset --local-dir .../genvidbench` ¹ |
| `genvideo/extracted/fake/{OpenSora,pika,SVD,SEINE,Latte}` + `.../real/msrvtt_youku` | GenVideo-100K (ModelScope) | Bu repodaki `python3 download_dataset.py --full` (veya `--light`) |
| `kinetics400/videos` | Kinetics-400 | [github.com/cvdfoundation/kinetics-dataset](https://github.com/cvdfoundation/kinetics-dataset) (resmi) |
| `genvidbench/extracted/fake/veo3` | Veo3 | Kaynağı kod içinde belgelenmemiş — muhtemelen elle toplanmış |
| `genvidbench/raw/local/{kling,sora}` | Kling / Sora | Kaynağı kod içinde belgelenmemiş (`raw/local` — elle eklenmiş); GenVidBench'in `6.7m` alt kümesinde (`keling.zip`, `OpenAI_Sora.zip`) aynı içerik olabilir ama doğrulanmadı |
| `aigvdbench/extracted/fake/{Gen2,Luma}` | AIGVDBench | Aşağıdaki Test Setleri bölümüne bakın (yazarlardan istek üzerine) |

¹ `jian-0/GenVidBench`, HF'de "GenVidBench" adıyla arattığımızda bulduğumuz, en çok indirilen
(1676) topluluk mirror'ı — dosya adları (`ms.rar`, `pika.rar`, `t2vz.rar`, `vc2.rar`,
`cogvideo.rar`, `mora.rar`, `svd.rar`, `hd_vg_130m.7z.00N`) projedeki klasör adlarıyla
birebir örtüşüyor. Resmi/ilk-taraf bir HF org hesabı değil, bu yüzden kalıcılığı garanti
değil — indirmeden önce sayfanın hâlâ ayakta olduğunu kontrol edin.

---

## Test Setleri (Eğitime Hiç Girmemiş)

| Kaynak | N | Format | Konum | İndirme |
|---|---|---|---|---|
| AEGIS Hard (keyframe) | 436 | parquet | `.../datasets/aegis/data/*.parquet` | `hf download Clarifiedfish/AEGIS --repo-type dataset` (ungated, `hard_test_set` alt kümesi = 436 satır) |
| AEGIS Hard (ham video) | 436 | .mp4 | `.../datasets/aegis_full/videos/test_data/` | `hf download Clarifiedfish/AEGIS-Full --repo-type dataset` (ungated, companion dataset — ham video/analiz içerir) |
| GenBuster-Bench++ | 2000 | .mp4 | `.../datasets/GenBuster-Bench-plusplus/video/` | `hf download l8cv/GenBuster-Bench-plusplus --repo-type dataset` — **gated**: önce huggingface.co/datasets/l8cv/GenBuster-Bench-plusplus sayfasında erişim talebini kabul etmeniz gerekiyor |
| AIGVDBench | 250 | .mp4 | `.../datasets/aigvdbench/extracted/fake/` | Kamuya açık indirme linki bulunamadı — yazarlardan istek üzerine temin edilmiş (kapalı kaynak modeller: Sora, Kling, Gen2, Gen3, Luma) |
| extra_test (Sora) | 51 | .mp4 | `.../datasets/final_dataset/extra_test.csv` | `build_final_dataset.py`'nin `genvidbench/raw/local/sora`'dan türettiği alt küme — kaynağı yukarıdaki tabloya bakın |
| fresh_real_test | 900 | .mp4 | `.../datasets/final_dataset/fresh_real_test.csv` | Ayrı indirilmez — `build_fresh_real_test.py` ile zaten indirilmiş Kinetics-400/HD-VG-130M/MSR-VTT'den türetilir |

---

## Benchmark Sonuçları — AEGIS Ham Video (n=436)

| Model | AUC | Acc | FPR | Recall | F1 | Süre(s) | Param(B) |
|---|---|---|---|---|---|---|---|
| **Bizim Model** | **0.891** | 0.794 | 0.151 | 0.739 | 0.782 | **0.081** | **0.095** |
| VideoVeritas | 0.882 | 0.878 | 0.161 | 0.922 | 0.887 | 36.67 | 8.77 |
| Skyra | 0.871 | 0.867 | 0.027 | 0.762 | 0.851 | 16.18 | 8.29 |
| IvyFake | 0.778 | 0.626 | 0.711 | 0.972 | 0.724 | 26.21 | 3.75 |
| BusterX | 0.705 | 0.684 | 0.041 | 0.447 | 0.603 | 36.93 | 4.54 |
| CoCoVideo | 0.407 | 0.452 | 0.725 | 0.628 | 0.534 | 0.36 | 0.034 |

**D3 (NSG-VD/XCLIP-16):** AP=0.842 (Real vs Kling), AP=0.780 (Real vs Sora) — farklı metodoloji

---

## Kod Dosyaları

### Model çekirdeği
```
src/branches/
  pixel_branch.py        DINOv2 + LNP + FFT, dino_feats çıktıya eklendi
  motion_branch.py       LightFlowNet + TemporalTransformer (değişmedi)
  consistency_branch.py  Semantic Stability Branch
  detector_model.py      v2 — TripleFusion + 7 kombinasyon + pos_weight=1.0
```

### Veri hazırlama pipeline'ı
```
  build_final_dataset.py    Tüm kaynaklardan örnekleme yapar, train/val split oluşturur;
                             AEGIS + GenVidBench-Sora'yı hiç eğitime sokmadan extra_test
                             olarak ayırır
  preprocess_dataset.py     Videoları önceden işleyip tensöre çevirir (erken sürüm)
  preprocess_final.py       Final dataset (train/val) için ön-işleme — 16 frame window
                             sampling, (16,3,224,224) float16 tensor. Worker'lar içinde
                             SIGALRM tabanlı gerçek zaman-sınırı koruması var: takılan bir
                             video işleme, ProcessPoolExecutor future-timeout'undan daha
                             güvenilir şekilde, pipeline'ı kilitlemeden bir sonraki göreve geçer
  dataset_loader.py         Gerçek video datasetleri için PyTorch Dataset/DataLoader
  build_fresh_real_test.py  Garantili görülmemiş 900 real video test seti
  test_aigvdbench.py        AIGVDBench zip dosyalarını açar ve test eder
  extract_dataset.sh        GenVideo-100K arşivlerini açan shell scripti
```

### Eğitim / inference
```
  train.py               Faz 2 eğitim scripti (final_dataset CSV'leri)
  inference.py            Tek video veya klasör üzerinde inference CLI'ı
```

### Değerlendirme / analiz
```
  ablation_eval.py       7 kombinasyon × 6 kaynak, timing+bellek ölçümü
  build_benchmark_table.py  Tüm modelleri benchmark_table.md/csv'ye yazar
  build_full_comparison.py  Bizim model + diğer 5 model, TÜM test setlerinde
                          (AEGIS/GenBuster/AIGVDBench/extra_test), threshold
                          tuning YAPILMADAN (varsayılan eşik) karşılaştırma
  branch_analysis.py     Disagreement + Correlation + Confidence histogram
  calibration_analysis.py  ECE + Reliability Diagram + Risk-Coverage Curve
  save_scores.py         7 kombinasyonun ham skorlarını .jsonl'e kaydeder
  build_calibration_set.py  AEGIS Hard + AIGVDBench + GenVideo real'den
                          kalibrasyon val seti hazırlar (calibration_set.json)
  calibrate.py            Temperature Scaling (ECE minimize) + branch-disagreement
                          tabanlı Uncertainty Threshold
  threshold_tuning.py    Val'de optimal threshold (F1-max) bul, ana kombinasyonu
                          tüm test kaynaklarına uygula (önce/sonra karşılaştırma)
  threshold_tuning_ablation.py  Aynısı ama 7 kombinasyonun HER BİRİ için ayrı ayrı
                          (her kombinasyonun kendi val-optimal eşiği)
```

---

## Analiz Çıktıları

Scriptler çıktıyı sunucuda `$AEGIS_BASE_DIR/checkpoints/phase2/` altına yazıyor (model
ağırlıklarıyla aynı klasör). Bu klasör `.pt` dosyaları içerdiği için tamamen gitignore'lu;
**json/csv/md/png analiz çıktıları** repoya `results/phase2/` altında (aynı iç yapıyla,
ağırlıklar hariç) kopyalanarak yayınlanıyor — repo içindeki güncel/erişilebilir konum budur.

```
results/phase2/  (sunucuda: checkpoints/phase2/)
  benchmark_table.md / .csv      AEGIS'te tüm model karşılaştırması (eski, AEGIS-only)
  full_comparison.md / .csv / .png   Bizim model + 5 model, TÜM test setlerinde
                                  (AEGIS/GenBuster/AIGVDBench/extra_test),
                                  threshold tuning YAPILMADAN — build_full_comparison.py çıktısı
  ablation_*.json                Her kaynak × her kombinasyon metrikleri (varsayılan eşik)
  history.json                   20 epoch eğitim geçmişi
  scores/                        Ham skorlar (.jsonl) — inference gerektirmez
    val_scores.jsonl
    aegis_raw_scores.jsonl
    genbuster_scores.jsonl
    aigvdbench_scores.jsonl
    extra_test_scores.jsonl
  branch_analysis/               Disagreement + korelasyon grafikleri
  threshold_tuning.json          Ana kombinasyon: val-optimal eşik analizi (F1-max, Youden-J)
  threshold_comparison.json/.md  Ana kombinasyon: önce(0.5)/sonra(tuned) tüm kaynaklarda
  threshold_tuning_ablation.json 7 kombinasyonun HER BİRİ için val-optimal eşik
  threshold_comparison_ablation.json/.md/.png
                                  7 kombinasyon × 4 kaynak, önce/sonra karşılaştırma (görsel)
```

---

## Yapılacaklar (Sıradaki Adımlar)

### Tamamlandı
- [x] `save_scores.py --source all` çalıştırıldı (ham skorlar `scores/*.jsonl`'de, bir daha inference gerekmez)
- [x] `threshold_tuning.py` + `threshold_tuning_ablation.py` çalıştırıldı — val-optimal eşik (F1-max)
      hem ana kombinasyon hem 7 kombinasyonun her biri için ayrı ayrı bulundu, tüm test
      kaynaklarına (inference'sız) uygulanıp önce/sonra karşılaştırıldı. Sonuç: genelleşiyor
      ama bedelli (recall/F1 hafif artıyor, FPR de artıyor) — bkz. Önemli Kararlar.
- [x] `build_full_comparison.py` ile bizim model + 5 model TÜM test setlerinde karşılaştırıldı
      (daha önce sadece AEGIS'te vardı)

### Acil (Şu An)
- [ ] `calibration_analysis.py --source aegis_raw` çalıştır (risk-coverage hatası düzeltildi)



---

## Önemli Kararlar ve Gerekçeler

**pos_weight=1.0 (nötr):** Veri seti dengeli (~1:1.26), pos_weight ile FPR'yi doğrudan düşürmeye çalışmak amaç fonksiyonunu değerlendirme metriğiyle karıştırır.

**Checkpoint epoch 7:** Val AUC'ye göre seçildi. Epoch 4 AEGIS'te daha yüksek AUC (0.901) ama FPR kötü (0.206). Epoch 7 GenBuster'da daha dengeli (AUC 0.870, FPR 0.135).

**WaveRep/Wavelet:** Augmentasyon Faz 3'e ertelendi (paired data gerektirir). Sadece mimari değişiklik (FFT→Wavelet) ayrı izole deney olarak yapılacak.

**Consistency Branch:** Deneysel, ablation ile doğrulandı. AEGIS'te Motion'dan tutarlı şekilde daha güçlü. Pixel↔Consistency korelasyonu 0.86 (yüksek) — makale için dürüst bir sınırlama notu gerekiyor.

**Motion Branch zayıflığı:** Tüm zor test setlerinde sistematik (AEGIS recall 0.44, GenBuster recall 0.24). Optik akış tabanlı yaklaşım yeni nesil modellere karşı kör. Faz 3'te yeniden tasarım planlanıyor.

**Threshold tuning (varsayılan 0.5 → val-optimal 0.217, ana kombinasyon):** Val'de neredeyse etkisiz (F1 +0.001, zaten AUC 0.998 ile çok iyi ayrışıyor). Zor test setlerine (AEGIS/GenBuster) taşındığında recall/F1 hafif iyileşiyor ama FPR de aynı oranda kötüleşiyor (AEGIS +2.3 puan, GenBuster +1.7 puan) — net kazanç değil, bir trade-off. `pos_weight=1.0` kararındaki gerekçeyle tutarlı: FPR'yi düşürmeye çalışmak (veya threshold ile telafi etmek) amaç fonksiyonunu karıştırıyor. **Motion branch tek başına** tuned eşikle belirgin iyileşiyor (AEGIS F1 0.58→0.71, AIGVDBench recall 0.45→0.60) çünkü 0.5 eşiği motion için kalibrasyonsuz (val-optimal eşiği 0.5 değil 0.218) — ama GenBuster'da AUC=0.51 (rastgele düzeyinde), yani eşik ayarı sıralama gücünü değiştiremiyor. **Consistency ve Motion+Consistency** ise tam tersi: val-optimal eşikleri ~0.78-0.79 (0.5'in çok üstü), extra_test'te tuning sonrası recall düşüyor (-0.02, -0.06) — tuning her koşulda iyileştirmiyor. Checkpoint epoch 7 + threshold 0.5 kombinasyonu muhtemelen bilinçli bir denge noktası, değiştirilmedi. Detay: `threshold_comparison_ablation.png`.

---

## Diğer Modeller (Karşılaştırma İçin)

Karşılaştırılan 6 modelin (CoCoVideo, VideoVeritas, Skyra, IvyFake, BusterX, D3) **tam kodu**
sadece sunucuda, `other_models/` altında tutuluyor — lisans ve boyut (checkpoint'ler dahil
GB'larca) nedeniyle repoya dahil edilmiyor (gitignore'lu). Her model için orijinal `infer.py`
scripti var, aynı test videolarını kullanıyor. Kendi kopyanızı çekmek için:

```bash
mkdir -p other_models && cd other_models
git clone https://github.com/l8cv/BusterX.git
git clone https://github.com/DonoToT/CoCoVideo.git
git clone https://github.com/Zig-HS/D3.git
git clone https://github.com/Pi3AI/IvyFake.git
git clone https://github.com/JoeLeelyf/Skyra.git
git clone https://github.com/EricTan7/VideoVeritas.git
```

Her modelin kendi `README`/lisans dosyasındaki kurulum ve ağırlık indirme talimatını
ayrıca izlemeniz gerekir (bu repo sadece adapte edilmiş inference wrapper'larını içerir,
model ağırlıklarını değil).

Repoda yayınlanan public karşılığı **`benchmark_scripts/`** klasörü:

```
benchmark_scripts/
  infer_busterx.py        BusterX için adapte edilmiş inference scripti
  infer_cocovideo.py      CoCoVideo için adapte edilmiş inference scripti
  infer_ivyfake.py        IvyFake için adapte edilmiş inference scripti
  infer_videoveritas.py   VideoVeritas için adapte edilmiş inference scripti
  skyra_model_engine_hf.py  Skyra için HuggingFace tabanlı model motoru
  build_manifest.py       Klasör yapısından (test_data/real|kling|sora/*.mp4) ground-truth
                           manifest üretir — 6 modelin sonuçlarını karşılaştırmak için
                           ortak referans
  compute_metrics.py      Sonuç CSV/JSON'ları manifest ile birleştirip metrik hesaplar.
                          --fakeonly modu (AIGVDBench/extra_test için) düzeltildi —
                          eskiden final tablo adımında KeyError ile çöküyordu.
```

(D3 için ayrı bir `eval.py` var, farklı metodoloji kullandığından `compute_metrics.py`
pipeline'ına dahil değil — bkz. Benchmark Sonuçları'ndaki not.)

Sunucudaki `other_models/` altında ayrıca üretilen ham sonuç raporları (gitignore'lu):
```
  comparison_report.csv   AEGIS sonuçları (real+fake, n=436)
  report_genbuster.csv    GenBuster-Bench++ sonuçları (real+fake, n=2000)
  report_aigvdbench.csv   AIGVDBench sonuçları (fake-only, n=250, sadece Recall)
  report_extratest.csv    extra_test/Sora sonuçları (fake-only, n=51, sadece Recall)
```

**Not — retry dosyaları:** VideoVeritas ve BusterX'in bazı AIGVDBench/extra_test videolarında
ilk çalıştırmada `ERROR` dönmüştü, ayrı `*_retry.csv` dosyalarında düzeltilmiş. `report_*.csv`
üretilirken bunlar video-path bazında merge edilerek (`results_*_merged.csv`) kullanıldı —
sadece retry dosyasını kullanmak eksik/yanlış sonuç veriyordu (örn. VideoVeritas AIGVDBench
recall'ü retry-only ile yanlışlıkla 0.50 çıkmıştı, merge sonrası doğrusu 0.964).

---

## Bağlam: Paralel Chat

Bu projenin **6 açık kaynak model karşılaştırması** ayrı bir Claude chat'te yürütüldü. Sonuçlar `comparison_report.csv`'de birleştirildi ve `build_benchmark_table.py` ile ana tabloya eklendi. İleride yeni modeller eklenince aynı scripti çalıştırmak yeterli.

---

## Lisans

AEGIS'in kendi kodu (`src/`, `download_dataset.py`) MIT lisansı ile yayınlanıyor — bkz. `LICENSE`.

`benchmark_scripts/` altındaki `infer_*.py` scriptleri, karşılaştırılan modellerin (BusterX,
CoCoVideo, IvyFake, VideoVeritas, Skyra) orijinal kodundan **adapte edilmiştir** ve o
projelerin kendi lisans koşullarına tabidir — bu dosyalar MIT kapsamında değildir.
