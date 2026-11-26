// Built-in fake backend, used when NEXT_PUBLIC_MOCK=true. It replays realistic
// docs/CONTRACT.md §3 event sequences (status, tool, sources, token, done) with
// small delays so the UI can be built and tested without the API or the model.
//
// Special switches (URL params or NEXT_PUBLIC_* env, see lib/config.ts):
//   ?mockOffline=1  every request fails with MODEL_OFFLINE and /v1/status says offline
//   ?mockWake=1     the first token takes ~5 s (shows "Waking up the model")
//   ?mockHosted=1   pretend the API is in hosted (bring-your-own-key) mode: key card, Settings, provider pill
//   ?mockError=CODE every chat request fails with that code, e.g. PROVIDER_RATE_LIMITED (hosted codes carry a provider)
//   ?mockCold=1     the server is "asleep" for about a minute (?mockCold=fail: it never wakes)
//   ?mockHold=tool  freezes on the first step; ?mockHold=text freezes after a few words (screenshots)
//
// The answer text here is sample content only. It never states real policy facts, dates or rules;
// the source cards use real registry URLs but generic snippets.
import { mockCold, mockError, mockHold, mockHosted, mockOffline, mockWake } from "./config";
import type { LlmCreds, MoodleCreds } from "./credentials";
import { httpError } from "./errors";
import { FALLBACK_PROVIDERS } from "./providers";
import { relativeDue } from "./utils";
import type {
  ChatRequest,
  LLMCheckResponse,
  DoneEvent,
  MoodleTokenRequest,
  MoodleTokenResponse,
  SSEEvent,
  SourceItem,
  StatusResponse,
} from "./types";

const MODEL = "gemma4:26b-a4b-it-q4_K_M";

// Tool labels are fixed by the contract.
const LABELS = {
  search_campus_docs: "Searching campus documents",
  get_official_link: "Finding the official page",
  get_my_deadlines: "Checking your Moodle deadlines",
  ask_clarification: "Asking a clarifying question",
} as const;

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(t), resolve()), { once: true });
  });

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();
/** A time `hours` from now, so deadlines are always in the coming days. */
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

/** An evening 'days' ahead at the given IST hour (so cards group nicely by day). */
function istEvening(days: number, hour = 23, minute = 59): string {
  const base = new Date(Date.now() + days * 86_400_000);
  const ymd = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(base);
  return new Date(`${ymd}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+05:30`).toISOString();
}

interface Script {
  tools: (keyof typeof LABELS)[];
  sources: SourceItem[];
  text: string;
  done: Partial<DoneEvent>;
}

const doc = (id: string, title: string, issuer: string, url: string, snippet: string, days: number, locator?: string): SourceItem => ({
  id,
  title,
  issuer,
  url,
  locator: locator ?? null,
  checked_at: daysAgo(days),
  kind: "doc",
  snippet,
});

function scriptFor(message: string): Script {
  const m = message.toLowerCase();

  if (/academic calendar|calendar/.test(m)) {
    return {
      tools: ["search_campus_docs"],
      sources: [
        doc("S1", "Academic calendar and timetable", "Academic Office", "https://acad.iitb.ac.in/academics/calendar-and-timetable", "The official page for the academic calendar and timetable, with links to the calendar and timetable PDFs.", 3),
        doc("S2", "Academic calendar (PDF)", "Academic Office", "https://acad.iitb.ac.in/academics/calendar-and-timetable", "The calendar PDF linked from the Academic Office page.", 3, "PDF"),
      ],
      text:
        "This is sample content from the built-in demo. In the live app I would read the **official academic calendar** [S1] and quote the dates for you.\n\n" +
        "For now, here is where each kind of date lives:\n\n" +
        "| Topic | Autumn | Spring |\n|---|---|---|\n" +
        "| Semester dates | See the official calendar PDF | See the official calendar PDF |\n" +
        "| Exam schedule | See the official calendar PDF | See the official calendar PDF |\n" +
        "| Holidays | See the official calendar PDF | See the official calendar PDF |\n\n" +
        "The calendar and timetable PDFs are linked from the Academic Office page [S2]. Always confirm dates there before planning around them.",
      done: { citations: ["S1", "S2"], freshness: "current" },
    };
  }

  if (/due|deadline|assignment/.test(m)) {
    // Course codes and titles follow the demo fixtures in data/fixtures/moodle/.
    const mk = (n: number, course: string, title: string, due: string, kind: "assign" | "quiz" = "assign"): SourceItem => ({
      id: `M${n}`,
      title,
      issuer: "Moodle",
      url: "https://moodle.iitb.ac.in/",
      kind: "moodle",
      course,
      due_at: due,
      activity_url: `https://moodle.iitb.ac.in/mod/${kind}/view.php?id=${5100 + n}`,
      demo: true,
      checked_at: new Date().toISOString(),
    });
    // "Tonight 11:59 PM", or one hour from now if that has already passed.
    const tonight = istEvening(0);
    const first = Date.parse(tonight) > Date.now() + 30 * 60_000 ? tonight : inHours(1);
    return {
      tools: ["get_my_deadlines"],
      sources: [
        mk(1, "IE624", "Assignment 3: Prototype report", first),
        mk(2, "IE611", "Problem Set 4", istEvening(2, 17, 0)),
        mk(3, "HS101", "Quiz 2 closes", istEvening(3, 11, 59), "quiz"),
        mk(4, "MA205", "Homework 6", istEvening(4, 23, 59)),
        mk(5, "IE624", "Project proposal revision", istEvening(5, 18, 0)),
        mk(6, "IE611", "Midsem feedback form closes", istEvening(6, 23, 59), "quiz"),
      ],
      // answer_kind "moodle": a template sentence written by the server, no citations (CONTRACT §10.4).
      text: `You have 6 deadlines in the next 7 days. The nearest is IE624 Assignment 3: Prototype report, due ${relativeDue(first).text}.`,
      done: { citations: [], freshness: "unknown", answer_kind: "moodle" },
    };
  }

  if (/hostel|maintenance|plumb|repair|complaint/.test(m)) {
    return {
      tools: ["search_campus_docs", "get_official_link"],
      sources: [
        doc("S1", "IIT Bombay support portal", "IIT Bombay services", "https://support.iitb.ac.in/", "The institute's support portal, where hostel maintenance requests are raised.", 6),
        doc("S2", "Hostel rules and regulations", "DoSA / Hostel authority", "https://dosa.iitb.ac.in/sites/default/files/hostelrulesregulations.pdf", "The hostel rules document, a good place to check who to contact for hostel matters.", 6, "PDF"),
      ],
      text:
        "This is sample content from the built-in demo. Maintenance requests are raised on the institute's support portal [S1], and the hostel rules explain who to contact for hostel matters [S2].\n\n" +
        "1. **Open the support portal** from the link in the sources above.\n" +
        "2. **Describe the problem** clearly: where it is and what is wrong.\n" +
        "3. **Check the hostel rules** if you are not sure who handles it.\n\n" +
        "CampusPilot can point you to the portal, but it cannot submit a request for you.",
      done: { citations: ["S1", "S2"], freshness: "current" },
    };
  }

  if (/code of conduct|conduct|discipline|ragging/.test(m)) {
    return {
      tools: ["search_campus_docs"],
      sources: [doc("S1", "Code of conduct", "Dean of Student Affairs", "https://dosa.iitb.ac.in/code-of-conduct", "The Dean of Student Affairs page for the student code of conduct.", 12)],
      text:
        "This is sample content from the built-in demo. The official **code of conduct** [S1] is published by the Dean of Student Affairs.\n\n" +
        "In the live app I would summarise the sections you ask about and cite them. For now, open the source above to read the rules in full, and treat any summary as a starting point only.",
      done: { citations: ["S1"], freshness: "current" },
    };
  }

  if (/change my room|room change|change room/.test(m)) {
    return {
      tools: ["ask_clarification"],
      sources: [],
      text: "Room change rules depend on your programme. Which one are you in?",
      done: {
        answer_kind: "clarify",
        follow_up: { question: "Which programme are you in?", options: ["UG (B.Tech / Dual Degree)", "PG (M.Tech / M.Sc)", "PhD"] },
      },
    };
  }

  if (/^(ug|pg|phd)\b/.test(m)) {
    return {
      tools: ["search_campus_docs"],
      sources: [doc("S1", "Hostel rules and regulations", "DoSA / Hostel authority", "https://dosa.iitb.ac.in/sites/default/files/hostelrulesregulations.pdf", "The hostel rules document.", 8, "PDF")],
      text: "This is sample content from the built-in demo. In the live app I would find the room-change rule for your programme and cite it [S1]. For now, check the hostel rules and your hostel office.",
      done: { citations: ["S1"], freshness: "current" },
    };
  }

  if (/mess|menu/.test(m)) {
    return {
      tools: ["search_campus_docs", "get_official_link"],
      sources: [],
      text:
        "I couldn't find a verified source for the 2031 mess menu, so I won't guess. The hostel office is the best place to ask.",
      done: {
        answer_kind: "abstain",
        office_links: [
          { title: "Student Affairs Office", url: "https://www.iitb.ac.in/students/students-affair-office", issuer: "IIT Bombay" },
          { title: "Contact IIT Bombay", url: "https://www.iitb.ac.in/contact-us", issuer: "IIT Bombay" },
        ],
      },
    };
  }

  return {
    tools: ["search_campus_docs"],
    sources: [doc("S1", "Student Affairs Office", "Student Affairs Office", "https://www.iitb.ac.in/students/students-affair-office", "The Student Affairs Office page.", 20)],
    text:
      "You're using CampusPilot's **built-in demo**, so I can only answer a few sample questions here: the academic calendar, deadlines, hostel maintenance, the code of conduct, room changes and the mess menu.\n\nWith the real model connected, I'd search the official IIT Bombay pages for this [S1] and cite what I find.",
    done: { citations: ["S1"], freshness: "current" },
  };
}

/** Split text into small pieces so it streams like a model would. */
function chunkText(text: string): string[] {
  return text.match(/\S+\s*|\s+/g) ?? [text];
}

const ERROR_TEXT: Record<string, string> = {
  MODEL_OFFLINE: "The CampusPilot model is offline right now. Check the tunnel (`ssh -fN passpoli-llm`) and try again.",
  TIMEOUT: "The model took too long to answer. Please try again.",
  BAD_REQUEST: "That request wasn't valid. Please try again.",
  RATE_LIMITED: "You're sending requests too fast. Please wait a moment.",
  INTERNAL: "Something went wrong on the server. Please try again.",
  MODEL_KEY_REQUIRED: "Add your AI key in Settings to start chatting.",
  PROVIDER_KEY_REJECTED: "Your {p} key was rejected. Check it in Settings.",
  PROVIDER_RATE_LIMITED: "{p} says you've hit your free limit; try again in a minute.",
  PROVIDER_TIMEOUT: "{p} took too long to answer. Please try again.",
  PROVIDER_ERROR: "{p} returned an error. Please try again.",
  NOT_AVAILABLE: "That isn't available in the hosted version.",
};

export async function* mockChatStream(req: ChatRequest, signal: AbortSignal, auth?: { llm: LlmCreds | null; moodle: MoodleCreds | null }): AsyncGenerator<SSEEvent> {
  const started = Date.now();
  const requestId = Math.random().toString(16).slice(2, 8);
  const hosted = mockHosted();
  const providerId = auth?.llm?.provider ?? "groq";
  const providerName = FALLBACK_PROVIDERS.find((p) => p.id === providerId)?.label ?? providerId;

  // Hosted without a key: the server answers HTTP 401 before any stream starts.
  if (hosted && !auth?.llm && !mockError()) {
    await sleep(150, signal);
    yield { event: "error", data: httpError(401, { code: "MODEL_KEY_REQUIRED", message: ERROR_TEXT.MODEL_KEY_REQUIRED }) };
    return;
  }

  // ?mockError=CODE. Three codes go through the HTTP mapping on purpose (the real 401/429 path).
  const forced = mockError();
  if (forced) {
    await sleep(250, signal);
    if (signal.aborted) return;
    const message = (ERROR_TEXT[forced] ?? ERROR_TEXT.INTERNAL).replace("{p}", providerName);
    const wait = forced === "PROVIDER_RATE_LIMITED" || forced === "RATE_LIMITED" ? 42 : undefined;
    if (forced === "MODEL_KEY_REQUIRED") yield { event: "error", data: httpError(401, { code: forced, message }) };
    else if (forced === "RATE_LIMITED") yield { event: "error", data: httpError(429, { code: forced, message, retry_after_s: wait }) };
    else {
      const providerError = forced.startsWith("PROVIDER_");
      yield {
        event: "error",
        data: {
          code: forced as never,
          message,
          provider: providerError ? providerId : null,
          retry_after_s: wait ?? null,
          at: Date.now(),
        },
      };
    }
    return;
  }

  yield { event: "status", data: { request_id: requestId, model: hosted ? "byok" : MODEL, mode: hosted ? "byok" : "mock" } };
  await sleep(350, signal);
  if (signal.aborted) return;

  if (mockOffline()) {
    yield {
      event: "error",
      data: {
        code: "MODEL_OFFLINE",
        message: "The CampusPilot model is offline right now. Check the tunnel (`ssh -fN passpoli-llm`) and try again.",
      },
    };
    return;
  }

  const script = scriptFor(req.message);
  const hold = mockHold();

  for (const name of script.tools) {
    const label = LABELS[name];
    yield { event: "tool", data: { name, label, state: "start" } };
    if (hold === "tool") await sleep(600_000, signal); // screenshots: stay on this step
    await sleep(650, signal);
    if (signal.aborted) return;
    yield { event: "tool", data: { name, label, state: "done" } };
  }

  if (script.sources.length > 0) yield { event: "sources", data: script.sources };

  if (mockWake()) await sleep(5000, signal);

  let sent = 0;
  for (const piece of chunkText(script.text)) {
    if (signal.aborted) return;
    yield { event: "token", data: { text: piece } };
    await sleep(22, signal);
    if (hold === "text" && ++sent === 14) await sleep(600_000, signal); // screenshots: stop mid-sentence
  }
  if (signal.aborted) return;

  yield {
    event: "done",
    data: {
      citations: [],
      follow_up: null,
      freshness: "unknown",
      limitations: [],
      latency_ms: Date.now() - started,
      answer_kind: "answer",
      office_links: [],
      ...script.done,
    },
  };
}

// ---------- mock for the other endpoints ----------

let mockMoodle: MoodleTokenResponse["mode"] = "none";

let coldStart = 0;

/** GET /v1/ping in mock mode. With ?mockCold the "server" stays asleep (about a minute, or forever for =fail). */
export async function mockPing(signal?: AbortSignal): Promise<boolean> {
  const cold = mockCold();
  if (!cold) return true;
  if (!coldStart) coldStart = Date.now();
  await new Promise<void>((resolve) => {
    const t = setTimeout(resolve, 700);
    signal?.addEventListener("abort", () => (clearTimeout(t), resolve()), { once: true });
  });
  return cold === "wake" && Date.now() - coldStart > 60_000;
}

/** Mock of POST /v1/llm/check. A key containing "bad" is rejected, one containing "slow" hits the rate limit. */
export async function mockCheckLlm(creds: LlmCreds): Promise<LLMCheckResponse> {
  await new Promise((r) => setTimeout(r, 700));
  const name = FALLBACK_PROVIDERS.find((p) => p.id === creds.provider)?.label ?? creds.provider;
  const model = creds.model ?? FALLBACK_PROVIDERS.find((p) => p.id === creds.provider)?.router_model ?? "";
  if (/bad/i.test(creds.key)) return { ok: false, provider: creds.provider, model, code: "PROVIDER_KEY_REJECTED", message: `Your ${name} key was rejected. Check it in Settings.` };
  if (/slow/i.test(creds.key)) return { ok: false, provider: creds.provider, model, code: "PROVIDER_RATE_LIMITED", message: `${name} says you've hit your free limit; try again in a minute.`, retry_after_s: 42 };
  return { ok: true, provider: creds.provider, model };
}

/** Mock of POST /v1/moodle/check. A value containing "bad" is rejected. */
export async function mockCheckMoodle(creds: MoodleCreds): Promise<MoodleTokenResponse> {
  await new Promise((r) => setTimeout(r, 700));
  if (/bad/i.test(creds.token ?? "") || /bad/i.test(creds.icalUrl ?? "")) {
    return { ok: false, mode: "none", message: "Moodle didn't accept that token. Check it and try again." };
  }
  const mode = creds.icalUrl ? "ical" : "rest";
  return { ok: true, mode, site_name: "IITB Moodle (mock)", user_fullname: mode === "rest" ? "Demo Student" : null, message: "Moodle accepted it (mock mode: nothing was saved)." };
}

export async function mockStatus(): Promise<StatusResponse> {
  await new Promise((r) => setTimeout(r, 150));
  const offline = mockOffline();
  if (mockHosted()) {
    return {
      model_online: true,
      model_loaded: true,
      model: "byok",
      moodle: "not_configured",
      moodle_mode: "demo",
      sources_indexed: 24,
      mode: "byok",
      deploy_mode: "hosted",
      index: "fallback",
      index_version: "fixtures",
      providers: FALLBACK_PROVIDERS.map((p) => ({ ...p, tested: false })),
    };
  }
  return {
    model_online: !offline,
    model_loaded: !offline,
    model: MODEL,
    moodle: "connected", // unconfigured Moodle falls back to demo data
    moodle_mode: mockMoodle === "none" ? "demo" : mockMoodle,
    sources_indexed: 24,
    mode: "mock",
    deploy_mode: "local",
  };
}

export async function mockSendMoodle(body: MoodleTokenRequest): Promise<MoodleTokenResponse> {
  await new Promise((r) => setTimeout(r, 600));
  mockMoodle = body.ical_url ? "ical" : "rest";
  return {
    ok: true,
    mode: mockMoodle,
    site_name: "IITB Moodle (mock)",
    user_fullname: mockMoodle === "rest" ? "Demo Student" : null,
    message: "Connected (mock mode: nothing was saved).",
  };
}

export async function mockDeleteMoodle(): Promise<MoodleTokenResponse> {
  await new Promise((r) => setTimeout(r, 300));
  mockMoodle = "none";
  return { ok: true, mode: "none", message: "Moodle disconnected." };
}
