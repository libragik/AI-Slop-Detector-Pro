# Frozen holdout comparison

**The revised detector did not improve heldout detection.** It detected 23 of 39 author-labeled AI clips, compared with 26 for the preserved baseline, and added two false positives among 36 author-labeled real clips. The intended reliability improvement has not been established. Do not market these changes as an accuracy gain.

## Freeze and replay integrity

The 75 original holdout clips were selected before observing outcomes; both completed runs remained sealed during development. Baseline: preserved `e0188f6` prompt and one Gemini 3.7 Flash agentic call. Candidate: Gemini 3.7 Flash static sweep at 2 fps, separate agentic review, and conditional adjudication. Parent recorded the final freeze in `heldout-selection.json` at 2026-09-05 01:11:14 UTC. No threshold, prompt, model, sampling, or decision-policy tuning followed unsealing.

Before unsealing, an additional development control found that synthetic and documented human narration could both trigger audio-origin claims. Final policy `evidence-2.8` conservatively guards findings supported only by audio observations. Scorer SHA-256: `a17582e15f5e0de592c98d2267cc63cfa42d8204be8248070b4e65fbaa8fe3ef`. The final scorer was replayed over the frozen `evidence-2.7` raw observations, with a source snapshot and standalone bundle. **All 75 decisions and every score field were identical.** There were zero model requests in the replay. Original observations, pass status, usage, inference identity, and latency are preserved, as are both original run directories. This verifies scoring equivalence on these clips; it is not a second full-pipeline run.

## Original-file outcomes

Intervals below are Wilson 95% intervals. All 75 scans completed in both runs. The final confusion counts are 23 true positives, 15 explicit false negatives, 2 false positives, 34 true negatives, and 1 AI abstention. The baseline counts are 26, 13, 0, 36, and 0 respectively.

| Metric | Baseline | Final policy |
|---|---:|---:|
| AI recall | 26/39 = 66.7% (51.0–79.4%) | 23/39 = 59.0% (43.4–72.9%) |
| False-positive rate on author-labeled real | 0/36 = 0.0% (0.0–9.6%) | 2/36 = 5.6% (1.5–18.1%) |
| Explicit false-negative rate | 13/39 = 33.3% (20.6–49.0%) | 15/39 = 38.5% (24.9–54.1%) |
| Miss rate including abstention | 13/39 = 33.3% (20.6–49.0%) | 16/39 = 41.0% (27.1–56.6%) |
| AI fraction among negative decisions | 13/49 = 26.5% (16.2–40.3%) | 15/49 = 30.6% (19.5–44.5%) |
| Abstention | 0/75 = 0.0% (0.0–4.9%) | 1/75 = 1.3% (0.2–7.2%) |
| Decision coverage | 75/75 = 100.0% (95.1–100.0%) | 74/75 = 98.7% (92.8–99.8%) |
| AI precision | 26/26 = 100.0% (87.1–100.0%) | 23/25 = 92.0% (75.0–97.8%) |

End-to-end correct decisions: baseline 62/75 (82.7%, 95% 72.6–89.6%); final 57/75 (76.0%, 65.2–84.2%). Abstention counts as failure to make a correct decision here. Baseline labeled every decision “High” confidence, including all 13 false negatives. Final reports “Not calibrated” for all 75; removing unjustified confidence is an honesty improvement, not increased detection accuracy.

Paired AI outcomes: 20 detections retained, 10 misses retained, 3 misses corrected, 5 detections became negative, and 1 detection became inconclusive. Recall difference is −7.7 percentage points; source-group paired bootstrap 95% interval −23.1 to +7.7 points, exact two-sided McNemar p=0.508. This small test does not establish a population difference in either direction. It does establish that the measured candidate did not meet the intended improvement on the reserved sample.

## Execution and usage

Final recorded 75/75 completed sweeps, 75/75 completed reviews and 9/9 completed adjudications: zero failed passes and zero scan errors. One completed adjudication was marked invalid for corroboration, and one scan was inconclusive. Baseline had 75 successful single-call scans but does not preserve the newer per-pass trace; absent trace is not proof of zero internal tool failures. Earlier development model-pass failures must not be misreported as holdout failures.

End-to-end latency: baseline median 13.43 seconds, p95 17.35 seconds, maximum 22.38 seconds; final median 19.51 seconds, p95 36.02 seconds, maximum 44.04 seconds. Measurements include upload/local preparation and concurrent execution in this session; they are not a controlled production load test. Offline replay retains those original latencies.

Reported tokens using the detector’s mapping: baseline 494,857 input including tool-use tokens and 74,350 output including thought tokens; final 1,532,393 input and 277,300 output. Final used 159 model calls versus 75. No billing receipt was supplied, so dollar cost is unavailable. Extra passes and extra tokens did not demonstrate a detection gain.

## Per-generator counts

These are small descriptive buckets, not dependable generator-specific accuracy estimates. Denominators are only one to three holdout originals per represented generator.

| Generator | Clips | Baseline detected | Final detected | Final AI abstentions |
|---|---:|---:|---:|---:|
| easyanimate | 2 | 2 | 2 | 0 |
| gen4.5 | 1 | 1 | 1 | 0 |
| hailuo2.3 | 1 | 0 | 0 | 0 |
| hunyuanvideo | 3 | 1 | 0 | 0 |
| jimeng | 2 | 1 | 1 | 0 |
| kling | 2 | 1 | 1 | 0 |
| kling2.5_turbo | 2 | 1 | 0 | 0 |
| kling2.6 | 2 | 2 | 2 | 0 |
| ltxvideo | 3 | 3 | 3 | 0 |
| luma | 1 | 1 | 1 | 0 |
| pika | 2 | 2 | 2 | 0 |
| pixverse_v5 | 3 | 3 | 3 | 0 |
| seedance1.5_pro | 3 | 2 | 2 | 0 |
| seedance2.0 | 2 | 0 | 1 | 0 |
| sora | 1 | 1 | 0 | 0 |
| sora2 | 2 | 1 | 0 | 0 |
| veo3.1 | 1 | 0 | 0 | 0 |
| wan2.5 | 3 | 2 | 3 | 0 |
| wan2.6 | 2 | 1 | 1 | 0 |
| wanx | 1 | 1 | 0 | 1 |

CogVideoX, Gen-3, and Vidu have no holdout clips in this deterministic split. HunyuanVideo, Kling 2.5 Turbo, Sora/Sora 2 and Veo 3.1 illustrate remaining misses; zero hits in these tiny buckets do not estimate all videos from those models.

## Limits and reproducibility

Ground truth comes from the public GenBuster authors, not independent camera records or fresh private generator receipts. Exact duplicate hashes and registered-group crossing were checked. Those groups use original-file hashes and preserve known derivatives; missing creator/prompt/camera lineage prevents treating different groups as proven independent semantic sources. The reported Wilson and paired bootstrap intervals and paired-test p-value are conditional on their independence assumptions, not evidence that those assumptions hold. Models may have encountered this public benchmark. All 75 originals have no audio, so this test cannot validate audio detection. It contains no conventional CGI, mixed-modality controls, or controlled Instagram reuploads. Development controls and simulated social derivatives need separate reporting; copies are not independent samples. The user’s exact Instagram false negative remains unavailable.

The 52% AI prevalence is constructed; 15/49 AI among final negative decisions is a property of this corpus, not a deployed negative-result probability. Zero baseline false positives still permits an upper Wilson bound of 9.6%. Further substantive candidates require a new untouched evaluation set; this holdout is now consumed.

Durable compact results and source hashes: `sources/heldout-final-summary.json`. Complete local artifacts: `runs/heldout-final-comparison.json`, `runs/current-holdout-e28-replay/replay-equivalence.json`, and original baseline/current run directories. Reproduction commands:

```sh
node scripts/eval-replay-scorer.mjs --input eval/runs/current-holdout-e27 --output eval/runs/current-holdout-e28-replay-NEW --unseal
node scripts/eval-compare.mjs --before eval/runs/baseline-holdout-e0188f6 --after eval/runs/current-holdout-e28-replay-NEW --manifest eval/manifest.jsonl --split holdout --output eval/runs/heldout-final-comparison-NEW.json --unseal
```

Use the saved frozen scorer source when reproducing after later code changes. Replay refuses to overwrite an existing output directory.
