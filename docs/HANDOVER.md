# Handover: current state

Last updated: 2026-11-27 (v2 Phase 1 in progress). Update this file at the end of every session (see `CLAUDE.md`).

## Where the project is

| Stage | State |
|---|---|
| v1 local build (`MASTER_BUILD_PROMPT.md`) | Done. Local app with Gemma over the tunnel; acceptance check 96% expected behaviour, 75% expected source cited (`docs/EVAL.md`). |
| Fresh-clone demo fix and hostel-rules note | Done and pushed. |
| v1.1 deploy (`DEPLOY_MASTER_PROMPT.md`), Phase 0: contract | Done. `docs/CONTRACT.md` §10. |
| v1.1 Phase 1: backend, Moodle, infra, frontend | Done and pushed. |
| v1.1 Phase 2: integration on a local Docker container | Done. |
| v1.1 Phase 3: deploy to Render and Vercel | **Live, and the smoke test passes.** Two fixes came out of the live deploy (see below). A browser check of the Vercel UI is still to do. |
| v1.1 Phase 4: hosted acceptance, docs, final sweep, report | **Next.** Not started. |
| v2 integrations (`INTEGRATIONS_BUILD_PROMPT.md`): Webmail, ASC, Google Calendar, local only | **Phase 0 done** (contract commit `947aa14`, `docs/CONTRACT.md` §11). **Phase 1 running:** 4 workers in git worktrees on branches `v2/webmail`, `v2/asc`, `v2/gcal`, `v2/web` (not pushed). Next: Phase 2 merges contract → A → B → C → D and runs the live test with the owner. Pushing to `main` needs the owner's OK (it redeploys Render and Vercel). |

Git: CI (api, web, docker) is green. The only untracked item is `.vscode/`; leave it alone. More
than one Claude session pushes to `main`, so `git fetch` before you assume your copy is current.

## Live deployment

- UI (Vercel): https://iitb-campus-assistant.vercel.app
- API (Render, free plan, Singapore, Docker): https://campuspilot-api-mve5.onrender.com
  - The Render service is `campuspilot-api` and auto-deploys from `main`.
  - Vercel builds `apps/web` from `main`.
- Checked 2026-11-27:
  - `/v1/status` reports `deploy_mode: hosted`, `index: release` and `index_version:
    index-2026-11-26`.
  - The CORS preflight from the Vercel origin returns 200 with the right allow-origin.
  - `make smoke-hosted URL=<api> ORIGIN=<ui>` passes all 6 checks. Chat with the test Groq key
    gave a first token in 1.8 s with 1 citation.
- Fixes found during the deploy (commits `9e51fb4` and `c3a3382`, from another session):
  - Render's shared outbound IPs hit GitHub's unauthenticated API limit (403), so startup fell
    back to the fixture index. The fix: `INDEX_TAG` pinned in `render.yaml` downloads the release
    directly. **Bump `INDEX_TAG` in `render.yaml` after every new Build index release.**
  - Browser content blockers block cross-site URLs ending in `/health`, so the UI's wake check
    now pings `GET /v1/ping`. Render's health check still uses `/health`.

## v1.1 definition of done

| # | Item | Status |
|---|---|---|
| 1 | Welcome/key card | implemented_and_tested (local) |
| 2 | Streamed cited answer with the student's own key | implemented_and_tested on the live Render API (smoke test). A click-through in a browser on the Vercel UI is not yet recorded. |
| 3 | 401 MODEL_KEY_REQUIRED and friendly provider errors | implemented_and_tested |
| 4 | curl examples in `docs/API.md` | Written. Still uses `<RENDER_URL>`; fill it with the live URL. |
| 5 | Moodle kept in the browser, never sent to an LLM | implemented_and_tested. Moodle from Render not yet checked. |
| 6 | "Waking the server" UI | implemented_and_tested locally (container stop/start). Switched to `/v1/ping`. Not yet watched on a cold Render start. |
| 7 | Fresh clone and CI | CI green. Fresh-clone test in a temp folder not run yet. |
| 8 | Index built as a GitHub release, downloaded at startup | implemented_and_tested. Render loads `index-2026-11-26` (`index: release`). The release holds 44 documents and 337 chunks; `/v1/status` shows `sources_indexed: 9`. |
| 9 | Acceptance check on the live site, numbers in `docs/EVAL.md` | Not done |
| 10 | No secrets in Git or on the server | Sweep clean before every push so far. The final sweep, including Render logs with fake secrets, is not done. |

## Next steps, in order

The owner does every dashboard action. Give one step at a time and wait.

1. **Owner or Claude:** open https://iitb-campus-assistant.vercel.app in a browser. Check that:
   - the key card appears;
   - a Groq key saves and streams a cited answer;
   - Settings → Forget works.
   Also check the Render logs (the owner reads them from the dashboard) for no key, header value
   or message text.
2. **Claude, Phase 4:**
   - Add hosted support to `scripts/acceptance_check.py` (BYO headers read from `.env`
     `TEST_LLM_*`). Run it against the live API and append a "Hosted (Groq, own key)" section to
     `docs/EVAL.md`.
   - Measure questions per minute and per day on a free Groq key.
   - Fill the placeholders: `<RENDER_URL>`, `<VERCEL_URL>`, "TBD after Phase 3" in `docs/API.md`
     and `docs/DEPLOY.md`, and `<INDEX_TAG>`, `<INDEX_VERSION>`, `<DATE>`, `<PROVIDER>` and
     `<MODEL_IDS>` in `docs/REPRODUCE.md`.
   - Add a README "Live pilot" section (link, bring your own free key, privacy in 3 bullets) and
     a "Reproduce" link.
   - Run `scripts/moodle_check.py --api-url <api>` with the owner's Moodle credentials from
     `.env`, and report the result honestly. Moodle may not be reachable from Render.
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
  `index-YYYY-MM-DD`. Render uses the tag pinned in `render.yaml` (`INDEX_TAG`). On any download or checksum failure the API falls back to the fixture demo
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

## v2 integrations: owner answers and what's still needed

- ASC: the internal portal (campus or VPN), login through IITB SSO with LDAP. The login URL is not confirmed yet.
- Webmail: IMAP over SSL. Host and port are not confirmed yet (placeholder `imap.iitb.ac.in:993`).
- Mail is read only by the local Gemma. ASC data and grades go to no model.
- Google Calendar: before Phase 2 the owner creates a "Desktop app" OAuth client in their own Google account, saves it at
  `~/.campuspilot/google_client.json` (never in the repo, never pasted in chat), and creates a separate "CampusPilot test"
  calendar for live tests.
- In Phase 2 the owner logs in to webmail, ASC and Google through the app UI. Claude never sees their passwords or OTPs.

## Owner's side tasks (not code)

- IE624 project submission form: GitHub link `https://github.com/biprabhanu/iitb-campus-assistant`.
- Project title: "CampusPilot: a cited AI assistant for IIT Bombay students".
- A PPT deck was offered and not yet requested. It needs the group name, member names and any
  slide limit from the owner.
