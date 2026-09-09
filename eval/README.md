# Detector evaluation

This corpus and harness measure detector behavior. A successfully downloaded clip or a passing software test does not establish detection accuracy.

## Public repository contents

This directory publishes the evaluation code, manifests, plans, and summarized research. Downloaded media, model weights, virtual environments, raw provider runs, and temporary dataset archive fragments remain local and are ignored by Git. Links into `runs/`, `media/`, `models/`, or `vendor/` refer to artifacts that are not in a fresh clone.

For publication, personal filesystem paths in saved records were made relative or replaced with tool names, and private provider resource identifiers were redacted consistently. Media hashes and measured outcomes were preserved. The redacted records are not byte-identical copies of the original frozen records, so their historical document/protocol checksums must not be treated as checksums of these public copies. Retain the guards in research scripts and create a new, independently reviewed evaluation plan when reproducing an experiment; do not bypass a checksum mismatch or replay an old paid execution blindly. The application and its offline tests do not require the excluded local artifacts.

Latest development checks: [AEGIS known-origin controls and failed mixed-content gate](./AEGIS_DEVELOPMENT.md), [direct generation and short-insert failures](./GENERATED_ORIGIN_CONTROL.md), [corrected native SPAI adaptation](./SPAI_ADAPTATION_AUDIT.md), [CORVI results](./CORVI_DEVELOPMENT.md), [mixed-control sampling qualification](./MIXED_CONTROL_PROVENANCE.md), [all derivative cadence verification](./TRANSFORM_RECIPE_AUDIT.md), and [the next-candidate decision](./RESEARCH_DECISION.md). These do not rescue the failed holdout accuracy comparison below.

The [frozen holdout comparison](./HELDOUT_RESULTS.md) found **no detection improvement**: the preserved baseline detected 26/39 AI clips with 0/36 false positives; the final policy detected 23/39 with 2/36 false positives and one AI abstention. Final policy 2.8 was replayed over frozen 2.7 observations after an explicitly recorded pre-unsealing amendment; every score field and decision remained identical. See the report for intervals, paired outcomes, latency, pass status, provenance limits, and exact source hashes. This holdout is now consumed and must not become a tuning set for a new accuracy claim.

## Corpus and ground truth

- `smoke-manifest.jsonl`: 35 development clips (23 author-labeled generated videos, 12 author-labeled real). Every clip is development-only, including when it appears in the expanded manifest.
- `manifest.jsonl`: 230 originals, 115 author-labeled real and 115 author-labeled generated, five from each of 23 generator buckets. Includes benchmark versions of Seedance 2.0, Kling 2.6, Sora 2, Veo 3.1, and Gen-4.5. This is not evidence of coverage of all releases/settings of those generators.
- `transformed-manifest.jsonl`: the same 230 originals plus two derivatives per original. Mild: scale at most 720 pixels wide, 24 fps, H.264 CRF 28. Severe: crop 15%, scale at most 360 pixels wide, 12 fps, CRF 36, top overlay bar. Audio removed in derivatives. These are controlled simulations, not actual social platform reuploads.

The source is the authors' [GenBuster-Bench](https://huggingface.co/datasets/l8cv/GenBuster-Bench), pinned to revision `68e41ab55726013f1c7455980180114302196c23`; [official project](https://github.com/l8cv/BusterX). Dataset card license: MIT. Each manifest row preserves its archive member, pinned download URL, label evidence, SHA-256, original source identifier, media properties, generator, transformation, and split. The files have opaque names, and truth metadata never enters the model adapter.

**Ground-truth limitation:** “real” here means the dataset authors placed the clip in their real category. Original camera provenance, creator IDs, and prompt IDs are not provided per clip. Our harness copies those author labels rather than inferring labels with a model; it does not independently authenticate camera origins. For all 230 originals, the archive filename stem used in `groupId` equals the original file's SHA-256; derivatives retain that ancestor's group. No same-stem aliases occur across generator directories in the pinned archive. These are registered file-identity groups, not verified semantic sources. Cross-creator/prompt leakage cannot be ruled out without better metadata. A separate, camera-authenticated and independently generated corpus is still required before strong deployment accuracy claims.

The authors' revised [GenBuster paper](https://arxiv.org/html/2505.12620v8) identifies OpenVid-1M as the real source and describes Wild samples as selected from circulating social videos. Our manifest contains 55 original Wild clips. This adds author-asserted social-source context, but not per-clip social URLs, original camera provenance, or a controlled platform round trip. See [BusterX assessment](./BUSTERX_ASSESSMENT.md) for the current training/evaluation separation and the decision not to pursue that gated checkpoint.

**Coverage gaps:** original source labels do not adequately cover conventional CGI/VFX, mixed clips, all current generator versions, or actual Instagram reposts. Do not treat these groups as tested when their denominators are absent. Do not benchmark BusterX itself on this corpus without checking its training data overlap.

`control-manifest.jsonl` adds six development controls: three conventional CGI excerpts from the same 2010 Sintel trailer and three short AI-insert durations using the same real/generated parent pair. These represent two source scenarios, not six independent videos. See [EVALUATION_RISKS.md](./EVALUATION_RISKS.md) for the independent audit of ground truth, splits, uncertainty, and permissible accuracy claims.

Selection is deterministic pseudorandom by archive member name, with a 20 MB per-clip cap. The cap excludes no MP4 in this pinned archive, whose largest video is 3,203,007 bytes; the public benchmark's curation and encoding can still create selection bias. The nominal split is 40% development / 20% calibration / 40% holdout by registered-group hash; initial smoke groups remain development regardless of hash. Do not inspect holdout predictions to tune prompts, thresholds, sampling, or aggregators. Once used for development, a holdout cannot be reused as an untouched test set.

## Commands

Run from the repository root:

```sh
python3 scripts/eval-download-corpus.py --per-generator 1 --real 12 --manifest eval/smoke-manifest.jsonl --smoke
python3 scripts/eval-download-corpus.py --per-generator 5 --real 115 --manifest eval/manifest.jsonl
python3 scripts/eval-transform-corpus.py
node scripts/eval-run.mjs --manifest eval/smoke-manifest.jsonl
```

The downloader reads only selected ZIP members with bounded HTTP range requests, validates ZIP CRCs, and checks all files with ffprobe. It never expands the 2.18 GB source archive onto disk. Media and run outputs are ignored by Git. Re-running recreates media from the pinned archive.

Actual API execution is opt-in:

```sh
pnpm exec tsx scripts/eval-run.mjs --manifest eval/smoke-manifest.jsonl --run --export analyzeBaselineEvaluationVideo --output eval/runs/baseline-smoke --concurrency 2
pnpm exec tsx scripts/eval-run.mjs --manifest eval/smoke-manifest.jsonl --run --export analyzeEvaluationVideo --output eval/runs/current-smoke --concurrency 2
```

The default adapter is `src/lib/analyzer/evaluation.ts`. The runner loads `.env.local` through Next's `@next/env` first. Adapter contract:

```ts
analyzeEvaluationVideo({ path, mimeType, id, metadata }): Promise<{
  decision?: "ai" | "not_ai" | "abstain";
  verdict: string;
  aiScore?: number;
  confidence?: string;
  // Full pipeline result and token/cost usage may be included and are saved.
}>;
```

`path` and `id` are opaque; `metadata` contains media dimensions/duration/bytes only. Return an explicit `decision` if the app's verdict strings change. Errors are recorded separately, never converted to a negative verdict. Existing experiments are not overwritten. Before requests, the runner saves detector/adapter/prompt source snapshots and an immutable executable bundle. The plan records source hashes, bundle hash, Node version, and a digest of non-secret detector configuration. Workspace edits during a run are reported but do not change its bundled detector. External package versions are pinned in the saved lockfile; provider-side model revisions remain outside local control.

`--resume` only resumes a matching saved source/configuration and validates existing prediction IDs/hashes; use a fresh directory after changing a model/prompt/adapter. `--resume --retry-errors` archives earlier failed rows and retries those clips. Missing credentials can be restored because keys are excluded from the configuration digest. Three consecutive identical errors stop further requests, and errors or unattempted clips produce a nonzero process exit. At concurrency greater than one, already-started requests finish before stopping.

`--split development` is the default. Use `--limit` to bound requests. `--concurrency` accepts 1–4. For saved predictions, `--predictions <jsonl>` generates reports without invoking a model; hashes are checked against manifest truth. Legacy source snapshots from commit `e0188f6` are saved as `baseline-gemini.ts.txt` and `baseline-scoring.ts.txt`.

## Metrics and interpretation

Reports include AI recall, false positives on real/CGI, false negative rate, false-negative contamination among claimed negatives, abstention, coverage, committed accuracy, high-confidence error rate, and completion/errors. `mixed` counts as positive for AI presence; conventional `cgi` counts as negative for generative AI. Abstentions on AI reduce recall, so a detector cannot succeed by calling everything inconclusive. False-negative contamination depends on corpus prevalence and must not be advertised as the deployment probability that a negative result is wrong.

Nominal Wilson 95% intervals accompany binomial metrics; registered-group bootstrap intervals preserve dependence among known original/transformed copies. Existing reports call the latter “source-group bootstrap,” but the grouping is based on original file identity. Bootstrap intervals degenerate with zero observed errors, so report original-file Wilson intervals and sample size as well. Both interval methods and paired-test p-values depend on independence assumptions that undocumented camera/creator/prompt lineage cannot verify. They do not establish population coverage or rule out semantic-source leakage. All reports break results down by label, generator, dataset, split, transformation, and platform. Scores remain uncalibrated, and no score is turned into an empirical probability by this harness.

Offline verification (zero model requests):

```sh
pnpm exec vitest run eval/metrics.test.mjs eval/runner.test.mjs
node scripts/eval-run.mjs --manifest eval/smoke-manifest.jsonl --adapter eval/fixtures/contract-adapter.mjs --run --limit 2 --output eval/runs/contract-check
```

The fixture always abstains and exists only to test execution, label isolation, and reporting. Its results are not detector evidence.

`scripts/eval-replay-scorer.mjs` provides an offline deterministic score replay into a new directory, retaining the original model observations, collection identity, usage, and latency. It snapshots and bundles the current scorer and records every changed score field separately. An explicit `--unseal` is required before reading saved run files, and existing experiment directories are never overwritten. This is a scorer replay, not a new media/model evaluation. Verify that its source matches the frozen policy before use; the complete heldout replay receipt is in the final comparison report.

## Local specialist experiments

These are isolated development experiments; none of these models is in the product. Raw scores are not probabilities. The primary comparison uses 125 development originals (61 AI, 64 author-labeled real); calibration and holdout predictions remain untouched by these experiments.

| Candidate | AUROC | AI recall at approximately 5% observed development FPR | Result |
|---|---:|---:|---|
| D3 temporal statistics, official BGR convention | 0.493 | 14.8% | Reject for this corpus |
| D3 RGB ablation | 0.445 | 9.8% | Reject for this corpus |
| SAFE wavelet image detector, eight frames / mean logits | 0.712 | 8.2% | Insufficient low-FPR recall; no production integration |
| SPAI spectral image detector, eight frames / mean logits | 0.849 | 44.3% | Complementary on originals, but default detection collapses on simulated reposts; fusion not validated |

The thresholds in this table were chosen on development negatives and are diagnostic, not validated deployment thresholds. SAFE at its default zero-logit threshold has 26.2% recall and 9.4% FPR. On the initial Gemini smoke failures, SAFE corrects two missed AI clips but introduces two false positives among twelve real clips; a simple OR ensemble is not an established improvement.

The table's SPAI results used the earlier bounded center-crop adapter. A later [implementation audit and faithful native-frame check](./SPAI_ADAPTATION_AUDIT.md) removed that shortcut while retaining official patch attention. It still failed the robustness gate: 8/23 original AI clips, 0/23 mild derivatives, 0/23 severe derivatives and 0/3 mixed controls detected at the unchanged zero threshold. This follow-up contains development data only; no production integration or additional threshold variants followed it.

SPAI's AUROC source-group bootstrap 95% interval is 0.772–0.914. At its default zero-logit threshold, recall is 22/61 (36.1%) and FPR is 3/64 (4.7%). At the development-selected threshold `-1.9279261827468872`, with strict `score > threshold`, recall is 27/61 (44.3%, Wilson 95% 32.5–56.7%) at the same three false positives (Wilson 95% FPR 1.6–12.9%). SPAI at the default threshold detects the Kling 2.5 Turbo and HunyuanVideo clips missed by the first improved Gemini smoke run, without false positives among the twelve smoke real clips. This is a development observation, not proof of fusion performance or statistical improvement.

The explicit exploratory OR rule is: positive if the saved Gemini policy result is AI or SPAI mean logit exceeds zero; otherwise preserve Gemini's negative/abstention. On the first 35 development smoke clips this yields TP 19 / FN 2 / AI abstentions 2 / FP 0 / TN 12. The gain must not be presented without its small-sample limits or the following robustness failures.

SPAI at the same default threshold on six controls correctly leaves all three Sintel excerpts negative, but detects only one of three mixed inserts. Mean logits for 0.5s / 1s / 2s inserts are −0.134 / +0.294 / −0.047. Sparse uniform frame sampling can miss a short insert, and averaging scores can dilute local generated content. Positivity alone does not establish that the model localized the inserted segment.

On two controlled derivatives of each of the 35 development smoke sources, SPAI detects **3/23 mild recompressed AI clips and 0/23 severe repost AI clips**, with 0/12 real false positives in each transform. The combined ranking AUROC remains 0.751 (bootstrap 95% 0.597–0.884), but threshold-zero detection is inadequate for these social simulations. This prevents treating the original-clip fusion result as evidence of a reliable Instagram detector. These 70 rows represent 35 sources and are all development.

[D3](https://github.com/Zig-HS/D3) is pinned to commit `c798fbc57fe0c4198d63a73732c2c0f9e4b4816c` (MIT); encoder `microsoft/xclip-base-patch16` revision `d6184e3fd8780d04c85d0f1eabe5f94bf44d98f6` is loaded from safetensors with remote code disabled. The adaptation uses a deterministic two-second center window instead of random windows and raw video decoding instead of intermediate JPEGs, so this is not an exact reproduction of published metrics. The official raw D3 statistic increases toward real; this runner negates it for AI ranking.

[SAFE](https://github.com/Ouxiang-Li/SAFE) is pinned to commit `4e998724651b227def64f5be0cd60c0aa1552c35` (Apache-2). Original checkpoint SHA-256: `b3f5ecfb46a154ed553aaaf4bf3ba59182310726ddb0cbb1fe42bd0e22d2f20e`. Its restricted `torch.load(weights_only=True)` succeeded with a tensor-only dictionary, converted locally to safetensors. The audited official model runs on MPS; eight uniform native-resolution center crops at 256 pixels adapt image inference to video, using mean frame logit differences. Model scores cannot establish whole-video authenticity, especially for mixed or spatially localized content.

Reproduce in the ignored project environment (no system Python changes):

```sh
uv venv eval/.venv --python python3
uv pip install --python eval/.venv/bin/python torch==2.8.0 torchvision==0.23.0 transformers==4.57.6 opencv-python-headless==4.12.0.88 pytorch-wavelets==1.3.0 PyWavelets==1.8.0 kornia==0.8.2 setuptools==80.9.0
eval/.venv/bin/python scripts/eval-d3.py --color bgr --output eval/runs/d3-new.jsonl
eval/.venv/bin/python scripts/eval-safe.py --output eval/runs/safe-new.jsonl
```

[SPAI](https://github.com/mever-team/spai) (Apache-2 code and weights) is pinned to commit `8ff7b3b6779b4fcb43cf313471d9cb1c62d129a4`. The authors' [934,865,338-byte checkpoint](https://drive.google.com/file/d/1vvXmZqs6TVJdj8iF1oJ4L_fcgdQrp_YI/view) downloaded successfully (SHA-256 `24159f27d7c8c2cd0cb6c4019189eb89ad0874a0d9d15f8dc9afd39ca9648a55`). Default restricted loading rejected its serialized `yacs.config.CfgNode`. Static scanning found only that unsupported class; after auditing the [official YACS v0.1.8 class](https://github.com/rbgirshick/yacs/blob/v0.1.8/yacs/config.py), context-scoped `safe_globals([CfgNode])` with `weights_only=True` succeeded. No general pickle fallback was used. Only the tensor `model` dictionary was retained and converted to safetensors (SHA-256 `2f713987c34dbbbddc5cc02e53d5990d77f15c66d814f9dff2194e2faeb35fd9`); checkpoint configuration methods were never invoked.

The SPAI runner uses a fresh config from the pinned source YAML, the official MFM backbone and five-patch image inference, eight uniform native center crops at 256 pixels, and mean frame logits. FFT runs on CPU and the vision network on MPS. Optional CLIP-backbone and image-export dependencies are disabled; these branches are not used by this configuration. `sources/spai-vendor-manifest.json` records every original source hash, and the runner checks those hashes before the two explicit dependency edits. This bounded video adaptation does not reproduce the paper's full-resolution image benchmarks.

```sh
uv pip install --python eval/.venv/bin/python yacs==0.1.8 timm==0.4.12 einops==0.8.0 scipy==1.14.1
eval/.venv/bin/python scripts/eval-spai.py --output eval/runs/spai-new.jsonl
node scripts/eval-score-report.mjs --input eval/runs/spai-new.jsonl --development-fpr 0.05 --output eval/sources/spai-new-report.json
```

The score reporter checks prediction hashes against manifest truth, produces per-group confusion metrics and uncertainty, and adds a source-group bootstrap AUROC interval. Threshold selection with `--development-fpr` is refused for any non-development row. Use `--threshold <frozen-value>` for later evaluation; do not choose thresholds from holdout results.

For a paired comparison of frozen completed runs, `scripts/eval-compare.mjs` requires `--before <run-directory> --after <run-directory> --output <report.json> --unseal`. It defaults to the full holdout split and validates both run plans against the manifest. Do not pass `--unseal` until both processes finish and model/prompt/threshold/sampling choices are frozen. The report separates scan completion from recorded pass failures, includes all-selected end-to-end recall alongside conditional metrics, and adds latency, paired transitions, a source-group recall-difference interval, and an exact paired test. Missing legacy pass traces are reported as unavailable.

Local SPAI feasibility: 139,945,243 tensor elements in a roughly 560 MB FP32 safetensors file. On this Apple Silicon host, MPS inference takes about 0.77 seconds per clip after warmup. A two-clip CPU measurement with four PyTorch threads took 5.6–5.7 seconds per clip, 17.18 seconds including process/model startup, maximum resident set size 2.73 GB, and macOS peak physical footprint 1.64 GB. CPU numbers were collected while other local model evaluations were active, so they are approximate, not a production capacity guarantee. A persistent worker would avoid repeated startup. A production runtime could use the audited vendored model, a plain frozen architecture config, and SHA-pinned safetensors, excluding pickle/YACS checkpoint loading and unused training/plotting/backbone branches. No production integration was performed.

NVIDIA's synthetic-video-detector requires private-access NGC credentials for its hosted preview or a supported Linux NVIDIA Tensor Core GPU with video codecs for local NIM. This Apple Silicon host cannot run that local NIM, and no existing NVIDIA credentials were found. [Official support matrix](https://docs.nvidia.com/nim/maxine/synthetic-video-detector/latest/support-matrix.html), [getting started](https://docs.nvidia.com/nim/maxine/synthetic-video-detector/latest/getting-started.html).
