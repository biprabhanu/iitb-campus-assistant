// Built-in fake backend, used when NEXT_PUBLIC_MOCK=true. It replays realistic
// docs/CONTRACT.md §3 event sequences (status, tool, sources, token, done) with
// small delays so the UI can be built and tested without the API or the model.
//
// Special switches (URL params or NEXT_PUBLIC_* env, see lib/config.ts):
//   ?mockOffline=1  every request fails with MODEL_OFFLINE and /v1/status says offline
//   ?mockWake=1     the first token takes ~5 s (shows "Waking up the model")
import { mockOffline, mockWake } from "./config";
import type {
  ChatRequest,
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
        doc("S1", "Academic Calendar 2026-27", "Academic Office", "https://www.iitb.ac.in/acad/academic-calendar", "Autumn semester: registration, classes, mid-semester and end-semester examinations, and the vacation periods.", 3, "p. 1"),
        doc("S2", "Academic Calendar (PDF)", "Academic Office", "https://www.iitb.ac.in/acad/files/calendar.pdf", "Last day for course add/drop and for withdrawing from a course.", 3, "p. 2"),
      ],
      text:
        "Here are the main dates in the **2026-27 academic calendar** [S1]. Treat these as a guide and confirm exact days on the official page.\n\n" +
        "| Event | Autumn semester | Spring semester |\n|---|---|---|\n" +
        "| Registration | Late July | Early January |\n| Classes begin | Early August | Mid January |\n| Mid-semester exams | September | February |\n| End-semester exams | November | April-May |\n\n" +
        "A few things worth knowing:\n\n- **Add/drop** closes in the first two weeks of classes [S2].\n- Holidays and the semester break are listed on the same page.\n- Your department can publish its own exam timetable, so check it too.\n\nWant me to look up a specific date, such as the last day to withdraw from a course?",
      done: { citations: ["S1", "S2"], freshness: "current" },
    };
  }

  if (/due|deadline|assignment/.test(m)) {
    const mk = (n: number, course: string, title: string, due: string): SourceItem => ({
      id: `M${n}`,
      title,
      issuer: "Moodle",
      url: "https://moodle.iitb.ac.in/",
      kind: "moodle",
      course,
      due_at: due,
      activity_url: "https://moodle.iitb.ac.in/mod/assign/view.php?id=1000" + n,
      demo: true,
      checked_at: new Date().toISOString(),
    });
    return {
      tools: ["get_my_deadlines"],
      sources: [
        mk(1, "CS 101", "Programming Assignment 3", inHours(5)),
        mk(2, "MA 105", "Problem Set 6", istEvening(1, 17, 0)),
        mk(3, "PH 107", "Lab Report: Photoelectric Effect", istEvening(1, 23, 59)),
        mk(4, "HS 101", "Reading Response Quiz", istEvening(3, 10, 30)),
        mk(5, "CS 101", "Quiz 2 (online)", istEvening(5, 21, 0)),
      ],
      text:
        "You have **5 deadlines** coming up this week. The most urgent is *Programming Assignment 3* in CS 101 [M1], due in a few hours.\n\nThese are sample deadlines from the demo Moodle, shown so you can see how the cards look.",
      done: { citations: ["M1", "M2", "M3", "M4", "M5"], freshness: "unknown" },
    };
  }

  if (/hostel|maintenance|plumb|repair|complaint/.test(m)) {
    return {
      tools: ["search_campus_docs", "get_official_link"],
      sources: [
        doc("S1", "Hostel Maintenance and Repair Requests", "Hostel Affairs Office", "https://www.iitb.ac.in/hostels/maintenance", "Raise a complaint for electrical, plumbing and carpentry issues through your hostel's maintenance portal or the hostel office.", 6, "Section 2"),
        doc("S2", "Hostel Rules and Regulations", "Hostel Affairs Office", "https://www.iitb.ac.in/hostels/rules", "Residents report faults to the hostel secretary or warden; urgent faults can be reported at the hostel office.", 6, "p. 4"),
      ],
      text:
        "To report a maintenance problem in your hostel:\n\n1. **Log the complaint** on your hostel's maintenance portal, or at the hostel office if the portal is down [S1].\n2. **Describe the issue** clearly: room number, what is broken, and when it started.\n3. **Tell your hostel secretary** so it can be followed up [S2].\n4. For anything unsafe (exposed wiring, gas smell), go to the hostel office straight away.\n\nIf nothing happens in a few days, escalate to the warden.",
      done: { citations: ["S1", "S2"], freshness: "current" },
    };
  }

  if (/code of conduct|conduct|discipline|ragging/.test(m)) {
    return {
      tools: ["search_campus_docs"],
      sources: [doc("S1", "Student Code of Conduct", "Dean of Student Affairs", "https://www.iitb.ac.in/students/code-of-conduct", "Students are expected to maintain academic integrity, respect others and follow institute rules.", 12, "p. 1-3")],
      text:
        "The **student code of conduct** [S1] covers a few basics:\n\n- **Academic integrity:** no plagiarism, copying or unauthorised help in assessments.\n- **Respect:** harassment and ragging are prohibited and can lead to serious action.\n- **Campus rules:** follow hostel, library and lab regulations.\n- **Process:** violations go to a disciplinary committee, and you have a chance to respond.\n\nThis is a summary only. Read the full document before relying on any detail.",
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
      sources: [doc("S1", "Hostel Room Allotment and Change Policy", "Hostel Affairs Office", "https://www.iitb.ac.in/hostels/room-allotment", "Room changes are considered at set times each semester, through the hostel council, subject to availability.", 8, "Section 5")],
      text: "For your programme, room changes are handled by your hostel and usually open at the start of a semester [S1]. Apply through your hostel secretary, and expect approval to depend on vacancies. Check with your hostel office for the exact window.",
      done: { citations: ["S1"], freshness: "current" },
    };
  }

  if (/mess|menu/.test(m)) {
    return {
      tools: ["search_campus_docs", "get_official_link"],
      sources: [],
      text:
        "I couldn't find a verified source for the 2031 mess menu, so I won't guess. Menus are set by each hostel's mess council and change often. The hostel office or your hostel mess secretary can tell you the current one.",
      done: {
        answer_kind: "abstain",
        office_links: [
          { title: "Hostel Affairs Office", url: "https://www.iitb.ac.in/hostels", issuer: "IIT Bombay" },
          { title: "IIT Bombay home page", url: "https://www.iitb.ac.in", issuer: "IIT Bombay" },
        ],
      },
    };
  }

  return {
    tools: ["search_campus_docs"],
    sources: [doc("S1", "Student Information Handbook", "Dean of Student Affairs", "https://www.iitb.ac.in/students/handbook", "An overview of student services, offices and policies at IIT Bombay.", 20, "Contents")],
    text:
      "You're using CampusPilot's **built-in demo**, so I can only answer a few sample questions here: the academic calendar, deadlines, hostel maintenance, the code of conduct, room changes and the mess menu.\n\nWith the real model connected, I'd search the official IIT Bombay pages for this [S1] and cite what I find.",
    done: { citations: ["S1"], freshness: "current" },
  };
}

/** Split text into small pieces so it streams like a model would. */
function chunkText(text: string): string[] {
  return text.match(/\S+\s*|\s+/g) ?? [text];
}

export async function* mockChatStream(req: ChatRequest, signal: AbortSignal): AsyncGenerator<SSEEvent> {
  const started = Date.now();
  const requestId = Math.random().toString(16).slice(2, 8);
  yield { event: "status", data: { request_id: requestId, model: MODEL, mode: "mock" } };
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

  for (const name of script.tools) {
    const label = LABELS[name];
    yield { event: "tool", data: { name, label, state: "start" } };
    await sleep(650, signal);
    if (signal.aborted) return;
    yield { event: "tool", data: { name, label, state: "done" } };
  }

  if (script.sources.length > 0) yield { event: "sources", data: script.sources };

  if (mockWake()) await sleep(5000, signal);

  for (const piece of chunkText(script.text)) {
    if (signal.aborted) return;
    yield { event: "token", data: { text: piece } };
    await sleep(22, signal);
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

export async function mockStatus(): Promise<StatusResponse> {
  await new Promise((r) => setTimeout(r, 150));
  const offline = mockOffline();
  return {
    model_online: !offline,
    model_loaded: !offline,
    model: MODEL,
    moodle: "connected", // unconfigured Moodle falls back to demo data
    moodle_mode: mockMoodle === "none" ? "demo" : mockMoodle,
    sources_indexed: 24,
    mode: "mock",
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
