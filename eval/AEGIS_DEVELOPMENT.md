# Aegis known-origin development screen

**Aegis detected the fully generated control but missed the mixed control. The preregistered gate failed, so the 105-file second stage was not run.** No production change, threshold fitting, or alternate checkpoint/branch/sampling test followed these results.

The [frozen protocol](./AEGIS_EVALUATION_PROTOCOL.md) required the whole generated clip and the CGI clip containing a two-second generated insert to be positive, and conventional CGI to be negative, with no processing errors. These three files share one directly generated Veo output and one Sintel CGI source. Their [generation and edit receipts](./GENERATED_ORIGIN_CONTROL.md) establish this diagnostic's origins; three related files are not a population accuracy sample.

## Results

The sole decision rule was main fused score **≥ 0.5**. Scores below are uncalibrated outputs, not probabilities.

| Control | Main score | Raw logit | Decision | Per-clip time |
| --- | ---: | ---: | --- | ---: |
| Entire generated clip | 0.9999158382 | 9.3827200 | AI detected | 1.493 s |
| Conventional CGI | 0.0000850057 | −9.3727074 | No AI detected | 1.481 s |
| CGI with generated insert | 0.0000446887 | −10.0157461 | No AI detected — missed | 1.624 s |

All three completed without errors. Each submitted input was an eight-second, 192-frame, 24 fps, silent 1280×720 derivative. Aegis used the official centered four-second window: 16 RGB frames resized to 224×224 and ImageNet-normalized, CPU FP32, four PyTorch threads, batch size one. Per-clip timing includes file validation, decoding, preprocessing and inference, but excludes model/runtime setup. These three short clips are not a production capacity benchmark.

## The generated insert was sampled

For the mixed file, **8 of 16 input frames fall inside the declared generated interval [3, 5) seconds**: source indices `73, 79, 86, 92, 98, 105, 111, 117`. Both nominal index/FPS times and recorded decoder timestamps place these frames inside the interval. The input contained generated content; this failure cannot be explained solely by the window missing the insert. It does not identify which internal feature or aggregation mechanism caused the wrong decision.

The mixed score is also lower than the CGI-only score. For these saved scores, any single threshold that marks high scores positive and detects the mixed clip would also flag this CGI control. This is an ordering property of the recorded outputs, not a fitted threshold or a claim about other videos.

Centered sampling intersects this particular insertion. A successful result would not have established detection of arbitrary-position short inserts, and this failure does not measure performance across other insert durations or scenes. The model card targets fully generated videos; mixed footage remains a challenge required by our intended application.

## Verified execution and stopped scope

The [compact audit summary](./sources/aegis-control-summary.json) independently checks input hashes, exact main scores/logits, saved output/receipt hashes, every source-snapshot hash, the recorded timm source hashes, and unchanged runner/weights. Strict loading supplied all **467 state tensors**, including **174 DINO backbone tensors**, with no random-weight or unsafe-pickle fallback. The published all-axis FFT behavior was preserved at batch size one; this does not reproduce multi-video batching behavior in the authors' benchmarks.

- Protocol SHA-256: `bde1f478fa3c2346cd8da014825f421f66376a31a4a88cbc6d216adc3987f171`.
- Runner SHA-256: `1390d13e5b54f0122316e672a0c0456f2602ee02ec68ada328dd3b1d50578838`.
- Recipe fingerprint: `98af59d1f2657a272d574d59e3560ea1ec7c60b88949fbb362e6ebd4697ecff9`.
- Raw output SHA-256: `8b56ea584a60729d2e8573c14897d0192a9a601f285eec309daea452f6b3b372`.
- Raw outputs and immutable source snapshot: `eval/runs/aegis-controls-v1.jsonl`, its `.receipt.json`, and `eval/runs/aegis-controls-v1.source/`.

A metadata-only invocation of the frozen runner's `validate_gate` rejected the completed results, as required. That audit imported no Torch, timm, OpenCV, or model module and performed no model forward call. Stage 2's 35 development originals and 70 derivatives remain unrun for Aegis. Our calibration allocation and consumed holdout were not evaluated in this candidate screen.

The whole-generated detection is a concrete successful diagnostic where the frozen Gemini tool previously missed the same derivative. It is not evidence of general superiority: Aegis still failed the mixed requirement. The authors' GenBuster-related checkpoint selection and unresolved data lineage also prevent treating their benchmark scores as independent evidence for our corpus. This candidate stopped under its declared rule; any future representation study needs a new protocol and fresh, documented-origin evaluation before accuracy or deployment claims.
