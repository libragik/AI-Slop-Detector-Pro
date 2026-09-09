# SPAI adaptation audit and native-frame development check

**Correcting the preprocessing did not rescue repost detection.** The native-frame evaluator detected 8/23 original AI clips, 0/23 mildly transformed AI clips, and 0/23 severely transformed AI clips at the unchanged zero-logit threshold. There were no positive decisions on the twelve real clips in each stage or the three CGI excerpts. The three author-labeled-source insertion controls were also negative, with sampling/provenance qualifications below. The transformed-source results are inadequate for integration. No further threshold variants are being pursued from these observations.

## What differed from the official implementation

The earlier bounded adapter cropped each video frame to its central 256×256 pixels before calling SPAI. Its five 224-pixel crops then overlapped heavily within that small region. The official configuration retains native image resolution and uses patch attention, with five-crop fallback only when fewer than four grid patches are available. This was a material adaptation shortcut, not a faithful execution of the model's arbitrary-resolution path. RGB normalization to [0,1], safetensor loading, and the CPU FFT workaround were consistent with the intended computation; no sign or normalization error was found. See the pinned [official configuration](https://github.com/mever-team/spai/blob/8ff7b3b6779b4fcb43cf313471d9cb1c62d129a4/configs/spai.yaml) and [patch-attention implementation](https://github.com/mever-team/spai/blob/8ff7b3b6779b4fcb43cf313471d9cb1c62d129a4/spai/models/sid.py).

The paper motivates preserving spectral information when processing images, but its image benchmarks do not establish video or Instagram accuracy. Our mean of eight frame logits remains an image-to-video adaptation. [Primary paper](https://arxiv.org/html/2411.19417v2).

The new evaluator supplies the full native frame to the official code. **This does not mean every pixel is inspected:** the official 224-pixel grid drops incomplete right/bottom margins. A 1024×1024 frame produces sixteen patches covering the upper-left 896×896 pixels, or 76.5625% of the frame, leaving 128 pixels at the right and bottom uninspected. Smaller inputs can use the official corner/center fallback. Per-input grid coverage and margins are recorded separately in `sources/spai-native-development-summary.json`; the frozen evaluator was not altered after its run began.

## Bounded execution

`scripts/eval-spai-native.py` preserves old outputs and snapshots its entry point, helper, vendor modules, configuration, and source hashes before model loading. Executable model code runs from the snapshot; the existing SHA-pinned safetensors are read into memory. Settings: eight uniformly sampled frames, mean logits, official 224-pixel grid/attention, feature batch eight, one worker, four Torch CPU threads, MPS model and CPU FFT. No model API calls were made.

Default resource limits are 224–1024 pixels per dimension, at most 1,048,576 pixels per frame, sixty seconds, and 20 MB. Inputs outside the limits fail explicitly; there is no resize or crop fallback. All existing development originals/derivatives fit the spatial limits. A real oversized development fixture was rejected as intended.

The initial AI/real contract succeeded at 2.78 and 2.31 seconds per clip, with 1.42 GB maximum resident size and 3.75 GB peak physical footprint. All 111 smoke/social/control evaluations completed without errors. The 35-original run had 1.465 GB maximum resident size and 3.744 GB peak footprint. These are local session measurements, not production capacity guarantees.

## Matched development results

Each stage contains the same 23 AI and twelve real source clips. Derivatives are paired copies, not independent samples.

| Stage | Earlier center-crop hits | Native-frame hits | False positives, either adapter | Earlier AUROC | Native AUROC | Native median latency |
|---|---:|---:|---:|---:|---:|---:|
| Originals | 10/23 | 8/23 | 0/12 | 0.862 | 0.888 | 2.512 s |
| Mild simulated repost | 3/23 | 0/23 | 0/12 | 0.826 | 0.790 | 1.221 s |
| Severe simulated repost | 0/23 | 0/23 | 0/12 | 0.667 | 0.630 | 0.680 s |

Native AUROC bootstrap 95% intervals are 0.761–0.981, 0.592–0.933, and 0.429–0.839 respectively. They describe this small development sample, not a validation result. Zero observed false positives among twelve negatives leaves substantial uncertainty.

Native CGI scores were −11.116, −26.404 and −1.814. Mixed-control scores were −0.612, −0.798 and −0.899. Thus the zero threshold avoids these CGI false positives and leaves all three author-labeled-source insertion controls negative. These are whole-pipeline outputs, not isolated tests of recognizing inserted pixels. Read-only verification of the frozen SPAI decoder matched all 24 frame RGB hashes in the independent Corvi sampling audit: zero inserted-source frames were sampled in the 0.5-second and one-second controls, and two in the two-second control. The latter score averages those two with six surrounding frames. The parent has only a dataset-author whole-video AI label; text-to-video versus image-to-video mode and per-frame origin are unknown. The six controls represent two underlying scenarios. See [the provenance audit](./MIXED_CONTROL_PROVENANCE.md) and `sources/spai-mixed-sampling-verification.json`. This verification decoded frames only; it did not rerun a classifier.

## Threshold and normalization feasibility

The original question about recompression was partly threshold drift and partly loss of ranking. With the old cropped adapter, each transform's exploratory maximum-negative threshold yielded 11/23 original, 9/23 mild and 5/23 severe hits at zero observed false positives. With native input, corresponding counts are 11/23, 8/23 and 3/23. These are separately fitted development thresholds based on only twelve negatives, not a deployable rule. Full 125-original cropped data had AUROC 0.849 and 27/61 hits at three false positives among 64 reals after a development-selected threshold.

A rule selecting thresholds from known transformation labels would encode benchmark conditions unavailable for arbitrary uploads. Codec, resolution or bitrate alone also do not identify the transformations that removed the signal. Input normalization would create another spectral perturbation, requiring a new preregistered candidate and untouched data. The concrete native-frame correction was the highest-priority mechanistic test; it failed the simulated-repost detection check. AUROC alone does not justify promoting it, and further threshold variants are stopped.

Study declaration: `spai-fullframe-study.json`. Raw data: `runs/spai-native-smoke-v1.jsonl`, `runs/spai-native-social-v1.jsonl`, `runs/spai-native-controls-v1.jsonl`. Durable hashes, settings, per-stage results and coverage: `sources/spai-native-development-summary.json`. Earlier score-ranking audit: `sources/spai-development-ranking-audit.json`. No calibration or holdout data informed this candidate or its thresholds.
