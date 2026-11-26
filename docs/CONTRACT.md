# CampusPilot interface contract (v1)

This is the one place that defines how the parts talk to each other. The Python
version of §2–§4 lives in `apps/api/campuspilot/schemas/` (**lead-owned**). If the
code and this file disagree, the schemas win; report the mismatch, don't fork it.

## 1. Directory ownership

| Owner | Paths | Notes |
|---|---|---|
| lead | `docs/CONTRACT.md`, `docs/BUILD_LOG.md`, `apps/api/campuspilot/schemas/`, `apps/api/campuspilot/config.py`, `apps/api/pyproject.toml`, `apps/api/tests/conftest.py`, `.env.example`, `.gitignore`, `Makefile`, `README.md`, `.claude/` | Workers ask for changes under `NEEDS:` |
| backend | `apps/api/campuspilot/{main.py,llm/,agent/,api/,tools/}`, `apps/api/tests/test_api*`, `apps/api/tests/test_agent*`, `apps/api/tests/test_llm*` | FastAPI, Ollama client, orchestrator, citations, tool registry, mock LLM |
| data | `apps/api/campuspilot/{ingestion/,retrieval/}`, `data/sources/`, `data/fixtures/docs/`, `scripts/ingest.py`, `scripts/reindex.py`, `apps/api/tests/test_retrieval*`, `apps/api/tests/test_ingestion*` | Registry, fetcher, parser, SQLite + FTS5, two doc tools |
| moodle | `apps/api/campuspilot/moodle/`, `data/fixtures/moodle/`, `scripts/moodle_check.py`, `apps/api/tests/test_moodle*` | REST + iCal, keyring, demo fixtures, three Moodle tools |
| frontend | `apps/web/` | Next.js UI, mock SSE, Playwright |
| qa (phase 3) | `apps/api/tests/test_journey*`, `apps/api/tests/test_injection*`, `data/eval/`, `scripts/acceptance_check.py`, `apps/web/e2e/screenshots*` | |
| docs (phase 3) | `docs/ARCHITECTURE.md`, `docs/SOURCES.md`, README draft in `docs/README_DRAFT.md` | Lead merges into `README.md` |

Python tests run from `apps/api` with `.venv/bin/pytest`. Imports are `campuspilot.<pkg>`.
Each worker puts shared test helpers in its own `tests/<area>_helpers.py`, not in `conftest.py`.

## 2. HTTP API (FastAPI, `127.0.0.1:8000`)

| Method & path | Body → response | Notes |
|---|---|---|
| `GET /health` | → `{"ok": true}` | Process is up. No dependencies checked. Used by Render's health check. |
| `GET /v1/ping` | → `{"ok": true}` | Same as `/health`, for the web UI's wake check. Browser content blockers block cross-site URLs ending in `/health`. |
| `GET /v1/status` | → `StatusResponse` | Calls Ollama `/api/tags` + `/api/ps` (3 s timeout) and `moodle.tools.moodle_status()`. |
| `POST /v1/chat` | `ChatRequest` → `text/event-stream` | §3. |
| `POST /v1/knowledge/search` | `KnowledgeSearchRequest` → `SearchCampusDocsOutput` | Raw retrieval, for debugging. |
| `POST /v1/moodle/token` | `MoodleTokenRequest` → `MoodleTokenResponse` | Verifies then stores in Keychain. Never echoes the token. |
| `DELETE /v1/moodle/token` | → `MoodleTokenResponse` | Removes token and iCal URL from the Keychain. |
| `GET /v1/sources` | → `list[SourcePublic]` | Public registry fields + counts. |

Rules: CORS only `http://127.0.0.1:3000` and `http://localhost:3000`. Body ≤ 32 KB.
In-memory rate limit 30 req/min per client IP on `/v1/chat` → HTTP 429 JSON
`{"code":"RATE_LIMITED","message":...}`. Validation errors → HTTP 422 with a friendly
message (no echo of input values). No stack traces or env values in any response.
One log line per request: `request_id model mode tools=[..] chunks=[..] latency_ms error_code`.
**Never** log message text, tokens, or Moodle content.

## 3. SSE stream from `POST /v1/chat`

Each event is `event: <name>\ndata: <json>\n\n`. Order:
`status` → (`tool` start/done pairs)* → `sources` (0 or 1 time, before the first token) → `token`* → `done`.
An `error` event may replace everything after `status` and ends the stream.

```
event: status   data: {"request_id":"a1b2c3","model":"gemma4:26b-a4b-it-q4_K_M","mode":"live|mock|fallback"}
event: tool     data: {"name":"search_campus_docs","label":"Searching campus documents","state":"start|done|error"}
event: sources  data: [SourceItem, ...]
event: token    data: {"text":"..."}
event: done     data: {"citations":["S1","M2"],"follow_up":null|{"question":"...","options":["UG","PG"]},
                       "freshness":"current|needs_review|unknown","limitations":[],"latency_ms":1234,
                       "answer_kind":"answer|clarify|abstain","office_links":[{"title":..,"url":..,"issuer":..}]}
event: error    data: {"code":"MODEL_OFFLINE|TIMEOUT|BAD_REQUEST|RATE_LIMITED|INTERNAL","message":"human-friendly text"}
```

`SourceItem` = `{id, title, issuer, url, locator, checked_at, kind: "doc"|"moodle", snippet,
course, due_at, activity_url, demo}`. A `moodle` item with `due_at` is drawn as a deadline card.
`demo: true` means fixture data; the UI must label it "Demo data".

Tool labels (exact strings for the UI): `search_campus_docs` → "Searching campus documents",
`get_official_link` → "Finding the official page", `list_my_courses` → "Reading your Moodle courses",
`get_my_deadlines` → "Checking your Moodle deadlines", `get_course_contents` → "Opening course contents",
`ask_clarification` → "Asking a clarifying question".

Citations in token text are written `[S1]`, `[M2]`, optionally grouped `[S1][S2]`. The UI only
renders chips for ids listed in `done.citations` (and present in `sources`); every other marker is
hidden. The server also strips invalid markers from what it streams where it can (buffer at `[`).

`freshness`: `current` if every cited doc has `published_at` or `checked_at` within 400 days;
`needs_review` if any cited doc is older; `unknown` if nothing was cited.

Error messages (exact meaning, wording may vary):
- `MODEL_OFFLINE`: "The CampusPilot model is offline right now. Check the tunnel (`ssh -fN passpoli-llm`) and try again." The UI also shows the official links it can.
- `TIMEOUT`: "The model took too long to answer. Please try again."

## 4. Tools (read-only, Pydantic in and out — `schemas/tools.py`)

| Tool name | Input model | Output model | Implemented in |
|---|---|---|---|
| `search_campus_docs` | `SearchCampusDocsInput` | `SearchCampusDocsOutput` | `campuspilot/retrieval/tools.py` |
| `get_official_link` | `GetOfficialLinkInput` | `GetOfficialLinkOutput` | `campuspilot/retrieval/tools.py` |
| `list_my_courses` | `ListMyCoursesInput` | `ListMyCoursesOutput` | `campuspilot/moodle/tools.py` |
| `get_my_deadlines` | `GetMyDeadlinesInput` | `GetMyDeadlinesOutput` | `campuspilot/moodle/tools.py` |
| `get_course_contents` | `GetCourseContentsInput` | `GetCourseContentsOutput` | `campuspilot/moodle/tools.py` |
| `ask_clarification` | `{question: str ≤300, options: list[str] ≤4}` | — (control tool, ends the loop) | `campuspilot/tools/registry.py` |

Exact function signatures the backend registry calls:

```python
# campuspilot/retrieval/tools.py  (sync; registry runs them in a thread)
def search_campus_docs(args: SearchCampusDocsInput, db_path: Path | None = None) -> SearchCampusDocsOutput
def get_official_link(args: GetOfficialLinkInput, registry_path: Path | None = None) -> GetOfficialLinkOutput
def list_sources(db_path: Path | None = None) -> list[SourcePublic]          # for GET /v1/sources
def count_indexed_sources(db_path: Path | None = None) -> int                # for /v1/status

# campuspilot/moodle/tools.py  (async)
async def list_my_courses(args: ListMyCoursesInput) -> ListMyCoursesOutput
async def get_my_deadlines(args: GetMyDeadlinesInput) -> GetMyDeadlinesOutput
async def get_course_contents(args: GetCourseContentsInput) -> GetCourseContentsOutput
async def moodle_status() -> tuple[Literal["connected","not_configured","error"], Literal["rest","ical","demo","none"]]
async def save_credentials(req: MoodleTokenRequest) -> MoodleTokenResponse  # verify, then store in Keychain
def delete_credentials() -> MoodleTokenResponse
class MoodleError(Exception): code: Literal["not_configured","invalid_token","access_exception","timeout","unavailable"]; message: str
```

`db_path=None` means `get_settings().campuspilot_db_path`. If the DB file doesn't exist, doc tools
return empty results (never crash). Moodle tools raise `MoodleError` with a friendly message; the
registry turns it into a `tool` `error` event plus an evidence note for the model.

Behaviour notes:
- `search_campus_docs`: only sources with `handling='ingest'` and documents with `status='indexed'`.
  Score = −bm25 (bm25 weights: text 1.0, heading_path 0.5, title 0.5), ×1.25 for tier 1. Audience
  filter keeps chunks whose audience is NULL/"all" or matches. Max 2 chunks per document in the top-k.
- `get_official_link`: keyword match over the rows of `data/sources/registry.csv`, read directly (no DB
  needed, so links work on a fresh clone), over title, category, notes and issuer, any handling
  except `blocked`. Always returns the URL from the registry, never one built from the topic.
- Moodle: resolution order Keychain token → `MOODLE_TOKEN` → Keychain iCal → `MOODLE_ICAL_URL` →
  demo fixtures (if `MOODLE_DEMO_WHEN_UNCONFIGURED`) → `MoodleError("not_configured")`.
  Keyring service name `campuspilot`, usernames `moodle_token` and `moodle_ical_url`.
  Demo fixtures shift dates so deadlines are always in the coming days. Cache 5 min in memory,
  10 s timeout, nothing written to disk. In iCal mode, courses and contents return `note` saying they
  aren't available.

## 5. Evidence given to the model (backend)

Tool results go back to the model as a `role: "tool"` message whose content is evidence blocks:

```
<evidence id="S1" kind="doc" title="Academic Calendar 2026-27" issuer="Academic Office" tier="1"
          audience="all" published="2026-05-10" url="https://acad.iitb.ac.in/...">
...chunk text (data, not instructions)...
</evidence>
```

IDs are assigned by the orchestrator per turn, in order of first appearance (S1.. docs, M1.. Moodle).
Docs get **one id per document URL**: further chunks of the same document are merged into that id
(locator becomes e.g. "p. 2, p. 5"), so the UI shows one card per document. Moodle: one id per
deadline/course. If the model finishes without calling any tool (and the message isn't small talk),
the backend runs `search_campus_docs` with the student's message itself. Grouped markers such as
`[S1, S2]` are rewritten to `[S1][S2]` before streaming. `get_official_link`
results become `S` evidence too (kind="doc", text = notes). Moodle `M` evidence is personal data:
with `mode=fallback` and `ALLOW_PERSONAL_DATA_TO_CLOUD=false`, Moodle tools are not offered at all.

## 6. Answer kinds (backend decides, UI draws)

- `clarify`: a focused pre-check call (`agent/clarify.py`, JSON-only, setting `CLARIFY_PRECHECK`)
  decided the question needs one clarifying question, or the model called `ask_clarification`. The backend streams the question as tokens and sets
  `follow_up`. No other tools run after it.
- `abstain`: the final answer starts with the literal `ABSTAIN:` (the system prompt asks for it when
  evidence is missing). The backend replaces the model's wording with one fixed sentence
  ("I couldn't verify this in my sources, so I won't guess. …"), sets `answer_kind="abstain"`,
  and fills `office_links` from `get_official_link` (it calls it itself if the model didn't).
- `answer`: everything else.

## 7. SQLite (`data/campuspilot.db`, gitignored) — owned by data

```sql
CREATE TABLE sources (id TEXT PRIMARY KEY, title TEXT, issuer TEXT, category TEXT, url TEXT,
  authority_tier INTEGER, audience TEXT, handling TEXT, robots_ok INTEGER, status TEXT,
  last_checked_at TEXT, notes TEXT);
CREATE TABLE documents (id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id), url TEXT,
  content_hash TEXT, title TEXT, published_at TEXT, fetched_at TEXT, parser TEXT, status TEXT,
  raw_path TEXT, fetched_via TEXT DEFAULT 'mac');           -- new row when the hash changes
CREATE TABLE chunks (id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents(id),
  heading_path TEXT, page INTEGER, text TEXT, audience TEXT);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, heading_path, title,
  content='', tokenize='porter unicode61');                 -- rowid = chunks.id
```

Only the latest `indexed` document per URL is searchable. `scripts/reindex.py` rebuilds chunks and FTS
from `data/raw/`. `data/sources/registry.csv` is the only copy of the registry and is loaded into
`sources` on every ingest.

## 8. Environment variables

See `.env.example` (lead-owned). Read only through `campuspilot.config.get_settings()`.
Frontend: `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`), `NEXT_PUBLIC_MOCK` (`true` = built-in mock SSE).

## 9. Mock modes

- `CAMPUSPILOT_MOCK_LLM=true`: the backend uses a scripted fake LLM (keyword rules → tool calls, then a
  canned answer that cites the real evidence ids). Real tools still run. `mode="mock"`.
- `NEXT_PUBLIC_MOCK=true`: the UI never calls the API; `apps/web/lib/mock-stream.ts` replays §3 events.

## 10. Hosted mode (v1.1, `DEPLOY_MODE=hosted`; spec: `DEPLOY_MASTER_PROMPT.md`)

Local mode (`DEPLOY_MODE=local`, the default) behaves as in §2–§9, except §10.4, which applies to
**both** modes.

### 10.1 Phase-1 ownership (v1.1)

| Owner | Paths |
|---|---|
| lead | as §1, plus `campuspilot/llm/providers.py`, `DEPLOY_MASTER_PROMPT.md`, `.python-version`, `.nvmrc`, root configs |
| backend | `campuspilot/{main.py,api/,agent/,llm/ (not providers.py),tools/}`, `tests/test_api*`, `tests/test_agent*`, `tests/test_llm*`, `tests/test_hosted*`, `tests/test_privacy*` |
| moodle | `campuspilot/moodle/`, `scripts/moodle_check.py`, `tests/test_moodle*` |
| infra | `apps/api/Dockerfile`, `.dockerignore`, `render.yaml`, `.github/workflows/`, `campuspilot/index_release.py`, `scripts/release_index.py`, `tests/test_index_release*` |
| frontend | `apps/web/` |

### 10.2 Bring-your-own-key headers

| Header | Rule |
|---|---|
| `X-LLM-Provider` | one of `groq`, `gemini`, `openai`, `openrouter` (`campuspilot/llm/providers.py`). Base URLs are hard-coded there; **no URL is ever accepted from the client**. |
| `X-LLM-Key` | `^[A-Za-z0-9_\-.]{20,300}$`. Lives only for that request: never stored, logged, cached, echoed, or put in an exception message. |
| `X-LLM-Model` | optional override for **both** router and answer model; `^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}$`. |
| `X-Moodle-Token` | optional; same rules as the LLM key (8–128 chars). Sent only to `MOODLE_BASE_URL`. |
| `X-Moodle-Ical-Url` | optional; must be `https://moodle.iitb.ac.in/...`; redirects to any other host are refused. |

Hosted `POST /v1/chat` order of checks (all before any work): body ≤ 8 KB → IP rate limit →
provider + key present (else **HTTP 401** `{"code":"MODEL_KEY_REQUIRED"}`) → header format
(bad provider/model → 400 `BAD_REQUEST`; malformed key → 401 `PROVIDER_KEY_REJECTED`). Then the
SSE stream starts. Provider failures after that arrive as SSE `error` events.
In local mode these headers are ignored.

### 10.3 Provider errors (one OpenAI-compatible client, `llm/byok.py`)

| Provider response | Code | Message (with the provider label) |
|---|---|---|
| 401 / 403 | `PROVIDER_KEY_REJECTED` | "Your Groq key was rejected. Check it in Settings." |
| 429 | `PROVIDER_RATE_LIMITED` | "Groq says you've hit your free limit; try again in a minute." + `retry_after_s` from `retry-after` if present |
| timeout | `PROVIDER_TIMEOUT` | retried **once**, then this |
| anything else | `PROVIDER_ERROR` | "Groq returned an error. Please try again." |

Never switch providers for the student. Router model = clarify pre-check + tool routing (temperature 0);
answer model = streamed final answer (temperature 0.2, `max_tokens` = `HOSTED_MAX_OUTPUT_TOKENS`, 400).
Hosted budgets: history ≤ 6 turns, evidence ≤ ~2,500 tokens (≤ 5 chunks, trimmed), short system prompt.
`CAMPUSPILOT_MOCK_LLM=true` in hosted mode still requires the headers but answers with `MockLLM`.

New endpoints:
- `POST /v1/llm/check` (BYO headers, no body) → `LLMCheckResponse`. One tiny router-model call
  (`max_tokens` 1). 200 with `ok:true`, or the HTTP status above with `ok:false` + code/message.
- `POST /v1/moodle/check` (Moodle headers) → `MoodleTokenResponse`. Verifies, stores nothing.
- Hosted: `POST`/`DELETE /v1/moodle/token` → 404 `{"code":"NOT_AVAILABLE"}` (no Keychain on a server).
- `GET /v1/status` (public) adds `deploy_mode`, `index`, `index_version`, `providers` (hosted:
  `ProviderInfo` list; no key data). Hosted: no Ollama probe; `model="byok"`, `mode="byok"`.
- `/health`, `/v1/status`, `/v1/sources`, `/v1/knowledge/search` stay public (IP rate limit applies).

Abuse limits (both modes, in memory): **20 requests/min and 400/day per client IP** on `/v1/chat`,
`/v1/llm/check`, `/v1/moodle/check`, `/v1/knowledge/search` → 429 `RATE_LIMITED` with
`retry_after_s`. Client IP in hosted mode: `CF-Connecting-IP`, else the **last** `X-Forwarded-For`
entry, else the socket peer (never the leftmost XFF entry, which the client controls).
CORS: `127.0.0.1:3000`, `localhost:3000`, plus `ALLOWED_ORIGINS` (comma separated); allowed request
headers are exactly `Content-Type` + the five headers above.

### 10.4 Moodle content never reaches an LLM (both modes)

- The LLM only **routes**: it may call `get_my_deadlines`, `list_my_courses`, `get_course_contents`
  with arguments taken from the student's own question (`course_code`, `days_ahead`).
- Moodle results go **straight to the UI** as `sources` items (`kind:"moodle"`, ids `M1..`). The answer
  sentence is a **template written by our code** (`agent/moodle_answer.py`), e.g. "You have 4 deadlines
  in the next 7 days. The nearest is IE624 Assignment 3, due in 20 hours." `answer_kind="moodle"`.
- The LLM's tool message for a Moodle tool is exactly `[Moodle results shown to the user: N items]`.
- If only Moodle tools ran, no final LLM call is made. If doc tools also ran, the template sentence
  is streamed first, then the LLM answer over the doc evidence only.
- History turns with `kind:"moodle"` are replaced by `[Moodle results were shown to the user]` before
  any LLM call (the browser sends `kind` back with each assistant turn).
- Test (`tests/test_privacy_moodle.py`): records every outgoing LLM request body and fails if any Moodle
  field value (titles, course names, URLs, dates) appears in it.
- `ALLOW_PERSONAL_DATA_TO_CLOUD` no longer gates Moodle tools (nothing personal is sent); keep the
  setting for compatibility.

### 10.5 Moodle per request (hosted)

Credentials come only from the request headers, held in a `contextvars.ContextVar` for that request.
No Keychain, no env token, no cache across requests (cache key must never be shared between users;
hosted mode disables the cross-request cache). No header → demo fixtures (labelled), as in local mode.
`scripts/moodle_check.py --api-url URL` checks Moodle through a deployed API (reads the token from `.env`).
If IITB Moodle doesn't answer from Render, `/v1/moodle/check` returns `NOT_AVAILABLE` with
"Moodle isn't reachable from the hosted version. Use the local app." and everything else still works.

### 10.6 Index release

GitHub Action `build-index.yml` (manual + weekly Monday 03:00 IST = Sunday 21:30 UTC) runs the ingest,
then `scripts/release_index.py` writes `manifest.json` (per source: id, url, fetched_at, sha256 of each
document) and `SHA256SUMS`, and creates release `index-YYYY-MM-DD` with assets `campuspilot.db`,
`manifest.json`, `SHA256SUMS`. It commits nothing and refuses to publish an index with fewer than
100 chunks. With `INDEX_SOURCE=release` the API (`campuspilot/index_release.py`, at startup, ≤ 30 s)
downloads the newest `index-*` release from `INDEX_REPO`, verifies the SHA-256, and uses it; on any
failure it builds the fixture demo index (`ingestion/demo.py`) and reports `index:"fallback"`.
Downloads follow redirects only to `github.com`, `api.github.com`, `objects.githubusercontent.com`,
`release-assets.githubusercontent.com`.

### 10.7 Frontend env

`NEXT_PUBLIC_API_URL` (falls back to `NEXT_PUBLIC_API_BASE`, then `http://127.0.0.1:8000`).
The UI learns local vs hosted from `/v1/status.deploy_mode`; one build serves both.
Client-only state `SERVER_WAKING`: `/v1/ping` not answering within 3 s → banner "Waking the server,
up to about a minute…" and retry with exponential backoff for up to about 90 s.

## 11. v2 connectors: Webmail, ASC, Google Calendar (local mode only; spec: `INTEGRATIONS_BUILD_PROMPT.md`)

Python source of truth: `apps/api/campuspilot/schemas/connectors.py` (lead-owned). If this section
and the schemas disagree, the schemas win.

### 11.1 Owner decisions (fixed)

- **Local only.** Webmail and ASC use the student's IITB LDAP password, so they run only with
  `DEPLOY_MODE=local`, the API on `127.0.0.1`, on campus or the IITB VPN. In hosted mode the
  connector router is **not mounted** and the tools are **not offered**, whatever the flags say
  (`Settings.webmail_on / asc_on / gcal_on`). Tested in `tests/test_connectors_contract.py`.
- Flags `WEBMAIL_ENABLED`, `ASC_ENABLED`, `GCAL_ENABLED` default to `false`. `CONNECTORS_DEMO=true`
  serves labelled fixture data (`demo: true`) instead of a live account.
- Webmail is read over **IMAP with SSL** (`IMAP_HOST`, `IMAP_PORT`=993; confirmed before Phase 2).
- ASC is the **internal portal** (`ASC_BASE_URL`), with login through **IITB SSO (LDAP)**. If it
  ever shows an OTP or CAPTCHA, the student completes it in the UI; nothing is bypassed.
- Mail text is read only by the **local Gemma** (`llm/personal.py`); a cloud model only with
  `ALLOW_PERSONAL_DATA_TO_CLOUD=true`. ASC data and grades go to **no model at all**.
- Calendar: **suggest, then the student confirms.** One click creates one event. Never a tool.

### 11.2 Ownership (Phase 1)

| Owner | Paths |
|---|---|
| lead | as §1 plus `schemas/connectors.py`, `connectors/` (errors, keychain), `api/connectors.py`, `tools/registry.py`, `tools/cards.py`, `agent/personal_answer.py`, `agent/orchestrator.py`, `agent/prompts.py`, `llm/personal.py`, `llm/mock.py`, `main.py`, `tests/test_connectors_contract.py`, `INTEGRATIONS_BUILD_PROMPT.md` |
| A webmail (`v2/webmail`) | `campuspilot/mail/**`, `data/fixtures/mail/**` (synthetic `.eml`), `scripts/mail_login.py`, `tests/test_mail*`, `tests/mail_helpers.py` |
| B asc (`v2/asc`) | `campuspilot/asc/**`, `data/fixtures/asc/**` (synthetic or fully anonymised HTML), `tests/test_asc*`, `tests/asc_helpers.py` |
| C gcal (`v2/gcal`) | `campuspilot/gcal/**`, `tests/test_gcal*`, `tests/gcal_helpers.py` |
| D web (`v2/web`) | `apps/web/**` |

Workers need something outside their paths → write `NEEDS:` in the report; the lead changes it.
**No new Python dependencies** without asking: IMAP and mail parsing use the standard library
(`imaplib`, `email`), ASC uses `httpx` + `beautifulsoup4`, Google uses plain `httpx` against the
OAuth and Calendar REST endpoints (no Google SDK), tests mock with `respx`.

### 11.3 Tools and cards

The model may call these (all read-only, offered only when the connector is on):

| Tool | Input | Output | Kind | Label (exact UI string) |
|---|---|---|---|---|
| `search_my_mail` | `SearchMyMailInput{query, days=14, summarize=false}` | `SearchMyMailOutput` | mail | "Searching your mail" |
| `get_upcoming_institute_events` | `UpcomingEventsInput{days=7, only_deadlines=false}` | `UpcomingEventsOutput` | mail | "Finding events in your mail" |
| `get_my_timetable` | `GetMyTimetableInput{when=today\|tomorrow\|this_week, on_date?}` | `AscTimetableOutput` | asc | "Reading your ASC timetable" |
| `get_my_registered_courses` | `GetMyRegisteredCoursesInput{semester?}` | `AscCoursesOutput` | asc | "Reading your ASC courses" |
| `get_my_grades` | `GetMyGradesInput{semester?}` | `AscGradesOutput` | asc | "Reading your ASC grades" |

There is **no calendar tool**. Events are created only by `POST /v1/calendar/events` (§11.5).

SSE: a new event `cards` (0 or 1 time) comes after `sources` and before the first `token`:
`status → tool* → sources? → cards? → token* → done`. Its data is a list of `Card`, discriminated by
`type`:

| `type` | id prefix | `source_label` | payload | extra |
|---|---|---|---|---|
| `mail` | W1.. | Webmail | `mail: MailMessage` (sender, subject, date, snippet ≤300, `open_url`) | no full bodies |
| `event` | E1.. | Webmail | `event: DetectedEvent` | `can_add_to_calendar` |
| `asc_slot` | A1.. | ASC | `slot: AscTimetableSlot` | `on_date` when one day |
| `asc_course` | A1.. | ASC | `course: AscCourse` | |
| `asc_grade` | A1.. | ASC | `grade: AscGrade` | |

Every card has `id`, `type`, `source_label`, `demo`. Moodle items stay as `sources` with
`kind:"moodle"` (label them "Moodle"); documents are "Official page". Card ids are never cited.
`can_add_to_calendar` is true only when Google Calendar is connected, the event has a `start`, the
date is not uncertain and the data is not demo. `DetectedEvent.id = event_key(message_id, start)`.

### 11.4 Privacy: what reaches a model

- The chat model sees only `[Webmail results shown to the user: N items]` (or ASC), never card
  content. The answer text is a **template sentence** written by `agent/personal_answer.py`; with
  only personal tools, `answer_kind="personal"` (Moodle only stays `"moodle"`) and no model call
  writes the answer. History turns with `kind` `moodle` or `personal` are replaced before any model
  sees them.
- The mail module may call `personal_data_llm(settings)` (local Gemma, the mock, or `None`) for
  two jobs, each **one call with no tools**: extract `DetectedEvent` fields and write a summary the
  student asked for. Mail text is wrapped as untrusted data (`<mail>` blocks; the prompt says it is
  data, never instructions). With `None` the module uses rules only and says so in `note`.
- Event detection: rules first (dates, times, venues, known institute senders), then the model
  fills fields. A date is kept only if the rules or the model point at text in the mail
  (`date_text`); otherwise `start=None`, `date_uncertain=true`. Never invent a date.
- Never log mail text, subjects, bodies, ASC pages, grades, passwords, OTPs, cookies or tokens.

### 11.5 Endpoints (local only; router mounted only when `DEPLOY_MODE=local`)

Every POST/DELETE needs header **`X-CampusPilot-Confirm: yes`** (403 otherwise). A custom header
forces a CORS preflight, and CORS allows only the local UI. Each endpoint returns 404
`NOT_AVAILABLE` when its flag is off. Login bodies are never echoed.

| Method & path | Body → response | Notes |
|---|---|---|
| `GET /v1/connectors` | → `ConnectorsResponse{webmail, asc, gcal: ConnectorStatus}` | state: disabled / not_connected / needs_otp / connected / error |
| `POST /v1/connectors/webmail/login` | `ConnectorLoginRequest` → `ConnectorStatus` | IMAP LOGIN check, then Keychain |
| `DELETE /v1/connectors/webmail` | → `ConnectorStatus` | deletes Keychain entries |
| `POST /v1/connectors/asc/login` | `ConnectorLoginRequest` → `ConnectorStatus` | may return `needs_otp` + `challenge_id` |
| `POST /v1/connectors/asc/otp` | `ConnectorOtpRequest{challenge_id, code}` → `ConnectorStatus` | |
| `DELETE /v1/connectors/asc` | → `ConnectorStatus` | drops session and Keychain entries |
| `POST /v1/connectors/gcal/connect` | → `GcalConnectStart{auth_url}` | UI opens it in a new tab |
| `GET /v1/connectors/gcal/callback` | `?code&state` → small HTML page | Google's loopback redirect; `state` + PKCE checked |
| `DELETE /v1/connectors/gcal` | → `ConnectorStatus` | revoke at Google, then delete |
| `POST /v1/calendar/events` | `CalendarEventRequest` → `CalendarEventResult` | the only write; idempotent |

`StatusResponse.connectors` lists the connectors that are on (always `[]` hosted).

Module signatures the API and registry call (Phase 0 stubs raise `ConnectorError("not_implemented")`):

```python
# campuspilot/mail/__init__.py
async def search_my_mail(args: SearchMyMailInput) -> SearchMyMailOutput
async def get_upcoming_institute_events(args: UpcomingEventsInput) -> UpcomingEventsOutput
async def mail_status() -> ConnectorStatus
async def mail_login(req: ConnectorLoginRequest) -> ConnectorStatus
def mail_logout() -> ConnectorStatus
# campuspilot/asc/__init__.py
async def get_my_timetable(args: GetMyTimetableInput) -> AscTimetableOutput
async def get_my_registered_courses(args: GetMyRegisteredCoursesInput) -> AscCoursesOutput
async def get_my_grades(args: GetMyGradesInput) -> AscGradesOutput
async def asc_status() -> ConnectorStatus
async def asc_login(req: ConnectorLoginRequest) -> ConnectorStatus
async def asc_submit_otp(req: ConnectorOtpRequest) -> ConnectorStatus
def asc_logout() -> ConnectorStatus
# campuspilot/gcal/__init__.py
def is_connected() -> bool                      # Keychain only, no network
async def gcal_status() -> ConnectorStatus
async def gcal_start_connect() -> GcalConnectStart
async def gcal_finish_connect(code: str, state: str) -> ConnectorStatus
async def gcal_disconnect() -> ConnectorStatus
async def create_event(req: CalendarEventRequest) -> CalendarEventResult
# each package re-exports ConnectorError (campuspilot/connectors/errors.py)
```

Keychain (`connectors/keychain.py`, service `campuspilot`): `webmail_username`, `webmail_password`,
`asc_username`, `asc_password`, `gcal_refresh_token`, `gcal_account`. ASC session cookies live in
memory only. Nothing secret in `.env`, logs, Git, a model prompt or an error message.

### 11.6 Errors

Connector modules raise `ConnectorError(code, message)`; `message` is friendly and secret-free.
In chat, a failed tool gives a `tool` `error` event and the message becomes the student-facing
sentence. On endpoints: `disabled`→404 NOT_AVAILABLE, `not_connected`→409 NOT_CONNECTED,
`auth_failed`/`otp_invalid`→401 AUTH_FAILED, `otp_required`→401 OTP_REQUIRED,
`session_expired`→401 SESSION_EXPIRED, `unreachable`/`timeout`→503 UNREACHABLE (say "on campus or
the IITB VPN"), `parse_failed`→502 INTERNAL, `blocked`→502 NOT_AVAILABLE, `google_error`→502
CALENDAR_ERROR, `not_implemented`→501 NOT_AVAILABLE.

### 11.7 Per-connector rules

- **Webmail (A):** `imaplib.IMAP4_SSL`; `select(folder, readonly=True)`; fetch with `BODY.PEEK[]`
  (or `BODY.PEEK[HEADER]` + a size-capped `BODY.PEEK[TEXT]`). Never STORE, COPY, MOVE, EXPUNGE,
  APPEND or send. `open_url` from `WEBMAIL_URL` only if a reliable link format is known, else `None`.
- **ASC (B):** an `httpx` session; after login only GET. Never submit registration, add/drop or
  feedback forms. One request at a time, cache `ASC_CACHE_TTL_S`, clear `session_expired` message.
  Allowed hosts: `*.iitb.ac.in` only. Can't automate safely → `blocked` with the reason.
- **Google Calendar (C):** installed-app OAuth with PKCE, loopback redirect
  `http://127.0.0.1:{API_PORT}/v1/connectors/gcal/callback`, scope
  `https://www.googleapis.com/auth/calendar.events` only. Client file `GCAL_CLIENT_FILE` (outside the
  repo). Calendar `GCAL_CALENDAR_ID`. Before inserting, look for an event with
  `privateExtendedProperty=campuspilotKey=<event_id>` and return `already_exists` if found. Time zone
  `GCAL_TIMEZONE`, reminder `GCAL_REMINDER_MINUTES` (popup), description = source mail subject +
  "Added by CampusPilot". `end=None` → start + 1 h (all-day → that day).
- **Web (D):** Settings → "Connectors" section (local mode only, hidden when
  `/v1/status.deploy_mode` is hosted): three cards with status, Connect / Disconnect, the OTP step,
  and "Turned off" with the env flag when disabled. Answer cards for every `Card` type, each with its
  `source_label`; event card "Add to Google Calendar" → `POST /v1/calendar/events` with the confirm
  header → "Added ✓ · View in Calendar" (`html_link`), or "Connect Google Calendar" when
  `can_add_to_calendar` is false because it isn't connected, or "Date unclear, open the mail".
  Demo cards say "Demo data". Mock SSE journeys for the three example questions; Playwright tests.
