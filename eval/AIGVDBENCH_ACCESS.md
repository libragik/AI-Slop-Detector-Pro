# AIGVDBench / DeCoF access audit

Checked 2026-09-04. This was an access and static source audit only: no detector inference, accounts, terms acceptance, installations, or full checkpoint downloads. Individual retrieved bodies were bounded below 2 MB; only 65,536 checkpoint bytes were retrieved.

**Decision: an actual public video-specific checkpoint exists. It is a concrete research lead, but this audit does not establish a licensed, reproducible Mac detector ready to evaluate or integrate.** Code licensing and the updated checkpoint's precise inference configuration remain unresolved. No production changes were made.

## Exact released candidate

The [official AIGVDBench paper](https://arxiv.org/abs/2601.11035) links [LongMa-2025/AIGVDBench](https://github.com/LongMa-2025/AIGVDBench). That repository's README still describes a future weights release, but its linked Hugging Face repository already contains **Weights/DeCoF.tar**. The author's [DeCoF README](https://github.com/LongMa-2025/DeCoF/blob/5f73e8dc4f8cd9faeed07d767c9517e3f2c66044/README.md) explains that the original pretrained weights were lost during server migration and directs readers to AIGVDBench for newly trained models.

| Item | Verified value |
| --- | --- |
| Model | DeCoF, a temporal frame-consistency detector, newly trained for the updated dataset; not the unavailable original paper checkpoint |
| Published artifact | [AIGVDBench/AIGVDBench — Weights/DeCoF.tar](https://huggingface.co/datasets/AIGVDBench/AIGVDBench/tree/bf48acaa4920990af3dd2a511ea88e63354df305/Weights) |
| HF revision | `bf48acaa4920990af3dd2a511ea88e63354df305` |
| Published size | 56,815,450 bytes |
| Published LFS SHA-256 | `4edb7b310cc729771e74b93f658c7fdc4f2e31fdfa617a88372a540d4f9e7b4a` — server metadata, not independently verified against the full file |
| Access | API reports `private: false`, `gated: false`; anonymous range GET returned HTTP 206 and exactly bytes `0–65535/56815450` |
| AIGVDBench source revision | `e38c75abda3d319c0c3072c77594f6eeef1c028f` |
| DeCoF source revision | `5f73e8dc4f8cd9faeed07d767c9517e3f2c66044` |

Despite its `.tar` extension, the range begins with a PyTorch ZIP checkpoint. Static `pickletools` disassembly reaches the end of its 8,607-byte `data.pkl` record without deserializing it. It contains model keys for positional embeddings, two transformer layers, and a classification head, plus optimizer state. The model-key names correspond to the official `ViT` head. Only ordinary PyTorch tensor-storage and `OrderedDict` globals appear in that record. This is evidence of a trained parameter archive, **not a completed safe load or exact tensor-shape compatibility test**. A subsequent authorized download must verify the full hash and load with `weights_only=True`, `map_location="cpu"`, without broad allowlisting or unsafe pickle fallback.

## License boundary

The [official HF dataset repository](https://huggingface.co/datasets/AIGVDBench/AIGVDBench) declares `cc-by-4.0`. Its card is only license front matter, with no separate checkpoint model card or narrower weight-specific conditions observed. This is the available license declaration for the hosted artifact; it should be preserved with attribution.

Both complete GitHub trees contain **no LICENSE file**, and both GitHub APIs return `license: null`. The DeCoF code's README describes research use but supplies no explicit code license. The HF license declaration does not establish a license for the separately hosted GitHub implementation. Therefore this check **cannot confirm the requested complete commercial/evaluation license for code plus weights**. An explicit license for the DeCoF implementation, or another independently licensed faithful implementation, is needed before calling this a usable licensed detector. Paper access and reported benchmark accuracy do not resolve that gap.

## Mac feasibility and fidelity

The [official model](https://github.com/LongMa-2025/DeCoF/blob/5f73e8dc4f8cd9faeed07d767c9517e3f2c66044/src/model.py) freezes CLIP ViT-L/14 and feeds eight 768-dimensional frame features into a [two-layer transformer head](https://github.com/LongMa-2025/DeCoF/blob/5f73e8dc4f8cd9faeed07d767c9517e3f2c66044/src/vit.py). The inspected inference path uses standard PyTorch operations; no required custom CUDA extension was found. CPU/MPS portability is plausible, not runtime-verified.

The supplied runner is CUDA-only as written: `src/test.py:38` selects CUDA; `src/model.py:20` and `src/vit.py:98` allocate CUDA tensors directly. Its checkpoint loader at `src/test.py:48` does not explicitly select safe loading or CPU remapping. Running it unchanged on this Mac is not appropriate. A faithful bounded adapter would require device-neutral allocations, safe loading, and a CPU/MPS agreement check.

The 56.8 MB archive is the temporal head and optimizer, **not the complete detector**. `src/clip_models.py:15` separately loads CLIP ViT-L/14; the bundled loader points to the official OpenAI backbone and can download it automatically. That backbone was not downloaded or executed in this audit.

Preprocessing must not be improvised. The [DeCoF paper](https://arxiv.org/html/2402.02085v8#S5.SS1) and README specify eight evenly selected frames from the **first 32 source frames**, centered into squares. The test dataset implementation then resizes to 224×224, converts RGB to tensors, and uses **ImageNet mean/std**, not CLIP's default preprocessing (`src/utils/data.py:132–143`; `src/clip_models.py` says its returned CLIP preprocessing is unused). Its supplied test code uses class 1 softmax for fake and argmax for the label.

AIGVDBench contains no corresponding new training/inference configuration, and the single HF checkpoint has no model card identifying the exact training subset, frame-index rounding, JPEG extraction settings, or whether preprocessing changed from the older DeCoF implementation. The paper's default Open-Sora training setup is insufficient to attribute this particular file to an exact run. The head's matching key names do not resolve those uncertainties. The older first-32-frame recipe also examines only about 1.33 seconds of a 24 fps video; it is not whole-video coverage for later synthetic inserts.

## Preserved evidence and next gate

Static snapshots and request hashes are in `eval/sources/aigvdbench-access/`: `retrieval-receipt.json`, `decof-source-receipt.json`, `decof-code-receipt.json`, both repository trees, HF metadata, `decof-range-receipt.json`, and `decof-checkpoint-static-audit.json`. Source files were read as text; checked-in `.pyc` files were neither fetched nor executed. No claim about local accuracy, social compression robustness, latency, or safe model loading follows from this access check.

The next useful gate is an explicit code license and authoritative configuration for this exact checkpoint. With those established, a separately authorized full-hash download, safe tensor conversion, and two development clips on CPU/MPS could establish the runtime contract before a frozen development evaluation. This audit did not begin that experiment.
