# Camera control inspection

Inspected locally after the three successful acquisitions recorded in `eval/sources/camera-origin-acquisition.json`. **Zero detector calls, zero new network requests, and no changes to original videos.** Full source SHA-256 hashes matched before and after decoding.

The files contain usable camera imagery, with specific processing limits. NASA and USGS are timelapses. NOAA is an edited presentation with a silent audio track, a species label, and an end slate. None is established as a pristine camera master or cryptographically authenticated capture. This inspection does not establish accuracy of any detector.

## Usable intervals

All intervals are half-open playback seconds. Selections use footage/source properties only, without detector outcomes. “Camera imagery” permits conventional processing; it does not mean untouched pixels.

| Source | Camera-imagery interval | Conservative short excerpt | Limits |
| --- | --- | --- | --- |
| NASA ISS aurora | `[0,45.766667)` | `[1,9)` | No visible titles or overlays in sampled review; explicitly accelerated still photographs; no audio stream |
| NOAA sea cucumber | `[5,35)` | `[20,27)` | Excludes opening label and end slate; tracking, reframing and apparent magnification changes; uninterrupted-take status unverified |
| USGS MLK collapse | `[0,12.1)` | `[0,8)` | Timestamp and USGS mark throughout; **no overlay-free interval**; roughly 600× timelapse; no audio stream |

These are preparation candidates, not a frozen inference manifest. If an experiment requires strictly overlay-free, continuous camera originals, USGS does not qualify and neither timelapse meets continuous real-time acquisition requirements. No crops or derived video excerpts were produced.

## Visual and source observations

**NASA.** Earth, clouds, aurora, and foreground ISS hardware remain visible throughout the fixed one-second contact sheets. No title/credit slate, visible graphic overlay, or shot cut was observed. Exposure and lighting change substantially; there are 3 adjacent pairs of exactly equal decoded RGB frames. Such duplicates do not establish interpolation or AI processing. The [primary NASA record](https://svs.gsfc.nasa.gov/30179/) explicitly attributes the sequence to ISS photographs captured September 17, 2011, 17:22:27–17:37:21 GMT. This confirms the intended timelapse origin, not an unmodified camera-video cadence.

**NOAA.** The sampled footage shows a translucent swimming sea cucumber against the seafloor/water column. A species label appears around 2–4 seconds and fades. An end slate occupies roughly 37–39 seconds, followed by black. The safe 5–35 second interval leaves margins around those graphics; the slate date reads **July 27, 2010**, strengthening the [agency page's INDEX2010 attribution](https://oceanexplorer.noaa.gov/multimedia/video-shorts-10index-seacuke-swims/). The date is still a publisher assertion, not independent camera telemetry. The encoded container's2021 creation time belongs to the later presentation, not the expedition capture.

Composition and apparent scale change around 11–12, 18–19, and 28–29 seconds. Sampled review does not reliably distinguish camera tracking/zoom from editorial transitions; do not describe 5–35 seconds as a verified uninterrupted take. The 20–27 second excerpt has more stable framing in the inspected samples. No rendered animal or CGI effect was apparent, but visual inspection alone does not prove absence of later processing.

NOAA's48 kHz stereo AAC track is **digitally silent**: full decoding to PCM float32 yielded 3,872,768 finite scalar samples, with 0 nonzero samples and maximum absolute amplitude 0.0. It is not a human-speech or synthetic-audio control. The silence receipt is retained; do not infer audible coverage merely from `hasAudio:true`.

**USGS.** The source shows a fixed view of the volcano, with steam, rapidly changing daylight, lava activity and cone collapse. A top-left capture timestamp and bottom-left USGS mark persist. Displayed times progress from 05:30:04 at playback 0 to 07:30:02 at playback 12 seconds, matching the [primary camera record](https://www.usgs.gov/media/videos/spatter-cone-collapse-mlk-vent). It specifies one photograph/minute and 10 fps playback, camera about 70 m from the vent, and the south-flank coordinates. The 121 unique frames cover 121 source instants, not smooth real-time motion. No separate title slate or change of viewpoint was seen. The formerly identified NASA mirror's 2006 label remains excluded; this is the direct USGS 2005 source.

## Measured cadence and identity

Every decoded native frame was hashed and every presentation timestamp inspected. All three streams have positive, regular PTS steps, consistent with their declared rates. This establishes **encoded playback cadence**, not camera acquisition cadence or lack of editing.

| Source | Dimensions | Encoded fps | Frames / duration | Unique native RGB frames | Adjacent exact duplicates |
| --- | --- | --- | --- | --- | --- |
| NASA | 1280×720 | 30 | 1373 / 45.766667 s | 1369 | 3 |
| NOAA | 960×540 | 30000/1001 | 1209 / 40.3403 s | 1192 | 13 |
| USGS | 1600×1200 | 10 | 121 / 12.1 s | 121 | 0 |

NASA retains a source sample-aspect ratio of 513:512. USGS is full-range `yuvj420p`; its native 10 fps must not be confused with the 24 fps/25 fps construction issue in earlier controls. Any later normalization should be separately recorded rather than changing these originals.

Original SHA-256 identities:

- NASA: `bdb30be02d028f903c820f4424eddf36036a504d90671ff4151e442940788960`
- NOAA: `32bdae2f731bf4190c796a6fbef6a6e9bed601b5ee3de1ca43739625b940c45a`
- USGS: `3760819946ae49f55d8e50ce9535caedfac66c16e670ed1b1dc6fd7b14604043`

## Retained evidence and limits

The compact source/interval receipt is `eval/sources/camera-control-inspection.json`. Detailed local artifacts are in `eval/runs/camera-control-inspection/`: acquisition-linked decoding receipt, native RGB frame hashes, complete PTS lists, silence verification, representative PNGs, and 5 labeled contact sheets. Sampling was fixed at the native frame nearest every integer playback second, plus each last frame. The inspection script and artifact hashes are retained. Frame differences were used only to flag visual-change candidates, never as a detector score.

This was bounded contact-sheet review, **not full-motion playback or semantic inspection of every frame**. Short unsampled edits cannot be ruled out. Current source hashes lock the acquired encodes; they do not retrospectively certify their custody since 2005/2010/2011. Rights and primary production records remain in `eval/INDEPENDENT_CAMERA_SOURCE_FEASIBILITY.md`.

These are 3 source groups. Trims, crops, inserted segments, and transformed versions from them must stay grouped. The provenance is stronger than the existing dataset labels, but these unusual scientific scenes do not establish coverage of human/social footage or independence from model pretraining.
