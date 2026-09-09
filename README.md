# AI Slop Detector

An evidence-based short-video scanner for YouTube, Instagram, TikTok, X, and uploaded clips. It combines optional Sightengine visual evidence with separate Gemini reviews, checks available Content Credentials and source disclosures, and shows the observations behind its assessment.

[Local setup](#run-locally) · [API keys](#3-add-your-own-api-keys) · [Troubleshooting](#troubleshooting)

The report does not display an AI probability. Its outcomes are **AI indicators detected**, **No clear AI indicators**, **Inconclusive**, **AI use disclosed**, or **Verified AI provenance**. A negative inspection cannot certify camera origin. Source disclosures and verified credentials are distinguished from model observations.

**Experimental:** the reserved 75-clip comparison did not demonstrate an accuracy improvement (23/39 AI detections and 2/36 real false positives, versus 26/39 and 0/36 for the original). Simulated reposts exposed further misses. See [measured results and limitations](docs/DETECTION_EVALUATION.md). The software safeguards are verified; general detection reliability is not.

**September 8 specialist results:** Sightengine flagged 19/23 sampled frames in the user-reported Instagram Reel where Gemini found no clear AI indicators. In a separate fixed 25-file screen, its temporal rule detected 10/12 publisher-labeled AI cases but also falsely flagged 4/12 documented camera/CGI controls. That standalone rule failed. The current app uses Sightengine as its primary visual detector: complete repeated flags produce an AI-indicator verdict even when Gemini disagrees. Gemini remains a separate review. This decision prioritizes detection sensitivity and can retain Sightengine false alerts; it does not establish general accuracy. See [integration and measured limits](docs/SIGHTENGINE_INTEGRATION.md).

A separate [known-origin diagnostic](eval/GENERATED_ORIGIN_CONTROL.md) also missed a clip generated directly from text and its two-second insert, despite complete model reviews and verified file identities. This confirms a recognition failure beyond social-media retrieval. Additional tested image-detector candidates did not establish repost robustness; the [research decision](eval/RESEARCH_DECISION.md) records what evidence is needed before another candidate can be promoted.

## Run locally

### 1. Install the prerequisites

- [Node.js](https://nodejs.org/en/download) **22.22 or newer** and npm.
- **pnpm 11.19.0**, matching this project's package-manager pin:

  ```sh
  npm install --global pnpm@11.19.0
  ```

- **Python 3.10+** with `venv` and pip, and **FFmpeg** (which includes `ffprobe`). On macOS with [Homebrew](https://brew.sh/):

  ```sh
  brew install python@3.13 ffmpeg
  ```

  On Ubuntu/Debian:

  ```sh
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip ffmpeg
  ```

On Windows, use **WSL2 with Ubuntu** and run the Linux instructions inside WSL, including installing Node and pnpm there. The media setup script requires Bash; native Windows setup is not covered here. Git is needed only if you choose to clone instead of downloading the ZIP.

Check that `node --version`, `pnpm --version`, `python3 --version`, `ffmpeg -version`, and `ffprobe -version` work in the terminal you will use to start the app.

### 2. Download the project

Clone this repository:

```sh
git clone https://github.com/mreflow/ai-slop-detector.git
cd ai-slop-detector
```

Alternatively, choose **Code → Download ZIP** on [the repository page](https://github.com/mreflow/ai-slop-detector), extract it, and open a terminal in the extracted folder. Run all remaining commands from that folder.

```sh
pnpm install --frozen-lockfile
cp .env.example .env.local
```

Copy the template once for a new installation. If you already have `.env.local`, edit it instead of copying over your existing keys.

### 3. Add your own API keys

Open `.env.local` in a text editor. **Only Gemini is required for real scans.** The app and its sample report can be opened without keys, but live scanning will be unavailable.

| Variable | Required? | How to get it / what it enables |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes, for scans | Create a key for your own project in [Google AI Studio](https://aistudio.google.com/apikey). See Google's [API key setup guide](https://ai.google.dev/gemini-api/docs/api-key). This powers the video reviews. |
| `SIGHTENGINE_API_USER` and `SIGHTENGINE_API_SECRET` | Optional | Create your own [Sightengine account](https://dashboard.sightengine.com/) and copy both API credentials from its dashboard. See [getting started](https://sightengine.com/docs/getstarted). These enable the specialist visual detector. |
| `YOUTUBE_API_KEY` | Optional | In your [Google Cloud Console](https://console.cloud.google.com/apis/library/youtube.googleapis.com), enable **YouTube Data API v3**, then create an API key under **APIs & Services → Credentials**. See [YouTube's setup guide](https://developers.google.com/youtube/v3/getting-started). This adds title, disclosure, and comment evidence. |
| `SUPABASE_URL` and `SUPABASE_SECRET_KEY` | Optional | Use your own Supabase project for persistent result caching. Apply both migrations as described under [Cache and hosting](#cache-and-hosting). Leave both blank to run without a database. |

Paste the Gemini key after `GEMINI_API_KEY=` in **`.env.local`**, leaving the other values at their defaults for a first run. Do not edit `.env.example` to hold real credentials. Optional providers turn off when their keys are absent; `SIGHTENGINE_ENABLED=false` explicitly disables Sightengine and `CACHE_ENABLED=false` disables persistent caching.

The default model and reviewer are `gemini-3.7-flash`. If your account cannot access that model, set both `GEMINI_MODEL` and `GEMINI_REVIEW_MODEL` to a model your account supports with the Gemini Interactions/video APIs. Consult [Gemini video documentation](https://ai.google.dev/gemini-api/docs/video-understanding); model availability changes. Scans can make multiple paid API calls. Your provider accounts need sufficient quota and any billing required for their selected models/features.

### 4. Install the media downloader and start the app

```sh
pnpm setup:media
pnpm dev --hostname 127.0.0.1
```

Open **[http://localhost:3000](http://localhost:3000)**. Paste a supported public video URL or upload a clip, then start a scan. The default limits are **three minutes** and **500 MB (500,000,000 bytes)**.

The setup script installs the pinned `yt-dlp` package with browser impersonation support into `.venv-media` and updates only `YT_DLP_PATH` in `.env.local`. It uses `python3` from your `PATH`; to select another interpreter, run `PYTHON_MEDIA=/path/to/python3 pnpm setup:media`. It does not install FFmpeg. Restart the server after changing environment values. Stop it with **Ctrl+C**.

Visit [the health endpoint](http://localhost:3000/api/health) to check configuration. Without a Gemini key it deliberately returns HTTP 503 with `status: "degraded"`; this is expected. With a key present, it reports provider configuration and optionally probes the cache. It does **not** validate Gemini/Sightengine credentials, account quota, or detection accuracy; a real scan is needed to exercise those providers.

### Production mode on your own computer

After completing the same setup:

```sh
pnpm build
HOSTNAME=127.0.0.1 pnpm start
```

`pnpm start` loads your local environment and prepares Next.js's standalone server assets. If port 3000 is busy, use `pnpm dev --hostname 127.0.0.1 --port 3001` for development, or `HOSTNAME=127.0.0.1 PORT=3001 pnpm start` for production, and open that port instead.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing Gemini configuration / HTTP 503 | Put your own key in the root `.env.local`, save it, and restart the app. |
| Provider authentication, quota, or model error | Check the key, model access, billing, and quota in your provider's dashboard. Changing keys or configuration requires a restart. |
| `python3`, `venv`, `yt-dlp`, or `ffprobe` missing | Install the prerequisites, rerun `pnpm setup:media`, and check `YT_DLP_PATH` / `FFPROBE_PATH`. Rerun setup if you move the project folder. |
| A social link cannot be downloaded | Platforms can block access or require login. Try uploading the original clip you are allowed to analyze. |
| Optional providers are unavailable | Leave their credentials blank to use Gemini alone, or configure your own accounts as above. |
| HTTP 429 | Fresh scans have rate and concurrency limits. Wait for an active scan to finish or for the limit window to reset. |

### Keys, privacy, and shared files

Credentials are read on the server. Never add a `NEXT_PUBLIC_` prefix to an API key: Next.js exposes those values to browsers. `.gitignore` excludes local environment files, credential files, Python environments, build output, logs, downloaded evaluation media, and raw evaluation runs. `.env.example` contains blank credential fields only.

Running the app locally still sends analyzed media to **Google Gemini** and, when configured, **Sightengine**. Supabase caching stores report JSON and source metadata in your own database. Local temporary media is removed after processing, and Gemini upload deletion is requested; provider retention follows their own policies. Review exported reports before sharing them, since reports can contain submitted URLs, filenames, and observations.

The repository includes application source, tests, evaluation scripts, manifests, and research notes. Large downloaded datasets, model weights, generated media, local logs, and raw provider run outputs are not distributed. Some historical research links refer to those local artifacts; see [the evaluation guide](eval/README.md) for reproduction steps and publication redactions.

To check Git-tracked history with [Gitleaks](https://github.com/gitleaks/gitleaks), run `gitleaks git . --redact --log-opts="--all --full-history"`. The included configuration retains the default rules and permits one exact, verified research-file checksum that resembles an API key.

## Detection flow

1. Normalize the URL, validate request limits, and look for a compatible cached report. **Rescan fresh** bypasses that lookup while retaining admission and rate limits.
2. Check duration before paid video analysis. Retrieve social media through its native extractor, validate the selected media identity, and inspect the actual file. Ambiguous multi-item downloads fail instead of selecting an arbitrary clip.
3. Record the downloaded/uploaded file's SHA-256, duration, dimensions, frame rate, and audio presence. When Sightengine is enabled, YouTube also uses safely downloaded, identity-checked bytes so both providers inspect the same file. Without the specialist, the existing YouTube URL-only route remains available.
4. Run a full static timeline sweep plus a separate reviewer. A disagreement or invalid assessment triggers a third inspection, including finer sampling around cited moments. Completed passes retain raw assessments, timing, sampling requests, and available token usage.
5. Check timestamp validity, internal consistency, modality evidence, sufficiency, coverage, and corroboration before choosing an outcome. The optional specialist retains repeated flags and isolated unresolved alerts separately. Complete repeated Sightengine flags determine an AI-indicator verdict without a Gemini veto. Isolated alerts and incomplete specialist evidence remain Inconclusive. A no-hit visual scan does not erase unresolved audio or identity findings from Gemini. No scores are averaged or converted into confidence percentages. Sampling receipts do not prove every-frame inspection or exclude subsecond AI inserts.
6. Inspect active, trusted C2PA assertions using structured source types. Missing credentials are neutral. Read available social captions and YouTube context separately; audience comments never increase or decrease the model score.
7. Save the complete report under a fingerprint covering the policy, schema, decision version, models, sampling, specialist configuration, and relevant configuration. Old percentage/confidence reports and incomplete specialist scans are not reused. Delete local temporary media and request deletion of Gemini uploads; Sightengine has its own data-processing policy.

The UI includes source context, media receipts, per-pass diagnostics, fresh rescanning, and a downloadable JSON report. User annotations stay in the browser and are explicitly unverified labels.

Model and sampling settings are in `.env.example`. The default independent reviewer uses agentic processing; the sweep always uses static sampling. More passes can share model biases, so agreement alone is not proof. The original uncalibrated numerical score survives only as a diagnostic for evaluation.

## Accuracy evaluation

Read [the evaluation guide](eval/README.md) for corpus label provenance, source-group splits, immutable evaluation execution, metrics, specialist experiments, and coverage gaps. The preserved original detector is available as a baseline adapter.

The automated software checks require no API keys:

```sh
pnpm test
pnpm lint
pnpm build
pnpm typecheck
```

For corpus evaluation, download the pinned corpus using the evaluation guide first. Validation alone makes no provider calls:

```sh
pnpm eval:validate --manifest eval/smoke-manifest.jsonl
```

The following optional command **makes provider calls and consumes your API quota/budget**:

```sh
pnpm eval:run --manifest eval/smoke-manifest.jsonl --output eval/runs/my-experiment --concurrency 2
```

Reports count abstentions against AI recall and record failed requests separately. Development results are not held-out accuracy or calibrated confidence. The corpus uses dataset-author labels; it is not a substitute for independent camera provenance, actual platform reposts, mixed-media controls, and the user's failure cases.

## Cache and hosting

For optional Supabase caching, create your own project and run **both** SQL migrations in its SQL Editor, in filename order: [create the cache table](supabase/migrations/20260902183114_create_video_analyses.sql), then [update the platform constraint](supabase/migrations/20260902193500_add_x_platform.sql). Copy your project URL into `SUPABASE_URL` and its **server secret key** into `SUPABASE_SECRET_KEY` in `.env.local`; a legacy service-role key is also accepted via `SUPABASE_SERVICE_ROLE_KEY`. Do not use a browser/publishable key for this private cache. Restart the app and check `/api/health` for `providers.cache: true`. The app works without Supabase. Keys never enter browser responses.

[Dockerfile](Dockerfile) packages the app as a persistent Node service with FFmpeg, native C2PA support, and pinned `yt-dlp` with impersonation support. Railway can build it directly. Configure values from `.env.example`, set `NEXT_PUBLIC_APP_URL`, and verify live scans after deployment. Extractors can stop working when social platforms change or require authentication; uploading the original clip remains the fallback.

With Docker installed, you can also run it locally after downloading the repository and creating `.env.local` with your own keys. Host Node/Python/FFmpeg installation is unnecessary for this option:

```sh
docker build -t ai-slop-detector .
docker run --rm -p 127.0.0.1:3000:3000 --env-file .env.local \
  -e YT_DLP_PATH=yt-dlp -e FFPROBE_PATH=ffprobe ai-slop-detector
```

The path overrides use tools inside the container even if local setup wrote a host-specific downloader path. The Docker build excludes real environment files; credentials are supplied only at runtime. For an Internet-facing deployment, add access controls and appropriate account-wide usage limits before exposing paid scan endpoints.

Media is capped at three minutes and 500 MB (500,000,000 bytes) by default. The request waits for the asynchronous specialist job when needed, allowing up to ten minutes for its upload and analysis. Unfinished jobs are stopped on failure when their media ID is known. The service uses explicit provider/retrieval timeouts and rejects excess fresh work with a retryable 429. Multiple passes increase latency and provider usage. Measure end-to-end latency on the target host before increasing limits; workloads beyond its HTTP request window require background jobs. In-memory admission/rate limits apply to one process and require shared storage for multiple replicas.

Immediate Gemini file deletion is attempted after every analysis; if cleanup fails, the provider may retain the upload until automatic expiry. Public launches should use billing alerts and monitor failure, abstention, false-positive, and false-negative rates.

Official references: [Gemini video understanding](https://ai.google.dev/gemini-api/docs/video-understanding), [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), and [Content Authenticity SDK](https://opensource.contentauthenticity.org/docs/c2pa-node/).
