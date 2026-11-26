# CampusPilot API

Base URL: `<RENDER_URL>` for the hosted pilot, `http://127.0.0.1:8000` locally. Request and response bodies are JSON. The full contract is `docs/CONTRACT.md`. This page covers hosted mode (`DEPLOY_MODE=hosted`); local differences are noted.

## Endpoints

| Method | Path | Auth headers | Rate limited | Notes |
|---|---|---|---|---|
| GET | `/health` | none | no | `{"ok": true}` |
| GET | `/v1/ping` | none | no | `{"ok": true}`. Same as `/health`; the web UI uses it because browser content blockers block URLs ending in `/health`. |
| GET | `/v1/status` | none | no | Mode, index, providers. No key data. |
| GET | `/v1/sources` | none | no | The source registry with index status. |
| POST | `/v1/knowledge/search` | none | yes | Search the index. No model involved. |
| POST | `/v1/chat` | `X-LLM-Provider`, `X-LLM-Key`, optional `X-LLM-Model`, optional Moodle headers | yes | SSE stream. |
| POST | `/v1/llm/check` | `X-LLM-Provider`, `X-LLM-Key`, optional `X-LLM-Model` | yes | One tiny model call. No body. Hosted only. |
| POST | `/v1/moodle/check` | `X-Moodle-Token` or `X-Moodle-Ical-Url` | yes | Verifies Moodle access. Stores nothing. |
| POST, DELETE | `/v1/moodle/token` | n/a | no | Hosted: always 404 `NOT_AVAILABLE`. Local only (Keychain). |

### GET /v1/status

```json
{
  "model_online": true, "model_loaded": true, "model": "byok",
  "moodle": "not_configured", "moodle_mode": "none",
  "sources_indexed": 0, "mode": "byok", "deploy_mode": "hosted",
  "index": "release", "index_version": "index-YYYY-MM-DD",
  "providers": [{"id": "groq", "label": "Groq", "router_model": "...", "answer_model": "...",
                 "key_url": "...", "recommended": true, "free_tier": true, "note": "...", "tested": false}]
}
```

- `index` is one of `release`, `local`, `fallback` (fixture demo index), `missing`.
- `moodle` is `connected`, `not_configured` or `error`. `moodle_mode` is `rest`, `ical`, `demo` or `none`.
- In hosted mode `model` is `"byok"`: the model depends on each student's key.

### POST /v1/knowledge/search

Request (extra fields are rejected):

| Field | Type | Rule |
|---|---|---|
| `query` | string | 1-300 chars, required |
| `category` | string or null | up to 50 chars |
| `audience` | string or null | up to 50 chars |
| `k` | integer | 1-8, default 6 |

Response: `{"hits": [ ... ]}`. Each hit has `chunk_id`, `source_id`, `document_id`, `title`, `issuer`, `url`, `heading_path`, `page`, `text`, `audience`, `authority_tier`, `category`, `checked_at`, `published_at`, `score`.

### POST /v1/chat

Request (extra fields are rejected):

| Field | Type | Rule |
|---|---|---|
| `message` | string | 1-2000 chars, required |
| `history` | array of turns | up to 100 turns; the server keeps the last 20 (hosted: 6 reach the model) |
| `history[].role` | `"user"` or `"assistant"` | required |
| `history[].content` | string | up to 8000 chars |
| `history[].kind` | `answer`, `clarify`, `abstain`, `moodle` or null | Send back the `answer_kind` of assistant turns. `moodle` turns are replaced with a placeholder before any model sees them. |

The whole body must be 8 KB or less in hosted mode (32 KB locally).

Response: `200` with `Content-Type: text/event-stream` (see SSE below). Header checks fail before the stream starts, as normal JSON errors.

### POST /v1/llm/check

No body. Success: `200 {"ok": true, "provider": "groq", "model": "<router model>"}`. Failure: the HTTP status in the error table, with `{"ok": false, "provider", "model", "code", "message"}`. Local mode: 404 `NOT_AVAILABLE`.

### POST /v1/moodle/check

Response: `{"ok", "mode": "rest|ical|none", "site_name", "user_fullname", "message"}`. If Moodle cannot be reached from the server: 503 `NOT_AVAILABLE`. Bad credentials or format: 400 `BAD_REQUEST`.

## Bring-your-own-key headers

| Header | Required | Rule |
|---|---|---|
| `X-LLM-Provider` | yes (chat, llm/check) | One of `groq`, `gemini`, `openai`, `openrouter`. Matched case-insensitively. Provider URLs are fixed in the server; no URL is ever accepted from the client. |
| `X-LLM-Key` | yes | Regex `^[A-Za-z0-9_\-.]{20,300}$`. Used for this request only; never stored, logged or echoed. |
| `X-LLM-Model` | no | Overrides both router and answer model. Regex `^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}$`. |

Check order for `/v1/chat`: body size, IP rate limit, provider and key present, provider known, model valid, key format. All happen before any model call.

In local mode these headers are ignored.

## Moodle headers (optional)

| Header | Rule |
|---|---|
| `X-Moodle-Token` | 8-128 chars. Sent only to `https://moodle.iitb.ac.in`. |
| `X-Moodle-Ical-Url` | Must be `https://moodle.iitb.ac.in/...`. Redirects to any other host are refused. |

With neither header, Moodle tools return clearly labelled demo data. Credentials live in memory for one request. Moodle results go to the browser only; the model never sees them (it sees `[Moodle results shown to the user: N items]`). A bad Moodle header gives 400 `BAD_REQUEST`.

## SSE events from /v1/chat

Each message looks like:

```
event: token
data: {"text": "Hello"}

```

Order: `status`, then zero or more `tool` events, then optionally `sources`, then zero or more `token`, then `done`. At any point a single `error` event can replace the rest and ends the stream.

| Event | Payload |
|---|---|
| `status` | `{"request_id", "model", "mode"}`. `mode` is `live`, `mock`, `fallback` or `byok`. |
| `tool` | `{"name", "label", "state"}`. `state` is `start`, `done` or `error`. |
| `sources` | List of `{"id", "title", "issuer", "url", "locator", "checked_at", "kind", "snippet", ...}`. `id` is `S1..` for documents, `M1..` for Moodle. `kind` is `doc` or `moodle`. Moodle items add `course`, `due_at`, `activity_url`, `demo`. |
| `token` | `{"text"}`: a piece of the answer. |
| `done` | `{"citations": ["S1"], "follow_up": {"question", "options"} or null, "freshness": "current|needs_review|unknown", "limitations": [], "latency_ms", "answer_kind": "answer|clarify|abstain|moodle", "office_links": [{"title", "url", "issuer"}]}` |
| `error` | `{"code", "message", "provider", "retry_after_s"}`. `provider` and `retry_after_s` can be null. |

## Error codes

JSON errors have the shape `{"code": "...", "message": "..."}`, plus `retry_after_s` and a `Retry-After` header on 429. Messages never contain keys, tokens or your input. Codes with a stream-only row arrive as an SSE `error` event after the stream has started.

| Code | HTTP | When |
|---|---|---|
| `MODEL_KEY_REQUIRED` | 401 | Hosted `/v1/chat` without `X-LLM-Provider` or `X-LLM-Key`. |
| `PROVIDER_KEY_REJECTED` | 401 | Key fails the format check, or the provider answers 401/403. On `/v1/llm/check` it is the HTTP status; in a chat stream it is an SSE event. |
| `PROVIDER_RATE_LIMITED` | 429 on `/v1/llm/check`; SSE in chat | Provider answered 429 (the student's free limit). `retry_after_s` is set when the provider sent `retry-after`. |
| `PROVIDER_TIMEOUT` | 504 on `/v1/llm/check`; SSE in chat | Provider timed out (30 s; retried once first). |
| `PROVIDER_ERROR` | 502 on `/v1/llm/check`; SSE in chat | Any other provider failure. |
| `BAD_REQUEST` | 400 | Unknown provider, invalid model name, bad Moodle header or value. |
| `BAD_REQUEST` | 422 | Body failed validation. The message lists field names only. |
| `BAD_REQUEST` | 413 | Body larger than the limit. |
| `RATE_LIMITED` | 429 | Per-IP limit hit (see below). |
| `NOT_AVAILABLE` | 404 | `/v1/llm/check` in local mode; `/v1/moodle/token` in hosted mode. |
| `NOT_AVAILABLE` | 503 | Moodle not reachable from the hosted server (`/v1/moodle/check`). |
| `MODEL_OFFLINE` | SSE | Local mode: the Ollama model is unreachable. |
| `TIMEOUT` | SSE | The request ran too long. |
| `INTERNAL` | 500 | Unexpected server error. Message is generic; details are not returned. |

## Rate limits and size limits

- Per client IP: **20 requests per minute and 400 per day**, on `/v1/chat`, `/v1/llm/check`, `/v1/moodle/check` and `/v1/knowledge/search`. Over the limit: 429 `RATE_LIMITED` with `retry_after_s`. Counted in memory; reset on restart.
- Hosted client IP: `CF-Connecting-IP`, else the last `X-Forwarded-For` entry, else the socket peer.
- Body limit: 8 KB hosted, 32 KB local. Message 2000 chars, history turn 8000 chars.
- Your model provider has its own limits (see `docs/DEPLOY.md`). Questions per minute on a free Groq key: TBD after Phase 3.

## CORS

Allowed origins: `http://127.0.0.1:3000`, `http://localhost:3000`, plus everything in `ALLOWED_ORIGINS`. Methods: `GET`, `POST`, `DELETE`, `OPTIONS`. Allowed request headers: `Content-Type`, `X-LLM-Provider`, `X-LLM-Key`, `X-LLM-Model`, `X-Moodle-Token`, `X-Moodle-Ical-Url`. Command-line clients are not affected by CORS.

## Examples

Set your own key in the environment first. Never paste it into files you commit.

```bash
export GROQ_API_KEY=...   # your own key from https://console.groq.com/keys
export API=<RENDER_URL>
```

No key: 401.

```bash
curl -i -X POST "$API/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"Where is the academic calendar?"}'
# HTTP/1.1 401 ... {"code":"MODEL_KEY_REQUIRED","message":"Add your own model key in Settings to start chatting."}
```

Streaming chat (`-N` turns off curl's buffering):

```bash
curl -N -X POST "$API/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-LLM-Provider: groq" \
  -H "X-LLM-Key: $GROQ_API_KEY" \
  -d '{"message":"Where can I find the academic calendar?","history":[]}'
```

Knowledge search (no key):

```bash
curl -X POST "$API/v1/knowledge/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"academic calendar","k":3}'
```

Check a key:

```bash
curl -X POST "$API/v1/llm/check" \
  -H "X-LLM-Provider: groq" -H "X-LLM-Key: $GROQ_API_KEY"
```

Python with `httpx`:

```python
import json, os
import httpx

api = os.environ["API"]
headers = {"X-LLM-Provider": "groq", "X-LLM-Key": os.environ["GROQ_API_KEY"]}
body = {"message": "Where can I find the academic calendar?", "history": []}

with httpx.stream("POST", f"{api}/v1/chat", json=body, headers=headers, timeout=90) as r:
    r.raise_for_status()
    event = "message"
    for line in r.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:])
            if event == "token":
                print(data["text"], end="", flush=True)
            elif event in ("done", "error"):
                print("\n", event, data)
```
