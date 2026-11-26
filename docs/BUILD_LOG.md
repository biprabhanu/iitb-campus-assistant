# Build log

Short notes per phase: decisions, conflicts and anything a teammate should know.

## Phase 0 — audit and contract (26 Nov 2026)

- Audit: the repo held only `README.md`, a GitHub Python `.gitignore` and `MASTER_BUILD_PROMPT.md`. The FastAPI-to-Ollama smoke test, `docs/`, `data/` and `.env.example` mentioned in the prompt didn't exist, so they were created from scratch. No existing tests.
- Checks: tunnel `127.0.0.1:11500` up (Gemma 4 26B and Qwen 3.5 listed, nothing loaded). `ssh passpoli true` works non-interactively. Gemma returned a correct native `tool_calls` reply to a `search_campus_docs` probe (cold load 9.1 s, eval 0.4 s).
- Conflicts fixed: the template `.gitignore` rule `lib/` would have hidden `apps/web/lib/`, so it's now anchored to `/lib/`. The old README mentioned IITB mail, which is out of scope for v1 and will be rewritten. System Python is 3.9, so the API uses a uv-managed Python 3.12 venv in `apps/api/.venv`. macOS has no `timeout` command, so scripts must not rely on it.
- Decisions: `schemas/` and `config.py` are lead-owned so that the workers share one contract. The contract adds `answer_kind`, `office_links`, `demo` and `moodle_mode` fields, the `RATE_LIMITED` code and an `ask_clarification` control tool (see `docs/CONTRACT.md` §3–§6). Commit attribution is off in `.claude/settings.json`.
- Effort policy (owner): high effort only for decisions; workers at medium on Sonnet/Haiku. Exception: the frontend is high effort (owner asked for a "top notch" UI), so a high-effort design review and polish pass follows the first frontend build.
