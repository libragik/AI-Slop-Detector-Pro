# AEGIS — Genel Model Karsilastirmasi (Tum Test Setleri)

Not: Threshold tuning YAPILMAMIS durumdaki (varsayilan karar esigi) sonuclardir.


## AEGIS Hard (ham video) (n=436)

| Model | Accuracy | Precision | Recall | F1 | AUC | Sure(s) | Param(B) | Disk(GB) | GPU(GB) |
|---|---|---|---|---|---|---|---|---|---|
| Bizim Model (ham video) | 0.7936 | 0.8299 | 0.7385 | 0.7816 | 0.8910 | 0.081 | 0.095 | 0.44 | 2.14 |
| VideoVeritas | 0.8784 | 0.8547 | 0.9217 | 0.8869 | 0.8818 | 36.670 | 8.770 | 16.34 | 30.17 |
| Skyra | 0.8670 | 0.9651 | 0.7615 | 0.8513 | 0.8706 | 16.180 | 8.290 | 15.46 | 20.62 |
| IvyFake | 0.6261 | 0.5769 | 0.9722 | 0.7241 | 0.7776 | 26.210 | 3.750 | 7.03 | 12.12 |
| BusterX | 0.6835 | 0.9271 | 0.4472 | 0.6034 | 0.7051 | 36.930 | 4.540 | 9.66 | 14.08 |
| CoCoVideo | 0.4518 | 0.4644 | 0.6284 | 0.5341 | 0.4069 | 0.360 | 0.034 | 0.37 | 0.63 |

D3 (NSG-VD/XCLIP-16, ayri metodoloji, AP skoru — dogrudan kiyaslanamaz): all_fake=0.6935, kling=0.8424, sora=0.7800


## GenBuster-Bench++ (n=2000)

| Model | Accuracy | Precision | Recall | F1 | AUC | Sure(s) | Param(B) | Disk(GB) | GPU(GB) |
|---|---|---|---|---|---|---|---|---|---|
| VideoVeritas | 0.9195 | 0.9022 | 0.9410 | 0.9212 | 0.9195 | 46.160 | 8.770 | 16.34 | 28.55 |
| Bizim Model (ham video) | 0.8005 | 0.8450 | 0.7360 | 0.7867 | 0.8695 | 0.130 | 0.095 | 0.44 | 2.14 |
| BusterX | 0.7745 | 0.9669 | 0.6614 | 0.7855 | 0.8292 | 45.630 | 4.540 | 9.66 | 24.95 |
| IvyFake | 0.6320 | 0.5976 | 0.8118 | 0.6885 | 0.7123 | 26.810 | 3.750 | 7.03 | 7.58 |
| CoCoVideo | 0.5035 | 0.5023 | 0.7810 | 0.6114 | 0.5176 | 0.900 | 0.034 | 0.37 | 0.63 |
| Skyra | 0.5350 | 0.5182 | 0.9960 | 0.6817 | 0.4994 | 23.250 | 8.290 | 15.46 | 19.35 |

D3 (NSG-VD/XCLIP-16, ayri metodoloji, AP skoru — dogrudan kiyaslanamaz): genbuster_fake=0.4807


## AIGVDBench (n=250, sadece FAKE video — Recall = tespit orani)

| Model | N | Recall | Sure(s) |
|---|---|---|---|
| VideoVeritas | 250 | 0.9640 | 30.060 |
| IvyFake | 250 | 0.9520 | 24.470 |
| Bizim Model (ham video) | 250 | 0.9000 | 0.084 |
| Skyra | 250 | 0.7520 | 17.920 |
| BusterX | 250 | 0.6480 | 35.310 |
| CoCoVideo | 250 | 0.6120 | 1.060 |

## extra_test (Sora) (n=51, sadece FAKE video — Recall = tespit orani)

| Model | N | Recall | Sure(s) |
|---|---|---|---|
| VideoVeritas | 51 | 0.9608 | 29.440 |
| IvyFake | 51 | 0.8431 | 28.480 |
| CoCoVideo | 51 | 0.6863 | 1.890 |
| Bizim Model (ham video) | 51 | 0.6275 | 0.089 |
| Skyra | 51 | 0.5294 | 18.700 |
| BusterX | 51 | 0.1765 | 29.380 |
