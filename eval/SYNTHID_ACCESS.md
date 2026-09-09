# SynthID video verification access

**No documented callable video SynthID decoder was found for this app's Gemini API/SDK.** This is a bounded finding about the inspected public interfaces, not a claim that Google has no detection API or internal detector. Checked official documentation and installed `@google/genai` 2.21.0; no sign-in, access application, terms acceptance, upload, or model call occurred.

| Interface | Actual documented capability | Consequence here |
|---|---|---|
| Gemini consumer app | Signed-in verification tool checks SynthID and Content Credentials. For video: one file, at most 100 MB and less than ninety seconds. SynthID recognition currently concerns Google-generated/edited content; changes can prevent detection. | This is a real watermark-verification tool, separate from ordinary model reasoning. It is an interactive, account-dependent route, not a documented backend endpoint. [Official help](https://support.google.com/gemini/answer/16722517?co=GENIE.Platform%3DDesktop&hl=en-AS). |
| SynthID Detector portal | Google describes media-professional testing and links an early-tester waitlist. | Access has not been established; no application submitted. [Official product page](https://deepmind.google/models/synthid/). |
| Google Cloud AI Content Detection API | Current technical documentation, updated September 2, 2026, specifies a **Private Preview** REST service accepting JPEG, PNG and WebP images, using learned pixel/noise/spectral signals. C2PA checking is excluded. | A real separate API exists, but this page does not document video input or a public SynthID video-decoding endpoint. No access request or image test performed. [Official technical guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/ai-content-detection). |
| Installed Gemini SDK | Searching declarations and Node implementation for `synthid`, `detectContent`, `contentDetection`, `verifyWatermark` and `watermarkDetection` found only the image-generation `addWatermark` documentation. No video-detection method/tool contract was found. | The current SDK cannot be treated as exposing the consumer verification tool. Search absence is scoped to these installed interfaces; it does not prove all private/future APIs absent. |

SDK evidence: `dist/genai.d.ts` SHA-256 `591ea5ad24d83a5e09dbaa208e142bde45375cf5c0797fe87d8dbd465996c288`; `dist/node/index.mjs` SHA-256 `a5775355f9271057cd1e089dd2bce71c5996a88d49da9cd0ed6f183e5905cdb8`. The single SynthID declaration match is at line 12396 and describes adding an image watermark.

## Interpreting the fresh Veo control

Google documents that Veo outputs contain SynthID watermarks and points to its verification platform. [Veo API guide](https://ai.google.dev/gemini-api/docs/veo). A preserved text-only generation request, response and file hash establish this control's origin without assuming the app can decode that watermark.

The app's Gemini Interactions assessment has no documented SynthID decoder receipt. Its ordinary statement that something is watermarked must not be relabeled as cryptographic/watermark verification. A successful assessment of one same-provider Veo clip would not establish cross-generator accuracy or explain which signal caused the success. C2PA and SynthID are separate mechanisms; missing C2PA does not establish that SynthID is absent. A future authorized decoder test would report positive watermark attribution separately from visual inference, and would never convert absence of a detected watermark into proof of camera origin.

Further integration work is deferred until an actual documented video-decoding endpoint and appropriate access are available. No additional provider search or inference follows from this check.
