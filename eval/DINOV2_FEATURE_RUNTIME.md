# DINOv2 feature runtime contract

Implementation preparation passed twelve offline contracts, including exact synthetic RGB decode/PTS checks and agreement between the pinned processor and the explicit PIL recipe. No pretrained model was constructed or forwarded in those offline tests. See the [test receipt](./sources/dinov2-training-backbone/feature-offline-contract-receipt.json). Subsequently, the official backbone was acquired and the [actual CPU/MPS contract](./runs/dinov2-backbone-contract-v1/contract.json) passed on two fixed synthetic images: maximum absolute difference `2.574920654296875e-05`, relative L2 difference `2.687325965276331e-06`. That numerical result does not measure detection accuracy.

`scripts/dinov2-temporal-features.py` imports without loading Torch or model code. Its public interface is:

- `probe_video(path)` → normalized `timestamps` and `absoluteTimestamps` arrays, `ptsOrigin`, `duration`, `frameCount`, width/height, source hash and probe hash. Native frame indices are array indices. Duration comes from the timestamped video timeline, excluding audio duration.
- `windows_for_probe(probe, mode, stable_parent_hash)` → `{start,end}` windows. Mode is `train` or `evaluation`. The training caller computes the window once from the original and reuses it for every derivative. Alternatively set `originalDuration` to that same original duration before planning each derivative. Evaluation uses two-second windows at one-second stride plus the tail. Videos shorter than two seconds use their full supported duration.
- `load_backbone(model_dir, device='cpu', contract_receipt=...)` → `(model,processor,load_receipt)`. Only the exact pinned local safetensors and config assets load. A successful, matching saved synthetic contract is mandatory for this public loader.
- `extract_window(path,window,model,processor,device)` → `(cls,receipt)`. `extract_windows(...,windows,...,probe=None)` shares one streaming decode across all supplied windows. The selected indexes are floor-linspace across the available native frames inside each half-open interval. All eight must be distinct.
- `save_features(path,cls,receipt)` writes an exclusive NPZ containing only finite FP32 `cls[8,384]`, verifies its safe roundtrip, and creates its immutable `.receipt.json`.

The nested receipt binds source bytes, eight native RGB hashes, selected timestamps, preprocessed tensor hashes, crop geometry, model/config/runtime/source hashes, exact strict loading and the CPU/MPS contract. Decoder PTS and sizes are independently read from ffmpeg showinfo and compared with ffprobe. Whole-window extraction fails on any missing frame, malformed timestamp, mismatch, changed file or bounds violation; no partial window is returned as successful.

Bounds: source 50,000,000 bytes, 16,000,000 native pixels, 30,000 frames, 0.5–120 seconds, at most 128 windows, two frames per model microbatch. Fewer than eight native frames in any requested window is an explicit failure. ffmpeg/ffprobe permit file/pipe protocols only. Probe and decode have time/output caps; the CLI's parent watchdog monitors the owned child process tree at 8 GiB RSS and 300/600/1,200 seconds for acquisition/contract/extraction. **An importing training driver needs its own external process watchdog**, since a native model operation in its process cannot be safely hard-killed by an ordinary Python exception. Source changes after import invalidate the runtime identity.

Prepared commands (do not infer they have run):

```sh
eval/.venv/bin/python scripts/dinov2-temporal-features.py acquire --model-dir eval/models/dinov2-small
eval/.venv/bin/python scripts/dinov2-temporal-features.py contract --model-dir eval/models/dinov2-small --output-dir eval/runs/dinov2-backbone-contract-v1
```

The contract uses two fixed synthetic RGB images, CPU FP32 reference and MPS FP32, with eager attention and frozen weights. Both maximum absolute difference ≤0.003 and relative L2 difference ≤0.001 must pass. Limits cannot change after the result. A failed or unavailable MPS path does not silently switch devices. Actual arrays and immutable receipts are retained. The completed contract's SHA-256 is `c916a1fea7352abd854121d4f4978f1ea522ad96b18d8e1880afefe401786374`; it authorizes the matching feature runtime, not an accuracy claim.

The extractor never accepts labels, generator names or quality names as model inputs. Root's training driver binds its own `id,parentId,split,label,generator,quality,window,sourceSha256` row to the returned feature file/hash and receipt. The feature module does not select training labels, fit a head, determine a detector threshold, or consume calibration/holdout predictions. The 224-square center crop and eight-frame sampling are explicit coverage limits, not claims that every generated pixel or brief insert is inspected.
