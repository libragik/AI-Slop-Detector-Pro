# Conditional extraction resource continuation

This is a read-only contingency review written while the original extraction is running. It does **not** establish that the run timed out, amend its limit, authorize an unmonitored worker, or report fitting/diagnostic results. No live process, cached feature, or media was inspected or changed for this review. No additional tests or model calls were made.

The frozen protocol remains `eval/fixtures/dinov2-temporal-protocol-v1.json`, SHA-256 `58812dcdde8f2ceaa7999f63a1aa81e477bf67c5049a17cd05fe5ba89050b41c`; the freeze receipt is `eval/runs/dinov2-temporal-v1-freeze/receipt.json`, SHA-256 `bf47b50381554deacc374442c4534826e686a443ef8ea7ef73b268eb3a3060d5`.

## Verified behavior

- The feature driver (`750a2230…`) sums `watchdog-*.json` elapsed times and passes that total into a hard 7,200-second/8-GiB supervisor. At or above 7,200 seconds, normal `--resume` rejects before spawning its worker. Changing only the protocol's limit would not work: the driver's limits are literals. The worker also has a 7,200-second per-invocation check. See `scripts/build-dinov2-training-features.py:117`, `:299`, and `:345`.
- Resume requires the exact original configuration and an absent `manifest.json`. It walks the original parent order, probes each original again, verifies completed derivatives and feature wrappers, and reuses their arrays. A derivative without its receipt or an NPZ without its wrapper causes a stop; existing valid files are not overwritten. Paths and encoding command arrays bind the existing cache location, so moving completed work into a different run directory is not a transparent resume. See the same driver at `:194`, `:230`, and `:258`.
- Feature JSON and NPZ publication is exclusive but not atomic. A hard stop can leave a partial derivative, NPZ, wrapper, or final manifest. Valid prior work must be distinguished from the interrupted frontier; “file exists” is insufficient.
- Trainer `36b405e3…` validates the complete 6,912-row cache, source hashes, acquisition allocation, media/array/wrapper bytes, numerical runtime identity, and extraction evidence. It does **not** require a successful feature-watchdog terminal. Evaluator `c119fe95…` repeats that cache check and strictly requires successful **training** supervision; it also has no separate feature-watchdog prerequisite. See `scripts/train-dinov2-temporal.py:373` and `scripts/eval-dinov2-temporal.py:305`.
- Original launcher `071ff5b8…` provides the feature success gate: nonzero child exit or missing manifest stops it before training. Its output directory is single-use, so rerunning that launcher is not the continuation path. Its failed stage record must remain failed.

## Smallest transparent recovery, only after an actual terminal timeout

Keep every frozen executable and the original protocol byte-identical. Use one small **new, separately pinned coordinator** and a resource-amendment sidecar; neither exists as a consequence of this document. This avoids changing preprocessing, samples, labels, splits, weights, feature values, head training, or thresholds merely to extend elapsed time. The assistant-selected operational cap can be prospectively amended before fitting; the original 7,200-second attempt must still be reported as resource-failed.

1. Require the original supervisor and launcher terminal records, an actual `cumulative_wall_time_limit` stop, and confirmed cleanup of that owned process tree. Require training and diagnostic outputs to be absent. A memory failure, decoder error, unexplained missing terminal, or earlier invalid receipted artifact needs its own diagnosis and is outside this timeout contingency.
2. Seal the failure point before any mutation: inventory every existing cache/configuration/source/watchdog file with path, bytes, SHA-256, and parse/validation status; retain copies or a read-only copy-on-write snapshot of those exact bytes plus the original launcher records. Record completed parent/quality IDs and the interrupted slot. Leave all valid cache paths and bytes in place. Do not rename/delete a failed watchdog, reset elapsed counters, or replace any original terminal receipt.
3. Only at the interrupted frontier, quarantine uncommitted or partial files under a new run-specific directory, with exclusive destination creation and a move journal binding original path, new path, bytes, hash, parent/quality, and reason. This includes an orphan derivative and its partial receipt, or an NPZ and incomplete wrapper. Never quarantine a previously valid wrapper merely because its hash/recipe now disagrees: that is an integrity failure. Any uncertain association stops recovery. A valid completed derivative may be retained while only its uncommitted feature pair is quarantined.
4. If a final manifest exists, first validate it fully. A complete valid manifest requires no repeated extraction, even if the original watchdog stopped after publication; retain the resource-failure label and proceed only through the separately receipted amended completion gate. A partial/uncommitted final manifest may be quarantined with evidence before resume. Never overwrite it or fabricate missing feature receipts.
5. Freeze the sidecar and coordinator before continuation. A bounded proposal is **one cumulative 10,800-second feature budget**, including all original supervised elapsed time, with the same 8-GiB tree limit. This is at most about one additional hour, not a reset to three more hours. The sidecar must bind the original protocol/freeze/source hashes, original terminal and inventory hashes, cache path/configuration hash, allowed quarantine records, exact worker arguments, coordinator source hash, original elapsed total, new cumulative cap, and unchanged model/data/training/gate recipe. Any later extension is outside this proposal.

The proposed coordinator would call the existing pinned driver's `supervise` function with `timeout_seconds=10800`, `memory_limit_bytes=8589934592`, and `prior_elapsed_seconds` equal to all previous supervised extraction time. Its **internally supervised** worker argv would be:

```text
eval/.venv/bin/python scripts/build-dinov2-training-features.py
  --protocol eval/fixtures/dinov2-temporal-protocol-v1.json
  --output eval/runs/dinov2-training-features-v1
  --resume --worker
```

Do not run that worker directly. A new coordinator must write exclusive running/terminal journals in its own resource-amendment run directory, preserve failures and cleanup details, and reject an unfinished prior continuation journal. It should not insert an amended record into the original driver's `watchdog-*.json` namespace or silently change what those records mean. The frozen worker's per-invocation 7,200-second check remains untouched and is looser than the proposed remaining allowance.

## Mandatory continuation gate before fitting

Require successful bounded continuation termination (zero exit, no stop/cleanup error, complete manifest, cumulative elapsed and tree RSS within the amended bounds), or the explicitly recorded complete-manifest/no-extra-extraction branch above. Rehash all pre-existing valid artifacts against the sealed inventory and require their bytes unchanged. Then call the existing `trainer.load_cache` on the final manifest and original protocol: exactly 2,304 acquired parents × all three qualities, with all original identities and complete extraction evidence. This is cache validation, not another backbone forward pass.

The new coordinator must enforce that gate itself because direct trainer/evaluator calls do not enforce feature resource completion. After it passes, the already frozen CLI commands remain:

```text
eval/.venv/bin/python scripts/train-dinov2-temporal.py train
  --protocol eval/fixtures/dinov2-temporal-protocol-v1.json
  --features eval/runs/dinov2-training-features-v1/manifest.json
  --output eval/runs/dinov2-temporal-training-v1

eval/.venv/bin/python scripts/eval-dinov2-temporal.py
  --protocol eval/fixtures/dinov2-temporal-protocol-v1.json
  --features eval/runs/dinov2-training-features-v1/manifest.json
  --training eval/runs/dinov2-temporal-training-v1
  --output eval/runs/dinov2-temporal-diagnostic-v1
```

These command displays are argument layouts, not instructions to execute now. Training retains its original 1,800-second/8-GiB supervisor; diagnostics retain 3,600 seconds/8 GiB and all 153 fixed cases. The coordinator stops on any unsuccessful stage and records the amendment hash alongside each new stage terminal. Do not amend the original launcher to claim completion.

The eventual report must distinguish **original numerical/data recipe, resource-amended execution** from success under the original resource cap. A completed extension would establish neither detection accuracy nor independent validation. There is no threshold adjustment, checkpoint selection, diagnostic omission, calibration access, or permission requirement introduced by this readiness note.
