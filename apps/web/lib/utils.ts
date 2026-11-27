import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names, letting later Tailwind classes win. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ---------- dates ----------

const IST = "Asia/Kolkata";

/** "checked 3 days ago" style text. */
export function checkedAgo(iso?: string | null, now = Date.now()): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const days = Math.floor((now - t) / 86_400_000);
  if (days <= 0) return "checked today";
  if (days === 1) return "checked yesterday";
  if (days < 60) return `checked ${days} days ago`;
  const months = Math.floor(days / 30);
  return `checked ${months} months ago`;
}

/** "just now", "5 minutes ago", "2 hours ago", "3 days ago" (for "Updated ..."). Empty when the date is unusable. */
export function relativePast(iso?: string | null, now = Date.now()): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const mins = Math.floor((now - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} ${mins === 1 ? "minute" : "minutes"} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}

/** "in 2 days", "in 5 hours", "overdue". `urgent` is true under 24 h. */
export function relativeDue(iso: string, now = Date.now()): { text: string; urgent: boolean; overdue: boolean } {
  const diff = Date.parse(iso) - now;
  if (diff < 0) return { text: "overdue", urgent: true, overdue: true };
  const mins = Math.round(diff / 60_000);
  const urgent = diff < 86_400_000;
  if (mins < 60) return { text: `in ${Math.max(mins, 1)} min`, urgent, overdue: false };
  const hours = Math.round(mins / 60);
  if (hours < 24) return { text: `in ${hours} ${hours === 1 ? "hour" : "hours"}`, urgent, overdue: false };
  const days = Math.round(diff / 86_400_000);
  return { text: `in ${days} ${days === 1 ? "day" : "days"}`, urgent, overdue: false };
}

/** "Fri, 28 Nov, 11:59 PM IST" */
export function istDateTime(iso: string): string {
  const s = new Intl.DateTimeFormat("en-IN", {
    timeZone: IST,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
  return `${s.replace(/\b(am|pm)\b/i, (m) => m.toUpperCase())} IST`;
}

/** "11:59 PM" in IST. */
export function istTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit", hour12: true })
    .format(new Date(iso))
    .replace(/\b(am|pm)\b/i, (m) => m.toUpperCase());
}

function istDayKey(d: Date | number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST }).format(d); // 2026-11-28
}

/** Day heading used to group deadlines: "Today", "Tomorrow" or "Fri, 28 Nov". */
export function istDayLabel(iso: string, now = Date.now()): { key: string; label: string } {
  const key = istDayKey(new Date(iso));
  if (key === istDayKey(now)) return { key, label: "Today" };
  if (key === istDayKey(now + 86_400_000)) return { key, label: "Tomorrow" };
  const label = new Intl.DateTimeFormat("en-IN", { timeZone: IST, weekday: "short", day: "numeric", month: "short" }).format(new Date(iso));
  return { key, label };
}

/** "Fri, 28 Nov" in IST. */
export function istDay(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, weekday: "short", day: "numeric", month: "short" }).format(new Date(iso));
}

/**
 * When an event happens, in IST, for the event card:
 *   all day:        "Fri, 28 Nov · All day"
 *   same-day span:  "Fri, 28 Nov, 5:00 PM – 6:30 PM IST"
 *   no end / other: "Fri, 28 Nov, 5:00 PM IST"
 */
export function istEventWhen(startIso: string, endIso?: string | null, allDay = false): string {
  if (allDay) return `${istDay(startIso)} · All day`;
  if (endIso && !Number.isNaN(Date.parse(endIso)) && istDayKey(new Date(endIso)) === istDayKey(new Date(startIso))) {
    return `${istDay(startIso)}, ${istTime(startIso)} – ${istTime(endIso)} IST`;
  }
  return istDateTime(startIso);
}

/** Heading for a day given as "YYYY-MM-DD": "Today", "Tomorrow" or "Fri, 28 Nov". */
export function dayHeadingFromKey(key: string, now = Date.now()): string {
  if (key === istDayKey(now)) return "Today";
  if (key === istDayKey(now + 86_400_000)) return "Tomorrow";
  // Noon IST on that date, so the weekday and day number can never slip across midnight.
  return istDay(`${key}T12:00:00+05:30`);
}

/** "10:30" -> "10:30 AM" (ASC gives 24-hour times in IST). */
export function hhmmTo12h(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

/** The link only if it is a plain web address. Server data is never trusted to be a safe href (no javascript: URLs). */
export function safeHttpUrl(url?: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

// ---------- citations ----------

const MARKER = /\[((?:S|M)\d+)\]/g;

/**
 * Turn "[S1]" markers into markdown links "[1](cite:S1)" for ids that were
 * validated by the server (done.citations). Every other marker is removed, and
 * so is a half-typed marker at the very end ("[S" while streaming).
 * `numbering` maps an id to the number shown in the chip.
 */
export function prepareCitations(text: string, validIds: string[]): string {
  const valid = new Set(validIds);
  const cleaned = text.replace(MARKER, (_m, id: string) => (valid.has(id) ? `[${validIds.indexOf(id) + 1}](cite:${id})` : ""));
  return cleaned.replace(/\s?\[[SM]?\d*$/, "").replace(/ {2,}/g, " ");
}

// ---------- small helpers for cards ----------

/** "acad.iitb.ac.in" from a full URL (without a leading "www."). */
export function domainOf(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/**
 * Which of the 6 course colours (CSS classes .course-0 ... .course-5) a course code gets.
 * The same code always gets the same colour.
 */
export function courseColorIndex(code: string): number {
  let hash = 0;
  for (const ch of code.replace(/\s+/g, "").toUpperCase()) hash = (hash * 31 + ch.charCodeAt(0)) % 1009;
  return hash % 6;
}

// Past-tense wording for a finished step, keyed by tool name (labels are fixed by docs/CONTRACT.md).
const DONE_LABELS: Record<string, string> = {
  search_campus_docs: "Searched campus documents",
  get_official_link: "Found the official page",
  list_my_courses: "Read your Moodle courses",
  get_my_deadlines: "Checked your Moodle deadlines",
  get_course_contents: "Opened course contents",
  ask_clarification: "Asked a clarifying question",
  // v2 connectors
  search_my_mail: "Searched your mail",
  list_recent_mail: "Read your latest mail",
  get_upcoming_institute_events: "Found events in your mail",
  asc_profile: "Read your ASC profile",
  asc_my_timetable: "Read your ASC timetable",
  asc_my_current_courses: "Read your ASC courses",
  asc_registration_status: "Checked your ASC registration",
  asc_fee_status: "Checked the ASC scholarship month view",
  asc_offered_courses: "Read ASC running courses",
  asc_course_offering_history: "Checked when the course runs",
  asc_course_details: "Read the course details on ASC",
};
export const doneLabel = (name: string, fallback: string) => DONE_LABELS[name] ?? fallback;
