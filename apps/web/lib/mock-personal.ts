// Mock answers for the v2 connector journeys (local mode): mail events and the ASC views (timetable,
// courses, registration, fees, profile, offered courses, offering history, course details).
// Everything here is invented sample data, with dates relative to today (in IST) so the cards always
// look current. No real names, mail, amounts or grades (grades are never read).
import { mockConnectors } from "./config";
import type { AscCourse, AscOffering, AscTimetableSlot, AscWeekday, Card, DetectedEvent, MailMessage } from "./types";

/** Tool names and the exact labels the contract fixes for them (CONTRACT sections 11.3 and 11.8). */
export const PERSONAL_LABELS = {
  search_my_mail: "Searching your mail",
  list_recent_mail: "Reading your latest mail",
  get_upcoming_institute_events: "Finding events in your mail",
  asc_profile: "Reading your ASC profile",
  asc_my_timetable: "Reading your ASC timetable",
  asc_my_current_courses: "Reading your ASC courses",
  asc_registration_status: "Checking your ASC registration",
  asc_fee_status: "Checking your ASC fee status",
  asc_offered_courses: "Reading ASC running courses",
  asc_course_offering_history: "Checking when the course runs",
  asc_course_details: "Reading the course details on ASC",
} as const;

/** What the real API says, with no tool run, when a cloud model gets a question about the student's own ASC data. */
export const ASC_LOCAL_ONLY_TEXT = "That needs your ASC data, which CampusPilot only shares with the local model. Switch to Local Gemma in Settings.";

export interface PersonalScript {
  tools: (keyof typeof PERSONAL_LABELS)[];
  cards: Card[];
  text: string;
}

const MS_DAY = 86_400_000;

/** "YYYY-MM-DD" for `days` ahead, in IST. */
function istDateKey(days: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() + days * MS_DAY));
}

/** A time on a day `days` ahead, as an ISO string with the IST offset (like the real server sends). */
function istAt(days: number, hour: number, minute = 0): string {
  return `${istDateKey(days)}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+05:30`;
}

const WEEKDAYS: AscWeekday[] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const weekdayOf = (key: string): AscWeekday => WEEKDAYS[new Date(`${key}T12:00:00+05:30`).getUTCDay()];

const demo = () => mockConnectors() === "demo";
/** The card flag the real server computes: Google Calendar connected, clear date, not demo data. */
const calendarReady = () => mockConnectors() === "connected";

function event(n: number, partial: Partial<DetectedEvent> & Pick<DetectedEvent, "title" | "category">): DetectedEvent {
  return {
    id: `mock-event-key-${n}-0000000000`.slice(0, 24),
    message_id: `<sample-${n}@mail.example.invalid>`,
    all_day: false,
    date_uncertain: false,
    date_text: "",
    confidence: 0.9,
    detected_by: "rules+llm",
    mail_subject: partial.title,
    mail_sender: "Student Events Cell",
    open_url: "https://webmail.iitb.ac.in/",
    ...partial,
  };
}

function eventCard(id: string, e: DetectedEvent): Card {
  return {
    id,
    type: "event",
    source_label: "Webmail",
    demo: demo(),
    event: e,
    can_add_to_calendar: calendarReady() && !!e.start && !e.date_uncertain,
  };
}

const slot = (course_code: string, course_title: string, start: string, end: string, venue: string, kind: AscTimetableSlot["kind"], s: string, instructor: string): Omit<AscTimetableSlot, "day"> => ({
  course_code,
  course_title,
  start,
  end,
  venue,
  kind,
  slot: s,
  instructor,
});

const ASC_SEMESTER = "2026-27 Autumn";

/** Which ASC view a question is about. The first five read the student's own data (local model only). */
type AscKind = "timetable" | "courses" | "registration" | "fees" | "profile" | "offered" | "history" | "detail";
const ASC_PERSONAL: AscKind[] = ["timetable", "courses", "registration", "fees", "profile"];

function ascKind(m: string): AscKind | null {
  if (/\bwhen\b.*\b(offered|offer|run|runs|running)\b|offering history/.test(m)) return "history";
  if (/prerequisite|prereq|syllabus|course details?/.test(m)) return "detail";
  if (/\boffered\b.*\bcourses\b|\bcourses\b.*\b(offered|running)\b|running courses/.test(m)) return "offered";
  if (/timetable|my classes|class schedule/.test(m)) return "timetable";
  if (/registered courses|my courses|current courses|courses am i/.test(m)) return "courses";
  if (/registration|am i registered/.test(m)) return "registration";
  if (/\bfees?\b/.test(m)) return "fees";
  if (/\bprofile\b|advisors?|academic standing|validity/.test(m)) return "profile";
  return null;
}

/** The course code in a question ("IE 307", "ie307"), as ASC writes it; IE 307 when there is none. */
function courseCodeIn(m: string): string {
  const hit = /\b([a-z]{2,3})\s?(\d{3})\b/.exec(m);
  return hit ? `${hit[1].toUpperCase()} ${hit[2]}` : "IE 307";
}

const ascCourse = (code: string, title: string, credits: number, status: AscCourse["status"], more: Partial<AscCourse> = {}): AscCourse => ({
  code,
  title,
  credits,
  status,
  semester: ASC_SEMESTER,
  ...more,
});

/** The answer for a question about mail or ASC, or null for anything else. With a cloud model, personal ASC questions are refused. */
export function personalScript(message: string, cloud = false): PersonalScript | null {
  const m = message.toLowerCase();
  const isDemo = demo();
  const asc = ascKind(m);

  if (asc && cloud && ASC_PERSONAL.includes(asc)) return { tools: [], cards: [], text: ASC_LOCAL_ONLY_TEXT };

  // 1. "Any institute events this week from my mail?" -> two event cards: one addable, one with an unclear date.
  if (/\bevents?\b.*\bmail\b|\bmail\b.*\bevents?\b/.test(m)) {
    return {
      tools: ["get_upcoming_institute_events"],
      cards: [
        eventCard(
          "E1",
          event(1, {
            title: "Guest talk: Analytics in supply chains",
            category: "talk",
            start: istAt(2, 17),
            end: istAt(2, 18, 30),
            venue: "Lecture Hall 3, Main Building",
            organizer: "Student Events Cell",
            mail_subject: "Guest talk this week: Analytics in supply chains",
            mail_date: istAt(-1, 10, 15),
          }),
        ),
        eventCard(
          "E2",
          event(2, {
            title: "Hackathon registration is open",
            category: "fest",
            start: null,
            date_uncertain: true,
            date_text: "later this month",
            confidence: 0.5,
            detected_by: "rules",
            organizer: "Tech Council",
            mail_sender: "Tech Council",
            mail_subject: "Hackathon registration is open",
            mail_date: istAt(-2, 9, 0),
          }),
        ),
      ],
      text: "I found 2 possible events in your mail from the last 7 days. One has no clear date, so open that mail to check.",
    };
  }

  // ASC, your own data. 'What's my timetable tomorrow?' -> slots for one day.
  if (asc === "timetable") {
    const on = istDateKey(1);
    const day = weekdayOf(on);
    const slots = [
      slot("IE 624", "Decision Models", "09:30", "10:55", "LH 301", "lecture", "1", "Prof. A. Sample"),
      slot("IE 611", "Stochastic Processes", "11:05", "12:30", "LH 102", "lecture", "2", "Prof. B. Sample"),
      slot("HS 101", "Economics", "14:00", "15:25", "LH 201", "tutorial", "3", "Prof. C. Sample"),
    ];
    return {
      tools: ["asc_my_timetable"],
      cards: slots.map((s, i): Card => ({ id: `A${i + 1}`, type: "asc_slot", source_label: "ASC", demo: isDemo, on_date: on, slot: { ...s, day } })),
      text: "You have 3 classes tomorrow. The first is IE 624 Decision Models at 9:30 AM.",
    };
  }

  // Current courses (the academic record, minus grades).
  if (asc === "courses") {
    const courses = [
      ascCourse("IE 624", "Decision Models", 6, "registered", { slot: "1", instructor: "Prof. A. Sample", tag: "DC", credit_audit: "Credit", venue: "LH 301" }),
      ascCourse("IE 611", "Stochastic Processes", 6, "registered", { slot: "2", instructor: "Prof. B. Sample", tag: "DE", credit_audit: "Credit", venue: "LH 102" }),
      ascCourse("HS 101", "Economics", 6, "approved", { slot: "3", instructor: "Prof. C. Sample", tag: "IC", credit_audit: "Credit", venue: "LH 201" }),
      ascCourse("MA 205", "Complex Analysis", 6, "audit", { slot: "4", instructor: "Prof. D. Sample", tag: "OE", credit_audit: "Audit", venue: "LH 305" }),
    ];
    return {
      tools: ["asc_my_current_courses"],
      cards: courses.map((c, i): Card => ({ id: `A${i + 1}`, type: "asc_course", source_label: "ASC", demo: isDemo, course: c })),
      text: `You have 4 courses this semester (${ASC_SEMESTER}).`,
    };
  }

  // Registration: the window is closed, so ASC shows the registered courses instead.
  if (asc === "registration") {
    const courses = [
      ascCourse("IE 624", "Decision Models", 6, "registered", { slot: "1" }),
      ascCourse("IE 611", "Stochastic Processes", 6, "registered", { slot: "2" }),
      ascCourse("HS 101", "Economics", 6, "registered", { slot: "3" }),
    ];
    return {
      tools: ["asc_registration_status"],
      cards: courses.map((c, i): Card => ({ id: `A${i + 1}`, type: "asc_course", source_label: "ASC", demo: isDemo, course: c })),
      text: `The registration window is closed right now. You are registered for 3 courses in ${ASC_SEMESTER}.`,
    };
  }

  // Fee status: amounts are invented.
  if (asc === "fees") {
    const fee = (label: string, amount: string, due_date: string | null, status: string) => ({ label, amount, due_date, status });
    const fees = [fee("Tuition fee", "Rs 10,000", null, "Paid"), fee("Hostel rent", "Rs 3,000", "15 Dec 2026", "Due"), fee("Mess advance", "Rs 2,000", null, "Paid")];
    return {
      tools: ["asc_fee_status"],
      cards: fees.map((f, i): Card => ({ id: `A${i + 1}`, type: "asc_fee", source_label: "ASC", demo: isDemo, fee: f })),
      text: "ASC shows 3 fee items: 2 paid and 1 due.",
    };
  }

  // Profile: no roll number, no name.
  if (asc === "profile") {
    return {
      tools: ["asc_profile"],
      cards: [
        {
          id: "A1",
          type: "asc_profile",
          source_label: "ASC",
          demo: isDemo,
          profile: {
            department: "Industrial Engineering and Operations Research",
            program: "Master of Technology (sample)",
            status: "Registered",
            validity: "2028-29 Spring",
            academic_standing: "Good standing",
            advisors: ["Prof. A. Sample", "Prof. B. Sample"],
          },
        },
      ],
      text: "Here is your ASC profile: Master of Technology (sample) in Industrial Engineering and Operations Research, status Registered.",
    };
  }

  // Running courses of a department: a long list (14), so the UI shows the first 10 and "Show all 14".
  if (asc === "offered") {
    const titles = [
      "Decision Models", "Stochastic Processes", "Linear Programming", "Network Optimization", "Supply Chain Analytics", "Simulation Methods", "Queueing Systems",
      "Financial Engineering", "Reliability Engineering", "Applied Statistics", "Inventory Theory", "Game Theory", "Optimization Seminar", "Data Analytics Lab",
    ];
    const courses = titles.map((t, i) =>
      ascCourse(`IE ${601 + i}`, t, i === 12 ? 2 : 6, "other", {
        slot: String((i % 6) + 1),
        instructor: `Prof. ${String.fromCharCode(65 + i)}. Sample`,
        venue: `LH ${301 + i}`,
        course_type: i % 3 === 0 ? "Core" : "Elective",
        division: i % 4 === 0 ? "1" : undefined,
        semester: "2026-27 Autumn",
      }),
    );
    return {
      tools: ["asc_offered_courses"],
      cards: courses.map((c, i): Card => ({ id: `A${i + 1}`, type: "asc_course", source_label: "ASC", demo: isDemo, course: c })),
      text: "ASC lists 14 running courses for IE in Autumn 2026-27. The first 10 are shown; open the list for the rest.",
    };
  }

  // 'When is IE 307 offered?' -> a year x semester grid.
  if (asc === "history") {
    const code = courseCodeIn(m);
    const offering = (year: number, semester: AscOffering["semester"], offered: boolean): AscOffering => ({ year, semester, offered });
    const offerings = [
      offering(2026, "autumn", true),
      offering(2026, "spring", false),
      offering(2025, "autumn", true),
      offering(2025, "spring", false),
      offering(2024, "autumn", false),
      offering(2024, "spring", true),
      offering(2023, "autumn", true),
      offering(2023, "spring", false),
    ];
    return {
      tools: ["asc_course_offering_history"],
      cards: [{ id: "A1", type: "asc_history", source_label: "ASC", demo: isDemo, course_code: code, title: "Queueing Systems (sample)", offerings }],
      text: `${code} was offered in 3 of the last 4 autumn semesters and in 1 of the last 4 spring semesters on ASC.`,
    };
  }

  // 'Prerequisites of IE 307' -> the course detail card.
  if (asc === "detail") {
    const code = courseCodeIn(m);
    return {
      tools: ["asc_course_details"],
      cards: [
        {
          id: "A1",
          type: "asc_detail",
          source_label: "ASC",
          demo: isDemo,
          detail: {
            code,
            title: "Queueing Systems (sample)",
            credits: 6,
            department: "Industrial Engineering and Operations Research",
            prerequisites: ["MA 106", "IE 201"],
            syllabus:
              "Sample syllabus text, not the real one.\nPoisson processes and the exponential distribution. Birth-death queues: M/M/1, M/M/c and finite-buffer variants.\nM/G/1 queues and the Pollaczek-Khinchine formula. Queueing networks and Jackson's theorem.\nApplications to service systems and manufacturing lines.",
            extra: { "Offered to": "UG and PG" },
          },
        },
      ],
      text: `${code} Queueing Systems (sample) is a 6-credit course. Its prerequisites on ASC are MA 106 and IE 201.`,
    };
  }

  // Mail search -> mail result cards (snippets only, never full bodies).
  if (/\bmail\b|\bemails?\b/.test(m)) {
    const mail = (n: number, subject: string, sender: string, hoursAgo: number, snippet: string, attach = false): Card => {
      const msg: MailMessage = {
        uid: String(100 + n),
        folder: "INBOX",
        message_id: `<sample-mail-${n}@mail.example.invalid>`,
        sender_name: sender,
        sender_email: `${sender.toLowerCase().replace(/\W+/g, ".")}@example.invalid`,
        subject,
        date: new Date(Date.now() - hoursAgo * 3_600_000).toISOString(),
        snippet,
        has_attachments: attach,
        open_url: "https://webmail.iitb.ac.in/",
      };
      return { id: `W${n}`, type: "mail", source_label: "Webmail", demo: isDemo, mail: msg };
    };
    return {
      tools: ["search_my_mail"],
      cards: [
        mail(1, "Hostel mess committee: feedback form", "Hostel Office", 20, "Please fill in the mess feedback form before the end of the week so the committee can review it.", false),
        mail(2, "Course registration reminder", "Academic Office", 50, "A reminder that course registration closes soon. Check your pending approvals on the portal.", true),
      ],
      text: "I found 2 mails that match in the last 14 days. I'm showing short previews only.",
    };
  }

  return null;
}

/** The mail-deadline cards added to "What's due this week?" in local mode. */
export function dueMailCards(): Card[] {
  return [
    eventCard(
      "E1",
      event(11, {
        title: "Hostel form submission deadline",
        category: "deadline",
        start: istAt(2, 17),
        all_day: false,
        mail_subject: "Reminder: hostel form due Friday",
        mail_sender: "Hostel Office",
        mail_date: istAt(-1, 11, 0),
        organizer: "Hostel Office",
      }),
    ),
    eventCard(
      "E2",
      event(12, {
        title: "Scholarship documents due",
        category: "deadline",
        start: istAt(4, 0, 0),
        all_day: true,
        mail_subject: "Documents needed for scholarship renewal",
        mail_sender: "Academic Office",
        mail_date: istAt(-3, 15, 30),
        confidence: 0.75,
      }),
    ),
  ];
}
