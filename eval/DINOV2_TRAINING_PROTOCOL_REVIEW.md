# DINOv2 compact training candidate: preregistration review

Prepared 2026-09-05 UTC, before this candidate's training or diagnostic predictions. This review used saved primary model/data documents and existing manifest metadata. It did not read calibration predictions, run a model, acquire media, or alter application code or earlier studies.

**A bounded weak-label training experiment is reasonable. Its completion must mean an honestly measured experiment, not a validated detector.** Freeze one complete training recipe and the diagnostic rules below before fitting. All 30 existing calibration originals and their 60 derivatives stay outside training, feature-statistic fitting, internal model selection and this diagnostic. A successful diagnostic permits planning independent evaluation; it does not permit a product accuracy claim.

This is a prospective review of the root's concrete candidate proposal. The final machine-readable training plan must pin this document together with exact acquisition rows, implementations, weights, dependency versions and resource limits. The augmentation quotas and reference-head suggestion below are proposed resolutions of open implementation choices; they must be accepted or replaced explicitly before the final freeze, never after diagnostic results.

## Training allocation and supervision

Use only the new GenBuster-200K-mini allocation for fitting: 2,048 training files and 256 internal-development files. The proposed deterministic selection ranks `SHA256("dinov2-temporal-v1|" + archiveMember)` within each publisher folder: the first 256 from each of `cogvideox`, `easyanimate`, `hunyuanvideo` and `ltxvideo` train, the next 32 from each go to internal development; real uses the first 1,024 and next 128. Thus both splits are 50% author-AI / 50% author-real, and each AI folder has equal weight. The acquisition plan owns exact eligibility, identities, ordering and byte verification.

These are publisher folder labels, not verified generator/version, camera, prompt, reference-asset or scene families. The [source audit](./TRAINING_SOURCE_AUDIT.md) found no per-clip lineage, CGI category, mixed intervals, or source sidecars. The full index has zero basename and `(CRC32, size)` matches with the saved benchmark index, but that does not exclude differently encoded/excerpted versions of the same source. Verify acquired SHA-256 values against all 230 known originals and every known control parent, and retain identity/exclusion records. Keep derivatives and any discovered duplicate/ancestry relations within one split. An unresolved cross-split source relationship must be disclosed; a related internal-development result is not independent validation. Do not silently replenish quarantined cases based on appearance, scores or successful decoding.

The existing 75 benchmark holdout originals are consumed and remain excluded from this experiment. The 35 old development originals below are diagnostic-only: no gradients, normalization/PCA fitting, donor sampling, checkpoint selection, threshold selection, augmentation design changes after results, or further training on their failures. The other 90 old development originals are also outside this bounded protocol. Existing CGI/camera/generated controls must not enter fitting simply because they expose the desired distinctions.

The 256 internal-development files may be measured once at the end of the fixed training schedule, including frozen quality variants if those variants are declared in the acquisition/training plan. They do not select a checkpoint, epoch count, threshold or a second candidate under this v1 recipe. Report them as author-label, file-identity-held internal diagnostics, not a clean source-disjoint test.

## Candidate recipe to freeze

The proposed backbone is the official DINOv2 ViT-S/14 without registers, frozen, returning the 384-dimensional CLS feature for each sampled frame. Preserve the pinned `facebook/dinov2-small` weight revision `ed25f3a31f01632728cabb09d1542f84ab7b0056` and its verified artifact hash once acquired. The [saved Meta model card](./sources/dinov2-training-backbone/meta-MODEL_CARD.md), from [pinned primary source](https://github.com/facebookresearch/dinov2/blob/7764ea0f912e53c92e82eb78a2a1631e92725fc8/MODEL_CARD.md), describes an image feature backbone, not a trained video-origin detector. Its success on general vision tasks does not establish AI-video detection.

Use the pinned official image preprocessing: RGB, bicubic resize of the short side to 256, center crop 224×224, 1/255 scaling, ImageNet mean `[0.485, 0.456, 0.406]` and standard deviation `[0.229, 0.224, 0.225]`. Pin library/version/interpolation behavior, not just these labels. This discards peripheral pixels and detail. The v1 claim is limited to sampled center crops; neither all-frame nor full-spatial coverage is established. Do not switch to full-frame resize after failures while calling it the same candidate.

For a window with eight CLS vectors `x[0..7]`, define `d[i] = abs(x[i+1] - x[i])` for `i < 7`, and `d[7] = 0`. The candidate head is `LayerNorm(768) → Linear(128) → GELU → Linear(1)` on concatenated `[x[i], d[i]]`. The window logit is the maximum of its eight outputs. Train with binary cross-entropy on that weak window/bag label. No frame or difference receives an independently verified AI-origin label. The final decision is positive for window logit ≥ 0; any positive window makes the video positive. A displayed sigmoid is an uncalibrated score, not a confidence estimate.

Use the root's proposed fixed AdamW schedule: learning rate 0.001, weight decay 0.0001, batch size 64, 20 epochs, seed 2026090503. Use the final epoch only. No diagnostic-driven checkpoint, seed, loss, head, augmentation, learning-rate, threshold or aggregation search is permitted in this candidate. Pin optimizer defaults, batch ordering, initial weights, dtype, deterministic settings and example weighting in the executable plan. If a technical error requires a correction, retain the failed run and its outputs, version the recipe, and disclose whether any diagnostics were already seen.

Train on one deterministic hash-selected two-second interval per new training parent, with three fixed versions: original, mild and severe using the declared existing simulation recipes. All quality versions belong to the same parent/split and have equal weight. Record the source interval, actual native sample indices and quality lineage rather than assuming identical frame indices after frame-rate conversion. Do not use archive paths, IDs, labels, generator names, transformation labels, dimensions or codec metadata as head inputs. Training-set-only feature statistics are required if any additional normalization is introduced.

### Resolve augmentation counts before fitting

A concrete way to interpret "50% feature splices" without accidental class imbalance is four equally weighted example categories, each with 1,024 examples per quality per epoch:

1. Original author-real feature windows.
2. Original author-AI feature windows.
3. Author-real hosts with a contiguous two-of-eight-frame author-AI donor feature splice, assigned a weak positive label.
4. Author-real hosts with the same splice geometry from another author-real donor, assigned a weak negative label.

This produces 4,096 examples per quality, half spliced and half positive. Across all three qualities that is 12,288 examples per epoch. Each real host appears once per splice category; each AI donor is used once in the positive category; real donors form a deterministic permutation without self-pairs. Match quality and use the same start index for each host's positive/negative splice. Fix start indices in `0..6` and all pairings from the training seed before any diagnostic results. Host and donor must both belong to the training split. The source plan may choose a different exact count, but must state it before training rather than leave "50%" ambiguous.

**Recompute every temporal difference after splicing.** Copying precomputed host/donor difference features through a boundary would produce a feature sequence inconsistent with its CLS vectors. Save host/donor IDs, splice indices, quality and seed in training receipts. A feature splice is an artificial representation-level augmentation; it is not a rendered video, a physical blend, or verified pixel-level temporal truth.

Real/real splices control the existence and position of abrupt boundaries, but positive splices uniquely cross the author-real/author-AI feature distributions. A detector could learn that distribution change rather than generated pixels. Whole-video AI assertions also do not imply that every selected window/frame is generated, particularly for possible image-to-video initial frames. These weaknesses must remain explicit even if training loss or internal accuracy looks strong.

### Cheap fixed reference head

Recommended before freeze: train one additional appearance-only reference on the same cached CLS vectors, same examples, labels, seed and schedule. Use the same head shape and supply zeros in place of all difference features, so preprocessing and aggregation remain identical. It requires no additional backbone extraction. Record the exact candidate/reference parameterization rather than claiming every effective capacity is identical.

The temporal head remains the nominated v1 candidate regardless of which head performs better. The reference is not a post-result fallback. It tests whether the added differences help under this experiment; a tie does not establish a temporal benefit, and a reference failure does not excuse a candidate failure. If this reference is omitted before fitting, do not later claim that observed performance demonstrates the value of temporal features rather than the backbone/classifier alone.

## Sampling and aggregation limits

The proposed inference contract is two-second windows with one-second stride plus an exact tail-aligned window; clips shorter than two seconds use their whole interval. Support requires at least 0.5 seconds and eight distinct decoded native frames in every planned window. Use all planned windows, including after the first positive. Operational limits are at most 120 seconds and 128 windows; these are resource limits, not validated accuracy scope.

Before the code freeze, specify interval endpoints and eight-frame selection exactly. Recommended: half-open windows; select available native frames by their actual PTS intervals, and take eight floor-linearly-spaced ordinals including first/last available frames. Tail alignment is deduplicated by exact chosen boundaries/indices. No black/previous-frame substitution, optical interpolation, or decoding failure hidden as a valid negative. Retain native dimensions, timestamps, decoded RGB hashes, tensor hashes, feature-cache/weight/recipe hashes and every per-window score. Record whether the rendered mixed control's sampled frames intersect `[3,5)` and how many; a missed interval is a sampling failure for the target, not a correct rejection of AI.

Any valid positive window makes a video positive, even if another window fails, but **any error/incomplete planned coverage fails the study's completion gate**. If no valid positive exists and coverage is incomplete, return abstain/error rather than negative. Distinguish technical failure from wrong classification and retain both raw information and stage status. Ordinary per-window failures do not erase subsequent valid windows; a genuine resource limit may stop execution with explicit unfinished IDs.

Max pooling avoids arithmetic dilution of one high score by low-scoring frames. It also lets one spurious frame/pair flag an entire clip. Training on one two-second bag and evaluating many bags creates a bag-size shift; this is not fixed by class balance or a sigmoid. The 153 diagnostic files are about five to eight seconds long and cannot validate the 120-second operational ceiling. Temporal head outputs describe a frame plus its successor; they are not verified frame-origin labels or reliable localization, especially near a cut.

## Exact existing diagnostic cohort and order

After training is fixed, run **all 153 distinct existing files** once with the nominated candidate, in this order. If the reference head is included, evaluate it from the same frozen features and retain all 153 paired outputs. Do not stop on the first false flag: the media are already present, the feature run is bounded, and completing the matrix exposes the pattern without paying for new generation. Stop only for genuine operational/resource failure, and record remaining cases as unrun. No new variants, threshold scans, or rescue training follow the first results.

| Order | Existing manifest, exact row order | Files | Expected target |
| --- | --- | ---: | --- |
| 1–45 | `eval/runs/aegis-shots-v1-negative-build/manifest.jsonl` | 45 | Negative: three documented agency camera parents, two conventional CGI parents, and their negative-only hard cuts/blends at all three qualities. |
| 46–48 | `eval/generated-origin-manifest.jsonl` | 3 | Existing order: whole receipt-backed Veo positive, normalized Sintel negative, rendered Sintel/Veo `[3,5)` mixture positive. |
| 49–153 | `eval/aegis-development-manifest.jsonl` | 105 | Thirty-five old development originals and their two paired delivery simulations; 23 author-AI and 12 author-real per quality. |

Exact input manifest SHA-256 values checked during this review:

- Negative 45: `87c02fc0b447bb0a5cc9f39ca18bda788c773db6f8e145b88bd863b54eb4dc4f`.
- Known-origin three: `122b79147249eab01d06e0fbd0b33955fc86eb9479d8df1697fd123c480b8b55`.
- Old development 105: `b2bf057723c542e38a7f796785292300a00b52ba9d0ae02ffe98eb87a3d80dfa`.
- Its 35-original reference: `a73696821312e5e286d9b96906331129a36ed912f281389e0eae43cfb2c8909f`.
- Full original allocation, used only to preserve split/identity boundaries: `cb49a2ea8e403656c67ce6741e61abe1e06207918a5cbecb963309d61e598f67`.

The three selected manifests contain 153 distinct IDs and SHA-256 values. This is a file count, not 153 independent sources. The known-origin three share Veo/Sintel ancestry; the negative 45 link all five parents through donor edits; the benchmark 105 collapse to 35 original-file groups. The 35 groups are file-hash identities, not established semantic-source independence. All of these are consumed development challenges. None becomes a fresh holdout for a new model because its model-specific predictions were previously unknown.

## Fixed advancement criteria

The candidate must meet **every** condition at the frozen zero-logit threshold. These are explicit research targets selected before this candidate's results, not population guarantees or learned operating points.

| Requirement | Minimum acceptable result |
| --- | --- |
| Technical completion | All 153 cases have complete planned coverage and finite outputs; no errors, missing cases or abstentions. Preserve actual decode/window counts. |
| Receipt-backed whole/mixed/CGI regression | 3/3 correct. Both the whole generated video and the actual two-second rendered mixture must be positive; Sintel must be negative. A feature-level splice result cannot substitute for the real mixture. |
| Documented camera and CGI false flags | 45/45 negative across every host, edit and quality. Any false positive fails this gate, even if the average is favorable. |
| Old author-real diagnostic | 36/36 negative: all 12 original-file groups must remain negative in all three qualities. State that their source labels are not independently camera-authenticated. |
| Outside-training-folder AI diagnostic | At least 16/19 positives in **each** of original, mild and severe conditions. Report the same 19 registered files paired across conditions. |
| Full old AI diagnostic | At least 19/23 positives in **each** condition, with all four shared-training-folder labels reported separately. Shared-folder success must not hide outside-folder failure. |

The 19 outside-training-folder labels are `gen3`, `gen4.5`, `hailuo2.3`, `jimeng`, `kling`, `kling2.5_turbo`, `kling2.6`, `luma`, `pika`, `pixverse_v5`, `seedance1.5_pro`, `seedance2.0`, `sora`, `sora2`, `veo3.1`, `vidu`, `wan2.5`, `wan2.6`, and `wanx`. Each has exactly one original in this diagnostic. They are outside the four small-head training folder labels, not proven unseen generators, independent families, or unseen to DINOv2 pretraining. Closely related versions are correlated. The thresholds require at least 84.2% of these 19 files and 82.6% of all 23 per condition; report integer numerators/denominators first.

If the appearance reference is included, report paired changed decisions and per-condition counts. Claiming a material temporal-feature benefit requires at least six net additional correct positives among the 57 outside-folder quality cases, the rendered mixture detected, and no increase in any negative file false flags relative to the reference. This is a descriptive effect-size rule, not an independent-sample significance test. Failure to show that difference limits the temporal hypothesis even if the absolute candidate gate passes. Do not swap in whichever model scored best after inspection.

An abstention/error does not improve recall or the false-flag result; it fails technical completion and remains visible. Do not lower the threshold after a missed insert or raise it after a CGI flag. A failed gate completes this experiment with a negative finding. Any later changed hypothesis is a new version with cumulative disclosure of these consumed diagnostics; it cannot rebrand a repeat as validation.

## Interpretation and next evidence

Report 153 case outcomes, all raw scores and windows, errors/unrun cases, inference/feature-cache receipts, internal-development results, per-quality counts, the 19 outside-folder labels, all known-origin regressions, and paired reference differences if present. Group views by complete known ancestry and keep each original's qualities together. Do not compute binomial/Wilson intervals by treating derivative rows as independent; this tiny selected set lacks the semantic lineage needed for a credible population interval. Accuracy, recall and false flags here mean observed author-label or documented-control counts only.

The data's balanced artificial prevalence does not provide a real-world negative predictive value. Training balance does not prove calibrated scores. Source-asserted whole-video labels, image-feature semantics, encoding/resolution shortcuts, feature-splice boundaries, center cropping and unsampled times are distinct remaining limitations. An internal split from the same public archive also cannot demonstrate unseen-generator or source-general behavior. The frozen backbone itself was trained on a broad image corpus whose exact overlap with these visual sources is not established here.

If every diagnostic gate passes, freeze this one candidate and obtain a separately preregistered set with documented camera capture/render/generation parents, full ancestry separation, new generator/prompt/reference families, actual authorized original/repost pairs, diverse short inserts and long negative clips. Compare a frozen control under the same resource/sampling rules. Preserve the current 30 calibration originals in this experiment; any later use is a separate once-only confirmation plan after all candidate choices are fixed, never a threshold-repair opportunity. Their 15 author-real originals cannot establish a low deployment false-positive rate.

A pass advances evidence collection, not product integration or a claim that the Instagram failure is solved. The experiment is already within the user's authorized bounded R&D; these are methodological freeze and reporting requirements, not a new account, purchase or user-permission flow.
