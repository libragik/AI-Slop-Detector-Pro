# Veo study runner audit

Reviewed `scripts/eval-generate-veo-study.mjs` against installed **@google/genai 2.21.0**, Node **26.7.0**, the study builder's actual parent-receipt validator, and `eval-aegis-shots.py::gate_check`. **No network connection, API submission, paid generation, or detector/model call occurred.**

Final reviewed runner SHA-256: `064f60cac0a18387f5b361102f2e18b910ae0526ad1581225f3d267e43b2ea0f`.

## Concrete findings and fixes

- The installed SDK accepts the current `source: {prompt}` request and requires a reconstructed `GenerateVideosOperation` instance when polling a saved operation. Offline transport tests verified both paths. `retryOptions.attempts:1` means exactly one attempted request, including the original; a mocked HTTP 503 caused one transport call.
- **The SDK rejects `config.seed` for Gemini Developer API Veo before making any request.** Its generic TypeScript config includes the field, but `generateVideosConfigToMldev` explicitly disallows it. The root agent removed the two Veo seed fields from the still-unfrozen plan and recorded the limitation. Wan seeds were unchanged. There is no caller-seed reproducibility claim for Veo.
- The original collector rewrote a successful raw receipt as a download failure if later parent-wrapper writing failed. That made the stored raw hash unstable and left an existing MP4 blocking recovery. Mutable operation history now lives in atomic `state.json`; successful `receipt.json` and `parent-receipt.json` use write-once atomic file creation.
- `validated-download.json` records the exact bytes before rename. Collection can resume before or after rename, and a missing wrapper can be reconstructed from the immutable successful raw receipt. Completed polling/finalization performs no API request. Source, slot, request, runtime, plan/protocol, and output-byte mismatches fail.
- Submission creates its fixed directory and initial state before the sole API call. The operation response is retained independently in `submission-response.json`, and its name is also logged immediately. A failure with no recoverable operation identity stays explicitly uncertain; the script never submits that slot again. Poll attempts and failed download attempts remain recorded.
- Failed, filtered, malformed, and uncertain terminal operations now return failure status. A second Veo submission requires the exact first slot's successful operation and unchanged output bytes.
- The SDK's Node downloader pipes a response readable into a writer and waits on the writer. A body-stream failure may not follow that completion promise cleanly. Downloads now run in a child process with a 60-second lifetime watchdog and 50 MB file bound; partial attempts remain recoverable using the same generation. The byte guard polls every 100 ms, so transient disk overshoot is possible; oversized final files are rejected.
- The runner calls the complete saved-evidence gate validator, not just a summary flag. The stable API remains `gate_check(path, 'negative-45', recipeFingerprint)`; it independently verifies the expected model/policy/source identities and saved media/window evidence. A fabricated passing summary was rejected offline.

## Evidence and schema

Self-contained offline suite: `scripts/eval-generate-veo-study.test.mjs`, SHA-256 `5f29111e847f72580e33a41674c6b50ec7066d6407a67dc17238e854174d183c`.

Run: `node --test scripts/eval-generate-veo-study.test.mjs` — **12 passed, 0 failed**. Its receipt is `sources/veo-offline-contract-receipt.json`, SHA-256 `3832bc8b2e0ceb5d65fb7083e8adf949ceaa97aae53f6830a9245e2ac376c9ff`. The initial failed test receipt is preserved separately as `sources/veo-offline-contract-initial-failures.json`; it records discovery of the seed mismatch. Tests used mocked fetch responses, artificial non-video bytes, an isolated plan copy for builder schema checks, and sleeper subprocesses. All temporary fixtures were removed; none entered the evaluation corpus. The actual study plans were not edited by this audit agent.

The generated-parent wrapper exactly matches the builder contract: `schemaVersion:1`, `status:'completed'`, `generationSlot`, frozen generation/evaluation hashes, `inputMedia:[]`, `modelId`, `modelRevision:'provider-managed-unpinned'`, `output:{path,sha256}`, and `rawGenerationReceipt:{path,sha256}`. The referenced immutable raw receipt has `status:'succeeded'`, the exact registered `request`, completed unfiltered `operation`, the same slot/hash/output identity, and runtime/source receipts. Paths are relative to the repository root. The actual builder accepted this schema in an offline fixture and rejected a changed raw receipt.

## Remaining limits

These tests establish local request serialization, guard, storage, and recovery behavior. They do not establish current paid API availability, live download success, generation quality, or detector performance. Veo remains provider-managed and its weights/revision are unpinned. A process or storage failure between provider acceptance and durable operation-name recording can remain uncertain; no automatic resubmission is permitted. The script expects the configured API key in its environment and checks a current official pricing receipt before each new submission. The study's negative gate, cost check, and fresh-parent usability checks remain required before later stages proceed.
