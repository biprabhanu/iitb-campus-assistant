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
- Security review: the per-request log line was silent (no logging configured), so the `campuspilot` logger now prints at INFO. Verified live: no message text, roll number or token in the logs; /v1/moodle/token doesn't echo.
- 26 Nov: fresh-clone demo. get_official_link reads registry.csv directly (no DB needed); make mock-dev builds a demo index from data/fixtures/docs/ (SRC-DEMO-*, labelled not official) only when data/campuspilot.db is missing, and make ingest removes demo sources first.

## v1.1 deploy (DEPLOY_MASTER_PROMPT.md), Phase 0 decisions (high effort)

- Test key absent from `.env` at Phase 0, so the Groq model list and tool-call probe are deferred; provider defaults in `llm/providers.py` are provisional (`tested=False`) until the probe runs.
- One build serves both modes: the UI reads `deploy_mode` from `/v1/status` instead of a second build flag.
- Moodle-never-to-LLM (§10.4) applies to local mode too: one code path, simpler tests, and Gemma never needed the Moodle text to route.
- Moodle tools keep `course_code` from the student's question as their only input, so routing needs no Moodle data.
- History turns carry `kind`; `kind="moodle"` content is replaced server-side before any LLM call (otherwise earlier template answers would leak course names back into the prompt).
- Client IP behind Render/Cloudflare: `CF-Connecting-IP`, else the last XFF entry; never the leftmost (client-controlled). To be confirmed on Render in Phase 3.
- Rate limits 20/min + 400/day per IP in both modes (was 30/min local); body 8 KB hosted, 32 KB local.
- Index is a release asset with SHA-256 verification; any failure falls back to the fixture index (the demo builder from the fresh-clone fix), reported as `index:"fallback"`.
- No Moodle Keychain endpoints in hosted mode (404 NOT_AVAILABLE); `/v1/moodle/check` verifies header credentials without storing them.
- Phase 1 backend decisions accepted: mixed Moodle+docs turn keeps answer_kind answer/abstain (template streamed first); `/v1/llm/check` is 404 NOT_AVAILABLE in local mode; check status codes 401/429/504/502; 429 bodies carry `retry_after_s` + a `Retry-After` header; the clarify pre-check stays on in hosted mode (one cheap router call), revisit after the Groq rate-limit probe.
- Docker image 348 MB → 115 MB: PyMuPDF 2.x pulls onnxruntime/numpy/networkx, and the hosted API never parses PDFs (index is pre-built; fallback is HTML only), so PyMuPDF is now the optional `pdf` extra, imported inside `parse_pdf`. Local setup, CI and build-index install it. Container idles at ~54 MB RAM.
- Hosted container runs uvicorn with `--no-access-log`: the access log records client IPs; our own per-request line (path, status, latency) is enough.
- Lead UI review (high effort): moved the 'key stays in your browser' note into the key card (it was hidden under the composer at 1440x900), guide starts open only on tall screens so Save stays visible, wordmark hidden below 420 px so the header fits; CSP kept in proxy.ts with a per-request nonce (stricter than 'unsafe-inline'); `npm run screenshots` no longer deletes docs/screenshots/*.png (it had wiped the live-Gemma shots, restored from git).
- Phase 2 (Docker API on 127.0.0.1:8001/8002, UI via `next dev`): no key → 401 MODEL_KEY_REQUIRED; fake key sent to real Groq → PROVIDER_KEY_REJECTED "Your Groq key was rejected" (chat SSE and /v1/llm/check); unknown provider → 400; foreign CORS origin refused; Moodle demo turn → template sentence + 6 cards, answer_kind moodle; rate limit 429 after exactly 20 requests/min; fake key, fake Moodle token and question text absent from container logs.
- Integration fix: the UI skipped the waking flow for any loopback API URL; now only when the last known mode isn't hosted. Verified live: container stopped → "Waking the server" in 0.3 s; container restarted → UI recovered in 6.8 s.
- Process note: `pkill` after the fresh-clone mock-dev check missed the `make`-spawned uvicorn/next parents; they ran ~1 h on 127.0.0.1 until found and stopped in Phase 2.
- build-index workflow (run 45829950999) on GitHub runners: IITB sites reachable from GitHub; 44 documents / 337 chunks; release `index-2026-11-26` with campuspilot.db, manifest.json, SHA256SUMS.
- Local check of the release download: blocked by this network, not the code. `github.com` answers 302, but its asset host `release-assets.githubusercontent.com` fails TLS (container: SSL EOF; Mac curl: 000). The API fell back to the fixture index and reported `index:"fallback"` as designed. To verify `index:"release"` on Render in Phase 3.
- Cosmetic: ingest logs `via=mac` on GitHub runners (the fetched_via default label), not a fetch from the Mac.
- Groq probe with the owner's test key (2026-11-26): provisional defaults `llama-3.1-8b-instant` / `llama-3.3-70b-versatile` no longer listed. Chosen: router `openai/gpt-oss-20b`, answer `openai/gpt-oss-120b` (tool-call probe pass; separate models spread the 8,000 tokens/min per-model budget; 1,000 requests/day each). Live local hosted run: smoke 6/6 pass (first token 1.7 s, cited calendar answer), `/v1/llm/check` ok, Moodle template turn ok, mess-menu abstain ok; "UG entrant documents" abstained (Gemma answered it) — to measure in the hosted acceptance run. Real key absent from the API log.
- Key-handling incident (no exposure): the owner first pasted the key into the tracked `.env.example`; the frontend worker moved it to the gitignored `.env` and restored `.env.example` before any commit. Verified: the real key is in no commit on any ref (local or origin); the only key-shaped strings in history are the two known fakes.

## v2 integrations (INTEGRATIONS_BUILD_PROMPT.md), Phase 0 (27 Nov 2026, high effort)

- Audit: `main` at b3dde6c, `make test` green (243 pytest, 20 Playwright). The hosted pilot (Render + Vercel) is live and stays as it is; v2 is local-only.
- Owner answers: ASC = internal portal (campus/VPN), login via IITB SSO with LDAP; webmail = IMAP over SSL; mail read by the local Gemma only; Google OAuth client set up later (Worker C builds against a mocked API). ASC login URL and IMAP host/port to be confirmed before Phase 2 (defaults `asc.iitb.ac.in`, `imap.iitb.ac.in:993` are configurable placeholders, not verified).
- Personal data follows the Moodle rule (§10.4): mail and ASC results go to the UI as a new `cards` SSE event plus a template sentence; the chat model only sees a count. One exception, by design: event extraction and requested summaries use the local model in separate tool-less calls (`llm/personal.py`), so an injected mail has no tool to trigger.
- New `answer_kind="personal"` (Moodle-only stays `"moodle"` so the hosted UI is unchanged); history turns of both kinds are hidden from the model.
- Hosted gating is structural: the connector router isn't mounted and the tools aren't offered when `DEPLOY_MODE=hosted`, whatever the flags say.
- Calendar writes are protected by a required `X-CampusPilot-Confirm: yes` header (forces a CORS preflight, so another site can't trigger logins or events) and are never a model tool.
- No new dependencies: imaplib/email, httpx + BeautifulSoup, Google REST over httpx with PKCE (no Google SDK, keeps the venv and image small).
- The lead writes the shared plumbing (registry, orchestrator, routes, cards, sentences, mock LLM) in Phase 0 so workers only touch their own packages; Phase 0 module stubs keep the exact signatures.

## v2 Phase 2: integration (27 Nov 2026)

- Merged `v2/webmail`, `v2/asc`, `v2/gcal` into `main` (no conflicts; 458 pytest). Workers' requests: two lead contract tests depended on the Phase 0 stubs; one would have opened a real IMAP connection after the merge. Both now fake the module.
- Webmail login, checked live from the campus network without logging in: `imap.iitb.ac.in` resolves to a campus-internal address, ports 993/143 open; perdition IMAP proxy; DigiCert `*.iitb.ac.in` certificate (valid to Feb 2027); TLS 1.2 only, cipher `AES256-GCM-SHA384` (RSA key exchange); pre-auth capabilities list no AUTH= mechanisms and no LOGINDISABLED, so plain IMAP LOGIN over TLS.
- Fix 1 (blocker): Python 3.12's default ciphers exclude RSA key exchange, so every connection failed the handshake. `imap_ssl_context()` keeps certificate and hostname verification and TLS ≥1.2, and appends only `AES256-GCM-SHA384` / `AES128-GCM-SHA256` after the ECDHE suites (no forward secrecy on this server's side; still encrypted and authenticated). Verified live: TLSv1.2 handshake and server greeting with the fixed client.
- Fix 2: TLS / certificate failures no longer say "connect to the VPN"; they say the secure connection failed and the password was not sent.
- Fix 3: the login username is the LDAP id; a typed `@iitb.ac.in` suffix is dropped before LOGIN and storage.
- Fix 4: webmail is Roundcube ("WM2 IITB"), so mail cards get an "open in webmail" link built from the IMAP UID. Whether Roundcube's UIDs match ours is a Phase 2 live check.
- Owner's first `make mail-login` with the LDAP id + LDAP password: the server answered NO (so TLS now works). Public IITB IMAP projects (harshitsinghbhandari/iitb-email-summarize README, CodeAcc2007-dev/KRNLv3) document that IITB IMAP needs an **SSO access token** (sso.iitb.ac.in → Manage account → Access tokens → Emails), not the LDAP password. KRNLv3 also hit the same TLS handshake failure (it lowers OpenSSL SECLEVEL; ours adds only the two RSA-GCM ciphers). Login copy, the auth error and `make mail-login` now ask for the token; Worker D told to change the UI wording.
- Still to verify with the owner's own login (owner types it; Claude never sees it): LOGIN accepted with the LDAP id + token, SEARCH behaviour, folder names.
- Owner's `make mail-login` with LDAP id + SSO access token: **Connected** (saved in the Keychain). Live counts-only check (no mail content printed): login and SELECT read-only fine.
- Fix 5: `SEARCH TEXT` on IITB's server takes 20+ s for a word it hasn't searched before (it scans every body) and hit the 20 s timeout; `SEARCH SINCE` over 14 days takes ~0.1 s. Search is now date-only on the server and matched client-side: 0.5–0.6 s per question over 173 mails (14 days).
- Fix 6: rules-only event detection returned 31 "upcoming" items, 26 without a clear date (mostly older mails). Undated items now come only from the last 3 days' mail, at most 5.
- Read-only proven live: the unread count was 4952 before and after all checks. Mail cards all got Roundcube links (UID match still to be clicked once by the owner).
- Owner bug: in mock mode "check my webmail latest msg" went to `search_campus_docs`. New `agent/mail_intent.py` (shared by the mock router and the orchestrator) spots mail questions (mail, webmail, inbox, email, msg, message, unread; "latest" or "from X" only together with a mail word).
- New read-only tool `list_recent_mail(limit, unread_only)`: `UID SEARCH ALL|UNSEEN`, newest UIDs, `BODY.PEEK` headers + short snippet, no full bodies. Mail cards, template sentence; the model sees only a count.
- Owner rule: with Webmail on, a mail question offers only the mail tools (no campus search, no official links, no clarify pre-check); if the model calls none, the backend runs the right one; a failure answers "I couldn't read your mail." + the reason, never campus documents. Tests: `tests/test_mail_routing.py` (10 phrasings through the rules and the mock, 4 non-mail questions, mail-only turn, failure, read-only IMAP, demo).
- With the tunnel up, event detection used Gemma (`rules+llm`) but took ~232 s for 12 model calls: too slow for chat. Open item: lower `MAX_MODEL_CALLS`, run calls in parallel, or refine only dated candidates.
