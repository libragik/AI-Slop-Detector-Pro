# DINOv2 v1 post-result audit

The frozen candidate failed its development gate. This retained-artifact audit found **no demonstrated label inversion, split leakage through the example builder, mismatched exported checkpoint, or summary arithmetic bug explaining the failure**. It found a large gap between author-label archive performance and the documented camera/CGI controls. A particular learned pixel or semantic shortcut is a hypothesis, not established causation.

Evidence: [audit receipt](./runs/dinov2-temporal-post-result-audit-v1/receipt.json), SHA-256 `6b38734d99764f14a7b5e90cfc8b873354abced9a8b0ba7e4619fc6102d9af84`; [raw diagnostic results](./runs/dinov2-temporal-diagnostic-v1/results.jsonl), SHA-256 `9a1c6e8084d6b0829a97e804e2131d0d8fbb7455b3c12005b9d6389467ef20cf`.

## Integrity checks performed

- The existing strict cache validator accepted every one of the 6,912 feature rows: 2,304 actual acquired file identities, exact frozen allocation/order and three qualities each, actual media/NPZ/wrapper hashes, eight finite CLS vectors, correct source windows, and pinned backbone/runtime/strict-load receipts. No calibration files or predictions were read.
- All 768 internal-development output rows match their exact feature-cache rows after removing only stored logits and the explicit non-probability flag. All logits are finite. This verifies label/row attachment; it does not independently authenticate publisher labels or rerun the stored scores.
- Metadata-only reconstruction of all 20 epoch allocations gives 12,288 examples each, exactly 6,144 positive labels, with whole/AI-splice/real-splice counts 6,144/3,072/3,072. Every host and donor is in the training split; donor quality matches its host. Positive/negative splices for a given host and quality share the same start position. No internal-development row enters these examples. Inputs to the head are CLS vectors and their differences, not archive paths, labels, generator names, dimensions, or other metadata.
- Final exports exactly equal the restricted, strictly restored epoch-20 tensors for both heads. Every optimizer parameter has 3,840 updates, matching the fixed 20 × 192 batches. The training configuration and completed supervisor journal match. Temporal export SHA-256 is `208f53ee576ea7d1ce50a51d4f5ba1e60a73dfc9ec20fdd01e07a11b68db19b0`; reference export is `b954d6df1af5c2b38037f8eab50bd603463ee221a38e68ae5156a51b1927de83`.
- The published summary was reproduced from all 153 retained window plans, source identities, NPZ/receipt hashes, sampled native-index records, and finite raw logits. Stored `ai`/`complete` flags were not used to decide the outcome. There were no failed windows or missing cases.

This audit loaded existing arrays and checkpoint tensors and reconstructed metadata. It did **not** decode media, run a backbone/head forward pass, fit any model, change a threshold, or edit frozen sources. The original feature watchdog completed successfully in 6,854.57 seconds; the conditional resource extension was unnecessary.

## What the retained outcomes demonstrate

| Observed result | Temporal candidate | Appearance reference |
| --- | ---: | ---: |
| Internal archive rows agreeing with weak labels | 736/768 | 737/768 |
| Internal parents correct at all three qualities | 243/256 | 242/256 |
| Documented negative-control false flags | 42/45 | 42/45 |
| Old author-real diagnostic false flags | 6/36 | 4/36 |
| Known whole-AI / CGI / mixed cases correct | 2/3 | 2/3 |
| Old author-AI detected, original / mild / severe | 17/23, 16/23, 17/23 | 17/23, 17/23, 16/23 |

These are selected, dependent case counts. Internal rows share 256 original file identities across qualities; the 45 negative files link five known parents through edits. Neither set supports treating its rows as independent population trials.

1. **Strong archive separation did not transfer to the target negatives.** Temporal internal author-real median logits are −21.75, −20.96, and −19.21 across original/mild/severe, yet 9/128 author-real files are false flags in each condition. AI-folder medians are roughly +19.5 to +24.4. Final average training losses are 0.000202 temporal and 0.0000282 reference. Those small losses do not establish reliable real-video detection.
2. **Failure is present before editing and is not solely one spurious maximum.** Both heads flag all nine base camera cases, all three rolling-CGI qualities, and all 30 negative hardcut/blend cases. Only the three base pendulum qualities remain negative. Temporal scores are positive in 151/195 negative-control windows, with every window positive in 25/45 files. Maximum aggregation adds sensitivity to individual wrong windows, but cannot by itself explain this pervasive error.
3. **The rendered mixture's positive verdict does not establish insert sensitivity.** The AI contribution is at [3,5) seconds. Its maximum temporal logit, +34.830, occurs around [6,8), with zero sampled AI-insert frames. The fully inserted [3,5) window also scores positive (+12.441), but the unchanged CGI host already does: pure Sintel has maximum +35.141, above the whole generated Veo maximum +14.222. Reporting the mixture as a correct case is arithmetically valid; attributing that success to detection of its AI insert is unsupported.
4. **Temporal differences did not deliver the declared benefit.** Candidate and reference agree on 149/153 decisions, including all 45 documented negatives. Temporal has zero net additional positives among the 57 outside-training-folder quality cases and adds two negative false flags. This result does not justify selecting the reference after the fact either.

## Supported interpretation and remaining uncertainty

The demonstrated issue is failure to distinguish the intended generative-origin target on these controls, despite strong separation of the archive's labels. A semantic/content or acquisition-domain shortcut is consistent with the results, particularly because both heads behave similarly. The training cohort supplies publisher-labelled “real” examples, with no independently documented conventional-CGI or agency-camera negative allocation. It therefore does not establish the target distinctions represented by these controls.

The saved metadata does **not** demonstrate a simple direct codec, dimension, or frame-rate label shortcut: all 2,304 acquired originals are HEVC, 1024 × 1024, 24 fps, in both labels and both splits. Their encoded history, visual content, hidden common origins, and publisher label correctness are not independently known. The head cannot directly read this metadata, but preprocessing and appearance features can retain domain information. Identifying a specific causal cue would need a new preregistered intervention; this audit makes no such claim.

One auditability limitation remains: epoch receipts retain category counts and losses rather than the full per-example donor/start list suggested in the prospective review. Those allocations are deterministically reconstructible from the frozen source, seed, and cache, and their metadata digests are now retained in the audit receipt. This is not evidence that the model used the wrong labels or an explanation for its classification failures.

Keep the failed candidate frozen and out of the product. These results do not justify a threshold repair, extra epochs, substituting the reference, using calibration to rescue the result, or relabelling the documented negatives as AI. A future experiment would need better documented target supervision and a separately fixed evaluation design; the present outcomes remain consumed development evidence.
