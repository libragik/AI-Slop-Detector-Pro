# Mixed-control provenance and sampling qualification

The three existing `mixed` development controls establish reproducible insertion of bytes from an **author-labeled Wan2.6 benchmark video**. They do not independently establish AI generation of each inserted frame. CORVI's eight-frame sampler skipped both shorter inserts entirely; only the two-second control supplied any inserted-source frames. The recorded scores remain valid pipeline outputs, but they do not isolate a frame classifier's ability to recognize every insert.

## Exact source and construction

`scripts/build-controls.py:40–57` selects the first `real` smoke row and first row whose generator field is `wan2.6`. It takes the **opening** 0.5, 1, or 2 seconds of the latter (`trim=duration=...`, with no later start offset), places that segment after five seconds of the real-labeled source, then appends another five seconds of that source. Frames are normalized to 24 fps, scaled to fit 640×360, padded, concatenated, and encoded H.264 CRF20 without audio. This is a deterministic local construction, not an independent generation receipt.

| Role | Dataset ID | SHA-256 / original archive basename |
|---|---|---|
| Author-labeled generated parent | `2129c615634c154928e05d23` | `729465f025efa399b37022cf61aa15bcec7aed112b7ec50cbfe3ab88c5b6877c` |
| Author-labeled real parent | `2c9ef7e6f3765b6365c25022` | `ea12d8848544c35ba515f0544d6aed303072d6dcee2d88ca54d9142db4e37eb7` |

The generated-parent archive path is `GenBuster-Bench/wild/fake/wan2.6/729465f025efa399b37022cf61aa15bcec7aed112b7ec50cbfe3ab88c5b6877c.mp4`. Its 566,379-byte local file matches that SHA-256 and the pinned archive index entry. It is 5.041667 seconds, 1024×1024, 24 fps, without audio. The real-labeled parent comes from `GenBuster-Bench/id/real/` and is also 5.041667 seconds at 1024×1024/24 fps.

The recorded download is pinned to GenBuster-Bench revision `68e41ab55726013f1c7455980180114302196c23`. The [authors' BusterX repository](https://github.com/l8cv/BusterX) identifies GenBuster-Bench as a video evaluation benchmark. The local manifest explicitly states `dataset-author-label` and says per-clip creator/camera authentication is unavailable. The saved archive index has media/directory entries, not a sidecar identifying this clip's prompt, generation job, reference image, or per-frame provenance.

**Unknown:** the exact Wan2.6 service/model variant, text-to-video versus image-to-video mode, prompt, seed, input/reference image, generation response, and whether any opening frame preserves a nongenerated input. The folder label supports the author's whole-video classification; it cannot fill these gaps.

## Opening-frame inspection

Read-only frame extraction and local visual inspection covered parent indices 0, 12, 24, 48, and 96: times 0, 0.5, 1, 2, and 4 seconds. The scene shows a woman working with fabric. The first half-second has relatively little visible motion; by one and two seconds, the hand/arm position changes substantially.

Decoded RGB hashes do **not** show an exact repeat of frame zero at any of the other 120 frames. Mean absolute channel difference from frame zero is 5.008/255 at 0.5 s, 9.827/255 at 1 s, and 20.581/255 at 2 s. These measurements establish pixel changes, not synthetic origin; encoding can also cause small differences. There is no basis to call the whole opening two seconds an exact static hold. There is also no basis to rule out reference-image conditioning or inherited image content. Neither conclusion can be settled from appearance alone.

## What CORVI actually sampled

The saved CORVI adapter decodes eight frames with `fps=8/duration`. FFmpeg's output-grid timestamps do not identify the source-frame timestamps: this filter selected frames near the middle of each interval. We traced pre/post-filter frame checksums and independently confirmed **exact RGB-byte equality** between each sampled frame and its mapped decoded source frame. No classifier was rerun.

The constructed MP4 files probe as 25 fps, with durations 10.48, 10.96, and 11.96 seconds. Nominal insertion intervals below come from the original construction manifest; re-encoding introduces frame-grid quantization.

| Insert | Control ID | Decoded source times actually sampled (s) | Frames inside nominal inserted segment |
|---|---|---|---:|
| 0.5 s, nominal [5, 5.5) | `0038f7ed04ca0c22d90586dd` | 0.64, 1.96, 3.24, 4.56, 5.88, 7.20, 8.48, 9.80 | **0/8** |
| 1 s, nominal [5, 6) | `528a540f40e0e96af72933a3` | 0.68, 2.04, 3.40, 4.76, 6.16, 7.52, 8.88, 10.24 | **0/8** |
| 2 s, nominal [5, 7) | `b75decf7062254d2fa31ce9f` | 0.72, 2.24, 3.72, **5.20, 6.72**, 8.20, 9.68, 11.20 | **2/8** |

The two included frames correspond approximately to 0.20 and 1.72 seconds into the inserted parent; exact original-parent frame correspondence is subject to the builder's 24-to-25-fps encoding. The first two controls therefore cannot test CORVI's recognition of the inserted source at all. The third tests a whole-pipeline score containing two such frames and six surrounding frames, with unknown per-frame generation provenance and mean-score dilution.

## Interpretation of the existing results

- The CGI-versus-mixed score ordering is an exact property of these recorded pipeline outputs. A single monotonic threshold cannot reverse that ordering. It is **not** proof that CORVI cannot distinguish observed generated pixels from CGI: two controls supplied no inserted frames to the classifier.
- Keep these as exploratory **author-labeled-source insertion / sampling controls**. Do not describe their early segments as independently known synthetic frames or use them alone to calibrate short-insert recognition.
- Three variants share the same parent pair and count as one constructed source group; the three CGI excerpts share one Sintel source. They are not six independent origins.
- A stronger future control would preserve an actual generation receipt, exclude an external image reference when the objective is independently known synthetic visual content, verify the exact inserted segment, and record sampled source timestamps. This audit created no new controls and ran no classifiers.

## Audit artifacts and preservation

Read-only decoding artifacts are under `eval/runs/mixed-provenance-audit/`:

- `sampled-timestamps.json`: decoded frame indices/times, checksum matching, exact RGB-byte verification, and sampled-insert counts.
- `*-sampling.log`: FFmpeg trace for each existing control.
- `parent-frame-change.json`: all 121 parent frame hashes and pixel-change measurements.
- `wan-parent-01.png` through `wan-parent-05.png`: extracted source-frame previews, without altering the source video.

Original manifests, media, raw classifier predictions, classifier code, and product behavior remain unchanged. This document qualifies the interpretation of already-recorded evidence.
