# Corpus identity and independence limits

Read-only audit, 2026-09-04. This audit used the existing manifest, cached ZIP directory, and downloader code. It made no network requests, downloaded no clips, changed no manifests, and inspected no calibration predictions.

## What was verified

The cached archive directory points to GenBuster-Bench revision `68e41ab55726013f1c7455980180114302196c23`, the same revision declared by `scripts/eval-download-corpus.py`. It records a 2,184,869,288-byte ZIP containing 3,150 MP4 members: 2,150 author-labeled AI and 1,000 author-labeled real.

The downloader constructs `groupId` as `genbuster:` plus the archive filename stem. **For all 230 existing originals, that stem exactly equals the SHA-256 of the downloaded video bytes.** Every video stem in the cached directory is a unique 64-character hexadecimal identifier. There are no additional same-stem members in other directories to exclude for the current 230 clips.

These facts establish registered **file-identity groups**. They do not establish independent camera sources, capture sessions, creators, prompts, reference images, scenes, or generation lineages. Different encodings or excerpts of the same underlying source can have different hashes and therefore different registered groups.

Originals and their two constructed derivatives retain the same registered group. The derivative's group uses its original ancestor's hash, not the derivative's own byte hash. Keeping those three copies together is necessary, but it addresses only relationships recorded by this pipeline. A “source-group bootstrap” in existing reports means resampling these registered groups; its interval cannot account for undocumented relationships between different hashes.

Use “original-file outcomes,” “registered-group split,” and “registered-group bootstrap” when describing this corpus. An original file is not a demonstrated independent source, and absence of registered-group crossing does not rule out related scenes, capture sessions, or prompt/reference families crossing splits. Grouped cross-validation prevents the known derivative leakage but cannot cure missing semantic lineage. Nominal Wilson intervals, paired bootstrap intervals, and paired-test p-values remain conditional on their independence assumptions; passing an arithmetic or resampling test does not verify those assumptions.

## Additional archive capacity

After excluding all 230 existing group IDs and archive members, including all same-stem aliases, the cached directory leaves:

| Author label | Existing originals | Remaining eligible members / registered groups |
| --- | ---: | ---: |
| AI | 115 | 2,035 |
| Real | 115 | 885 |
| Total | 230 | 2,920 |

All 23 AI generator buckets still have at least five unused members. The smallest remaining buckets are Gen-4.5, PixVerse v5, Sora 2, Veo 3.1, Wan 2.5, and Wan 2.6, with five each. Thus another 40 AI and 40 real clips is feasible by registered identity, including broad generator coverage. No real/AI same-stem overlap appears in the directory.

The largest MP4 in this pinned directory is 3,203,007 bytes. The current 20,000,000-byte clip cap excludes **none** of its MP4s. The benchmark's existing encoding and curation remain selection constraints, but this particular cap is not causing additional exclusions in this revision.

A metadata-only illustration allocating two clips to 17 AI buckets, one to the other six, and 40 real clips totals approximately 59.4 MB of compressed member data. Extra bucket quotas and member order in that illustration were chosen by fixed hashes, independent of model performance. This was a feasibility calculation, not a selected or frozen holdout; no selection manifest was saved.

## What the existing downloader cannot promise

`scripts/eval-download-corpus.py` currently selects the first hash-ranked members of each bucket. It has no exclusion-manifest option. Re-running it with a different output filename selects previously used clips again; increasing counts includes the old selection. Its `split_for` function also assigns development/calibration/holdout by hash, rather than making a requested additional cohort entirely held out.

Before any future acquisition, a separate frozen selection must:

- Exclude every current original member, file hash, registered group, and known parent/alias across all existing splits and controls. Do not exclude only the 75 consumed holdout rows.
- Declare a new selection salt, generator quotas, and eligibility/replacement rules before looking at candidate media or scores. Avoid quotas chosen around a detector's known successful generators.
- Give the new cohort its own immutable manifest and intended split. Preserve the original manifests and the untouched 30-clip calibration allocation.
- Confirm the cached directory's pinned URL and size, preserve the selected member metadata, and verify CRC, SHA-256, and media validity during acquisition. Compare downloaded hashes against the declared filename hashes and all prior hashes; do not silently trust an already-present local file.
- Audit perceptual similarity, excerpts, shared scenes/reference assets, and any available creator/prompt metadata against the prior corpus. Register discovered families together. Similarity checks can reduce contamination; they do not supply missing provenance or prove independence.
- Record all exclusions and replacements without looking at detector outcomes. Acquisition errors remain visible rather than becoming an opportunity to choose easier clips.

An 80-clip selection from this same archive can be an untouched **registered-identity-disjoint benchmark extension**. Calling it a proven source-disjoint or independently camera-authenticated holdout would exceed the available evidence. It also remains within the same public benchmark distribution and cannot establish separation from a detector's training data.

## A stronger new set with documented origins

Before promotion beyond an experimental assessment, obtain a separately collected, previously unexamined set with auditable origins:

- For real footage, retain original capture files, capture/session records, and consent or rights from the contributing owner. Use diverse devices, sessions, scenes, and contributors; register related excerpts, alternate encodings, and repeated sessions as families rather than independent files.
- For generated footage, retain generator/version/settings, prompts, reference assets, seeds or job IDs where available, original outputs, and generation receipts. Separate prompt/reference families and identify any shared real parent. Do not treat several variations from one prompt as independent sources.
- Define the target label by modality. A visual-only study does not validate synthetic speech or identity detection. Keep conventional CGI/VFX and partial-AI inserts as explicitly labeled challenge sets with multiple documented origins.
- Derive all quality variants from these preserved originals using frozen recipes. Add actual authorized platform round trips if the intended claim is about Instagram or another platform; synthetic recompression is not a platform test.
- Keep origins and labels away from the detector and whoever selects the final candidate. Freeze the evaluation protocol and one candidate before exposing results. If a real/generated pair shares a scene or reference family, cluster that relationship in the analysis instead of counting it twice as independent evidence.

The initial target of 40 AI and 40 real originals is useful for a bounded screen, but it is small. Even zero false positives among 40 independent real sources has a two-sided Wilson 95% upper bound of 8.8%. Forty originals with three encodings still provide 40 real source units, not 120. At least 59 independent real sources with zero errors would be needed merely for an exact one-sided 95% upper bound below 5%; category coverage and label quality remain separate requirements.

The [MNW assessment](./MNW_ASSESSMENT.md) does not supply this replacement: its social-case links add context, but it has only six likely-authentic video files, lacks camera and generated-family lineage, and restricts commercial use and training.

## Proposed gates for the next development study

These are prospective research gates, not measured achievements or a release authorization. Freeze them before examining the new study's outputs.

1. Restrict fitting and candidate comparison to the 125 development originals and their derivatives. Keep all frames and all three versions of a registered group in the same outer fold. Fit preprocessing statistics, quality offsets, hyperparameters, and thresholds inside training folds; inner grouped validation selects among a small, predeclared candidate list. Give each original group equal total weight. The untouched calibration set and consumed holdout must not participate in fitting.
2. Compare against a fair control: the same frozen preprocessing and scores with a global threshold fitted using the same training folds and false-positive target. Beating an obviously unsuitable default zero threshold does not demonstrate that quality normalization adds value.
3. Use only features available on an arbitrary incoming video. Do not use manifest transformation names, generator/source identity, filenames, or knowledge that a particular file is the original. Audit a quality-features-only baseline and resolution/encoding strata for dataset shortcuts. Scores remain uncalibrated unless probability calibration receives its own validation.
4. Before spending a new holdout, require out-of-fold AI recall of at least 70% in **each** original/mild/severe stratum, at most 5% observed FPR in each stratum and across real groups flagged in any variant, and at least a 15-percentage-point macro-recall gain over the fair control. Do not allow more than a five-point original-quality recall regression. Count abstentions and errors as AI recall failures; report them separately as well. At the current development denominators, 5% FPR permits at most three of 64 real groups.
5. If the development gate passes, freeze exactly one complete candidate and its control before new-set evaluation. For an 80-original research screen, a concrete success target is at least 30/40 AI detections in every quality stratum, zero of 40 real groups falsely flagged in any variant, and at least a 15-percentage-point gain over the control on the paired primary endpoint. Require the paired 95% interval to exclude no gain as well as meeting the material effect-size target. These thresholds justify further work; passing them on public author labels alone does not justify product promotion.

The proposed primary endpoint is mean per-group AI recall across the three quality versions, alongside the per-quality floors. A 15-point gain corresponds to 18 net additional correct AI detections among 120 versions; the statistical sample remains 40 paired AI groups. Bootstrap and compare paired registered groups, never independent derivative rows. A full-frame adapter, normalization rule, frame count, crop policy, aggregation method, and threshold are all candidate choices and must be included in the freeze. Repeated development experiments remain exploratory even when reported with cross-validation.
