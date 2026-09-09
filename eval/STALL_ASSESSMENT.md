# STALL access and feasibility assessment

**Technically plausible on this Mac, but not available for the current unrestricted integration path.** The implementation is noncommercial and its required official DINOv3 weights need access approval and contact-information sharing. No weights, calibration arrays, or benchmark embeddings were downloaded; no model calls, account creation, terms acceptance, or contact submission occurred.

## Verified access and licensing

- Official STALL source revision: `bfcc603ae83b4e609681277b9b5e80e7a9497e15`. Its license is **CC BY-NC 4.0**, not MIT/Apache. The provided VATEX parameters are distributed in the same repository; no separate permissive parameter license was found. Commercial use would need an appropriate license from the rights holder. [Official license](https://github.com/OmerBenHayun/STALL/blob/bfcc603ae83b4e609681277b9b5e80e7a9497e15/LICENSE.txt).
- Required backbone: `facebook/dinov3-vitl16-pretrain-lvd1689m`, revision `ea8dc2863c51be0a264bab82070e3e8836b02d51`. Official HF metadata reports a **manual gate**. Anonymous HEAD of `model.safetensors` returned **401 / GatedRepo**. The form requests identifying/contact information and acceptance of Meta's terms. The checkpoint exists as safetensors: 303,129,600 FP32 parameters, approximately 1.21 GB of tensors. [Official model card](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m).
- DINOv3 uses its own license, with use/redistribution conditions; it is not an Apache/MIT checkpoint. Its official alternate download process requires approval before emailing model URLs. No gate-free official weight route was established. [DINOv3 license](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md), [official download instructions](https://github.com/facebookresearch/dinov3#pretrained-models).
- `precomputed/stall_params_vatex_dino_v3.npz` is publicly accessible: anonymous HEAD returned 200 and Content-Length 16,820,270 bytes. This only removes the need to re-fit whitening; it does not remove the DINOv3 dependency for new pixel inputs. [Official parameters](https://github.com/OmerBenHayun/STALL/blob/bfcc603ae83b4e609681277b9b5e80e7a9497e15/precomputed/stall_params_vatex_dino_v3.npz).

## Runtime and format

The stock CLI selects CUDA when available and CPU otherwise; it does not automatically select MPS. The model wrapper accepts a device string and the likelihood/percentile calculations use NumPy, so a bounded Mac CPU evaluation appears feasible. MPS would need a small, audited adapter and an actual numeric/runtime contract test. No latency or memory claim has been measured for STALL here. [Official runtime](https://github.com/OmerBenHayun/STALL/blob/bfcc603ae83b4e609681277b9b5e80e7a9497e15/src/eval.py).

The installed isolated environment has Torch 2.8.0, torchvision 0.23.0, Transformers 4.57.6, safetensors 0.8.0 and NumPy 2.2.6. Meta documents Transformers support from 4.56.0. The official STALL loader uses a local Meta repository plus `.pth` weights; a safetensors/Transformers path therefore needs equivalence checks, not simply substitution. In particular, retain STALL's exact square 224-pixel preprocessing and class-token embedding before applying the supplied whitening matrices. Do not replace it with a library's default resize/crop or a different DINO backbone. [DINOv3 support](https://github.com/facebookresearch/dinov3), [STALL loader and preprocessing](https://github.com/OmerBenHayun/STALL/blob/bfcc603ae83b4e609681277b9b5e80e7a9497e15/src/stall.py).

## Calibration and test separation

The authors report that VATEX's 33,976 real clips are separate from their VideoFeedback, GenVideo and ComGenVid evaluation benchmarks. That is a documented authors' claim about those benchmarks, not proof of separation from every future corpus. The released parameter file contains fitted quantities; no per-clip VATEX index was found in the repository tree. Our GenBuster camera/source IDs are insufficient to rule out overlap with older public-video collections. A future test built from newly recorded camera footage and independently generated clips with retained receipts could establish cleaner separation. [Primary paper, calibration details](https://arxiv.org/html/2603.15026v1).

Their standard experiment samples sixteen frames from two seconds at 8 fps. The stock local-directory mode instead uses native fps and duration, so it is not the same protocol. The paper tests JPEG, blur, crop and noise perturbations; these do not establish performance after H.264 Instagram processing. Published AUROC/AP and real-calibration percentiles are not calibrated probabilities or demonstrated recall at a low deployment false-positive rate. [Primary paper](https://arxiv.org/html/2603.15026v1).

The official precomputed ComGenVid embeddings can run without the backbone, but that would only reproduce an existing embedding benchmark. It would not test new video pixels, the user's Instagram failure, or our simulated reposts. [Official input modes](https://github.com/OmerBenHayun/STALL#-usage).

## Concrete next gate

Before any new download or implementation: resolve the noncommercial implementation/parameter license and obtain authorized access to the exact Meta backbone. If those are available, freeze the supplied parameters, exact preprocessing and sampling, validate safetensors/native feature equivalence on two development clips, then measure development recall/FPR on originals, matched transformations and CGI/mixed controls. Only a successful candidate warrants a new untouched test set. No production integration is supported by this read-only assessment.

Machine-readable access receipts and inspected source hashes: `sources/stall-access-assessment.json`.
