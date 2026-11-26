# CampusPilot: notes for Claude Code sessions

CampusPilot is a chat assistant for IIT Bombay students (IE624 student prototype, not an official
IITB service). It gives short answers with citations to official public IITB pages, plus a
read-only view of the student's own Moodle deadlines.

It runs in two modes, from one codebase:

- **Local:** the API and UI run on the owner's Mac. The model is Gemma 4 26B via Ollama on the
  IEOR course server ("Passpoli"), reached through an SSH tunnel on `127.0.0.1:11500`.
- **Hosted:** the API runs on Render (Docker) and the UI on Vercel. Each student brings their own
  LLM key (Groq recommended). The server holds no model key.

**Current state, pending work and next steps are in `docs/HANDOVER.md`. Read it first.**

@docs/HANDOVER.md

## Layout

- `apps/api/`: FastAPI backend (Python 3.12, uv, `uv.lock`).
  - `campuspilot/agent/`: orchestrator.
  - `campuspilot/llm/`: Ollama, BYOK and mock clients.
  - `campuspilot/retrieval/`: SQLite FTS5 search.
  - `campuspilot/moodle/`: Moodle access.
  - `campuspilot/ingestion/`: fetching and indexing sources.
  - `campuspilot/api/`: routes, hosted headers, rate limits.
- `apps/web/`: Next.js 16 UI. This is NOT the Next.js in your training data: read
  `apps/web/AGENTS.md` and `node_modules/next/dist/docs/` before changing it.
- `scripts/`: ingest, reindex, acceptance check, provider probe, hosted smoke test, index release.
- `data/sources/registry.csv`: approved sources. `data/fixtures/`: demo data.
  `data/raw/`, `data/processed/` and `data/*.db` are gitignored.
- `docs/`:
  - `CONTRACT.md`: the API contract; §10 covers hosted mode.
  - `ARCHITECTURE.md`, `API.md`, `DEPLOY.md`, `REPRODUCE.md`, `STUDENT_GUIDE.md`, `SOURCES.md`.
  - `EVAL.md`: acceptance numbers.
  - `BUILD_LOG.md`: every decision, one line each.
- `MASTER_BUILD_PROMPT.md` (v1 build) and `DEPLOY_MASTER_PROMPT.md` (v1.1 deploy) are the owner's
  specs. They are the source of truth for scope and rules.

## Commands

- `make setup` installs dependencies. `make dev` runs the real app; it needs the tunnel
  (`make tunnel-check`). `make mock-dev` uses a fake model and needs no tunnel.
- `make test` runs everything offline: pytest, ruff, eslint, tsc, next build and Playwright smoke.
  It must pass before any push.
- `make secrets-check` runs the security sweep.
- `make docker-build` and `make docker-run` run the hosted image on `127.0.0.1:8001`.
- `make smoke-hosted URL=... ORIGIN=...` checks a deployed API.
- `make acceptance` runs the live 25-question check against Gemma.
- `python scripts/probe_provider.py` probes the BYOK provider using `TEST_LLM_*` from `.env`.
- The API listens on `127.0.0.1:8000` and the UI on `127.0.0.1:3000`. Bind local services to
  127.0.0.1 only. Stop the processes you start, including the `make`-spawned uvicorn and next
  parents; `pkill` has missed them before.

## Rules (from the owner's prompts; they still apply)

**Git**
- The repo is **public**. Only the lead agent commits.
- Stage specific paths. Never use `git add -A`.
- The author is the owner's configured git identity. Never set or override it.
- No co-author or "Generated with" lines. Check `git log -1` after each commit.
- Push to `origin main` only after `make test` passes and the security sweep is clean.
- Never force-push, rewrite history, or delete releases or branches.

**Secrets**
- Never commit `.env`, keys, tokens, DBs, `data/raw/`, `data/processed/`, ssh configs, server
  IPs, usernames, roll numbers or private notes.
- Before every push: `git grep` must find no `gsk_`, `AIza`, `sk-` followed by 20+ characters, or
  `wstoken=`, excluding the prompt files.
- Never print, echo or log the test LLM key; scripts read it from `.env` themselves. The owner must
  never paste keys into the chat.
- The hosted server never stores, logs or caches student keys or Moodle tokens.
- Moodle content is never sent to any LLM.

**Hard stops (ask the owner first)**
- Creating or logging into an account, or entering anything into a dashboard (Render, Vercel,
  GitHub settings). The owner does the dashboard steps; you give one step at a time.
- Anything that needs a payment card or a paid plan.
- Force-push, or deleting releases or branches.
- Any change on Passpoli. Never use GPU 1 there, and touch only processes you started.
- Exposing Passpoli or its Ollama to the internet.

**Honesty**
- Never fabricate content, results or numbers.
- Status words: `implemented_and_tested`, `implemented_not_tested`, `blocked`,
  `needs_human_review`, and `not_tested` for providers.
- Before claiming something is done, free or committed, check it with a command.

**Effort**
- High effort only for decisions: the contract, security review, hard bugs, final reports.
- Subagents run on Sonnet at medium effort; use Haiku for searches.
- Frontend work runs at high effort, at the owner's request.

## Keeping this handover current

At the end of every work session, or after each finished phase, update `docs/HANDOVER.md`:
status table, what changed, next steps and open questions. Add one line per decision to
`docs/BUILD_LOG.md`. Commit both.
