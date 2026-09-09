# CORVI local development evaluation

This candidate is the `Grag2021_latent` checkpoint from the official Corvi et al. ICASSP 2023 image-detection repository, not a video-trained model. [Official project](https://github.com/grip-unina/DMimageDetection); [pinned test instructions and weights link](https://github.com/grip-unina/DMimageDetection/blob/745ad9e1eee82bdac4aab6e1e7e7dbf20753633a/test_code/README.md).

The official implementation uses modified ResNet-50 (`stride0=1`, `gap_size=1`, one output channel), native full RGB images, ImageNet mean/std normalization, and mean spatial logits. It applies no image resizing or cropping. Its published image decision is synthetic when the logit is positive. The repository and its test instructions carry Apache-2.0; the preserved license is `eval/sources/CORVI-LICENSE.txt`.

This local adapter samples eight frames uniformly, preserves their native dimensions, averages their spatial logits, then averages the eight frame logits. The temporal averaging is an exploratory image-to-video adaptation; it is not a validated video detector. Scores are not probabilities. No threshold fitting is performed in this smoke test.

## Observed development results

The 35-clip smoke completed with zero errors at the published threshold of zero: **1/23 AI clips detected, 22/23 missed, and 0/12 real clips flagged**. No abstention mechanism was added to this specialist test. Raw-score AUROC was **0.9529** (source-group bootstrap 95% interval 0.8547–1.0). The ranking is exploratory; the published decision threshold performs poorly on this video sample, and no threshold was fitted here.

The MPS smoke took 78.42 seconds: median 2.234 seconds per clip, nearest-rank p95 2.285 seconds, maximum 2.333 seconds. All 280 input tensors retained shape 3×1024×1024 and produced 1×1×128×128 spatial logits. Frozen source copies and weights remained unchanged. Two CPU and two matching MPS contract executions are preserved separately; those repeated sources do not increase the 35-source denominator.

Machine-readable results: `eval/sources/corvi-development-report.json`; integrity/timing checks: `eval/sources/corvi-development-verification.json`.

## Development social variants and controls

The unchanged runner then processed the existing 35 development sources at both social transformations, followed by the six existing controls. All 76 new inferences completed without errors in 55.13 seconds. Every frame retained its native dimensions; sources, weights and raw media identities verified after each batch. The runner's 35-clip bound was preserved by splitting the 70 derivatives into two quality batches.

| Quality | AI / real sources | Raw-score AUROC | Group-bootstrap 95% interval | AI detected at 0 | Real flagged at 0 |
|---|---:|---:|---:|---:|---:|
| Original | 23 / 12 | 0.9529 | 0.8547–1.0000 | 1/23 | 0/12 |
| Mild 720p/CRF28 | 23 / 12 | 0.8225 | 0.6709–0.9490 | 0/23 | 0/12 |
| Severe 360p/CRF36/12fps/crop/overlay | 23 / 12 | 0.6558 | 0.4533–0.8182 | 0/23 | 0/12 |

The three CGI control logits were **-5.556895, -6.651246, -0.702849**. The three controls containing opening segments from an **author-labeled Wan2.6 benchmark video** had logits **-11.958032, -11.939574, -10.998217**. All were negative at zero. Their construction proves which source bytes were inserted, not independent AI generation of those individual frames. Every CGI control scored higher than every mixed-labeled control, so a global monotonic threshold cannot separate these recorded pipeline outputs. This is not a clean test of recognition of inserted generated pixels: a subsequent exact-frame audit found that the 0.5-second and 1-second inserts were never sampled, while the two-second insert contributed only two of eight frames. See [mixed-control provenance and sampling qualification](MIXED_CONTROL_PROVENANCE.md). Control AUROC is zero, but the controls represent only two underlying source groups; its degenerate bootstrap interval does not imply a precise population estimate.

These are 35 repeatedly evaluated development sources, not 105 independent videos, plus three Sintel excerpts and three same-parent insertion variants. Severe processing changes several factors simultaneously. The eight-frame sampling omitted the two shorter inserted segments entirely, and mean aggregation may dilute the longer segment. The parent's text-to-video versus image-to-video mode and opening-frame provenance are unknown; its opening frames change over time, which does not independently establish their generated origin. No threshold was fitted, no production classifier changed, and no holdout prediction was inspected in this candidate screen.

Raw outputs:

- `eval/runs/corvi-social-mild-v1.jsonl`
- `eval/runs/corvi-social-severe-v1.jsonl`
- `eval/runs/corvi-controls-v1.jsonl`

Each has an immutable source snapshot and execution receipt. Exact scores and all paired score shifts are in `eval/sources/corvi-social-screen-summary.json` and `eval/sources/corvi-social-exact-scores.csv`. Separate published-default reports are `corvi-social-mild-report.json`, `corvi-social-severe-report.json`, and `corvi-controls-report.json` in `eval/sources/`.

Safety and reproducibility:

- All five preexisting source files match official commit `745ad9e1eee82bdac4aab6e1e7e7dbf20753633a` byte-for-byte.
- Original download receipts connect the local ZIP and checkpoint hashes to the official linked Google Drive file. The checkpoint matches its ZIP member.
- Checkpoint inspection returned no unsupported globals. Conversion used `torch.load(weights_only=True, map_location="cpu")` with no allowlisting. Only the 320 model tensor entries were saved; the safetensors roundtrip is exactly equal. Inference supports safetensors only.
- The adapter imports the exact copied architecture and normalization modules directly. It does not run the upstream CLI or its unqualified checkpoint loader.
- Every run snapshots the adapter and pinned source files, verifies media hashes, and saves frame dimensions, spatial score-map dimensions, all raw logits, configuration, device, and timing.
- Bounds: at most 35 existing development clips, eight frames each, native dimensions at most 1536×1536, duration at most 120 seconds, one clip and one frame in flight, four CPU threads, stop after the first clip error. Oversized input is rejected instead of silently resized or cropped.
- CPU/MPS agreement was checked on the same two development sources before the smoke test. The largest absolute frame-logit difference was 0.00000334; clip-score difference was 0.00000245. Both decisions matched. Predeclared tolerance was 0.001 absolute/relative. This establishes numerical agreement, not accuracy.

The smoke manifest contains the existing 35 development sources (23 author-labeled AI, 12 author-labeled real). It does not add independent holdout evidence. Calibration and holdout predictions were not read in this candidate experiment. No production classifier changes or paid model calls were made.

Artifacts:

- `scripts/eval-corvi.py`
- `eval/sources/corvi-source-verification.json`
- `eval/sources/corvi-safe-conversion-receipt.json`
- `eval/sources/corvi-cpu-contract-verification.json`
- `eval/sources/corvi-device-agreement-verification.json`
- `eval/runs/corvi-cpu-contract-v1.jsonl`
- `eval/runs/corvi-mps-contract-v1.jsonl`
- `eval/runs/corvi-development-v1.jsonl`
- Each raw run has a sibling `.receipt.json` and `.source/` snapshot.

Reproduce the smoke inference from the repository root with:

```sh
eval/.venv/bin/python scripts/eval-corvi.py --manifest eval/smoke-manifest.jsonl --output eval/runs/corvi-development-FRESH.jsonl --device mps
```

Generate the published-default report with:

```sh
node scripts/eval-score-report.mjs --input eval/runs/corvi-development-v1.jsonl --manifest eval/smoke-manifest.jsonl --threshold 0 --output eval/sources/corvi-development-report.json
```
