# AEGIS shot/window study: rejected

The frozen shot/window candidate falsely flagged **19 of 45 non-generative videos**. All 45 files and all 102 planned model windows completed, with zero processing errors, abstentions or unsupported intervals. This fails the declared negative gate. The candidate is not integrated into the product, and its 60 planned AI-positive cases were not acquired, constructed or evaluated.

The run completed September 4, 2026 local time (September 5 UTC). It is a separate experiment from the [failed centered-window screen](./AEGIS_DEVELOPMENT.md). Neither that screen's clips nor the consumed benchmark holdout were reused.

## What was tested

The hypothesis was that separating detected shots and examining overlapping windows might better match AEGIS's clip-level training than one centered sample. The unchanged official model, verified complete safetensors state, main fused head and inclusive 0.5 threshold were retained. FFmpeg scene detection used threshold 10; supported shots received windows of at most four seconds, with two-second strides and a mandatory tail window. Every window used 16 actual decoded frames. Any positive window flagged its video. All windows ran even after a positive result.

The five negative parents were NASA and USGS photographic timelapses, NOAA expedition footage, and two newly rendered conventional CGI scenes. Each supplied an unedited five-second case, a hard-cut edit and a blended edit with another negative parent, at master/mild/severe quality: 45 files total. The CGI used explicitly authored geometry and motion with no generative pixel model or neural denoiser. AI assistance in writing the scene code does not make these generatively synthesized pixels.

The full prospective design contained nine parent slots and 105 cases. Source selection, generation requests, editing recipes, detector policy, runtime, model identity and executable files were frozen before inference. The five existing parent paths and hashes did not overlap the checked prior-media manifests. The first stage deliberately tested negatives before any new Veo generation or 28.929 GB Wan weight acquisition.

## Complete negative-stage results

| Quality | Selected | Correct negative | False flag | Abstention/error |
|---|---:|---:|---:|---:|
| Master | 15 | 7 | 8 | 0 |
| Mild repost simulation | 15 | 7 | 8 | 0 |
| Severe repost simulation | 15 | 12 | 3 | 0 |
| **Total** | **45** | **26** | **19** | **0** |

| Composition | Selected | False flags |
|---|---:|---:|
| Unedited | 15 | 7 |
| Hard cut between negative sources | 15 | 10 |
| Blended edit between negative sources | 15 | 2 |

Grouped by host, false flags were NASA 0/9, NOAA 3/9, USGS 7/9, pendulum 5/9 and rolling track 4/9. These host groups share donor ancestry and must not be treated as independent samples.

The failures include ordinary render output and camera-origin footage, not only edited boundaries. The pendulum master had a maximum raw fused score of 0.999921 despite its conventional CGI origin. The USGS master reached 0.975705. In the NOAA hard-cut cases, the selected USGS donor interval was falsely positive at every quality. The raw scores are model outputs, **not calibrated probabilities or confidence in AI origin**.

Thirty of 102 windows were positive. All 4,500 native frames were decoded and every prescribed window was processed; this does not mean every frame was classified. Total stage time was 147.6 seconds, median per-video time 2.925 seconds, maximum 4.435 seconds, and peak recorded process RSS 2,136,178,688 bytes. The strict checkpoint load supplied all 467 tensors. Source snapshots, weights and the working runner remained unchanged.

## Decision and limits

The negative gate required 45 complete negative decisions with no errors. Nineteen false flags reject this exact candidate. No threshold adjustment, alternate head, changed crop, new scene threshold, repeated inference or selection of easier clips followed these outputs. No new Veo parents or Wan weight bodies were acquired for this study; all four generation slots and 60 AI-positive cases remain unexecuted. Consequently, this wrapper has **no measured AI recall from this study**.

These are five source parents in one connected ancestry family, expanded through edits and quality versions. The counts describe a targeted rejection screen, not a population false-positive estimate. Camera sources are agency archives rather than pristine capture masters; two are timelapses. Conventional CGI is deliberately included as a separate negative category. The delivery variants are local simulations, not actual social-platform uploads. This study also does not isolate whether shot sampling worsened the original AEGIS model: a paired centered-window baseline on these new files was not run.

The result does establish that this implementation is unsuitable for integration as configured. Better coverage and successful execution did not make its predictions trustworthy. The broader accuracy goal remains unmet.

## Retained evidence

- [Prospective protocol](./AEGIS_SHOT_EVALUATION_PROTOCOL.md) and [immutable freeze record](./runs/aegis-shots-v1-freeze/receipt.json).
- [Complete construction receipt](./runs/aegis-shots-v1-negative-build/build-receipt.json), [45-file manifest](./runs/aegis-shots-v1-negative-build/manifest.jsonl), and [independent actual-media review](./runs/aegis-shots-v1-negative-review/review-receipt.json).
- [Raw results](./runs/aegis-shots-negative-v1.jsonl), [execution receipt](./runs/aegis-shots-negative-v1.receipt.json), and [complete case summary](./sources/aegis-shot-negative-summary.json).
- [Independent final audit](./runs/aegis-shots-negative-v1-audit/summary.json) rechecked all 41 frozen files and snapshots, decoded-frame hashes, all 102 preprocessing tensor hashes, raw decisions and gate rejection without another classifier call. The [generation-stop check](./sources/aegis-shot-generation-stop-check.json) confirms the failed stage cannot authorize the next generator.

The standalone Node generation contract and frozen run snapshots are excluded from ordinary Vitest discovery. The existing 22 Vitest suites still pass all 250 tests; targeted lint also passes. This test-runner maintenance does not change detector behavior or the frozen study files, and passing software checks does not establish detection accuracy.

Recipe fingerprint: `898d95740e2942cdf022a34fb8663b5b1f0a7fb0e73e3ba527e366848de7a336`.
Raw result SHA-256: `ad52ff95b3a0517849d1b4f9481652b58dcdad54f7182f71c655c926c01ff524`.
Freeze receipt SHA-256: `e17fd0377cbe341ccc48c47f6a076ab1071fac2114cd3d7327cb282f361f82a0`.
