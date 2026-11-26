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
| `GET /health` | → `{"ok": true}` | Process is up. No dependencies checked. |
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
def get_official_link(args: GetOfficialLinkInput, db_path: Path | None = None) -> GetOfficialLinkOutput
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
- `get_official_link`: keyword match over registry rows (title, category, notes, issuer), any handling
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

IDs are assigned by the orchestrator per turn, in order of first appearance (S1.. docs, M1.. Moodle,
one id per chunk/deadline/course). The same chunk keeps its id within a turn. `get_official_link`
results become `S` evidence too (kind="doc", text = notes). Moodle `M` evidence is personal data:
with `mode=fallback` and `ALLOW_PERSONAL_DATA_TO_CLOUD=false`, Moodle tools are not offered at all.

## 6. Answer kinds (backend decides, UI draws)

- `clarify`: the model called `ask_clarification`. The backend streams the question as tokens and sets
  `follow_up`. No other tools run after it.
- `abstain`: the final answer starts with the literal `ABSTAIN:` (the system prompt asks for it when
  evidence is missing). The backend strips the prefix before streaming, sets `answer_kind="abstain"`,
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
