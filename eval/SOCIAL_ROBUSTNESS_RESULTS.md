# Frozen social robustness check — evidence-2.8

Sixteen deterministically selected holdout source groups (8 AI, 8 real), each with an original, mild derivative and severe derivative. The 32 derivative inferences used an immutable 2.8 bundle. No classifier changes or outcome-based selection were made.

| Version | AI detected / 8 | AI explicit misses / 8 | AI abstentions / 8 | Real false positives / 8 | Real negatives / 8 | Real abstentions / 8 | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| original | 4 | 4 | 0 | 1 | 7 | 0 | 0 |
| mild | 3 | 5 | 0 | 0 | 8 | 0 | 0 |
| severe | 1 | 5 | 2 | 1 | 7 | 0 | 0 |

New derivative latency: median 18.00 s; nearest-rank p95 31.37 s; max 31.68 s.

All 32 requests returned assessment records. 1 internal inspection pass failed; that severe AI case returned Inconclusive. Its failed adjudication took 99 ms; the saved receipt does not expose the underlying cause or billed usage. All other inspection passes completed.

Media identities and provenance match the preselected manifest. All completed inference receipts use Gemini 3.7 and policy 2.8. The source and immutable adapter bundle remained unchanged during the run.

Originals were scored by offline replay of preserved 2.7 inference through the frozen 2.8 scorer. All original decisions and score fields were unchanged. The derivative run used the same model/configuration fingerprint.

| Original source ID | Label | Original | Mild | Severe |
|---|---|---|---|---|
| 9a742aea700afda5a925ec2f | ai | AI indicators | AI indicators | No clear AI indicators |
| 27b4cf51b8fd4064411a0f2c | ai | No clear AI indicators | No clear AI indicators | Inconclusive |
| 549f99f804eb55002750cf8b | ai | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 33d627aa653f9aeef1d7caaa | ai | No clear AI indicators | No clear AI indicators | Inconclusive |
| fc36d444b527e7dbf51b0ab7 | ai | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 2b1dc134d88cbcc180e33729 | ai | AI indicators | No clear AI indicators | No clear AI indicators |
| 50e49097c645cbcdf1d1ded2 | ai | AI indicators | AI indicators | AI indicators |
| 742610e2a546103d49cbfadd | ai | AI indicators | AI indicators | No clear AI indicators |
| 48c583eb5bedfceac8785a7d | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 8b4b0a11d44ea1d0205d7bb5 | real | No clear AI indicators | No clear AI indicators | AI indicators |
| 32d3f2110234f8a398d1a920 | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 0876ee5cc40b7f3906ce1986 | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| f68177620d510f7f9c98cc5d | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 6ec9b7bd788a325da777c629 | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |
| 9fc29db32cdb49266b629f20 | real | AI indicators | No clear AI indicators | No clear AI indicators |
| d934cb4a46b407423ce981b0 | real | No clear AI indicators | No clear AI indicators | No clear AI indicators |

- These are 16 preselected source groups with paired derivatives, not 32 independent new sources.
- Each stage has eight AI and eight real sources; this small sample has wide uncertainty.
- These are local transformations, not actual Instagram, TikTok, or X upload/download roundtrips.
- Severe transformation changes crop, frame rate, resolution, encoding and adds an overlay; changes cannot be attributed to compression alone.
- Single model runs per version confound transformation effects with model response variability; no causal attribution is claimed.
- Ground truth is the benchmark author label, not independently authenticated per-clip creator/camera provenance.
- Abstentions count as detection misses for AI recall; they are reported separately from explicit negative decisions.
- Original latency is the original inference duration, not offline replay duration. Concurrent experiment latency is not a deployment service-level guarantee.

Full raw predictions, immutable source bundle, plan and selected original records are saved under `runs/social-check-e28/`. A durable machine-readable paired summary is saved at `sources/social-check-paired-summary.json`. Reproduce this summary from the project root with `node eval/runs/social-check-e28/summarize-pairs.mjs` while the local run artifacts are available.
