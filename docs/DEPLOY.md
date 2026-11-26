# Deploying CampusPilot (hosted pilot)

For the project owner. You need a GitHub account with this repo, a Render account and a Vercel account. All three have free plans. No payment card is needed for this setup.

No secret is set anywhere. Students bring their own model key, and the server never holds one.

Placeholders used below: `<RENDER_URL>` (for example `https://campuspilot-api-xxxx.onrender.com`) and `<VERCEL_URL>` (the production URL, no trailing slash). Both are TBD until you finish steps 1 and 2.

## Steps

### 1. Render (the API)

1. Open the Render dashboard. Click **New** -> **Blueprint**.
2. Connect GitHub and pick this repository.
3. Render reads `render.yaml`: one free Docker web service named `campuspilot-api`, region Singapore, health check `/health`, auto-deploy on push.
4. When it asks for `ALLOWED_ORIGINS`, leave it empty for now (you set it in step 3).
5. Click **Apply** and wait for the first deploy to finish. The first Docker build takes several minutes.
6. Copy the service URL (`https://....onrender.com`). This is `<RENDER_URL>`.
7. Open `<RENDER_URL>/health`. It should show `{"ok":true}`.

### 2. Vercel (the web app)

1. Open Vercel. Click **Add New** -> **Project**.
2. Import this GitHub repository.
3. Set **Root Directory** to `apps/web`.
4. Under **Environment Variables** add `NEXT_PUBLIC_API_URL` = `<RENDER_URL>` (no trailing slash).
5. Click **Deploy**.
6. Copy the production URL. This is `<VERCEL_URL>`.

`NEXT_PUBLIC_*` values are baked in at build time. If you change one later, redeploy.

### 3. Render again: allow the web app (CORS)

1. In Render, open the service -> **Environment**.
2. Set `ALLOWED_ORIGINS` = `<VERCEL_URL>` (no trailing slash). Several origins can be comma separated.
3. Save. Render redeploys.

### 4. Build the index

1. On GitHub open **Actions** -> **Build index** -> **Run workflow**. Or run:

   ```bash
   gh workflow run build-index.yml
   ```

2. Wait for the run to finish. It creates a release named `index-YYYY-MM-DD` (a numeric suffix is added if that tag exists) with assets `campuspilot.db`, `manifest.json` and `SHA256SUMS`. It commits nothing. It also runs weekly, Monday 03:00 IST.
3. In Render, restart the service (**Manual Deploy** -> **Restart**, or the service menu). The API downloads the newest `index-*` release at startup, checks the SHA-256, and uses it.
4. Check the result:

   ```bash
   curl -s <RENDER_URL>/v1/status
   ```

   Look for `"index":"release"` and an `index_version` such as `index-YYYY-MM-DD`. `"index":"fallback"` means the download failed and the tiny demo index (`index_version` `fixtures`) is in use. Check the Render logs.

### 5. Smoke test

From the repo root, after `make setup`:

```bash
make smoke-hosted URL=<RENDER_URL> ORIGIN=<VERCEL_URL>
```

`ORIGIN` is optional. The script reads `TEST_LLM_PROVIDER` and `TEST_LLM_KEY` from your local `.env` (your own test key; never deployed, never printed). Without a key, the live-answer and bad-key checks are skipped and the script says so. It exits with code 1 on any failure. The first request may take about a minute if the service was asleep.

### 6. Logs

- **Render:** service -> **Logs**. The API starts with `--no-access-log`, so the only per-request lines come from the app.
- **Vercel:** project -> **Deployments** -> pick one -> **Logs** (build logs) and **Runtime Logs**.

A normal chat request writes one line when the stream ends:

```
request_id=1a2b3c4d model=<model> mode=byok provider=groq tools=[...] chunks=[...] latency_ms=<n> error_code=-
```

Other requests (health, status, search, errors) write:

```
request_id=- model=- mode=- tools=[] chunks=[] latency_ms=<n> error_code=- path=/health status=200
```

`error_code` is `-` on success and the HTTP status for a failed non-chat request. Keys, Moodle tokens and question text are never logged.

### 7. Roll back

- **Render:** service -> **Events** (or **Deploys**) -> pick an earlier successful deploy -> **Rollback**. Turn off auto-deploy first if you want it to stay there.
- **Vercel:** project -> **Deployments** -> pick an earlier production deployment -> **Promote to Production** (Instant Rollback).
- **Index:** to roll back the index, delete the newest `index-*` release on GitHub (Releases), then restart the Render service. It picks the next newest.

## Environment variables

None of these is secret. No model key is ever set on Render or Vercel.

### Render (service `campuspilot-api`)

Set in `render.yaml` or the dashboard:

| Variable | Value / default | Meaning |
|---|---|---|
| `DEPLOY_MODE` | `hosted` (code default `local`) | Hosted mode: student's own key per request, Moodle credentials per request, no Ollama, no Keychain. |
| `INDEX_SOURCE` | `release` (code default `local`) | `release` downloads the newest `index-*` GitHub Release at startup. |
| `INDEX_REPO` | `biprabhanu/iitb-campus-assistant` | GitHub repo whose releases hold the index. |
| `CAMPUSPILOT_DB_PATH` | `/tmp/campuspilot.db` | Where the index is stored. Free-tier disk is ephemeral. |
| `ALLOWED_ORIGINS` | empty (`sync: false`, set in dashboard) | Extra CORS origins, comma separated. Set to `<VERCEL_URL>`. |

Set in the Dockerfile (override in the dashboard only if needed):

| Variable | Default | Meaning |
|---|---|---|
| `CAMPUSPILOT_RAW_DIR` | `/tmp/raw` | Scratch directory for raw files. |
| `PORT` | `8000` (Render sets its own) | Port uvicorn listens on, `0.0.0.0` inside the container. |

Optional settings from `apps/api/campuspilot/config.py` that matter in hosted mode:

| Variable | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_PER_MIN` | `20` | Requests per minute per client IP. |
| `RATE_LIMIT_PER_DAY` | `400` | Requests per day per client IP. |
| `MAX_BODY_BYTES_HOSTED` | `8192` | Request body limit in hosted mode. |
| `PROVIDER_TIMEOUT_S` | `30.0` | Timeout for one call to the model provider. |
| `HOSTED_MAX_HISTORY_TURNS` | `6` | Chat history turns sent to the model. |
| `HOSTED_EVIDENCE_TOKEN_BUDGET` | `2500` | Approximate token cap for document evidence (about 4 characters per token). |
| `HOSTED_MAX_EVIDENCE_CHUNKS` | `5` | Maximum evidence chunks per question. |
| `HOSTED_MAX_OUTPUT_TOKENS` | `400` | Cap on the answer length. |
| `INDEX_TAG_PREFIX` | `index-` | Release tag prefix to look for. |
| `INDEX_TAG` | `index-2026-11-26` in `render.yaml` (code default empty) | Pinned release tag, downloaded straight from `github.com` with no `api.github.com` call. Render's shared outbound IPs exhaust GitHub's unauthenticated API limit (403). After a new `Build index` release, update it in `render.yaml` (or the Render dashboard). Empty = look up the newest release through the API. |
| `INDEX_DOWNLOAD_TIMEOUT_S` | `30.0` | Index download time limit at startup. |
| `MOODLE_BASE_URL` | `https://moodle.iitb.ac.in` | The only Moodle host the API talks to. |
| `MOODLE_TIMEOUT_S` | `10.0` | Moodle call timeout. |
| `TOOL_TIMEOUT_S` | `15.0` | Timeout for one tool call. |
| `MAX_TOOL_CALLS` | `4` | Maximum tool calls per question. |
| `CLARIFY_PRECHECK` | `true` | One short model call that decides whether to ask a clarifying question. |
| `AUTO_OFFICIAL_LINKS` | `true` | After a document search, also add official portal links. |
| `CAMPUSPILOT_MOCK_LLM` | `false` | Scripted fake model. Headers are still required. For tests only. |

Ignored in hosted mode (local only): `OLLAMA_*`, `LLM_FALLBACK_*`, `MOODLE_TOKEN`, `MOODLE_ICAL_URL`, `ALLOW_PERSONAL_DATA_TO_CLOUD`.

### Vercel (project, Root Directory `apps/web`)

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | The API base URL. Set to `<RENDER_URL>`. Public by design. (`NEXT_PUBLIC_API_BASE` is the older name and still works.) |
| `NEXT_PUBLIC_MOCK` | `false` | `true` makes the UI replay a built-in fake stream and never call the API. Leave `false` in production. |

## Default models

From `apps/api/campuspilot/llm/providers.py`. The router model does the short clarify check and tool routing. The answer model writes the streamed answer. A student can override both with the Advanced model field (`X-LLM-Model`).

| Provider id | Router model | Answer model | Create a key | Free tier | Tested | Date |
|---|---|---|---|---|---|---|
| `groq` (recommended) | `openai/gpt-oss-20b` | `openai/gpt-oss-120b` | https://console.groq.com/keys | yes | yes: tool-call probe passed, plus a live end-to-end answer | 2026-11-26 |
| `gemini` | `gemini-2.5-flash-lite` | `gemini-2.5-flash` | https://aistudio.google.com/app/apikey | yes | not tested (no key available) | — |
| `openai` | `gpt-4.1-nano` | `gpt-4.1-mini` | https://platform.openai.com/api-keys | no (paid) | not tested (no key available) | — |
| `openrouter` | `meta-llama/llama-3.3-70b-instruct:free` | `meta-llama/llama-3.3-70b-instruct:free` | https://openrouter.ai/settings/keys | free models, low daily limits | not tested (no key available) | — |

The probe is `scripts/probe_provider.py`. It uses the owner's own test key from `.env`.

Groq probe, 2026-11-26: `/models` listed 11 models; the earlier guesses `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` were **no longer listed**. Tool-call probe passed for `openai/gpt-oss-20b`, `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`. Groq's response headers reported, per model: 1,000 requests per day and 8,000 tokens per minute. The router and answer models are different, so each has its own per-minute budget. Model lists change; re-run the probe before relying on these ids.

Measured questions per minute on a free Groq key: TBD after Phase 3.

## Free-tier limits

- **Render sleeps after 15 minutes idle.** The next request takes about a minute to wake it. The web app shows "Waking the server" and retries for up to about 90 seconds.
- **512 MB RAM.**
- **Ephemeral disk.** The index is downloaded again on every start (up to 30 s), so a restart needs network access to GitHub. If it fails, the API serves the small fixture index and reports `"index":"fallback"`.
- **Rate limits are in memory.** They reset when the service restarts.
- Vercel and Groq have their own free-tier limits. Check their pricing pages; none are measured here.
