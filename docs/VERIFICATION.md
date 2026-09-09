# Verification record

## 2026-09-08 — three-minute / 500 MB support and Sightengine-led verdicts

The running evidence-2.10 build accepts videos through **180 seconds and 500,000,000 bytes**. It routes long videos to asynchronous analysis jobs and large files through Sightengine's Upload API. These are now transport choices, not reasons to skip the specialist. Complete repeated Sightengine flags produce **AI indicators detected** even when Gemini disagrees, remains unresolved, or fails. Gemini findings stay attributed and visible. Isolated alerts, incomplete specialist evidence, and unresolved audio/identity evidence can still require an Inconclusive result; no calibrated probability is claimed.

### Final verification

- **396 tests across 31 files passed**, plus lint, TypeScript, production build, and `git diff --check`. Tests include separate upload/job IDs, signed S3 storage, exact 500 MB file streaming, 60/120/180-second jobs, terminal status and job identity, timeout cleanup, large Gemini upload budgets, and specialist-positive results after Gemini failure.
- Final detector fingerprint: `fcaa58ee49ca41589977bf7c895c8db68cab1e19b8834641e659daae2f55d0bc`. The current `.env.local` sets `MAX_MEDIA_BYTES=500000000`; API keys were retained. Source and build hashes are in [the software receipt](../eval/runs/live-e210/software.json).
- **Real multipart boundary test:** an exactly 180-second, 500 MB valid MP4 returned HTTP 200 in **172.54 seconds**, with an AI indicators detected verdict. Sightengine's asynchronous job finished, returned **360/360 flagged samples**, and reported 1,800 operations. Its upload asset ID and analysis-job media ID were distinct and correctly tracked; all polls were bound to the submitted job/request. Both Gemini passes also completed. The source/request SHA-256 matched `c119df2cebd13fa0ddeba5875195d4fe75ad91080bb1a5d56299c1af18af39fd`. [Upload receipt](../eval/runs/live-e210/upload-receipt.json).
- That boundary fixture repeats an existing receipt-backed Veo control without audio and includes a legal MP4 free atom to reach exactly 500 MB. It verifies complete transport and processing at both limits, not accuracy on a fresh independent example. The recipe and byte identity are in [the fixture receipt](../eval/runs/live-e210/fixture.json).
- **Actual Reel browser scan:** `https://www.instagram.com/reel/Da7nZ5hs6H7/` returned **AI indicators detected**, with 19/23 Sightengine flags and two completed Gemini passes finding no clear indicators. Report `7c0fed75-6613-4979-9a19-95e37ce8cde1`, analyzed `2026-09-08T21:22:59.816Z`, used the final fingerprint and `cacheHit:false`. Its original downloaded media SHA remains `57be227b22cb166521cf698611886f6380c7f658a41217d03842395c63d270db`. The real Download report action exported matching evidence; desktop client and scroll widths were both 1260 px, the screenshot was inspected, and the report was left open. [Browser readback](../eval/runs/live-e210/reel-readback.json).
- The upload selector visibly reports **500 MB / 3 minutes**. The assessment explains that Sightengine is primary and Gemini disagreement does not override repeated flags. Browser evidence here covers desktop; the multipart request verifies file submission without claiming an automated file-picker interaction.

### Live integration repairs retained in the record

The first 500 MB app request passed local validation but the specialist rejected the provider-returned S3 upload URL, since its validator only recognized the hostname pictured in the documentation. The second returned HTTP 502 after Gemini's concurrent 500 MB upload exceeded its earlier 60-second budget; that response did not retain the specialist failure details. These unsuccessful attempts remain under `upload-attempt-1` and `upload-attempt-2` in [the run folder](../eval/runs/live-e210/).

A 72 MB version of the same three-minute fixture then exposed the remaining specialist issue: the app incorrectly required the upload asset ID and analysis-job media ID to match. Upload and analysis succeeded remotely, with distinct asset/job IDs; a read of that exact returned job recovered all 360 positions and 1,800 reported operations. The application now accepts the provider's signed S3 storage URL, follows the returned analysis-job ID, and keeps both IDs in its receipt. Gemini large-file uploads have a five-minute allowance within a ten-minute lifecycle, while small uploads and individual inference calls retain their previous deadlines. The final full-size request above passed after these repairs. No automatic paid resubmission or retries were added.

These results verify the requested limits and verdict policy. The earlier false-positive results remain relevant: giving Sightengine precedence can retain specialist false alerts. Historical agreement-policy results below describe evidence-2.9, not the current decision. No commit, push, or deployment was performed.


## 2026-09-08 — Sightengine integration and real request repairs

**The integration works; general AI-video detection reliability remains unproven.** The fixed 25-file specialist screen failed: 10/12 publisher-labeled AI cases were detected and 4/12 documented camera/CGI controls were falsely flagged. Offline conservative fusion detected 5/12 AI cases; it changed five Gemini clear misses to Inconclusive without improving recall. Only 4/12 negatives received a clear result. One Gemini case was interrupted and counted as a technical-error non-detection. The four-original follow-up exposed sensitivity to a combined crop/resize/frame-rate/overlay/encoding transformation, not compression alone. [Results and limits](./SIGHTENGINE_INTEGRATION.md).

### Final software

- `pnpm test`: **381 tests across 30 source test files passed**; generated `.next` copies and frozen evaluation snapshots are excluded.
- `pnpm lint`, `pnpm typecheck`, `pnpm build`, and `git diff --check`: passed.
- Production starts through `pnpm start` at `http://localhost:3000`. Final fingerprint: `6cf0e22eafe74b03c7885a5c45fc1bef4d47a39d42f2c7b2728e85e44960c684`, policy `evidence-2.9`. Gemini 3.7 Flash, C2PA, and Sightengine are configured. Optional YouTube metadata/comments and Supabase are unavailable; the UI says limited mode. Credentials were not printed or changed.
- Sightengine uses the same validated local file as Gemini, returns attributed sampled evidence, and does not supply a confidence percentage. Agreement between both providers is required for an ordinary AI-indicator verdict; disagreement or incomplete specialist evidence stays Inconclusive. Source disclosure and trusted provenance retain their separate meanings. Incomplete specialist or Gemini results are not reusable cached results.
- Source hashes and build identity: [software receipt](../eval/runs/live-e29-deadlines/software.json). No commit, push, merge, or deployment was performed.

### Actual reported Reel and browser verification

A fresh final-build browser scan of `https://www.instagram.com/reel/Da7nZ5hs6H7/` returned **Inconclusive / conflicting / Not calibrated**. Both Gemini passes completed and found no clear indicators; Sightengine flagged **19/23 positions** across three stretches, using 115 reported operations. The report exposes the disagreement. This is a user-reported AI case with unverified independent origin, not an authenticated false-negative benchmark.

- Report ID `ff51e3e3-36f7-45bd-b7e7-35d44fda4b99`, analyzed `2026-09-08T20:25:21.367Z`, `cacheHit:false`.
- Exact local media SHA-256 `57be227b22cb166521cf698611886f6380c7f658a41217d03842395c63d270db` matches the specialist request receipt and the retained original Instagram delivery file. Gemini streams that validated file unchanged; a remote provider-reported byte digest was not independently verified.
- The real Download report UI exported the same final fingerprint and source. Export SHA-256 `9014bd6ac9df64c75e766735b402656d55e5b2617fa2a0b9ed2d9d99ae8f3e49`. [Report and readback](../eval/runs/live-e29-deadlines/reel-final/readback.json).
- Desktop at effective 1265 px and mobile at effective 360 px (375 px viewport request) had matching client/scroll widths and no horizontal overflow. Screenshots were inspected in the browser. The heading fits without an orphaned final letter, and the specialist timeline remains usable. No browser console errors/warnings were observed. The desktop report remains open.

### Final live link and upload checks

All four link paths completed on the final fingerprint. The reported Instagram Reel was exercised through the actual browser above; the remaining platforms used fresh API requests. Each downloaded source retained its canonical identity and matching local-media/specialist-request hashes. No cached result or automatic retry was used.

| Input | HTTP | Elapsed | Sightengine samples | Result |
|---|---:|---:|---:|---|
| YouTube `jNQXAC9IVRw` | 200 | 44.6 s | 38 | No clear AI indicators |
| TikTok `7679483952507276558` | 200 | 64.9 s | 51 | Inconclusive |
| X `2040619776100147411` | 200 | 55.2 s | 37 | No clear AI indicators |
| Original receipt-backed Veo upload | 200 | 27.6 s | 16 | Inconclusive |

All seven Gemini passes completed across YouTube, TikTok, and X; Sightengine returned 126 valid samples and reported 630 operations. The TikTok result retained five specialist flags while Gemini found no clear indicators. These public platform clips are transport checks, not authenticated origin labels. All six before/after health snapshots showed an idle queue. [Platform receipts and readback](../eval/runs/live-e29-deadlines/platforms/README.md).

The real multipart upload used the previously consumed, receipt-backed original Veo control, SHA-256 `25a522abf8139a4f6f21c9194dbac20115411c1721dd49a8b65ee56fdc7238e6`. Its generation label and prompt were not sent to either detector. All three Gemini passes completed and described camera footage, but unresolved audio coverage made each invalid for corroborating a negative assessment. Sightengine flagged 16/16 samples and reported 80 operations. The final result was **Inconclusive / conflicting / Not calibrated**, with matching source hashes, the final fingerprint, `cacheHit:false`, and an idle queue afterward. This verifies execution but remains a known AI non-detection by the combined decision. It is not a fresh accuracy trial. [Upload receipt](../eval/runs/live-e29-deadlines/upload/receipt.json).

Final health returned HTTP 200 with Gemini, C2PA, and Sightengine configured and zero active/pending requests. All eleven recorded source hashes and the build ID still matched the tested build. [Final health readback](../eval/runs/live-e29-deadlines/health-final.json).

### Request failures found and repaired

An earlier YouTube request disconnected after 301 seconds, and one frozen Gemini comparison case was interrupted after 372 seconds. The installed SDK did not inherit the constructor timeout for Interactions. Explicit per-call options, abort signals, and independent deadlines now bound requests. Gemini's uploaded lifecycle cancels at 175 seconds and reserves up to five seconds for cleanup; C2PA report latency is bounded to ten seconds. Provider branches settle before the queue slot and local file are released.

The first timeout patch broke SDK uploads by replacing required resumable headers and duplicating the API-version path. A real upload-only probe returned 404, which mocked application tests had not caught. Native streamed upload now follows Google's documented endpoint, keeps metadata neutral, rejects redirects/unexpected session origins, and bounds response reads. An unread cloned response can make awaited cancellation hang; teardown no longer waits for that cancellation promise. The real upload/poll/delete probe passed in 6.564 seconds, and a direct timeline sweep passed in 17.305 seconds. Failed browser attempts remain preserved with unknown response/billing fields explicitly marked rather than invented.

A subsequent real report exposed an adjudication HTTP 400: its 4.1-second observation generated `2.0999999999999996s`, beyond protobuf Duration precision. Canonical strings now use at most nine fractional digits, with matching receipt bounds. The preserved adjudication completed after this repair in 22.283 seconds including upload/cleanup. The frozen comparison's original failures remain unchanged. These fixes restore execution, not proof of detection quality. [Diagnostic receipts](../eval/runs/live-e29-deadlines/reel-first-attempt/).

## 2026-09-04 — final local experimental build

**Software verification passed; improved detection accuracy did not.** The untouched 75-clip comparison caught 23/39 AI clips versus 26/39 for the original, and falsely flagged 2/36 real clips versus 0/36. See [the full heldout results](../eval/HELDOUT_RESULTS.md) and [evaluation summary](./DETECTION_EVALUATION.md). The product labels itself experimental. No production deployment, push, or merge was performed.

### Final software and runtime

- `pnpm test`: **250 tests across 22 files passed**. Meaningful regressions cover contradictory evidence, modality grounding, audio-only abstention, invalid timestamps, actual coverage, trusted provenance, cache validation/timeouts, Gemini file cleanup, source-bound rescans, and immutable evaluation integrity.
- `pnpm lint`, `pnpm typecheck`, and `pnpm build`: passed.
- `pnpm start` starts the proper Next.js standalone output, copies static/public assets into that layout, and loads the local environment without copying secrets into commands. The final build is running at `http://localhost:3000`.
- Final health: policy `evidence-2.8`, fingerprint `e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f`, Gemini 3.7 Flash for both passes, agentic separate review, 2 fps timeline sweep / 6 fps detailed windows, `calibrated:false`. Gemini and C2PA are available; YouTube Data API and Supabase cache are not configured. The UI reports limited mode.
- The report has five evidence outcomes, no probability dial or unsupported high confidence, an origin limitation, per-pass inspection records, media identity/hash, separate disclosure/provenance, local annotations, and fresh rescan.

### Real network and upload checks

All four public platform paths completed fresh evidence-2.7 production scans without retries. Canonical IDs, source receipts, `cacheHit:false`, and detector fingerprints matched. Full responses are under `eval/runs/live-e27/platforms/`. Policy 2.8 changed only audio-only decisions, not inference; offline scoring replay preserved all four platform outcomes. The replay is not a second retrieval test.

| Platform | HTTP | Time | Completed passes |
|---|---:|---:|---:|
| YouTube Shorts | 200 | 32.4 s | 2/2 |
| Instagram Reels | 200 | 36.1 s | 2/2 |
| TikTok | 200 | 46.0 s | 3/3 |
| X | 200 | 28.7 s | 2/2 |

The NASA clips have not been independently origin-authenticated. TikTok returned limited AI indicators while the other three returned no clear indicators; successful transport does not establish that either judgment was correct.

Two documented positive Instagram examples also completed under evidence-2.7: the creator's [Ray2 Ferrari Reel](https://www.instagram.com/reel/DGJFMzsSnfj/) returned AI use disclosed with a positive raw visual assessment; the [official Luma emoji demo](https://www.instagram.com/reel/DBOo30tPJGk/) returned visual AI indicators. Two creator/vendor-asserted examples do not establish general recall. The exact user-reported Reel has not been supplied.

Actual multipart uploads on evidence-2.8 verified matching media hashes and the final fingerprint:

- Generated TTS over author-labeled real visuals: HTTP 200 in 15.3 s, **Inconclusive**, raw audio likely synthetic, review required.
- Documented LibriVox 2006 human narration over identical encoded visual packets: HTTP 200 in 30.2 s, **No clear AI indicators**, raw audio likely recorded. The first simultaneous upload received the intended `429 UPLOAD_BUSY`; it succeeded when retried sequentially. That first response is preserved.

The preceding evidence-2.7 human scan had falsely reported synthetic audio. Replaying that exact old report through the final scorer yields Inconclusive, as does its matched TTS report. The fresh human scan's changed raw judgment demonstrates model variability; it does not independently prove audio accuracy. Files and all attempts are retained under `eval/runs/live-e28/`.

A later [first-party generated-video diagnostic](../eval/GENERATED_ORIGIN_CONTROL.md) used one text-only Veo 3.1 generation with its operation, original hash and exact recipe preserved. Three fresh final-policy uploads completed: full silent generated footage (21.5 s), documented conventional CGI (14.4 s), and CGI with a two-second generated insert (23.3 s). All three returned **No clear AI indicators**. All six passes completed, file/source hashes and detector fingerprints matched, and both mixed-clip reviews explicitly described the inserted scene. These are known AI misses despite successful processing, not evidence of improved accuracy. The model did not receive the generation receipt or labels. No detector changes followed these outcomes.

The evaluation-only follow-up corrected SPAI preprocessing in a separate frozen adapter, measured CORVI on originals and delivery variants, audited all 460 derivative hashes/frame cadences, and qualified older short-insert sampling/source limitations. The old mixed-control builder now explicitly sets its output frame rate and refuses to overwrite existing frozen controls; the refusal was exercised and all seven protected manifest/media hashes remained unchanged. New generated-control media and manifest validation passed. Repository lint and both new helper syntax checks passed. Product source has not changed since the 250-test/typecheck/build verification above, so these evaluation-only additions did not trigger another paid corpus run or a new production build.

A subsequent isolated AEGIS evaluator verified the publisher checkpoint, restricted conversion, all 467 expected tensors, pinned upstream sources, and fixed CPU/frame-processing settings. All three known-origin controls ran without errors in 1.48–1.62 seconds each, excluding model setup. Full generated footage was flagged and conventional CGI was negative; the mixed clip was missed with eight sampled insert frames. The failed gate stopped the larger stage before any of its model calls. This was an evaluation of a separate candidate, with no change to the running app or its accuracy claims. [Control results](../eval/AEGIS_DEVELOPMENT.md).

### Browser and final presentation evidence

Actual evidence-2.5 production browser checks used the NASA Instagram Reel and verified fresh rescanning after changing the intake to a different YouTube URL. The report remained bound to the original Instagram source. Initial report `8d10cd19-b5ea-4a88-85fe-8e12dbd73cf5` and rescan `43c1fcb0-f913-433e-a6e6-b7c4dc214588` had different IDs/times, the same media SHA-256 `6a02fc3e54ca87c42fa780147c45b029b33ad88ff03f0cb53cedee0e6189a19f`, and `cacheHit:false`. Desktop and 375 px mobile had no horizontal overflow or console errors/warnings. JSON exports and screenshots are preserved in `tmp/release-verification-2026-09-04/`.

Earlier development browser checks verified saved local annotations and downloaded JSON, including their explicit unverified-user-note status. File attachment through browser automation was unavailable, so actual multipart API uploads provide the upload-path evidence above; an automated file picker interaction is not claimed.

The final presentation adds an experimental limitation in the existing hero notice and labels possible AI audio as unverified. Server-render tests verify that copy. A new browser capture was unavailable because the Mac was locked; the OS lock was not bypassed. Final HTTP/asset/health readback is recorded separately in `tmp/release-verification-e28/`. Prior screenshots are not represented as final-build captures.

### Detection limits

Software checks establish processing and decision safeguards, not general detection accuracy. Multiple passes shared errors, the final candidate was descriptively worse on the reserved originals, and the original confidence rule called all 75 results High including 13 false negatives. No calibrated probability is advertised. The consumed holdout must not be reused as an untouched test for future tuning. Further accuracy claims require a new, independently grounded corpus and a candidate that passes it.

## 2026-09-02 — historical software and transport verification

The following record is preserved from the earlier implementation. Its “high confidence” labels and numeric scores describe legacy outputs that have since been retired. They were not calibrated, did not establish the videos' origin, and are not detection-accuracy evidence. Platform availability and environment configuration below are historical snapshots, not current guarantees.

### Automated checks

- `pnpm test`: 71 tests passed across URL normalization, scoring, UI response parsing, comment derivation, YouTube duration enforcement, social download boundaries, safe retrieval errors, request-body limits, and admission control.
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm build`: passed with the home page and all three API routes included in the production output.
- `pnpm audit --prod`: no known vulnerabilities.

### Live checks

- Gemini 3.7 Flash completed real agentic scans from each supported link platform: a 93-second NASA YouTube Short, a 71-second NASA Instagram Reel, a 25-second NASA TikTok, and an 18-second NASA Artemis video on X.
- All four returned HTTP 200 with the expected canonical platform and URL, high confidence, and an observed agentic processing call/result trace. The final scores were 5, 1, 95, and 2 respectively.
- The exact unavailable Instagram link reported by the first tester returns HTTP 422 with a specific private/deleted/expired-link explanation and upload fallback.
- An X status containing only an outbound NASA article returns HTTP 422 before download. This confirms the Twitter extractor/status preflight blocks unrelated webpage media.
- A 213-second YouTube video was rejected with HTTP 422 before Gemini was called, confirming the three-minute guard.
- `/api/health` reports Gemini, optional YouTube evidence, operational cache state, C2PA, model, processing mode, and current worker capacity without exposing credentials.
- Browser checks covered the refreshed four-platform copy, X status detection, the exact Instagram failure state and upload action, the ready/limited state, sample evidence report, score trace, accessibility structure, and horizontal overflow.

| Platform | Public smoke-test URL | HTTP | Canonical result |
| --- | --- | ---: | --- |
| YouTube Shorts | `https://www.youtube.com/shorts/myZ9kn9MIWQ` | 200 | `youtube:myZ9kn9MIWQ` |
| Instagram Reels | `https://www.instagram.com/reel/DWhqiudAoQr/` | 200 | `instagram:DWhqiudAoQr` |
| TikTok | `https://www.tiktok.com/@nasa/video/7679483952507276558` | 200 | `tiktok:7679483952507276558` |
| X | `https://x.com/NASAArtemis/status/2040619776100147411` | 200 | `x:2040619776100147411` |

### Environment status during verification

- Gemini: configured and working.
- YouTube Data API: not configured, so title, disclosure, and comment evidence are unavailable.
- Supabase: not configured, so completed reports are not persisted or reused.
- C2PA inspection: enabled for uploaded or retrieved local media.

The app deliberately presents this configuration as `LIMITED MODE`. Add `YOUTUBE_API_KEY`, apply the Supabase migration, and configure the two Supabase server variables before a public launch that advertises all evidence channels and cached results.
