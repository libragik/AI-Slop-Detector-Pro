# Official demo access check

Checked live on 2026-09-04. After the initial read-only Chrome check, five authorized public development fixtures were uploaded through an isolated headless browser. No account, paid signup or contact-sharing form was used. Preloaded example scores were excluded.

## Hive

The official [AI-generated content page](https://hivemoderation.com/ai-generated-content-detection) offers **Try our Demo**, which loads the official [Hive demo](https://thehive.ai/demos/ai-generated-content-detection?hideSidebar=true&isFromIframe=true) in an iframe. **Upload** opens a dialog with **Browse Files** and a media-URL field. Its supported formats include MP4, H.264, WebM and AVI. No login, contact-sharing form, paid signup, or explicit agreement checkbox/button appeared before the file-selection step. The dialog displays a site terms notice. Later submission limits, rate limits and production API access have not been verified.

The Chrome extension file chooser timed out before file selection. The installed browse skill's isolated browser uploaded the exact local files successfully. Each sequential upload produced a new response ID, technical media receipt and JSON with per-frame scores; screenshot readback verified the displayed verdict. Four HEVC originals could not play in the browser preview, although inference returned five processed frames for each. The H.264 CGI preview worked. The returned filename is null, so file association relies on the recorded upload action and local SHA, not a server-returned hash. A working free demo does not establish a supported production API or permission for high-volume use.

| Targeted development input | Displayed AI video score | Displayed decision | Outcome |
| --- | ---: | --- | --- |
| Kling 2.5 Turbo | 28.9% | Not likely AI/deepfake | Miss |
| HunyuanVideo | 36.1% | Not likely AI/deepfake | Miss |
| Author-labeled real 1 | 29.9% | Not likely AI/deepfake | Correct negative |
| Author-labeled real 2 | 37.4% | Not likely AI/deepfake | Correct negative |
| Sintel conventional CGI | 0.6% | Not likely AI/deepfake | Correct negative |

Model metadata reads `AI art and deepfake and audio detection`, version `1`. Five uploads returned five model results; both selected AI misses remained missed. This is a diagnostic sample, not an estimate of population accuracy. Derivatives were not uploaded because the prerequisite of correctly detecting the original AI clips failed. No production integration followed. [Structured results](./sources/hive-demo-v1-results.json) contain exact file SHA values, response IDs, raw per-frame scores, screenshot paths and JSON hashes. The demo's displayed aggregation/rounding is not documented here; computed frame means are stored separately.

## NVIDIA

The official [Synthetic Video Detector Experience](https://build.nvidia.com/nvidia/synthetic-video-detector) exposes a 100 MB video uploader and **Run**. Before use, a live modal requires **Acknowledge & Continue**, explicitly agreeing to trial terms and input/output recording. It was not accepted. This demo route must be distinguished from the private-access hosted API/NGC deployment route. No claim is made that an anonymous upload will complete after acceptance, or that the visible example's score resulted from our file.

The exact gate links the [API Trial Terms](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf). Any future evaluation should use only the public benchmark clips authorized for that destination, preserve the chosen model threshold, and measure failures as well as detection results.

Final primary-source readback confirmed that the trial terms limit use to internal testing/evaluation and exclude production without a separate subscription (sections 1.2 and 1.4). Section 3.3 describes collection of user content and generated content, including product/model improvement. Section 4.12 also restricts using the service or its outputs to develop or improve competing products/services. Thus a visible free uploader is not evidence of an appropriate production integration or unrestricted product-development evaluation. Confirm an agreement suitable for this detector before choosing that route; no terms were accepted or uploads performed here.
