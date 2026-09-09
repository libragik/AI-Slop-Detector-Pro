# GenBuster-200K-mini source audit

Checked 2026-09-05 UTC. **The release provides 9,800 binary-labeled training videos, but the inspected index and official reader do not supply the source-family records or CGI/mixed supervision needed for a trustworthy product-training split.** This is an archive-metadata audit, not a media-origin verification or a training experiment.

The [dataset revision](https://huggingface.co/datasets/l8cv/GenBuster-200K-mini/tree/58af00f022d8272f42de3be912e9a905bf6087d2) is fixed to `58af00f022d8272f42de3be912e9a905bf6087d2`. Existing publisher metadata identifies a 5,458,325,142-byte ZIP with LFS SHA-256 `332a012eac1c0207378714d639391f991a9a200108d9c3c8f9f493a1e4c81c20`; the archive was not downloaded and that full-file hash was not independently verified. The dataset card declares MIT, while its 24-byte README provides no per-clip provenance. These are publisher declarations, not a rights audit of each video. [Prior metadata receipt](./sources/training-feasibility/access-receipt.json).

## Exact index census

Ordinary anonymous HTTP Range requests returned 206 with the expected Content-Range. Four reads obtained only the 22-byte end record, 20-byte ZIP64 locator, 56-byte ZIP64 end record, and 1,665,339-byte central directory: **1,665,437 bytes total**, below the 2 MiB limit. No media member or local media header was opened. The directory was parsed twice independently, by a strict struct parser and Python's standard ZIP reader; all names, sizes, CRC32 values and offsets agreed.

| Publisher folder | MP4 entries |
| --- | ---: |
| `train/fake/cogvideox` | 1,507 |
| `train/fake/easyanimate` | 1,954 |
| `train/fake/hunyuanvideo` | 502 |
| `train/fake/ltxvideo` | 1,037 |
| `train/real` | 4,800 |
| **Total** | **9,800** |

There are 5,000 fake-labeled and 4,800 real-labeled entries. The only other seven entries are directories. There are no JSON/CSV/text sidecars, no separate validation/test directories, and no explicit CGI or mixed-video category. All 9,800 basenames are unique 64-character hexadecimal strings. Their appearance alone does not prove they are SHA-256 hashes, and no media bytes were read to verify that interpretation. The index declares 5,477,893,994 uncompressed media bytes; this is not a decode-validation result.

[Complete entry census](./sources/training-source-audit/zip-entry-census.json), [range receipt](./sources/training-source-audit/range-access-receipt.json), [initial access and end record](./sources/training-source-audit/initial-access-receipt.json). Central-directory SHA-256: `8ec46b65298ca386992636a88784a4224fc6db9868d4ca62457dd94774b47d71`.

## What the official reader preserves

The audited [BusterX code revision](https://github.com/l8cv/BusterX/tree/734e280c894caca5eafa79e40aa08e2be1b30a85) is `734e280c894caca5eafa79e40aa08e2be1b30a85`. Its [GenBuster200K class](https://github.com/l8cv/BusterX/blob/734e280c894caca5eafa79e40aa08e2be1b30a85/busterx/datasetpp/genbuster_200k.py) uses `RealFakeFlatMixin`. Although that mixin's comment says flat files, the base listing is recursive: nested generator folders are found. It assigns `A` to every file beneath `real` and `B` beneath `fake`. It returns the path and binary solution, without preserving the generator folder as an explicit subcategory or reading lineage annotations. [Mixin](https://github.com/l8cv/BusterX/blob/734e280c894caca5eafa79e40aa08e2be1b30a85/busterx/datasetpp/mixin.py), [base reader](https://github.com/l8cv/BusterX/blob/734e280c894caca5eafa79e40aa08e2be1b30a85/busterx/datasetpp/base.py).

The [Makefile](https://github.com/l8cv/BusterX/blob/734e280c894caca5eafa79e40aa08e2be1b30a85/Makefile) points this builder at the archive's `train` directory and offers whole-video or 2-fps image inputs. Generated JSONL contains an assessment instruction and media paths plus the binary solution. That instruction is **not** the original video-generation prompt. No camera-session, creator, reference-image, prompt-family, render-project or ancestry grouping is created, and this builder performs no family-aware train/validation/test split. The current default `build_all_datasets` comments out the mini builders; `train_dapo.sh` targets the separate Unified image/video JSONLs. Therefore this code's current default training command must not be presented as a completed mini-dataset recipe. Exact source bodies and hashes are retained in the [reader-source receipt](./sources/training-source-audit/reader-source-receipt.json).

## Overlap and remaining origin limits

A local metadata-only comparison against all **3,150** MP4 entries in the already saved GenBuster-Bench index at revision `68e41ab55726013f1c7455980180114302196c23` found **zero matching basenames and zero matching `(CRC32, uncompressed size)` pairs**. All 230 registered benchmark originals also have zero basename matches. No predictions were read. An older local training index has the same 9,800-path set; the new audit adds a pinned revision and retained raw range evidence. [Exact comparisons](./sources/training-source-audit/census-overlap-summary.json).

This screens for some file-identity overlap only. CRC32 is not a cryptographic content proof; names can be reassigned, and re-encoding or editing changes bytes while retaining the same scene or reference asset. Zero metadata matches cannot establish cross-corpus semantic independence. The index cannot prove successful decoding, labels, full-content hashes, source rights, camera authenticity, generator versions, T2V versus I2V origin, short generated intervals, or independence of underlying families. It also cannot rule out unexamined metadata embedded inside MP4s. No externally linked per-clip source mapping was established by the inspected release and reader.

**Do not start product training on the assumption that this closes the data gate.** It is a possible source of author-labeled full-video examples after a separately recorded, bounded acquisition/verification step. A defensible training allocation still needs independently documented camera and conventional-CGI families, generation/reference lineage, verified temporal or spatial mixtures, and prospective family splits. Scene-similarity auditing of acquired media could flag suspected duplication but cannot manufacture missing source records. Keep the consumed benchmark as development evidence and preserve the untouched calibration allocation.

No full acquisition, alternate session, model download, inference, training, account action, terms acceptance, application edit or frozen-study change occurred. Network reads stopped after the bounded directory and official code audit.
