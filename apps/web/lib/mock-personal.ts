// Mock answers for the v2 connector journeys (local mode): mail events, the ASC timetable, courses
// and grades. Everything here is invented sample data, with dates relative to today (in IST) so the
// cards always look current. No real names, mail or grades.
import { mockConnectors } from "./config";
import type { AscCourse, AscGrade, AscTimetableSlot, AscWeekday, Card, DetectedEvent, MailMessage } from "./types";

/** Tool names and the exact labels the contract fixes for them (CONTRACT section 11.3). */
export const PERSONAL_LABELS = {
  search_my_mail: "Searching your mail",
  list_recent_mail: "Reading your latest mail",
  get_upcoming_institute_events: "Finding events in your mail",
  get_my_timetable: "Reading your ASC timetable",
  get_my_registered_courses: "Reading your ASC courses",
  get_my_grades: "Reading your ASC grades",
} as const;

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

const slot = (course_code: string, course_title: string, start: string, end: string, venue: string, kind: AscTimetableSlot["kind"], s: string): Omit<AscTimetableSlot, "day"> => ({
  course_code,
  course_title,
  start,
  end,
  venue,
  kind,
  slot: s,
});

/** The answer for a question about mail, the timetable, courses or grades, or null for anything else. */
export function personalScript(message: string): PersonalScript | null {
  const m = message.toLowerCase();
  const isDemo = demo();

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

  // 2. "What's my timetable tomorrow?" -> ASC slots for one day.
  if (/timetable|my classes|class schedule/.test(m)) {
    const on = istDateKey(1);
    const day = weekdayOf(on);
    const slots = [
      slot("IE 624", "Decision Models", "09:30", "10:55", "LH 301", "lecture", "1"),
      slot("IE 611", "Stochastic Processes", "11:05", "12:30", "LH 102", "lecture", "2"),
      slot("HS 101", "Economics", "14:00", "15:25", "LH 201", "tutorial", "3"),
    ];
    return {
      tools: ["get_my_timetable"],
      cards: slots.map((s, i): Card => ({ id: `A${i + 1}`, type: "asc_slot", source_label: "ASC", demo: isDemo, on_date: on, slot: { ...s, day } })),
      text: "You have 3 classes tomorrow. The first is IE 624 Decision Models at 9:30 AM.",
    };
  }

  // 3. Registered courses.
  if (/registered courses|my courses|courses am i/.test(m)) {
    const course = (code: string, title: string, credits: number, s: string, status: AscCourse["status"], instructor: string): AscCourse => ({
      code,
      title,
      credits,
      slot: s,
      instructor,
      status,
      semester: "2026-27 Autumn",
    });
    const courses = [
      course("IE 624", "Decision Models", 6, "1", "registered", "Prof. A. Sample"),
      course("IE 611", "Stochastic Processes", 6, "2", "registered", "Prof. B. Sample"),
      course("HS 101", "Economics", 6, "3", "approved", "Prof. C. Sample"),
      course("MA 205", "Complex Analysis", 6, "4", "pending", "Prof. D. Sample"),
    ];
    return {
      tools: ["get_my_registered_courses"],
      cards: courses.map((c, i): Card => ({ id: `A${i + 1}`, type: "asc_course", source_label: "ASC", demo: isDemo, course: c })),
      text: "You are registered for 4 courses this semester (2026-27 Autumn).",
    };
  }

  // 4. Grades: sensitive, so the UI hides the values until the student asks.
  if (/\bgrades?\b|\bspi\b|\bcpi\b/.test(m)) {
    const grade = (course_code: string, course_title: string, g: string): AscGrade => ({ course_code, course_title, credits: 6, grade: g, semester: "2025-26 Spring" });
    const grades = [grade("IE 601", "Optimization", "AA"), grade("IE 603", "Simulation", "AB"), grade("HS 102", "Ethics", "AP")];
    return {
      tools: ["get_my_grades"],
      cards: grades.map((g, i): Card => ({ id: `A${i + 1}`, type: "asc_grade", source_label: "ASC", demo: isDemo, grade: g })),
      text: "I found grades for 3 courses. They stay hidden until you choose to show them.",
    };
  }

  // 5. Mail search -> mail result cards (snippets only, never full bodies).
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
