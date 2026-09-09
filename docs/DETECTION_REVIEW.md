**AI Slop Detector reliability review — September 4, 2026**

This is the preserved pre-implementation review of commit `e0188f6`; its code line references and runtime description refer to that version. The subsequent implementation and measured results are documented in [DETECTION_EVALUATION.md](./DETECTION_EVALUATION.md) and [VERIFICATION.md](./VERIFICATION.md).

The current application does not have evidence supporting its high-confidence detection claims. Its main result starts with one Gemini-generated number, and its scoring rules convert extreme numbers into high confidence even when the accompanying assessment is inconclusive. Improving actual detection requires controlled evaluation as well as changes to evidence collection and decision logic.

This review inspected commit `e0188f6`, ran the existing tests, exercised the actual scoring and schema code with controlled inputs, and checked the running local service. Application code and runtime settings were unchanged. This file is the review deliverable.

The reported Instagram URL and original report were not supplied during the review. The exact incident remains unreproduced; the findings below distinguish proven application defects from plausible reasons Gemini missed the footage.

**What the running detector does**

The local service on port 3000 was verified to belong to this checkout. Its health response reported Gemini `gemini-3.7-flash`, agentic processing, analyzer version `mvp-1`, C2PA enabled, and YouTube context and cache unconfigured. This describes the local service, not an independently verified deployment.

For Instagram, the pipeline downloads a media file, checks embedded Content Credentials, uploads the video to Gemini, performs one video interaction, and aggregates the result. Instagram captions, creator disclosures, and comments do not enter a separate context assessment. See [pipeline.ts](../src/lib/analyzer/pipeline.ts#L82) and [media.ts](../src/lib/analyzer/media.ts#L383).

**Confirmed findings and priorities**

1. **P1: Confidence is calculated from score extremity, with no measured reliability behind it.** At [scoring.ts:99](../src/lib/analyzer/scoring.ts#L99), scores below 50 become “Probably Not AI”; scores at or below 15 become “High” confidence. The same confidence rule applies to scores at or above 85. The model prompt and schema explicitly call the score uncalibrated. The scorer cannot account for video quality, missing evidence, failed coverage confirmation, or limitations because its video input only uses the likelihood and classification fields. The percentage dial and prominent confidence text amplify this at [result-report.ts:126](../src/components/result-report.tsx#L126).

2. **P1: Inconclusive or conflicting evidence does not prevent a confident binary verdict.** The schema validates individual fields without reconciling their meanings. The scorer ignores visual assessment, synthetic-audio findings, identity manipulation, suspicious moments, and limitations. A mixed-media classification changes a subordinate label while leaving a contradictory headline possible. See [schemas.ts:20](../src/lib/analyzer/schemas.ts#L20) and [scoring.ts:106](../src/lib/analyzer/scoring.ts#L106).

3. **P1: Existing validation establishes processing success, with no measured detection accuracy.** All 71 tests across eight files passed. They cover retrieval, parsing, scoring rules, and request controls. The scoring tests explicitly expect an inconclusive fixture to produce a high-confidence negative. The four live checks in [VERIFICATION.md:15](../docs/VERIFICATION.md#L15) record NASA videos, HTTP success, and scores, without verified ground-truth labels or accuracy metrics. The TikTok score of 95 merits investigation, but its origin cannot be determined from that record alone.

4. **P2: Video inspection has no enforced timeline coverage or targeted verification.** [gemini.ts:118](../src/lib/analyzer/gemini.ts#L118) sends a video URI, processing mode, and MIME type in one interaction. It does not request an explicit sampling density, a segment sweep, or a second inspection of suspicious moments. Its agentic flag confirms that at least one processing call/result pair exists; it does not establish what fraction of the video was viewed. Missing confirmation only adds a limitation. This creates a plausible route for missed brief artifacts, but does not prove what happened in the reported Reel.

5. **P2: Instagram lacks external corroboration and a record of the analyzed asset.** Downloaded metadata is deliberately not retained. A creator caption admitting AI generation therefore cannot correct a visual miss. Media validation checks file type, size, and duration, but duration is discarded; the social result also omits the computed content hash. There is no contact sheet, decoded resolution/FPS record, or resolved Instagram media ID to verify what was analyzed. See [media.ts:314](../src/lib/analyzer/media.ts#L314). No evidence in this review establishes that the wrong file was downloaded.

6. **P1: The strongest provenance label can be triggered by unrelated manifest text.** [c2pa.ts:11](../src/lib/analyzer/c2pa.ts#L11) recursively examines every string and accepts matching suffixes from any domain. A controlled test mocked the SDK reader as returning a trusted manifest with a digital-capture action and no AI assertion. Changing only the manifest title to `trainedAlgorithmicMedia` caused the actual parser and scorer to return 98 and “Verified synthetic.” This proves a parser defect under a mocked trusted manifest; no real signed credential was constructed. Parse defined assertions and their scope, rather than searching arbitrary strings, before using the strongest label. This is a false-positive issue, separate from the reported Instagram miss.

7. **P2: Future detector changes can reuse outdated cached results.** Cache lookup checks the URL key and a manually maintained analyzer version; the default lifetime is 30 days. Model, prompt, processing, and scoring changes do not automatically invalidate results. See [cache.ts:33](../src/lib/analyzer/cache.ts#L33) and [env.ts:42](../src/lib/config/env.ts#L42). This cannot explain a cached result from the currently inspected local service because its cache is unconfigured.

8. **P2: YouTube crowd influence uses the wrong sample threshold.** [scoring.ts:86](../src/lib/analyzer/scoring.ts#L86) requires ten total sampled comments, rather than ten directional claims. One “real” claim among 99 neutral comments produces a strong-consensus adjustment of minus four points. Crowd opinion should remain contextual and should not determine forensic confidence. This issue is YouTube-specific.

**Controlled reproductions**

These ran the existing application logic without model calls. They establish decision-logic behavior, not Gemini's accuracy on real videos.

| Input to existing logic | Actual result |
| --- | --- |
| Score 5; inconclusive; poor-resolution limitation; no observed agentic processing | Probably Not AI; High confidence |
| Score 5; likely AI-generated classification | Probably Not AI; High confidence |
| Score 10; mixed/AI-edited; synthetic audio; face swap | Probably Not AI; High confidence; Mixed or AI-edited label |
| Trusted mocked credential; digital-capture action; only title changed to an AI source-type token | Score 98; Verified synthetic |
| Score 15; one “real” comment and 99 neutral comments | Score 11; strong-real-consensus adjustment |

**Recommended implementation sequence**

1. **Correct the result contract first.** Make “Inconclusive” a real top-level outcome. Distinguish “AI indicators detected” from “No clear AI indicators found.” Remove unsupported probability percentages and high-confidence negatives until calibration exists. Model contradictions, insufficient coverage, or unreadable media should trigger reinspection or abstention. Display visual generation, material AI editing, synthetic audio, and identity manipulation separately. Preserve a distinction between an AI-generated scene and a real scene with an AI voiceover. Correct the provenance parser and add focused regressions for the reproduced failures.

2. **Build the evaluation set before tuning detection.** Start with roughly 200–300 known-origin source clips as a development corpus, including generated originals with generation records, camera originals, realistic AI scenes, obvious AI scenes, ordinary CGI/VFX/animation, unusual real events, voice-only changes, and short AI inserts. Include the reported Reel when available, with its origin label supported by evidence. This starter set is not sufficient to certify universal reliability. Keep development, calibration, and untouched evaluation partitions separate; an original and all its crops, reposts, and transcodes must stay together. Hold out creators and generators as well as clips.

3. **Compare better inspection strategies against the same baseline.** Test a bounded timeline sweep, explicit static sampling, scene-change frames, and denser short windows around motion or transitions. Preserve temporal sequences rather than relying exclusively on isolated still frames. Have a later review verify candidate observations against those windows, including mundane explanations. Google's documentation describes agentic processing as selective and supports static sampling and clipping controls; static defaults to 1 FPS, which can lose fast-action detail. Its guidance supports evaluating explicit coverage for this short-video task. It does not establish that static mode will detect AI better. [Gemini video documentation](https://ai.google.dev/gemini-api/docs/video-understanding)

4. **Benchmark a specialist detector alongside Gemini.** NVIDIA Synthetic Video Detector is a concrete candidate designed for diffusion-generated video, with per-frame outputs and an intended resistance to video compression. Its internal benchmark results do not establish performance on our Instagram clips. Evaluate the specialist alone, Gemini alone, and their combination; retain an extra component only if it improves held-out results at acceptable latency and cost. Confirm access and hosting requirements before integrating it. [NVIDIA model card](https://build.nvidia.com/nvidia/synthetic-video-detector/modelcard)

5. **Collect corroboration and make failures diagnosable.** Add a bounded, separate Instagram context pass where captions or platform disclosures are accessible. Keep source claims separate from visual observations and distinguish generative video from AI audio or minor edits. Preserve the retrieved file's hash, media identity, duration, decoded properties, detector versions, sampling plan, and actual coverage when observable. Label requested coverage separately from verified coverage. Offer temporary previews/contact sheets and a controlled rescan/report-error flow while preserving existing media cleanup and URL protections. Fingerprint the entire detector configuration for caching. Additional passes may require background jobs to stay within the current request window.

**Evidence required before claiming greater confidence**

Evaluate both original uploads and actual platform-served copies. Include recompression, cropping, resizing, overlays, frame-rate changes, and screen recordings. Report AI recall, real-video false-positive rate, the rate of AI inside negative results, abstention, and confidently wrong predictions, with uncertainty intervals and platform/content/generator breakdowns. Evaluate both per-segment and whole-video outcomes for mixed footage. Test repeated runs on a subset for instability. Freeze thresholds before the final evaluation; report detection coverage so a system cannot look accurate simply by calling everything inconclusive.

Once a held-out calibration set supports it, a probability claim can be tied to observed outcomes for similar cases. Agreement between two correlated models is not independent proof, and a low model-written score does not establish camera origin. Tune for fewer confidently wrong negatives while also measuring false accusations against real footage.

Recent RA-Bench research reports inconsistent generalization across specialist and multimodal detectors and deterioration during social dissemination. It reinforces the need for our own evaluation. Its models, sampled-frame protocol, and crisis-event dataset differ from this application's native-video setup, so its reported accuracy cannot be assigned to this detector. [RA-Bench preprint](https://arxiv.org/abs/2608.14391)

The practical next milestone is a corrected verdict contract plus a repeatable labeled benchmark. Improved sampling, prompts, models, or specialist services should earn their place through that benchmark. The specific Instagram miss still needs its URL and original report to determine whether Gemini overlooked evidence, produced conflicting fields, or analyzed inadequate media.
