# Existing social-transform frame-rate audit

**No frame-rate mismatch was found.** All 460 existing derivative files match the transformation recipe, manifest metadata, and encoded presentation cadence. The earlier 25-fps issue in the mixed-control construction does not affect these saved corpus derivatives. No media was regenerated and no classifier was run.

## Scope and method

The read-only audit covered every non-original row in `eval/transformed-manifest.jsonl`: 230 mild and 230 severe derivatives, comprising 250 development, 60 calibration, and 150 holdout derivative files. This was an artifact-metadata audit, without consulting classification outcomes.

For each file, the audit:

1. Recomputed SHA-256 and compared it with the existing manifest.
2. Read FFprobe's `r_frame_rate`, `avg_frame_rate`, dimensions, duration, time base, packet presentation timestamps, and frame count.
3. Sorted the encoded packet presentation timestamps and checked their **exact rational cadence**, rather than relying only on the frame-rate header.
4. Compared the observed dimensions, duration, and frame rate with the original manifest receipt.

All checks passed in 4.67 seconds. The machine-readable per-file receipts are in `eval/sources/transform-recipe-audit.json`.

## Actual saved artifacts

| Recipe | Files | Dimensions | Header and average FPS | Exact presentation-time step | Frames | Duration |
|---|---:|---|---:|---|---:|---:|
| `social_720p_crf28` | 230 | 720×720 | 24/1 | 1/24 s | 121 | 5.041667 s |
| `repost_360p_crf36_12fps_crop` | 230 | 360×360 | 12/1 | 1/12 s | 61 | 5.083333 s |

The roughly 0.041666-second longer severe duration is recorded correctly in the manifest and results. A 61-frame output at 12 fps spans 5.083333 seconds. It should not be described as having exactly the original duration.

## Script and evaluation linkage

The audited `scripts/eval-transform-corpus.py` uses a simple video filter:

- Mild: `scale='min(720,iw)':-2,fps=24`, H.264 CRF28.
- Severe: crop both dimensions to approximately 85%, scale width to at most 360, `fps=12`, and draw a dark top overlay, H.264 CRF36.

Both remove audio and metadata. The command does not explicitly pass output `-r` or `-fps_mode`; nevertheless, the **existing outputs are independently verified as 24-fps and 12-fps constant-cadence files**. This finding concerns these saved files, not a guarantee about every future FFmpeg version or different filter graph.

The file/hash/metadata audit includes:

- All **32 frozen social-check files**: 16 mild and 16 severe. Their saved `social-check-e28` analysis `mediaReceipt` values also match actual FPS, dimensions, duration, and SHA-256.
- All **70 development social variants**: 35 mild and 35 severe. The exact file hashes and media receipts match both CORVI runs and the legacy and corrected native-frame SPAI runs.
- The remaining existing derivative files across all splits. No prediction was recomputed.

Saved receipt linkage checked `eval/runs/social-check-e28/predictions.jsonl`, `corvi-social-mild-v1.jsonl`, `corvi-social-severe-v1.jsonl`, `spai-social-development-v1.jsonl`, and `spai-native-social-v1.jsonl`.

## Reporting implications

No frame-rate correction, relabeling, or regeneration of these frozen derivative results is necessary. The recorded 24-fps mild and 12-fps severe conditions are accurate.

Describe the dimensions as **720×720** and **360×360** for this corpus. The recipe limits width; it is not a universal 720p/360p landscape or maximum-edge resize for arbitrary aspect ratios. All audited source clips are square, so this distinction does not create a mismatch here.

Continue to describe the severe condition as a combined crop, downscale, frame-rate reduction, compression, and overlay transformation. It does not isolate compression alone, and neither condition is an actual social-platform upload/download roundtrip.

For future construction, explicit frame-rate/CFR arguments and post-encode frame-cadence assertions would make the intended output easier to enforce. Any recipe changes should use a new version and preserve frozen files. This audit made no script changes.

## Integrity references

- Existing transformed manifest SHA-256: `a9a7b07a9e8513b753fb879e9e41154454d789a34c9fcf6edb7755e615db7fa1`.
- Audited transformation script SHA-256: `cf398125c4ed85adf47067e6686d97dc6652ad627a5b732ca8fa12792f0e2696`.
- Per-file audit: `eval/sources/transform-recipe-audit.json`.
- Separate mixed-control qualification: [MIXED_CONTROL_PROVENANCE.md](MIXED_CONTROL_PROVENANCE.md).
