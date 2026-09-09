# Sightengine video detector: actual access diagnostic

Checked September 5, 2026 UTC. **The public demo returned no detection result. Its first attempted upload stopped at a free-use/sign-up gate. Accuracy remains untested; this is neither a detector pass nor a detector failure.** No account was created, subscription purchased, or integration added.

Before the first file selection, a [five-control diagnostic](./fixtures/sightengine-demo-diagnostic-v1.json) was frozen with SHA-256 `2b2934eb888db109df9def867bd7e13e9f5d01083e1d7a9021c7644ee9ae5825`. It fixes file hashes, order, primary video-level decisions, secondary temporal findings, and stop conditions. All sources are previously consumed development evidence. Even five correct outcomes would only justify considering an independent evaluation.

| Fixed order | Known visual origin | Actual outcome |
| --- | --- | --- |
| Whole Veo control | Directly observed text-only generation | File selected; no result, access refused |
| Sintel with two-second Veo insert | Documented CGI plus generated interval | Not attempted after stop |
| Sintel | Conventional CGI | Not attempted after stop |
| Procedural pendulum | Conventional renderer, no generated pixels | Not attempted after stop |
| NOAA fixed five-second trim | Documented camera archive | Not attempted after stop |

The [public video page](https://sightengine.com/detect-ai-generated-videos) loaded in an isolated headless browser. Its hidden initial 98% example was explicitly excluded. The first control's bytes were verified immediately before selection: 3,205,223 bytes, SHA-256 `e575e1447fe39f97dd9e3bda98d76ea091fc730fc7c33fb7320f9cd879d087bc`.

The browser associated that filename and size with the file input and showed its coffee-video preview. The visible result area instead said **“FREE LIMIT REACHED”** and required sign-up. [Screenshot](./runs/sightengine-demo-diagnostic-v1/01-free-limit.png), [visible state](./runs/sightengine-demo-diagnostic-v1/01-visible-state.json), [command receipt](./runs/sightengine-demo-diagnostic-v1/01-upload-command.json), and [network log](./runs/sightengine-demo-diagnostic-v1/01-network.txt) are preserved. The log shows local blob previews and no observed analysis/media POST; the tool's “Uploaded” wording establishes file selection, not completed remote inference. No new session, quota reset, alternative endpoint, or remaining upload was attempted. The independently checked [terminal receipt](./runs/sightengine-demo-diagnostic-v1/receipt.json) records zero completed predictions and hashes all seven evidence artifacts; its SHA-256 is `a699edb295b5dcbb2d7d8f8ffe95f38ef4522b2b6e0af01a45ae0ee73c2feede`.

## Callable API route and its limits

The vendor documents `models=genai`, multipart media, and an API-user/secret pair for short-video analysis. Responses expose sampled positions and AI-generated scores; the chosen sampling and aggregation must be fixed before an API evaluation. The docs describe whole-generated-versus-real classification, so short mixed intervals require explicit testing. The reviewed documentation does not establish a pinned model version or our operating-point accuracy. [Official API documentation](https://sightengine.com/docs/ai-generated-video-detection).

The current pricing table lists Starter at **$29/month**, 10,000 operations, maximum 50 MB videos, and one concurrent video job. Its Free column has no video processing. The demo's sign-up wording therefore does not prove that a free account will enable video API evaluation. No plan was purchased. [Official pricing](https://sightengine.com/pricing).

The vendor counts five operations per sampled frame for `genai`, with a default one frame every two seconds. A bounded evaluation must account for actual returned operations and freeze a sampling interval rather than infer cost from clip count alone. [Operation definition](https://sightengine.com/faq/what-is-an-operation).

Only relevant credential names/presence were checked in this workspace and process environment; no Sightengine pair was configured and no secret values were printed. Suitable account access is the concrete missing prerequisite for this provider. Once available, perform a separately recorded API diagnostic before any integration. Scores remain uncalibrated evidence until a new source-independent evaluation supports stronger claims.
