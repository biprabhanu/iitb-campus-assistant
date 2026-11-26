// The student's own AI key and Moodle credentials, kept in THIS browser only (hosted mode).
//
// "Remember on this device" off  -> sessionStorage (gone when the tab closes)
// "Remember on this device" on   -> localStorage
// Every storage call is wrapped in try/catch: storage can be blocked, full or missing.
// Nothing here is ever logged, and the values are sent only as request headers (docs/CONTRACT.md §10.2).

export const KEY_RE = /^[A-Za-z0-9_\-.]{20,300}$/;
export const MOODLE_TOKEN_RE = /^[A-Za-z0-9_\-.]{8,128}$/;
export const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$/;
export const MOODLE_ICAL_PREFIX = "https://moodle.iitb.ac.in/";
const ICAL_RE = /^https:\/\/moodle\.iitb\.ac\.in\/[\x21-\x7e]*$/;

export interface LlmCreds {
  provider: string;
  key: string;
  model?: string;
}

export interface MoodleCreds {
  token?: string;
  icalUrl?: string;
}

export type Section = "llm" | "moodle";

const STORE_KEY: Record<Section, string> = {
  llm: "campuspilot.llm.v1",
  moodle: "campuspilot.moodle.v1",
};
const MODE_KEY = "campuspilot.deploy_mode"; // not secret: which kind of server this origin talks to

type Kind = "local" | "session";

function area(kind: Kind): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function read(kind: Kind, key: string): string | null {
  try {
    return area(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(kind: Kind, key: string, value: string): boolean {
  try {
    area(kind)?.setItem(key, value);
    return area(kind) !== null;
  } catch {
    return false;
  }
}

function remove(kind: Kind, key: string) {
  try {
    area(kind)?.removeItem(key);
  } catch {
    /* ignore */
  }
}

// ---------- validation (the same rules the server applies) ----------

export function validateKey(key: string): string | null {
  const k = key.trim();
  if (!k) return "Paste your key first.";
  if (!KEY_RE.test(k)) return "That doesn't look like an API key. Copy the whole key, with no spaces.";
  return null;
}

export function validateModel(model: string): string | null {
  const m = model.trim();
  if (!m) return null; // optional
  if (!MODEL_RE.test(m)) return "Model names use letters, digits and . _ : / - only (up to 100 characters).";
  return null;
}

/** One box accepts a token or an iCal link. A link starts with https://. */
export function parseMoodleInput(raw: string): { creds: MoodleCreds | null; error: string | null } {
  const v = raw.trim();
  if (!v) return { creds: null, error: "Paste your Moodle token or calendar link first." };
  if (/^https?:\/\//i.test(v)) {
    if (!ICAL_RE.test(v)) return { creds: null, error: `A calendar link must start with ${MOODLE_ICAL_PREFIX}` };
    return { creds: { icalUrl: v }, error: null };
  }
  if (!MOODLE_TOKEN_RE.test(v)) return { creds: null, error: "That doesn't look like a Moodle token (8 to 128 letters and digits)." };
  return { creds: { token: v }, error: null };
}

// ---------- load / save / forget ----------

function parse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" ? (v as T) : null;
  } catch {
    return null;
  }
}

function cleanLlm(v: Partial<LlmCreds> | null): LlmCreds | null {
  if (!v || typeof v.provider !== "string" || typeof v.key !== "string" || !KEY_RE.test(v.key)) return null;
  const model = typeof v.model === "string" && MODEL_RE.test(v.model) ? v.model : undefined;
  return { provider: v.provider, key: v.key, ...(model ? { model } : {}) };
}

function cleanMoodle(v: Partial<MoodleCreds> | null): MoodleCreds | null {
  if (!v) return null;
  const token = typeof v.token === "string" && MOODLE_TOKEN_RE.test(v.token) ? v.token : undefined;
  const icalUrl = typeof v.icalUrl === "string" && ICAL_RE.test(v.icalUrl) ? v.icalUrl : undefined;
  return token || icalUrl ? { ...(token ? { token } : {}), ...(icalUrl ? { icalUrl } : {}) } : null;
}

export interface Stored {
  llm: LlmCreds | null;
  moodle: MoodleCreds | null;
  remember: Record<Section, boolean>;
}

/** Read both sections. A value found in localStorage means "remembered". */
export function loadStored(): Stored {
  const out: Stored = { llm: null, moodle: null, remember: { llm: false, moodle: false } };
  for (const s of ["llm", "moodle"] as Section[]) {
    for (const kind of ["local", "session"] as Kind[]) {
      const parsed = parse<object>(read(kind, STORE_KEY[s]));
      const value = s === "llm" ? cleanLlm(parsed) : cleanMoodle(parsed);
      if (value) {
        (out as unknown as Record<string, unknown>)[s] = value;
        out.remember[s] = kind === "local";
        break;
      }
    }
  }
  return out;
}

/** Save one section where the switch says. Returns false if the browser refused. */
export function saveSection(section: Section, value: LlmCreds | MoodleCreds, remember: boolean): boolean {
  forgetSection(section);
  return write(remember ? "local" : "session", STORE_KEY[section], JSON.stringify(value));
}

export function forgetSection(section: Section) {
  remove("local", STORE_KEY[section]);
  remove("session", STORE_KEY[section]);
}

/** Move a saved value from one storage to the other (the switch was toggled). */
export function moveSection(section: Section, value: LlmCreds | MoodleCreds | null, remember: boolean): boolean {
  if (!value) return true;
  return saveSection(section, value, remember);
}

// ---------- what kind of server is this? (cached so the first paint is right) ----------

export function cachedDeployMode(): "local" | "hosted" | null {
  const v = read("local", MODE_KEY);
  return v === "local" || v === "hosted" ? v : null;
}

export function cacheDeployMode(mode: "local" | "hosted") {
  write("local", MODE_KEY, mode);
}

// ---------- request headers (docs/CONTRACT.md §10.2) ----------

export function authHeaders(llm: LlmCreds | null, moodle: MoodleCreds | null): Record<string, string> {
  const h: Record<string, string> = {};
  if (llm) {
    h["X-LLM-Provider"] = llm.provider;
    h["X-LLM-Key"] = llm.key;
    if (llm.model) h["X-LLM-Model"] = llm.model;
  }
  if (moodle?.token) h["X-Moodle-Token"] = moodle.token;
  if (moodle?.icalUrl) h["X-Moodle-Ical-Url"] = moodle.icalUrl;
  return h;
}

/** Show the end of a secret only, e.g. "••••••••a1b2". */
export function maskTail(secret: string): string {
  return `${"•".repeat(8)}${secret.slice(-4)}`;
}
