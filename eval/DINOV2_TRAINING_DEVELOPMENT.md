# DINOv2 temporal-head training experiment

**Completed and rejected. The trained candidate failed the declared detection gates.** All 6,912 feature rows, 20 fixed training epochs, and 153 diagnostic files completed. The failure was classification quality, with no missing diagnostic coverage or processing errors. The candidate remains outside the app; the product remains uncalibrated.

## Actual preparation and execution

- The [training-source audit](./TRAINING_SOURCE_AUDIT.md) verified a public training archive index. Its labels are publisher assertions, with no semantic source-family or explicit conventional-CGI/mixed-video annotations. Those limitations remain in force for this experiment.
- A [fixed training subset](./fixtures/dinov2-training-subset-v1.json) was frozen at `2026-09-05T04:53:42.482377+00:00`, before acquisition. SHA-256: `4fc4c7edc054c2184c0abef2b9f8618288a569913661750298f2a1493eec3621`. It contains 2,048 training files and 256 internal-development files, balanced by author label. The four generated folders receive equal weight. Exact selection, archived proposed/frozen copies and the executable hash are retained in [the freeze receipt](./runs/genbuster-training-subset-v1-freeze/receipt.json).
- The bounded acquisition completed all 2,304 selected files at `2026-09-05T05:20:10Z`. One transport timeout was retained and recovered using the predeclared single technical retry; successful files were rehashed, with no replacement or redownload. Cumulative reserved range bytes were 1,340,219,332, within the 1.5 GB cap. The [completion receipt](./runs/genbuster-training-subset-v1-acquisition/completion.json) binds the final manifest SHA-256 `c3ef8c466e3db704023ec9e2c4978adcac1292f2c443cdbc538d6d055b1c8180`. An [independent readback](./runs/genbuster-training-subset-v1-acquisition/independent-readback.json) rehashed all files and verified the exact frozen allocations, all 2,304 unique content hashes, and known-media exclusions. The fixed download caps and 20 offline contracts are recorded in [the downloader receipt](./runs/genbuster-training-subset-contract/receipt.json).
- The official [backbone](./DINOV2_TRAINING_BACKBONE.md) was acquired and all three asset hashes matched. The 88,249,960-byte safetensors SHA-256 is `ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1`. No pickle model or gated alternative was used. [Actual acquisition](./models/dinov2-small/acquisition.json).
- The actual synthetic CPU/MPS contract passed: all 223 tensors, totaling 22,056,576 FP32 elements, loaded strictly with identical values. Maximum feature difference was `2.574920654296875e-05`, and relative L2 difference was `2.687325965276331e-06`, below the predeclared `0.003` and `0.001` limits. These were two deterministic synthetic images, not detection examples. [Contract](./runs/dinov2-backbone-contract-v1/contract.json).
- A separate [synthetic throughput check](./runs/dinov2-synthetic-throughput-v1/receipt.json) processed one 1024×1024, 121-frame HEVC test pattern at all three qualities in 1.783 seconds after model loading. It supports retaining the two-hour extraction cap; real-video tail cost remains uncertain. This clip and its features are outside all training and diagnostic manifests.

## Fixed learning hypothesis

The nominated head receives eight 384-dimensional CLS vectors and their absolute adjacent differences. A small per-frame network produces logits, and the maximum supplies the window decision. A same-shape, identically initialized appearance control receives zeros for the difference channels. It remains a comparison, with no post-result swap of the nominated candidate.

Training uses one deterministic two-second window per new parent at original, mild and severe local compression conditions. Whole weak-label examples and representation-level splices have equal declared quotas; real/real splices supply negative boundary controls. Differences are recomputed after splicing. These are artificial feature sequences and weak labels, not verified pixel-origin supervision.

The schedule is fixed at 20 epochs of CPU FP32 AdamW. Internal-development results are read only after that final epoch, with no checkpoint, threshold, or seed selection. The zero-logit decision and all diagnostic conditions were fixed prospectively in [the protocol review](./DINOV2_TRAINING_PROTOCOL_REVIEW.md). The [machine plan](./fixtures/dinov2-temporal-protocol-v1.json) was frozen at `2026-09-05T05:25:09.790712+00:00`, SHA-256 `58812dcdde8f2ceaa7999f63a1aa81e477bf67c5049a17cd05fe5ba89050b41c`, before any training-media feature extraction or fitting. The [freeze receipt](./runs/dinov2-temporal-v1-freeze/receipt.json) preserves the proposed plan, final plan, six executable snapshots and preparation evidence.

The sequential runner completed extraction at `2026-09-05T07:19:29Z`, training at `07:19:52Z`, and all diagnostics at `07:23:58Z`. Its immutable [stage records](./runs/dinov2-temporal-experiment-v1/) retain each command, protocol identity, terminal status and completion-file hash. Extraction and training exited zero. Diagnostics exited one because the acceptance gates failed; there was no resource stop or cleanup error. The original two-hour extraction cap was sufficient, and no resource amendment or restart was used.

## Measured outcome

The [diagnostic summary](./runs/dinov2-temporal-diagnostic-v1/summary.json) derives decisions from retained finite per-window logits at the fixed zero threshold. All 153 files had complete coverage; there were zero failed windows, planning failures or undetermined decisions. Both heads failed every substantive detection gate.

| Fixed diagnostic | Required | Temporal candidate | Appearance control |
| --- | --- | --- | --- |
| Documented camera/CGI negatives | 45/45 correctly negative | 3/45; **42 false flags** | 3/45; **42 false flags** |
| Earlier author-labeled real videos, all qualities | 36/36 correctly negative | 30/36; 6 false flags | 32/36; 4 false flags |
| Receipt-backed whole AI, CGI, and mixed controls | 3/3 correct | 2/3 | 2/3 |
| All AI, original / mild / severe | At least 19/23 at each quality | 17/23, 16/23, 17/23 | 17/23, 17/23, 16/23 |
| AI outside the four training folders, original / mild / severe | At least 16/19 at each quality | 13/19, 12/19, 13/19 | 13/19, 13/19, 12/19 |

Both heads classified the whole AI and mixed controls as positive, but also falsely classified the CGI-only control as positive. The mixed clip's strongest temporal score was in its final CGI-only window, at 6–8 seconds (logit 34.8304, zero sampled inserted-AI frames). The 3–5 second window contained eight of eight sampled AI frames and scored 12.4408. The mixed video being positive therefore does not establish insert recognition or useful localization.

The temporal candidate produced two additional negative false flags relative to the appearance control and zero net additional detections across the 57 outside-folder AI quality cases. The predeclared temporal-benefit condition failed. The control does not replace the nominated candidate.

Same-archive internal-development classification was 736/768 correct for the temporal head and 737/768 for the control, over 256 parent videos and three dependent qualities. These figures were read only after the final epoch and did not select a checkpoint or threshold. Their contrast with the diagnostic failures demonstrates poor transfer to the challenge set; it does not identify the exact visual shortcut learned or establish independent generalization.

An [independent raw-result audit](./runs/dinov2-temporal-diagnostic-v1-independent-audit/REPORT.md) verified all 153 media identities, 741 retained windows, 5,928 sampled-frame occurrences, and exact epoch-20 exported tensors without new inference. Its independently recomputed temporal totals are 52 true positives, 19 false negatives, 49 false positives and 33 true negatives. The [training and failure audit](./DINOV2_POST_RESULT_AUDIT.md) also checked labels, splits, all 20 epoch allocations and cache bindings; it found no demonstrated implementation error explaining the failed classifications. Neither audit establishes the weak archive labels' authenticity or the hidden origin of its source families.

| Completed stage | Supervised wall time | Peak owned-process RSS | Evidence |
| --- | --- | --- | --- |
| Feature extraction | 6,854.6 s | 1,577,205,760 bytes | [Watchdog](./runs/dinov2-training-features-v1/watchdog-001.json), [6,912-row manifest](./runs/dinov2-training-features-v1/manifest.json) |
| Head training, including validation and export | 22.8 s | 603,652,096 bytes | [Watchdog](./runs/dinov2-temporal-training-v1/training-watchdog-001.json), [completion](./runs/dinov2-temporal-training-v1/complete.json) |
| All 153 diagnostic files | 245.6 s | 1,418,690,560 bytes | [Watchdog](./runs/dinov2-temporal-diagnostic-v1/watchdog.json), [raw results](./runs/dinov2-temporal-diagnostic-v1/results.jsonl) |

Final evidence SHA-256 values:

- Feature manifest: `1acded842b534aa9c45cd92fe32e790fae392fe96c0e2c003ae31cf1759c9147`.
- Temporal export: `208f53ee576ea7d1ce50a51d4f5ba1e60a73dfc9ec20fdd01e07a11b68db19b0`.
- Appearance-control export: `b954d6df1af5c2b38037f8eab50bd603463ee221a38e68ae5156a51b1927de83`.
- Diagnostic raw results: `9a1c6e8084d6b0829a97e804e2131d0d8fbb7455b3c12005b9d6389467ef20cf`.
- Diagnostic summary: `a9f53caeb637b3743069d7be8b19ed64e3a986e924b37310675278856807bfc8`.

No threshold, seed, epoch, reference set, or nominated-head change followed these results. The 30 calibration files and consumed 75-file holdout remain outside this experiment. Further candidate work requires a materially different hypothesis or a demonstrated implementation defect, followed by a separate frozen evaluation.

The [feature runtime](./DINOV2_FEATURE_RUNTIME.md) documents the center-crop and sampling limits. General DINOv2 features and temporal changes are not a newly established forensic signal. The experiment's potential value is a measured learned decision rule; its training loss, runtime success or internal accuracy cannot prove the Instagram failure is solved.

A [conditional fresh-source readiness review](./INDEPENDENT_VALIDATION_READINESS.md) identifies camera events captured after the training archive, newly authored CGI, and receipt-backed new generation for a possible later rejection study. Nothing in that review has been acquired or classified. Actual Instagram round trips and broader generator/camera coverage remain separate requirements; this preparation does not authorize advancing a failed candidate.
