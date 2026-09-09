# Known-origin video diagnostic

**The frozen evidence-2.8 detector missed a video generated directly for this test and a two-second insert from the same output.** This removes the original mixed controls' uncertainty about image conditioning and per-frame source origin. It is one generated source, not an accuracy estimate.

## Origin and frozen test

The exact request was declared in [the plan](./fixtures/video-generation-plan.json) before generation. The plan's hand-entered `createdAt` is 25.205 seconds later than the recorded request start and must not be treated as a clock receipt. Predeclaration is instead established by the verified submission script reading/hashing the plan and persisting its record before the provider call; the actual recorded request start is `2026-09-05T01:52:34.795Z`. The original plan remains unchanged, with a separate [timestamp correction note](./fixtures/video-generation-plan-timestamp-note.json). One text-only `veo-3.1-generate-preview` request produced one eight-second, 1280×720, 24 fps video: a person in a green sweater pouring coffee in a kitchen. No image, video, reference frame or identity asset was supplied. The request was not repeated and no output was selected among variants.

The operation was `models/veo-3.1-generate-preview/operations/local-generation-redacted`. Original file SHA-256: `25a522abf8139a4f6f21c9194dbac20115411c1721dd49a8b65ee56fdc7238e6`, 3,352,004 bytes. [Generation receipt](./fixtures/video-generation-receipt.json) preserves the request, operation, source resource, file hash, media probe and timestamps. The generation charge is estimated at USD 3.20 from the [published USD 0.40 per second standard 720p price](https://ai.google.dev/gemini-api/docs/pricing#veo-3.1); actual billing was not read. The [official generation API](https://ai.google.dev/gemini-api/docs/veo) supports text-only video creation.

The negative control is seconds 12–20 of the Blender Foundation's conventional CGI film Sintel (2010), from the [public trailer file](https://media.w3.org/2010/05/sintel/trailer.mp4). Attribution and CC BY 3.0 terms are documented by the [Sintel project](https://durian.blender.org/sharing/). This establishes a conventional CGI control; it is not camera footage.

The [builder](../scripts/build-generated-controls.py) creates three silent eight-second derivatives, all at 1280×720, 24 fps, H.264 CRF20, with source aspect ratio preserved and metadata stripped. The mixed version replaces control seconds 3–5 with generated seconds 3–5. All three preserve explicit parent links and remain in one development group. The manifest validates: one AI, one CGI and one mixed row. Exact FFmpeg arguments, final 192-frame cadence and output hashes are in the [build receipt](./fixtures/generated-control-build-receipt.json).

The local production upload route received only the opaque MP4 filename, its actual video bytes and `fresh=true`. Origin labels, generation prompt/receipt and creator captions were withheld. No detector source, prompt, sampling, model or scoring change was made for this diagnostic. The detector fingerprint remained `e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f`.

## Actual upload results

| Control | ID | Outcome | Time |
|---|---|---|---:|
| Full generated video | `dff4042041e63458ae52bc1f` | No clear AI indicators — missed | 21.512 s |
| Conventional CGI | `0d90f27f1d7915a793493ee4` | No clear AI indicators | 14.395 s |
| CGI with two-second generated insert | `10a7c358371f29ddd7acb538` | No clear AI indicators — missed | 23.275 s |

All three uploads returned HTTP 200, fresh reports and the exact expected media hash, canonical file identity and detector fingerprint. All six inspection passes completed. All outcomes remain explicitly uncalibrated. No retry was needed for an analysis upload, and no reported AI provenance or source disclosure supplied the answer.

Both mixed-clip passes explicitly described the coffee scene. They interpreted it as live action; the separate reviewer also recognized Sintel. Thus this miss is not solely a failure to see the inserted content. The full generated clip was likewise described coherently, including the carafe, mug, sweater and kitchen, but the reviews incorrectly treated physical plausibility as evidence of optical capture. Model agreement did not prevent the shared mistake.

Google documents that Veo output contains SynthID. These ordinary Gemini API assessments do not expose a SynthID-decoding result; same-provider use does not establish that a watermark verifier ran. See [the verified access distinction](./SYNTHID_ACCESS.md). Audio was removed to isolate the visual track, but stripping metadata cannot be assumed to remove a pixel watermark.

These controls demonstrate a concrete remaining false negative. They do not measure general recall, independent camera specificity, actual Instagram processing, other generator families, or partial inserts at other locations/durations. No threshold was fitted and the consumed holdout was not rerun. Success on a future rerun would also require accounting for model variability rather than replacing these saved misses.

## Execution record

One initial read-only poll failed locally because a JSON-restored SDK operation lacked its class prototype. The helper was corrected and resumed the **same** operation; no generation was resubmitted. The submitted script was reconstructed and matched against its recorded SHA-256, then preserved. An initial preparation output failed the cadence assertion because FFmpeg selected 25 fps despite the filter requesting 24. It was retained as a failed preparation, then rebuilt with explicit output cadence before any detector call. Final derivatives verified at exactly 24 fps and eight seconds.

Durable outcome and response hashes: [generated-origin-summary.json](./sources/generated-origin-summary.json). Raw requests, complete model responses, submission snapshot, generation operation, failed preparation and upload receipts are preserved under `eval/runs/generated-origin-control/`. Original/derived media and raw runs are ignored by Git. The frozen manifests and existing corpus results were not overwritten.

An independent agent read back the original/derived hashes, exact submitted-script and plan hashes, raw response hashes, canonical upload identities, fresh-result flags and fingerprint. Fresh probes confirmed all three submitted files have 192 frames, exactly eight seconds and no audio. It found the plan timestamp discrepancy above; no result-integrity blocker was found.
