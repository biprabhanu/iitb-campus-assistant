"""Chat request and SSE event models (docs/CONTRACT.md §2 and §3).

The SSE stream from `POST /v1/chat` sends, in order:
  status -> (tool start/done)* -> sources? -> cards? -> token* -> done
(`cards` is v2, local mode only: Webmail / ASC cards, CONTRACT §11.)
or, at any point, a single `error` event that ends the stream.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# live = Ollama via the tunnel, mock = scripted fake model, fallback = optional cloud fallback,
# byok = hosted mode with the student's own provider key.
Mode = Literal["live", "mock", "fallback", "byok"]
DeployMode = Literal["local", "hosted"]
ToolState = Literal["start", "done", "error"]
SourceKind = Literal["doc", "moodle"]
Freshness = Literal["current", "needs_review", "unknown"]
# moodle = a template sentence written by our code over Moodle results (no LLM wording).
# personal = the same for v2 connectors (Webmail, ASC, possibly with Moodle): our sentence plus
#            cards. The browser echoes it in history and the server hides that content (§11.4).
AnswerKind = Literal["answer", "clarify", "abstain", "moodle", "personal"]
ErrorCode = Literal[
    "MODEL_OFFLINE",
    "TIMEOUT",
    "BAD_REQUEST",
    "RATE_LIMITED",
    "INTERNAL",
    # hosted (bring-your-own-key) mode, CONTRACT §10:
    "MODEL_KEY_REQUIRED",
    "PROVIDER_KEY_REJECTED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_TIMEOUT",
    "PROVIDER_ERROR",
    "NOT_AVAILABLE",
    # v2 connectors (local only, CONTRACT §11.6); used by the /v1/connectors endpoints:
    "NOT_CONNECTED",
    "AUTH_FAILED",
    "OTP_REQUIRED",
    "UNREACHABLE",
    "SESSION_EXPIRED",
    "CALENDAR_ERROR",
]


# ---------- request ----------


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)
    # The browser echoes the answer_kind of assistant turns. Turns with kind="moodle" hold
    # personal data, so the server replaces their content before any LLM sees the history.
    # The same goes for kind="personal" (v2 connectors).
    kind: AnswerKind | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    # The browser may send more; the server keeps only the last 20 turns.
    history: list[ChatTurn] = Field(default_factory=list, max_length=100)


# ---------- SSE event payloads ----------


class StatusEvent(BaseModel):
    request_id: str
    model: str
    mode: Mode


class ToolEvent(BaseModel):
    name: str
    label: str  # human text for the UI, e.g. "Searching campus documents"
    state: ToolState


class SourceItem(BaseModel):
    """One citable piece of evidence. `id` is S1.. for docs, M1.. for Moodle."""

    id: str
    title: str
    issuer: str
    url: str
    locator: str | None = None  # "p. 3" or a heading path
    checked_at: str | None = None  # ISO 8601 date the source was last fetched
    kind: SourceKind
    snippet: str | None = None  # short preview (<= 240 chars) for the hover card
    # Moodle-only fields (kind == "moodle"):
    course: str | None = None
    due_at: str | None = None  # ISO 8601 with timezone; present => deadline card
    activity_url: str | None = None
    demo: bool = False  # True when this came from fixture data, not live Moodle


class TokenEvent(BaseModel):
    text: str


class FollowUp(BaseModel):
    """A clarifying question with 0-4 quick-reply options."""

    question: str
    options: list[str] = Field(default_factory=list, max_length=4)


class OfficeLink(BaseModel):
    title: str
    url: str
    issuer: str | None = None


class DoneEvent(BaseModel):
    citations: list[str] = Field(default_factory=list)  # validated ids only
    follow_up: FollowUp | None = None
    freshness: Freshness = "unknown"
    limitations: list[str] = Field(default_factory=list)
    latency_ms: int
    # Additive fields (beyond the master prompt's minimum contract):
    answer_kind: AnswerKind = "answer"
    office_links: list[OfficeLink] = Field(default_factory=list)


class ErrorEvent(BaseModel):
    code: ErrorCode
    message: str  # human-friendly; never a stack trace or env value
    provider: str | None = None  # hosted: "groq" etc., so the UI can say "Change key"
    retry_after_s: int | None = None  # PROVIDER_RATE_LIMITED / RATE_LIMITED, when known


# ---------- non-chat endpoints ----------


class ProviderInfo(BaseModel):
    """Public facts about one allowed provider (no key data, ever)."""

    id: str
    label: str
    router_model: str
    answer_model: str
    key_url: str
    recommended: bool = False
    free_tier: bool = False
    note: str = ""
    tested: bool = False


class StatusResponse(BaseModel):
    # Hosted mode: model_online/model_loaded are true when the API is up (the model depends on
    # each student's key, checked per request) and model is "byok".
    model_online: bool
    model_loaded: bool
    model: str
    moodle: Literal["connected", "not_configured", "error"]
    moodle_mode: Literal["rest", "ical", "demo", "none"] = "none"
    sources_indexed: int
    mode: Mode
    deploy_mode: DeployMode = "local"
    # release = downloaded GitHub Release, local = data/campuspilot.db,
    # fallback = fixture demo index (download failed), missing = no index at all
    index: Literal["release", "local", "fallback", "missing"] = "local"
    index_version: str | None = None  # e.g. "index-2026-11-30", or "fixtures"
    providers: list[ProviderInfo] = Field(default_factory=list)  # hosted only
    # v2: connectors turned on in .env (local only; always empty in hosted mode). Their live
    # state comes from GET /v1/connectors.
    connectors: list[Literal["webmail", "asc", "gcal"]] = Field(default_factory=list)


class LLMCheckResponse(BaseModel):
    """POST /v1/llm/check: one minimal model call with the student's key."""

    ok: bool
    provider: str
    model: str
    code: ErrorCode | None = None
    message: str | None = None


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=50)
    audience: str | None = Field(default=None, max_length=50)
    k: int = Field(default=6, ge=1, le=8)


class MoodleTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly one of these. The value is stored in the Keychain and never echoed.
    token: str | None = Field(default=None, min_length=8, max_length=128)
    ical_url: str | None = Field(default=None, min_length=10, max_length=1000)


class MoodleTokenResponse(BaseModel):
    ok: bool
    mode: Literal["rest", "ical", "none"]
    site_name: str | None = None
    user_fullname: str | None = None  # shown once in Settings so the student knows it worked
    message: str


class SourcePublic(BaseModel):
    id: str
    title: str
    issuer: str
    category: str
    url: str
    authority_tier: int
    audience: str | None = None
    handling: Literal["ingest", "link_only", "blocked", "needs_review"]
    status: str  # e.g. "indexed", "failed", "not_fetched", "link_only"
    last_checked_at: str | None = None
    documents: int = 0
    chunks: int = 0
