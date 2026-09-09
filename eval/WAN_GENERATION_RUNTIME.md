# Isolated Wan generation preparation

The isolated environment and guarded generator are prepared. **No model checkpoint has been loaded and no model forward pass has run.** This preparation does not establish Mac generation feasibility or detector accuracy. The study must pass its negative and Veo detector gates before any Wan loading.

## Runtime and loading contract

- Interpreter: `eval/.venv-wan`, Python 3.12.9. The existing `eval/.venv` was not modified.
- Input pins: `wan-requirements.in`; complete, hash-locked 45-package resolution: `wan-requirements.lock`. Core versions are Diffusers 0.40.0, Transformers 5.16.1, Torch 2.8.0, Torchvision 0.23.0, Accelerate 1.14.0, Safetensors 0.8.0, and NumPy 2.2.6. `uv pip check` passes.
- Runner: `scripts/eval-generate-wan.py`. It requires the frozen study generation plan and evaluation protocol, with explicit SHA pins. The plan pins the script, dependency lock, and publisher manifest; run receipts preserve these plus prerequisite receipts and critical installed source snapshots.
- Model: `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`, revision `0fad780a534b6463e45facd96134c9f345acfa5b`, at `eval/models/wan2.1-t2v-1.3b-diffusers`. All 19 files must match `sources/wan-model-publisher-manifest.json`, their acquisition receipt, byte counts, and publisher LFS SHA-256 or Git blob identity. Extra files, symlinks, incomplete downloads, and mismatches fail before loading.
- Built-in Wan/UMT5/VAE/tokenizer/scheduler classes load local files only. Every weight loader requires safetensors; Transformers remote code is disabled, and the worker blocks socket connections/name resolution and all `torch.load` calls. There is no network, pickle, adapter, quantization, or random-weight fallback.
- Each component's loading report must be empty. Header keys/shapes/dtypes must match the loaded state. The sole intentional missing serialized alias is UMT5's documented `encoder.embed_tokens.weight → shared.weight`; the runner requires actual shared tensor storage. Full-checkpoint compatibility remains untested, so any unforeseen mismatch stops the contract.
- CPU FP32, four computation threads, one interop thread, deterministic Torch algorithms, fixed text prompts/seeds, no input media, no prompt expansion. The worker records the exact cleaned text, token IDs, masks, scheduler config, latent hashes, output shapes, unclamped decode range, numerical frames, raw RGB frames, MP4, and encoding command/hashes. A finite output is only a technical result; the study's separate usability and detector gates still apply.

## Frozen recipes

| Stage | Dimensions / frames | Denoising | Limits | Use |
| --- | --- | --- | --- | --- |
| Technical contract | 128×128 / 9 | 2 steps | 10 minutes, 64 GiB process-tree RSS | Always excluded from detector evaluation |
| Each of two normal parents | 832×480 / 81 | 50 steps | 30 minutes, 64 GiB process-tree RSS | Fixed study parents, subject to the study's usability gate |

Both use guidance 5, maximum text length 512, 16 fps, and the model's unchanged UniPC scheduler: flow shift 3, flow prediction, flow sigmas, solver order 2, `bh2`, 1,000 training timesteps. These are explicit plan settings. The technical contract has 192 latent patch tokens; the normal recipe has 32,760. Tiny success therefore gives limited evidence about full-size attention memory or elapsed time. The normal timeout is an experimental bound, not a measured runtime prediction.

The supervisor samples the child process tree's RSS every 0.25 seconds and stops its process group on timeout, memory-limit detection, or interruption. This is a polling limit: a transient memory overshoot is possible. A global advisory lock prevents simultaneous generator supervisors. Every run directory is single-use, failures remain recorded, and the second normal run requires the first to have succeeded under the same plan. A failure aborts the fixed study; there is no replacement generation or silent retry.

## Prerequisites and invocation

The SHA-pinned prerequisite receipt must have `status: "passed"`, `completedStages` containing both `negative-45` and `veo-30`, and matching `generationPlanSha256` and `evaluationProtocolSha256`. Its underlying stage-receipt hashes should be retained for audit. The acquisition receipt must include the pinned `modelRevision` (or `revision`) and exactly 19 `records` (or `files`) with `path`, `success: true`, `sha256`, and `bytes`.

After the root agent verifies weights and authorizes execution, the command shape is:

```sh
eval/.venv-wan/bin/python scripts/eval-generate-wan.py \
  --plan eval/fixtures/shot-study-generation-plan.json --plan-sha256 PLAN_SHA \
  --evaluation-protocol eval/AEGIS_SHOT_EVALUATION_PROTOCOL.md --protocol-sha256 PROTOCOL_SHA \
  --gate-receipt GATE_RECEIPT --gate-sha256 GATE_SHA \
  --acquisition-receipt eval/sources/wan-model-acquisition.json --acquisition-sha256 ACQUISITION_SHA \
  --run-id wan-technical-contract
```

Normal `W1` / `W2` additionally require `--contract-receipt` and `--contract-sha256` identifying the successful, excluded technical contract from the same plan. Output locations and settings come exclusively from the frozen plan. Placeholder hashes above are not executable approval and no command above has been run with real model weights.

Successful normal runs emit `parent-receipt.json` beside the raw `receipt.json`. Its fixed fields are `schemaVersion:1`, `status:"completed"`, `generationSlot`, both frozen plan/protocol hashes, `inputMedia:[]`, model ID/revision, `output:{path,sha256}`, and `rawGenerationReceipt:{path,sha256}`; paths are relative to the repository root. The raw receipt has `status:"succeeded"`, `stage:"normal"`, exact normalized parameters in `run`, and the same model/slot/output identity. The parent receipt references the raw receipt without a hash cycle. Technical contracts never emit a parent receipt.

## Verification performed without model inference

- Import and complete dependency-version checks: `runs/wan-runtime-imports-v2/runtime.json` (`modelLoaded:false`, `forwardCalls:0`).
- Operational guards: `sources/wan-generator-guard-checks.json`. Missing prerequisites, changed recipe, path escape, nonempty loading reports, and reused output reject. Short-lived sleeper subprocesses were stopped by the time/RSS watcher; they did not load models.
- Offline, pickle, and nonfinite tensor guards: `sources/wan-offline-guard-checks.json`. No network connection or checkpoint decoding occurred in these rejection tests.
- Final supervisor interruption handling: `sources/wan-supervisor-final-checks.json`; time/RSS/SIGTERM tests all terminated sleeper process groups and retained explicit failure reasons.
- All nine critical installed Python sources matched their official Diffusers release commit / Transformers 5.16.1 tag byte for byte: `sources/wan-runtime-source-verification.json`. This check read 693,448 bytes of primary source and no weights.

Primary release/access evidence and exact download accounting remain in [WAN_LOCAL_FEASIBILITY.md](WAN_LOCAL_FEASIBILITY.md). No reduced-quality contract output may be substituted for a normal parent, and no output from this preparation has entered a detector cohort.
