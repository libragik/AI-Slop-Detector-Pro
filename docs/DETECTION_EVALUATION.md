# Detection evaluation — 2026-09-04

The software reliability changes are implemented. **The untouched comparison did not demonstrate improved AI-video detection.** The final candidate detected fewer AI clips and produced more false positives than the original on this sample. A passing build, successful Instagram retrieval, agreement between model calls, or removal of misleading confidence does not establish accuracy. Treat this as an experimental evidence-review tool, not a validated detector.

## Untouched original-video comparison

Both configurations were frozen before their 75 holdout outcomes were read. The original detector uses the preserved video-only rubric from commit `e0188f6`. Final inference used evidence-2.7; an audio-only abstention amendment was frozen as evidence-2.8 using separate development controls before unsealing. Replaying the final scorer over all 75 original inference outputs changed **zero decisions and zero score fields**. Prompts, models, and sampling were unchanged by that amendment.

| Outcome | Original detector | Final candidate |
|---|---:|---:|
| AI clips detected | 26 / 39 (66.7%) | 23 / 39 (59.0%) |
| AI clips given a negative result | 13 / 39 | 15 / 39 |
| AI clips inconclusive | 0 / 39 | 1 / 39 |
| Real clips falsely flagged | 0 / 36 | 2 / 36 (5.6%) |
| Real clips given a negative result | 36 / 36 | 34 / 36 |

The revised detector gained three AI detections and lost six on paired clips. The recall difference is −7.7 percentage points, with a paired registered-group bootstrap 95% interval of −23.1 to +7.7 points; exact McNemar p = 0.508. These results do not establish an improvement. Zero baseline false positives in 36 real clips also does not prove a zero population false-positive rate (nominal Wilson 95% upper bound 9.6%). The archive's registered groups are original file hashes, not verified independent creator/capture/prompt families; intervals and paired-test significance are conditional on independence that this corpus cannot establish. Final median latency increased from 13.4 to 19.5 seconds. All scans and all 159 recorded candidate passes completed, so failed requests do not explain the missed detections. Full uncertainty, paired changes, usage, and generator counts are in [HELDOUT_RESULTS.md](../eval/HELDOUT_RESULTS.md); the [source audit](../eval/CORPUS_SOURCE_LIMITS.md) defines the grouping limitation.

These are author-labeled public benchmark clips, not independently camera-authenticated recordings. The set contains no audio tracks. Results cannot establish audio detection, actual Instagram repost performance, all generator versions, or a deployment probability that a negative is genuine. The scorer was not tuned after unsealing.

## Frozen repost simulations

Sixteen holdout sources (eight AI and eight real) were selected by a fixed hash rule using metadata alone. Each had a mild and a severe derivative, yielding 32 new model scans. The same frozen detector was used for all copies.

| Version | AI detected / 8 | AI negative / 8 | AI inconclusive / 8 | Real false positives / 8 |
|---|---:|---:|---:|---:|
| Original | 4 | 4 | 0 | 1 |
| Mild simulation | 3 | 5 | 0 | 0 |
| Severe simulation | 1 | 5 | 2 | 1 |

All 32 requests returned assessments; one internal adjudication failed and the affected scan was Inconclusive. Median latency was 18.0 seconds, p95 31.4 seconds. These copies are paired observations from 16 sources, not 32 independent examples. Severe processing changes cropping, frame rate, and overlays as well as compression; single-run model variability is also present. The test demonstrates remaining weakness on these simulated reposts, not a causal compression estimate or an actual Instagram round trip. See [paired results](../eval/SOCIAL_ROBUSTNESS_RESULTS.md); complete raw records are under `eval/runs/social-check-e28/`.

## Development comparisons

These are the same 35 development originals: 23 dataset-author-labeled AI clips from 23 generator buckets and 12 author-labeled real clips. Ground-truth and split limitations are in [the evaluation guide](../eval/README.md). Abstentions count against AI recall. None of the following is a held-out result.

| Frozen run | AI detected / 23 | AI missed as negative | AI inconclusive | Real false positives / 12 | Real inconclusive |
|---|---:|---:|---:|---:|---:|
| Original detector, preserved video-only baseline | 16 | 7 | 0 | 0 | 0 |
| Early two-pass candidate, evidence-2.1 / Gemini 3.7 | 17 | 4 | 2 | 0 | 0 |
| evidence-2.4 / Gemini 3.8 | 14 | 1 | 8 | 1 | 5 |
| evidence-2.5 / Gemini 3.7 | 14 | 7 | 2 | 0 | 2 |
| evidence-2.5 / Gemini 3.7 / 8 fps sweep | 15 | 7 | 1 | 0 | 0 |

The original detector called all 35 results high confidence, including seven errors. That confidence was an arbitrary numerical rule. The revised product has no calibrated-probability or high-confidence claim. The early candidate's small apparent improvement was not statistically established; later runs did not reproduce a recall improvement. Do not cherry-pick the best development run as the product's accuracy.

Gemini 3.8 was not promoted: it was slower, had failed adjudication passes, produced more inconclusive results, and introduced a false positive in this sample. Dense 8 fps sampling detected one additional AI clip compared with the 2 fps sweep. That small development difference does not establish an improvement sufficient to justify the denser default; the selected configuration retains a 2 fps full-timeline sweep and 6 fps detailed adjudication windows when needed. The small denominators give broad uncertainty: zero observed false positives in 12 real clips still has a Wilson 95% upper false-positive bound of approximately 24.2%.

New evaluations snapshot source, build an immutable executable adapter, and save its hash. Workspace edits cannot change an in-progress frozen experiment. Provider-side model updates and nondeterminism remain possible. Scan completion and individual pass completion are different; a valid inconclusive report can include a failed inspection pass.

## Concrete operational and modality checks

The final local production app serves evidence-2.8 with fingerprint `e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f`. It passes 250 automated tests, lint, typecheck, and production build. The [verification record](./VERIFICATION.md) distinguishes final API/HTTP evidence from earlier actual browser checks and the unavailable final screenshot while the Mac was locked.

- Real NASA Instagram scan and fresh rescan succeeded. Editing the intake to a different YouTube URL did not change which source the existing report rescanned. New IDs, identical media hash, later timestamp, and `cacheHit:false` were verified in exported reports. Desktop and 375px mobile had no horizontal overflow or console errors.
- [Creator-documented Ray2 Ferrari Reel](https://www.instagram.com/reel/DGJFMzsSnfj/): HTTP 200 in 40.7 seconds, source disclosure recognized, raw visual analysis also classified likely AI-generated.
- [Official Luma emoji-prompt demo](https://www.instagram.com/reel/DBOo30tPJGk/): HTTP 200 in 38.0 seconds, AI indicators detected from visual evidence. These are creator/vendor-asserted origins, not independent camera authentication, and only two positive examples.
- An independently generated Gemini TTS control used known synthetic narration over author-labeled real footage. Evidence-2.7 returned AI indicators, but a matched negative control exposed a false positive: it also classified a documented 2006 human recording as synthetic. Both controls contain identical encoded video packets. The voice, words, and recording conditions differ, so this is a narrow counterexample, not an audio accuracy estimate. Agreement between multiple model calls did not protect against the shared error. Final audio-only handling abstains while retaining the observations. Offline replay of both prior reports returns Inconclusive. Fresh final uploads returned Inconclusive for TTS and No clear AI indicators for human narration; the changed raw human assessment also demonstrates model variability. The first simultaneous human upload was rejected as busy and succeeded on a sequential retry. Successful TTS recognition alone is not validation.
- Three 2010 Sintel CGI excerpts were correctly negative in the Gemini 3.8 control run. Three short inserts from the same author-labeled Wan2.6 source were inconclusive. Their inserted bytes are reproducible, but the exact frames lack a generation receipt and their generation mode/reference-image origin is unknown. These are exploratory insertion controls, not independently established per-frame synthetic ground truth. A later CORVI sampling audit found its eight-frame sampler skipped both shorter inserts entirely; that result cannot isolate frame recognition. The three original mixed controls were encoded at 25 fps despite the builder requesting a 24 fps filter; the CGI excerpts were 24 fps. Old media and results are preserved, and the builder now requires explicit output cadence and refuses to overwrite the frozen manifest. See [the provenance and sampling audit](../eval/MIXED_CONTROL_PROVENANCE.md). All 460 existing mild/severe corpus derivatives separately verified at their declared 24/12 fps, with matching hashes and timestamps; the mixed-builder issue did not affect those [repost experiments](../eval/TRANSFORM_RECIPE_AUDIT.md).

Fresh evidence-2.7 production scans also succeeded on YouTube, Instagram, TikTok, and X with matching canonical source identities and detector fingerprints. The two Instagram AI examples were repeated successfully. Full responses are saved under `eval/runs/live-e27/`; these transport checks do not authenticate the public NASA clips. In particular, the TikTok scan reported limited AI indicators whose truth was not established by this test.

The exact Instagram URL from the user's reported failure has not been supplied, so that incident has not been reproduced.

## First-party generation control

A separate development diagnostic generated exactly one eight-second Veo 3.1 clip from text, with no image, reference frame, or video input. The operation, exact request, original byte hash and deterministic edit recipe were retained before inspection. The detector received only opaque filenames and actual silent video bytes; it did not receive origin labels, prompts, generation receipts, or creator captions. The frozen evidence-2.8 detector was unchanged.

| Uploaded control | Known origin | Final outcome |
|---|---|---|
| Full generated coffee-pouring clip | Direct text-only generation receipt | No clear AI indicators — missed |
| Eight-second Sintel excerpt | Documented 2010 conventional CGI | No clear AI indicators |
| Same CGI with generated seconds 3–5 inserted | Documented parents and exact edit timeline | No clear AI indicators — missed |

All three actual production-route uploads returned HTTP 200 with six of six passes complete, fresh results, matching media hashes and matching detector fingerprints. Latencies were 21.5, 14.4 and 23.3 seconds. Both reviews of the mixed clip described the coffee insert but interpreted it as live-action footage; this specific miss cannot be explained solely by the insert never being observed. The whole generated clip was also missed. These results establish concrete failures on known AI-origin content, not a population accuracy estimate. They involve one generator output and one conventional-CGI source. No threshold or prompt was tuned to these outcomes. [Exact receipts and interpretation](../eval/GENERATED_ORIGIN_CONTROL.md).

## Specialists evaluated

No specialist was added to production merely because it is marketed as a detector.

- D3 temporal features: development AUROC 0.493; rejected for this distribution.
- SAFE image wavelets: AUROC 0.712, poor recall at low false-positive rates; rejected.
- SPAI: the earlier center-crop adapter had AUROC 0.849 over 125 development originals. An implementation audit found that its central 256-pixel crop did not faithfully use the official native-resolution path. The corrected adapter was actually run on all 35 smoke originals, 70 paired social derivatives and six controls. It detected 8/23 original AI clips and 0/23 AI clips at each transformed quality; severe AUROC was 0.630. Native input still has the official patch-grid margins, so it does not inspect every pixel. Correcting this adaptation did not establish repost robustness. [Adaptation audit](../eval/SPAI_ADAPTATION_AUDIT.md).
- CORVI: official source and weights were verified and safely loaded; CPU/MPS numerical agreement was checked. It ranked 35 original development clips well (AUROC 0.953), but detected only 1/23 AI clips at its published threshold. Mild and severe derivatives yielded 0/23 detections each, with AUROC falling to 0.823 and 0.656. A seemingly strong original-video ranking did not survive the delivery changes sufficiently to justify integration or threshold fitting. Its mixed-control ordering also reflects sparse sampling, as qualified above. [Measured results](../eval/CORVI_DEVELOPMENT.md).
- Hive's official public demo processed five actual uploaded controls. It missed both selected hard AI clips (Kling 2.5 Turbo and HunyuanVideo), while correctly rejecting two real controls and one CGI control. Preloaded demo results were not counted. Five tests are insufficient for a population estimate and gave no reason to integrate it for the observed misses.
- BusterX++: current official weights require a contact-sharing access gate; no standard Hugging Face token is configured. No access terms were accepted. Its documented training/evaluation distinction is useful, but exact checkpoint-to-clip overlap and a Mac port remain unverified. Published results alone would not establish reliable performance here.
- NVIDIA's demo requires explicit trial terms and recording input/output; these were not accepted. Local NIM requires supported Linux/NVIDIA hardware. No credentials were configured.
- STALL: the video-specific method's official implementation/parameters have noncommercial terms and require manually gated DINOv3 weights; no inference was performed. [Access assessment](../eval/STALL_ASSESSMENT.md).
- AEGIS: the published video model loaded completely from verified safetensors and processed all three known-origin controls on CPU without errors. It detected the whole generated clip and left conventional CGI negative, but missed the two-second generated insert even though eight of sixteen selected frames contained it. This failed the predeclared gate, so the 105-file quality comparison was not run and the model was not integrated. No cutoff or branch was selected from these outputs. [Measured controls](../eval/AEGIS_DEVELOPMENT.md).
- A separate, prospectively frozen AEGIS shot/window candidate then ran on 45 fresh camera/CGI negative cases. It falsely flagged 19, including unedited conventional CGI and camera-origin timelapse footage. All 102 windows completed with no processing errors or abstentions. This failed the negative gate, so its 60 planned AI-positive cases were not acquired or run. The new candidate was rejected without threshold tuning or product integration. These dependent source/edit/quality counts are a rejection screen, not population accuracy. [Complete shot-study results](../eval/AEGIS_SHOT_DEVELOPMENT.md).

- Sightengine's public video demo was tested with a frozen five-control plan. The first selection immediately showed a free-limit/sign-up gate; zero predictions completed and the remaining four files were not submitted. This is an access limitation, not accuracy evidence. Its video API requires suitable account access. [Browser evidence](../eval/SIGHTENGINE_ACCESS.md).
- NSG-VD has public weights but unresolved released-code/paper preprocessing differences, a broken CPU fallback, a required separate real-reference bank, and a commercially restricted dependency. No inference was performed. [Access and runtime audit](../eval/NEXT_DETECTOR_ACCESS_CHECK.md).

Training a compact temporal model is technically plausible on the local Mac, but current data does not adequately supervise conventional CGI, short generated intervals, semantic source independence, and actual platform delivery. A [training feasibility assessment](../eval/TRAINING_FEASIBILITY.md) records the available source counts and public training-release leads. This is research preparation; no trained replacement or fresh validation result exists.

Detailed sources, licenses, exact scores, safe checkpoint-loading records, and reproduction commands are preserved under `eval/`. Raw media, model weights, and run outputs are ignored by Git.

## Handoff and next decision

The heldout selection, pre-unseal audio amendment, and hashes are recorded in `eval/heldout-selection.json`. Original inference outputs and the final scorer replay are retained separately. Final software, real uploads, four platform paths, and HTTP/asset readback have been verified with their version boundaries documented. The app is running locally; no production deployment or accuracy claim was made.

The intended detection improvement remains unmet. Further prompt changes should be treated as new experiments, not repairs known to solve the problem. The current holdout is consumed. A substantive next candidate needs a new untouched, better-grounded set with actual platform-served copies, a declared recall/false-positive operating target, and either a specialist that demonstrates robustness or a properly trained detector. None of the specialists evaluated here justified production integration. More files from the same public archive would be file-disjoint, not proven independent sources. Audio-only decisions remain disabled pending a separately validated audio detector. The exact reported Instagram URL and original report are still needed to reproduce that incident. The [research decision](../eval/RESEARCH_DECISION.md) records the rejected candidates and the specific access/data conditions that would justify another experiment.
