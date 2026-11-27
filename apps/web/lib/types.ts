// Mirrors apps/api/campuspilot/schemas/chat.py (the source of truth).
// If the Python schemas change, change this file too.

export type Mode = "live" | "mock" | "fallback" | "byok";
export type DeployMode = "local" | "hosted";
export type ToolState = "start" | "done" | "error";
export type SourceKind = "doc" | "moodle";
export type Freshness = "current" | "needs_review" | "unknown";
// moodle = a template sentence written by the server over Moodle results (no model wording).
// personal = the same for v2 connectors (Webmail, ASC), possibly with Moodle: our sentence plus cards.
export type AnswerKind = "answer" | "clarify" | "abstain" | "moodle" | "personal";
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
  | "NOT_AVAILABLE"
  // v2 connectors (local only), docs/CONTRACT.md section 11.6:
  | "NOT_CONNECTED"
  | "AUTH_FAILED"
  | "OTP_REQUIRED"
  | "UNREACHABLE"
  | "SESSION_EXPIRED"
  | "CALENDAR_ERROR";
// "NETWORK" is added by the browser when the API cannot be reached at all.
export type UiErrorCode = ErrorCode | "NETWORK";

// ---------- request ----------

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  // The answer_kind of an assistant turn. The server hides the content of "moodle" and "personal" turns from the model.
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

/** A short label that says where a card's data came from (schemas/connectors.py SourceLabel). */
export type SourceLabel = "Webmail" | "ASC" | "Moodle" | "Official page";

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
  | { event: "cards"; data: Card[] } // v2, local only: after sources, before the first token
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
  connectors?: ConnectorName[]; // v2: connectors turned on in .env (always empty in hosted mode)
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
  cards?: Card[]; // v2 connector cards (Webmail / ASC); kept in memory only, never saved to localStorage
  cardsOmitted?: boolean; // the cards were dropped when the chat was saved (after a reload)
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

// ---------- v2 connectors (mirrors apps/api/campuspilot/schemas/connectors.py) ----------

export type ConnectorName = "webmail" | "asc" | "gcal";
export type ConnectorState = "disabled" | "not_connected" | "needs_otp" | "connected" | "error";

export interface ConnectorStatus {
  name: ConnectorName;
  enabled: boolean;
  state: ConnectorState;
  account?: string | null; // the linked LDAP id or Google email; never a secret
  message?: string | null; // friendly text for "error" / "needs_otp"
  challenge_id?: string | null; // set with state "needs_otp"
  demo?: boolean; // CONNECTORS_DEMO=true: fixture data
  refreshed_at?: string | null; // ASC: when the personal snapshot was last read (ISO)
}

/** GET /v1/connectors */
export interface ConnectorsResponse {
  webmail: ConnectorStatus;
  asc: ConnectorStatus;
  gcal: ConnectorStatus;
}

/** POST /v1/connectors/{webmail|asc}/login. Sent once; never stored in the browser. */
export interface ConnectorLoginRequest {
  username: string;
  password: string;
}

/** POST /v1/connectors/asc/otp */
export interface ConnectorOtpRequest {
  challenge_id: string;
  code: string;
}

/** POST /v1/connectors/gcal/connect */
export interface GcalConnectStart {
  auth_url: string;
}

export interface MailMessage {
  uid: string;
  folder: string;
  message_id: string;
  sender_name: string;
  sender_email: string;
  subject: string;
  date: string; // ISO, timezone-aware
  snippet: string; // at most 300 characters, never the full body
  has_attachments: boolean;
  open_url?: string | null;
}

export type EventCategory = "talk" | "workshop" | "fest" | "deadline" | "exam" | "other";

/** A suggestion found in a mail. The date is never invented: `start` is null when unclear. */
export interface DetectedEvent {
  id: string;
  message_id: string;
  title: string;
  category: EventCategory;
  start?: string | null;
  end?: string | null;
  all_day: boolean;
  date_uncertain: boolean;
  date_text: string; // the phrase the date came from
  venue?: string | null;
  organizer?: string | null;
  confidence: number; // 0..1
  detected_by: "rules" | "rules+llm";
  mail_subject: string;
  mail_sender: string;
  mail_date?: string | null;
  open_url?: string | null;
}

export type AscWeekday = "Mon" | "Tue" | "Wed" | "Thu" | "Fri" | "Sat" | "Sun";

export interface AscCourse {
  code: string; // normalised, e.g. "IE 624"
  title: string;
  credits?: number | null;
  slot?: string | null;
  instructor?: string | null;
  venue?: string | null;
  tag?: string | null; // academic record "Tag"
  credit_audit?: string | null; // "Credit" / "Audit"
  course_type?: string | null; // running courses "Course Type"
  division?: string | null;
  status: "registered" | "approved" | "pending" | "dropped" | "audit" | "other";
  semester: string; // e.g. "2026-27 Autumn"
}

export interface AscTimetableSlot {
  course_code: string;
  course_title: string;
  day: AscWeekday;
  start: string; // "HH:MM", Asia/Kolkata
  end: string;
  venue?: string | null;
  instructor?: string | null;
  slot?: string | null;
  kind: "lecture" | "tutorial" | "lab" | "other";
}

/** AcademicRecord table 1, minus roll number and name. */
export interface AscProfile {
  department: string;
  program: string;
  status: string;
  validity: string; // "Program/Semester validity"
  academic_standing: string;
  advisors: string[];
}

/** One row of the fee status table. Amounts are shown as ASC writes them. */
export interface AscFeeItem {
  label: string;
  amount?: string | null;
  due_date?: string | null;
  status?: string | null; // e.g. "Paid", "Due"
}

export interface AscCourseDetail {
  code: string;
  title: string;
  credits?: number | null;
  department: string;
  prerequisites: string[];
  syllabus: string; // trimmed text, at most 3000 characters
  extra: Record<string, string>; // other label: value pairs shown on ASC
}

export type AscSemesterName = "autumn" | "spring" | "summer" | "winter";

export interface AscOffering {
  year: number; // start year of the academic year: 2026 = 2026-27
  semester: AscSemesterName;
  offered: boolean;
}

// The `cards` SSE event: a list of these, discriminated by `type`. Every card has an id (for keys only)
// and a source label; ids are never cited.
interface CardBase {
  id: string;
  demo?: boolean;
}
export interface MailCard extends CardBase {
  type: "mail";
  source_label: "Webmail";
  mail: MailMessage;
}
export interface EventCard extends CardBase {
  type: "event";
  source_label: "Webmail";
  event: DetectedEvent;
  can_add_to_calendar: boolean;
}
export interface AscSlotCard extends CardBase {
  type: "asc_slot";
  source_label: "ASC";
  slot: AscTimetableSlot;
  on_date?: string | null; // "YYYY-MM-DD" when the answer is for one day
}
export interface AscCourseCard extends CardBase {
  type: "asc_course";
  source_label: "ASC";
  course: AscCourse;
}
export interface AscProfileCard extends CardBase {
  type: "asc_profile";
  source_label: "ASC";
  profile: AscProfile;
}
export interface AscFeeCard extends CardBase {
  type: "asc_fee";
  source_label: "ASC";
  fee: AscFeeItem;
}
export interface AscHistoryCard extends CardBase {
  type: "asc_history";
  source_label: "ASC";
  course_code: string;
  title: string;
  offerings: AscOffering[];
}
export interface AscDetailCard extends CardBase {
  type: "asc_detail";
  source_label: "ASC";
  detail: AscCourseDetail;
}
export type Card = MailCard | EventCard | AscSlotCard | AscCourseCard | AscProfileCard | AscFeeCard | AscHistoryCard | AscDetailCard;

/** POST /v1/calendar/events: sent when the student clicks "Add to Google Calendar". */
export interface CalendarEventRequest {
  event_id: string;
  message_id: string;
  title: string;
  start: string; // ISO with a time zone
  end?: string | null;
  all_day: boolean;
  venue?: string | null;
  mail_subject: string;
}

export interface CalendarEventResult {
  ok: boolean;
  status: "created" | "already_exists" | "error";
  google_event_id?: string | null;
  html_link?: string | null;
  message: string;
}
