// Mirrors apps/api/campuspilot/schemas/chat.py (the source of truth).
// If the Python schemas change, change this file too.

export type Mode = "live" | "mock" | "fallback";
export type ToolState = "start" | "done" | "error";
export type SourceKind = "doc" | "moodle";
export type Freshness = "current" | "needs_review" | "unknown";
export type AnswerKind = "answer" | "clarify" | "abstain";
export type ErrorCode = "MODEL_OFFLINE" | "TIMEOUT" | "BAD_REQUEST" | "RATE_LIMITED" | "INTERNAL";
// "NETWORK" is added by the browser when the API cannot be reached at all.
export type UiErrorCode = ErrorCode | "NETWORK";

// ---------- request ----------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
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

export interface StatusResponse {
  model_online: boolean;
  model_loaded: boolean;
  model: string;
  moodle: "connected" | "not_configured" | "error";
  moodle_mode: "rest" | "ical" | "demo" | "none";
  sources_indexed: number;
  mode: Mode;
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
