# Handover: current state

Last updated: 2026-11-27. Update this file at the end of every session (see `CLAUDE.md`).

## Where the project is

| Stage | State |
|---|---|
| v1 local build (`MASTER_BUILD_PROMPT.md`) | Done. Local app with Gemma over the tunnel; acceptance check 96% expected behaviour, 75% expected source cited (`docs/EVAL.md`). |
| Fresh-clone demo fix and hostel-rules note | Done and pushed. |
| v1.1 deploy (`DEPLOY_MASTER_PROMPT.md`), Phase 0: contract | Done. `docs/CONTRACT.md` §10. |
| v1.1 Phase 1: backend, Moodle, infra, frontend | Done and pushed. |
| v1.1 Phase 2: integration on a local Docker container | Done. |
| v1.1 Phase 3: deploy to Render and Vercel | **Not started. Waiting on the owner's dashboard steps.** |
| v1.1 Phase 4: hosted acceptance, docs, final sweep, report | Not started. Needs Phase 3. |
| Integrations build (`INTEGRATIONS_BUILD_PROMPT.md`) | Not started. The owner mentioned this file on 2026-11-27, but it is not in the repo yet. Ask for it. Also ask whether it comes before or after finishing the deploy. |

Git: `main` equals `origin/main` at the time of writing. CI (api, web, docker) is green. The only
untracked item is `.vscode/`; leave it alone.

## v1.1 definition of done

| # | Item | Status |
|---|---|---|
| 1 | Welcome/key card | implemented_and_tested (local) |
| 2 | Streamed cited answer with the student's own key | Worked on the local Docker container with the owner's Groq key; not yet tried on the live URL. |
| 3 | 401 MODEL_KEY_REQUIRED and friendly provider errors | implemented_and_tested |
| 4 | curl examples in `docs/API.md` | Written. Still uses `<RENDER_URL>`. |
| 5 | Moodle kept in the browser, never sent to an LLM | implemented_and_tested. Moodle from Render not yet checked. |
| 6 | "Waking the server" UI | implemented_and_tested (container stop/start). |
| 7 | Fresh clone and CI | CI green. Fresh-clone test in a temp folder not run yet. |
| 8 | Index built as a GitHub release, downloaded at startup | Release `index-2026-11-26` built (44 documents, 337 chunks, SHA256SUMS). The startup download is unverified. This network can't reach `release-assets.githubusercontent.com`, so the app used the fallback index. Check on Render. |
| 9 | Acceptance check on the live site, numbers in `docs/EVAL.md` | Not done |
| 10 | No secrets in Git or on the server | Sweep clean before every push so far. The final sweep, including Render logs with fake secrets, is not done. |

## Next steps, in order

The owner does every dashboard action. Give one step at a time and wait.

1. **Owner, Render:** New → Blueprint → `iitb-campus-assistant`. Leave `ALLOWED_ORIGINS` empty.
   Paste back the `https://….onrender.com` URL.
2. **Claude:** check `<RENDER_URL>/health` and `/v1/status`. Expect `deploy_mode: hosted`,
   `index: "release"` and `index_version: index-2026-11-26`. Then run
   `make smoke-hosted URL=<RENDER_URL>`. Confirm that SSE streams through Render, that the client
   IP comes from `CF-Connecting-IP` or the last XFF entry, and that logs hold no key or message
   text.
3. **Owner, Vercel:** import the repo with root directory `apps/web` and env
   `NEXT_PUBLIC_API_URL=<RENDER_URL>` (no trailing slash). Paste back the production URL.
4. **Owner, Render:** set `ALLOWED_ORIGINS=<VERCEL_URL>`.
5. **Claude:** run `make smoke-hosted URL=<RENDER_URL> ORIGIN=<VERCEL_URL>` and check CORS from
   Vercel in a browser.
6. **Claude, Phase 4:**
   - Add hosted support to `scripts/acceptance_check.py` (BYO headers read from `.env`
     `TEST_LLM_*`). Run it against the live URL and append a "Hosted (Groq, own key)" section to
     `docs/EVAL.md`.
   - Measure questions per minute and per day on a free Groq key.
   - Fill the placeholders: `<RENDER_URL>`, `<VERCEL_URL>`, "TBD after Phase 3" in `docs/API.md`
     and `docs/DEPLOY.md`, and `<INDEX_TAG>`, `<INDEX_VERSION>`, `<DATE>`, `<PROVIDER>` and
     `<MODEL_IDS>` in `docs/REPRODUCE.md`.
   - Add a README "Live pilot" section (link, bring your own free key, privacy in 3 bullets) and
     a "Reproduce" link.
   - Run `scripts/moodle_check.py --api-url <RENDER_URL>` with the owner's Moodle credentials
     from `.env`, and report the result honestly.
   - Run the final §6 security sweep, then a fresh-clone test in a temp folder (`git clone`,
     `make setup`, `make test`, `docker build`).
   - Write the final report (40 lines or fewer): live links, the definition-of-done table,
     default models per provider, free-Groq expectations, hosted vs Gemma numbers, Moodle hosted
     status, and the 3 next steps.

## Facts worth knowing

- **Providers** (`apps/api/campuspilot/llm/providers.py`):
  - Groq is the default and the only provider tested. Router `openai/gpt-oss-20b`, answer
    `openai/gpt-oss-120b`, both probed live on 2026-11-26. The free tier allows about 1,000
    requests per day and 8,000 tokens per minute per model.
  - Gemini, OpenAI and OpenRouter are `not_tested` (no key available).
- **Hosted headers:** `X-LLM-Provider`, `X-LLM-Key`, `X-LLM-Model`, `X-Moodle-Token`,
  `X-Moodle-Ical-Url`. The server never accepts a base URL from the client.
- **Hosted limits:** 20 requests per minute and 400 per day per IP; request body up to 8 KB; 6
  history turns; 400 output tokens.
- **Index:** the `build-index.yml` workflow runs weekly and on dispatch, and publishes release
  `index-YYYY-MM-DD`. On any download or checksum failure the API falls back to the fixture demo
  index and reports `index: "fallback"`.
- **Docker image:** 115 MB. PyMuPDF is the optional `pdf` extra, because the hosted API never
  parses PDFs.
- **Test key:** lives only in the gitignored `.env` as `TEST_LLM_PROVIDER` and `TEST_LLM_KEY`. It
  is never set on Render or Vercel.
- **Hostel rules PDF:** scanned, with no text layer, so it is link-only. See `docs/SOURCES.md`.
- **Mock UI switches:** `?mockHosted=1`, `?mockError=CODE`, `?mockCold=1|fail`.
- **Playwright:** the smoke project only picks up `*smoke.spec.ts`. Screenshots run with
  `SCREENSHOTS=1`.
- **Past incidents** (details in `docs/BUILD_LOG.md`):
  - The owner once pasted the key into `.env.example`. It was moved before any commit, and the key
    is in no commit.
  - Stale `make`-spawned dev servers once kept ports 3000 and 8000 busy.

## Owner's side tasks (not code)

- IE624 project submission form: GitHub link `https://github.com/biprabhanu/iitb-campus-assistant`.
- Project title: "CampusPilot: a cited AI assistant for IIT Bombay students".
- A PPT deck was offered and not yet requested. It needs the group name, member names and any
  slide limit from the owner.
