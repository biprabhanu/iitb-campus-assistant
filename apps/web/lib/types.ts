// Mirrors apps/api/campuspilot/schemas/chat.py (the source of truth).
// If the Python schemas change, change this file too.

export type Mode = "live" | "mock" | "fallback" | "byok";
export type DeployMode = "local" | "hosted";
export type ToolState = "start" | "done" | "error";
export type SourceKind = "doc" | "moodle";
export type Freshness = "current" | "needs_review" | "unknown";
// moodle = a template sentence written by the server over Moodle results (no model wording).
export type AnswerKind = "answer" | "clarify" | "abstain" | "moodle";
export type ErrorCode =
  | "MODEL_OFFLINE"
  | "TIMEOUT"
  | "BAD_REQUEST"
  | "RATE_LIMITED"
  | "INTERNAL"
  // hosted (bring-your-own-key) mode, docs/CONTRACT.md §10:
  | "MODEL_KEY_REQUIRED"
  | "PROVIDER_KEY_REJECTED"
  | "PROVIDER_RATE_LIMITED"
  | "PROVIDER_TIMEOUT"
  | "PROVIDER_ERROR"
  | "NOT_AVAILABLE";
// "NETWORK" is added by the browser when the API cannot be reached at all.
export type UiErrorCode = ErrorCode | "NETWORK";

// ---------- request ----------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  // The answer_kind of an assistant turn. The server hides the content of "moodle" turns from the model.
  kind?: AnswerKind;
}

export interface ChatRequest {
  message: string;
  history: ChatTurn[];
}

// ---------- SSE event payloads ----------

export interface StatusEvent {
  request_id: string;
  model: string;
  mode: Mode;
}

export interface ToolEvent {
  name: string;
  label: string;
  state: ToolState;
}

export interface SourceItem {
  id: string; // S1.. for docs, M1.. for Moodle
  title: string;
  issuer: string;
  url: string;
  locator?: string | null;
  checked_at?: string | null;
  kind: SourceKind;
  snippet?: string | null;
  course?: string | null;
  due_at?: string | null; // present => deadline card
  activity_url?: string | null;
  demo?: boolean; // true => fixture data, label "Demo data"
}

export interface TokenEvent {
  text: string;
}

export interface FollowUp {
  question: string;
  options: string[];
}

export interface OfficeLink {
  title: string;
  url: string;
  issuer?: string | null;
}

export interface DoneEvent {
  citations: string[];
  follow_up: FollowUp | null;
  freshness: Freshness;
  limitations: string[];
  latency_ms: number;
  answer_kind: AnswerKind;
  office_links: OfficeLink[];
}

export interface ErrorEvent {
  code: UiErrorCode;
  message: string;
  provider?: string | null; // hosted: "groq" etc.
  retry_after_s?: number | null; // PROVIDER_RATE_LIMITED / RATE_LIMITED, when known
  at?: number; // browser-only: when we received it (so a countdown survives a reload)
}

/** One parsed Server-Sent Event, tagged by its name. */
export type SSEEvent =
  | { event: "status"; data: StatusEvent }
  | { event: "tool"; data: ToolEvent }
  | { event: "sources"; data: SourceItem[] }
  | { event: "token"; data: TokenEvent }
  | { event: "done"; data: DoneEvent }
  | { event: "error"; data: ErrorEvent };

// ---------- non-chat endpoints ----------

/** Public facts about one allowed provider (no key data, ever). */
export interface ProviderInfo {
  id: string;
  label: string;
  router_model: string;
  answer_model: string;
  key_url: string;
  recommended?: boolean;
  free_tier?: boolean;
  note?: string;
  tested?: boolean;
}

export interface StatusResponse {
  model_online: boolean;
  model_loaded: boolean;
  model: string;
  moodle: "connected" | "not_configured" | "error";
  moodle_mode: "rest" | "ical" | "demo" | "none";
  sources_indexed: number;
  mode: Mode;
  deploy_mode?: DeployMode; // absent on an older local API: treat as "local"
  index?: "release" | "local" | "fallback" | "missing";
  index_version?: string | null;
  providers?: ProviderInfo[]; // hosted only
}

/** POST /v1/llm/check: one minimal model call with the student's key. */
export interface LLMCheckResponse {
  ok: boolean;
  provider: string;
  model: string;
  code?: ErrorCode | null;
  message?: string | null;
  retry_after_s?: number | null;
}

export interface MoodleTokenRequest {
  token?: string;
  ical_url?: string;
}

export interface MoodleTokenResponse {
  ok: boolean;
  mode: "rest" | "ical" | "none";
  site_name?: string | null;
  user_fullname?: string | null;
  message: string;
}

// ---------- what the UI keeps in the browser ----------

export type MessageStatus = "streaming" | "complete" | "error" | "stopped";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  // Assistant-only fields:
  status?: MessageStatus;
  steps?: ToolEvent[];
  sources?: SourceItem[];
  done?: DoneEvent;
  error?: ErrorEvent;
  feedback?: "up" | "down";
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}
