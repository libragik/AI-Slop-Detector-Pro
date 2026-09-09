# MNW video corpus assessment

Checked 2026-09-04. **MNW cannot supply the proposed 40-generated/40-real holdout with documented origins.** It is a potentially useful supplementary social-media challenge collection, subject to its restrictive usage notice. No clips or model weights were downloaded, no detector was run, and no account or contact details were submitted.

This note preserves the completed read-only inspection of official repository commit [`df66c459dd8b043cc7a8aeab30de8f8126710c7f`](https://github.com/microsoft/MNW/tree/df66c459dd8b043cc7a8aeab30de8f8126710c7f), advertised as the spring April 2026 update. It uses repository trees, documentation, the 519,902-byte browser manifest, two Git LFS pointer records, and anonymous HTTP HEAD responses. The root recursive tree was truncated, so the video subtrees were separately fetched and verified untruncated. The counts below come from those complete subtrees, not the benchmark's aggregate publicity figures.

## Available video inventory

| Collection | Verified files | What the label establishes |
| --- | ---: | --- |
| AI Video | 200 MP4s: 20 generator folders, 10 each | Authors' generated-video category |
| Deepfake Video | 120 MP4s: 12 generator folders, 10 each | Authors' manipulation/impersonation category, not real controls |
| In-the-wild video, likely authentic | 6 MP4s | Expert assessment found no evidence of AI manipulation |
| In-the-wild video, likely manipulated | 17 MP4s | Expert assessment found evidence of likely AI manipulation |
| In-the-wild video, inconsistent | 5 MP4s | Expert analysis was inconclusive; not usable as binary truth |

The video categories total 348 files. One additional MP4 is filed under `AI_media_in_the_wild/Audio/inconsistent`; it is not counted as a video ground-truth sample here. Sources: [AI video inventory](https://github.com/microsoft/MNW/tree/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_Video), [deepfake video inventory](https://github.com/microsoft/MNW/tree/df66c459dd8b043cc7a8aeab30de8f8126710c7f/Deepfake_Video), [in-the-wild inventory](https://github.com/microsoft/MNW/tree/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_media_in_the_wild).

Forty generated clips could be selected as two per generator. This would establish generator coverage by the repository labels, not 40 independent prompt or reference families. The collection cannot provide 40 real video files: only six are labeled likely authentic, and none is documented as independently camera-authenticated. Two of those six, `A096_1` and `A096_2`, share a case prefix. Conservatively retain that relationship until investigated; their distinct social URLs do not establish independence. [Original video cases](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_media_in_the_wild/Video/readme.md), [March 2026 video cases](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_media_in_the_wild/update%20March%202026/video/readme.md).

## Provenance and grouping limits

The authors describe generating the synthetic collection themselves. Their earlier July 2025 paper explains the distinction between wholly generated video frames and manipulated identity videos, and states that audio was removed from those video samples. That paper predates the current update; it is not verification of every current file's audio track or generation history. [Authors' paper, sections 2.3 and 2.3.3](https://bpb-us-e1.wpmucdn.com/sites.northwestern.edu/dist/4/6420/files/2025/07/MNW_benchmark.pdf).

The current AI and deepfake video trees contain MP4 files plus a generator-list README. There are no per-video prompt, reference-asset, creator, seed, generation-job, capture-session, or transformation-lineage sidecars in those trees. The browser manifest's per-file records contain only `path`, `filename`, and `type`. Its generator records add names, company, year, category, counts, and occasional descriptions/model links. Those are useful categories, not source-family identifiers or generation receipts. [Pinned browser manifest](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/docs/manifest.json).

The in-the-wild labels explicitly represent expert judgments, including uncertainty. In particular, lack of discovered manipulation is the stated basis for the likely-authentic category. It is not an original-camera record. The README describes voluntary submissions to WITNESS' Deepfakes Rapid Response Force, predominantly public social content. [Label definitions and collection process](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_media_in_the_wild/README.md).

Compared with GenBuster's file-hash-derived groups, MNW supplies more contextual traceability for its social cases and a first-party account of creating its generated collection. It still does not establish semantic independence among generated videos, camera provenance for real footage, cross-corpus source-family separation, or separation from a detector's training data. No cross-corpus byte or perceptual overlap audit was performed.

## Social-media relevance

The in-the-wild video READMEs supply live and archived social URLs, including an Instagram source for `M126`. These are actual submitted social cases. The inspected repository does not expose paired pre-upload and platform-downloaded versions of the generated video collection, platform processing receipts, or controlled video transformation recipes. It therefore supports a social-case challenge, not a paired measurement of accuracy lost to Instagram processing. [March source links](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/AI_media_in_the_wild/update%20March%202026/video/readme.md).

## Access and usage restrictions

Public anonymous access is technically feasible. MP4s use Git LFS, and pointer records expose expected SHA-256 and byte length. Two HEAD-only checks against commit-pinned `media.githubusercontent.com/media/microsoft/MNW/` URLs returned HTTP 200 with matching size, hash ETag, and byte-range support:

| File | Declared bytes | Expected SHA-256 |
| --- | ---: | --- |
| `AI_Video/Adobe_Firefly_video/Adobe_Firefly_video_01.mp4` | 1,945,481 | `980948965fd113cad7eb808a0927818025719b75c6c9282bf3c745eb7dd3a0ee` |
| `AI_media_in_the_wild/Video/likely_authentic/A022.mp4` | 26,344,145 | `119ca1f2301bfc40d06de60515da9cb4704b908f079d7691317907030ce16378` |

No response body containing media was requested. These checks establish metadata and endpoint availability at audit time; they do not establish full-download integrity, duration, decoding success, or future availability. The 26.3 MB real example also exceeds the current GenBuster downloader's 20 MB cap, so that acquisition policy cannot simply be reused. [LFS configuration](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/.gitattributes), [generated pointer blob](https://api.github.com/repos/microsoft/MNW/git/blobs/1a2865ef3087f67e3106e95095aadacf27186521), [real pointer blob](https://api.github.com/repos/microsoft/MNW/git/blobs/47bfcde3bfe6d4ed0801802b527f8e0e8ec4def1).

The official README limits use to evaluation and prohibits training and commercial purposes. It also recommends against using the dataset to evaluate commercial detection tools for purchasing decisions. No separate permissive dataset license was found in the complete root tree. Public availability is not permission for commercial product evaluation or threshold fitting; the restriction must be resolved before considering such use. No permission request or contact submission was made. [Pinned usage notice](https://github.com/microsoft/MNW/blob/df66c459dd8b043cc7a8aeab30de8f8126710c7f/README.md).

## Decision

Do not acquire MNW as the replacement balanced holdout. It lacks the required real count and origin evidence, has no paired platform-video transformations, and carries usage restrictions relevant to this product. Where its terms permit, it could complement a separate evaluation as a small, explicitly uncertain social-case challenge. The decisive new set still needs documented capture and generation records, registered family relationships, and an evaluation protocol frozen before results are exposed. See [CORPUS_SOURCE_LIMITS.md](./CORPUS_SOURCE_LIMITS.md).
