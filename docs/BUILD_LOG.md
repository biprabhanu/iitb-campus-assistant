# Build log

Short notes per phase: decisions, conflicts and anything a teammate should know.

## Phase 0 — audit and contract (26 Nov 2026)

- Audit: the repo held only `README.md`, a GitHub Python `.gitignore` and `MASTER_BUILD_PROMPT.md`. The FastAPI-to-Ollama smoke test, `docs/`, `data/` and `.env.example` mentioned in the prompt didn't exist, so they were created from scratch. No existing tests.
- Checks: tunnel `127.0.0.1:11500` up (Gemma 4 26B and Qwen 3.5 listed, nothing loaded). `ssh passpoli true` works non-interactively. Gemma returned a correct native `tool_calls` reply to a `search_campus_docs` probe (cold load 9.1 s, eval 0.4 s).
- Conflicts fixed: the template `.gitignore` rule `lib/` would have hidden `apps/web/lib/`, so it's now anchored to `/lib/`. The old README mentioned IITB mail, which is out of scope for v1 and will be rewritten. System Python is 3.9, so the API uses a uv-managed Python 3.12 venv in `apps/api/.venv`. macOS has no `timeout` command, so scripts must not rely on it.
- Decisions: `schemas/` and `config.py` are lead-owned so that the workers share one contract. The contract adds `answer_kind`, `office_links`, `demo` and `moodle_mode` fields, the `RATE_LIMITED` code and an `ask_clarification` control tool (see `docs/CONTRACT.md` §3–§6). Commit attribution is off in `.claude/settings.json`.
- Effort policy (owner): high effort only for decisions; workers at medium on Sonnet/Haiku. Exception: the frontend is high effort (owner asked for a "top notch" UI), so a high-effort design review and polish pass follows the first frontend build.

## Phase 1 — four workers (26 Nov 2026)

- All four workers reported done; 110 tests passed. Data: 9 sources ingested (44 docs, 335 chunks), 5 link_only; the hostel rules PDF was demoted to link_only (scanned, no text layer, no OCR). Everything fetched from the Mac, so Passpoli wasn't needed. Moodle: a public, credential-free probe shows the IITB mobile web service is enabled; the live token is untested. Frontend: `node_modules` is 543 MB (Next 206 MB + swc 97 MB), slightly over the ~500 MB guideline; noted, not trimmed.
- The owner authorised pushing to GitHub after each phase (an exception to hard stop 2; force-push is still a hard stop).

## Phase 2 — integration (26 Nov 2026)

- Live run of the definition-of-done questions through the real API, Gemma and the index. Three fixes (decided by the lead): (1) one evidence id per document URL, because chunk-level ids gave duplicate source cards; (2) a backend retrieval guard: Gemma sometimes abstained without searching, so the backend now runs `search_campus_docs` itself if no tool was called (small talk excepted); (3) prompt v2026-11-26.4: explicit clarify examples ("Can I change my room?" now asks UG/PG/PhD), "never abstain without searching", and "only name offices that appear in evidence". Also: `[S1, S2]` is rewritten to `[S1][S2]`, and untitled PDFs show a file-name title.
- Live results after the fixes: calendar → cited answer (S1–S5, 7.8 s); "what's due" → 4 demo deadline cards (4.6 s); mess menu 2031 → searched then abstained, with hostel office links; "Can I change my room?" → one clarifying question (1.3 s), and the follow-up "UG student" → cited answer; tunnel down → `MODEL_OFFLINE` error event and `/v1/status` model_online=false.
- QA found TTFT = total latency: after tools, the answer came from a non-streaming routing call and was then chopped up. Decision: one routing round, then a real `stream: true` answer call with no tools (Gemma asks for parallel tools in one reply). Live TTFT went from 11–20 s to 2.3–4.8 s.
- UI wired to the real API (CORS ok, 0 console errors). Decisions after the live review: (1) clarify flipped 50/50 even at temperature 0 (alternating runs, which points to the Ollama prompt cache), so a focused JSON-only "needs clarification?" pre-check call was added: 6/6 stable, ~1 s, no false positives in 6 control questions; (2) abstentions now use one fixed honest sentence, because free text invented portal names; (3) the UI makes only links we provided clickable; (4) sources are cited-first and hidden on abstain; (5) the Moodle badge shows demo mode; (6) routing runs at temperature 0.

## Phase 4 — acceptance and finish (26 Nov 2026)

- 5 live acceptance runs (25 questions). From 88% behaviour / 44% source-cited to 96% / 75%, 0 errors. Decisions: auto official-link lookup after a document search; the pre-check owns clarification (cohort-named questions skip it; the routing call no longer sees `ask_clarification`); unoffered tool calls are ignored so the search guard still runs. The overfitting caveat is in `docs/EVAL.md`.
