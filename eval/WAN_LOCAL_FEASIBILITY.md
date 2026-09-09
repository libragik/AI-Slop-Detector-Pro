# Wan 2.1 local generation feasibility

Status: primary-source and anonymous file-metadata inspection only. No weights downloaded, dependencies installed, or generation performed. This is a possible source of fresh generation receipts, not a validated detector or a measured Mac generation recipe.

## Decision

A concrete CPU implementation path exists using the official **Wan 2.1 T2V 1.3B Diffusers** release. Second-provider credentials are therefore not intrinsically required to attempt independent fresh generation. The complete model is substantially larger than its denoiser: **28,928,887,859 bytes (28.929 GB / 26.942 GiB)** including its text encoder, VAE, tokenizer, and configuration. The weights are public, nongated, Apache 2.0, and available as safetensors. All eight weight-file anonymous HEAD requests returned 200 with lengths matching publisher metadata; no weight bodies were read.

The native Wan implementation assumes CUDA and will not run unchanged on this Mac. Diffusers provides device-parametric Wan inference and a CPU inference test, but that test uses tiny synthetic components. Full-checkpoint CPU and MPS execution, peak memory, image quality, and elapsed time remain **unmeasured** on this M3 Ultra / 256 GB host. General Apple silicon support and MPS-specific code accommodations do not establish a successful full Wan generation.

## Pinned primary sources

| Component | Revision / license | Evidence |
| --- | --- | --- |
| Official model `Wan-AI/Wan2.1-T2V-1.3B-Diffusers` | `0fad780a534b6463e45facd96134c9f345acfa5b`; Apache 2.0 | [Pinned files](https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers/tree/0fad780a534b6463e45facd96134c9f345acfa5b), [publisher metadata](https://huggingface.co/api/models/Wan-AI/Wan2.1-T2V-1.3B-Diffusers/revision/0fad780a534b6463e45facd96134c9f345acfa5b?blobs=true): `gated:false`, `private:false`, built-in Diffusers architecture, safetensors. |
| Official Wan code | `9737cba9c1c3c4d04b33fcad41c111989865d315`; Apache 2.0 | [Repository](https://github.com/Wan-Video/Wan2.1/tree/9737cba9c1c3c4d04b33fcad41c111989865d315) endorses Diffusers integration. [Native pipeline](https://github.com/Wan-Video/Wan2.1/blob/9737cba9c1c3c4d04b33fcad41c111989865d315/wan/text2video.py) constructs a CUDA device and uses CUDA AMP/generator/cache/synchronization; `t5_cpu` alone does not provide CPU generation. |
| Diffusers 0.40.0 | `d035dcd7cc7c88e0a154609b62887d50bba9fdc2`; Apache 2.0 | [Wan API](https://huggingface.co/docs/diffusers/api/pipelines/wan), [CPU test](https://github.com/huggingface/diffusers/blob/d035dcd7cc7c88e0a154609b62887d50bba9fdc2/tests/pipelines/wan/test_wan.py): explicit CPU test with tiny Wan/T5/VAE, 9 frames at 16×16, two steps. This proves an implemented CPU path, not full-weight performance. |
| Apple silicon support | Host macOS 15.6.1 verified | [MPS documentation](https://huggingface.co/docs/diffusers/optimization/mps) is general pipeline guidance, not a full Wan benchmark. [Wan transformer](https://github.com/huggingface/diffusers/blob/d035dcd7cc7c88e0a154609b62887d50bba9fdc2/src/diffusers/models/transformers/transformer_wan.py) explicitly selects float32 rotary frequencies when MPS is available to avoid unsupported float64. |

## Download accounting

The following exact byte totals include each component's weights, indexes, and configuration; they exclude README/demo assets, package installations, caches, and generated media.

| Required component | Bytes |
| --- | ---: |
| Text encoder | 22,723,695,074 |
| Transformer | 5,676,144,409 |
| VAE | 507,592,616 |
| Tokenizer | 21,454,609 |
| Scheduler | 751 |
| Model index | 400 |
| **Total** | **28,928,887,859** |

The eight published safetensors use FP32. Built-in `WanPipeline`, `UMT5EncoderModel`, `T5TokenizerFast`, `WanTransformer3DModel`, `AutoencoderKLWan`, and `UniPCMultistepScheduler` permit loading without remote model code or pickle fallback. A future download should be revision-pinned and verified against each published file digest before loading.

## Execution limits and next gate

- Use a separate, fully pinned generation environment; do not modify the detector evaluation environment. Diffusers 0.40.0 declares Python ≥3.10 and its Torch extra ≥2.6. Its newer Hub requirement may conflict with the existing environment's older Transformers dependency; the complete dependency lock is not established in this read-only check.
- CPU FP32 is the defensible reference implementation for a bounded runtime contract. MPS is an optional acceleration experiment whose full-model operator support and numerical behavior still require testing. The model weight size alone fits the host's memory capacity; this does not bound activation memory or runtime.
- The authors recommend 480p for the 1.3B model. Their approximately four-minute RTX 4090 result for five seconds of 480p output is a CUDA measurement and cannot be transferred to this Mac. No credible Mac wall-clock estimate is established.
- Before full execution, use a bounded loading/short-generation contract with explicit timeout and memory limits. Such a reduced contract is not a representative detector control. Only after it succeeds should a normal, preregistered generation recipe produce controls, retaining exact model/package hashes, prompt, seed, sampler/settings, logs, and output SHA. Keep that new generation family separate from the detector's consumed benchmark when assessing independence.

No local generation success, Mac compatibility guarantee, or new accuracy claim follows from this feasibility check.
