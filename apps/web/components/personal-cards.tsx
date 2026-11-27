"use client";
// Cards for the v2 connectors (the `cards` SSE event): events and mail from Webmail, and from ASC the
// timetable, courses, profile, fee status, offering history and course details (CONTRACT section 11.8).
// They sit under the answer text like the Moodle deadline cards, and every card wears a source label.
// Grades are never read, so there is no grades card.
import { useEffect, useId, useRef, useState } from "react";
import {
  BookOpen,
  CalendarCheck,
  CalendarClock,
  CalendarPlus,
  Check,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  GraduationCap,
  History,
  Info,
  Loader2,
  Mail,
  MapPin,
  Minus,
  Paperclip,
  RotateCw,
  UserRound,
  Wallet,
} from "lucide-react";
import { useAppActions } from "@/components/app-actions";
import { SourceLabel } from "@/components/source-label";
import { Button } from "@/components/ui/button";
import { addCalendarEvent } from "@/lib/api";
import { cn, courseColorIndex, dayHeadingFromKey, hhmmTo12h, istDateTime, istEventWhen, safeHttpUrl } from "@/lib/utils";
import type {
  AscCourse,
  AscCourseCard,
  AscDetailCard,
  AscFeeCard,
  AscHistoryCard,
  AscProfileCard,
  AscSemesterName,
  AscSlotCard,
  AscWeekday,
  Card,
  EventCard,
  EventCategory,
  MailCard,
} from "@/lib/types";

// ---------- small shared pieces ----------

const CARD = "rounded-xl border bg-card px-3.5 py-3";
const HEADING = "mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground";

function CourseChip({ code }: { code: string }) {
  return <span className={cn("course-chip rounded-md px-2 py-0.5 text-xs font-semibold", `course-${courseColorIndex(code)}`)}>{code}</span>;
}

/** One calm notice for the whole group of cards, like the Moodle demo banner. */
function DemoBanner() {
  const { openSettings } = useAppActions();
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-card px-3.5 py-2.5 sm:flex-row sm:items-center sm:gap-3">
      <p className="flex min-w-0 flex-1 items-start gap-2.5 text-sm leading-snug">
        <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
        <span>
          <strong className="font-semibold">Demo data</strong>
          <span className="text-muted-foreground"> — sample items, not yours. Connect your accounts in Settings to see your own</span>
        </span>
      </p>
      <Button size="sm" variant="outline" onClick={() => openSettings("connectors")} className="self-start max-sm:ml-[26px] sm:self-auto">
        Open Settings
      </Button>
    </div>
  );
}

// ---------- event card ----------

const CATEGORY: Record<EventCategory, { label: string; tone: "accent" | "warning" }> = {
  talk: { label: "Talk", tone: "accent" },
  workshop: { label: "Workshop", tone: "accent" },
  fest: { label: "Fest", tone: "accent" },
  deadline: { label: "Deadline", tone: "warning" },
  exam: { label: "Exam", tone: "warning" },
  other: { label: "Event", tone: "accent" },
};

/** Below this the card says "double-check": the rules or the model were not sure. */
const LOW_CONFIDENCE = 0.6;

type AddState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "created"; link: string | null }
  | { kind: "exists"; link: string | null }
  | { kind: "error"; message: string };

function CalendarLink({ href }: { href: string | null }) {
  const safe = safeHttpUrl(href);
  if (!safe) return null;
  return (
    <>
      <span aria-hidden className="text-muted-foreground">·</span>
      <a href={safe} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-text underline-offset-4 hover:underline">
        View in Calendar <ExternalLink className="h-3 w-3" aria-hidden />
      </a>
    </>
  );
}

function EventCardView({ card }: { card: EventCard }) {
  const { openSettings, connectors } = useAppActions();
  const ev = card.event;
  const [add, setAdd] = useState<AddState>({ kind: "idle" });
  const inFlight = useRef(false); // one click = one request, even for a fast double click

  const hasClearDate = !!ev.start && !ev.date_uncertain;
  // The live Google state (from Settings) wins over the flag that came with the card: the student may
  // have connected or disconnected since the answer was written. Unknown yet = trust the card.
  const gcal = connectors?.data?.gcal;
  const connected = gcal ? gcal.state === "connected" && !gcal.demo : card.can_add_to_calendar;
  const canAdd = hasClearDate && !card.demo && connected;
  const needsConnect = hasClearDate && !card.demo && !connected;

  // A card that cannot add yet wants to know if Google Calendar is connected: load it once.
  const ensureLoaded = connectors?.ensureLoaded;
  useEffect(() => {
    if (needsConnect && !gcal) ensureLoaded?.();
  }, [needsConnect, gcal, ensureLoaded]);

  async function onAdd() {
    if (inFlight.current || !ev.start) return;
    inFlight.current = true;
    setAdd({ kind: "pending" });
    try {
      const res = await addCalendarEvent({
        event_id: ev.id,
        message_id: ev.message_id.slice(0, 500),
        title: ev.title,
        start: ev.start,
        end: ev.end ?? null,
        all_day: ev.all_day,
        venue: ev.venue ? ev.venue.slice(0, 200) : null,
        mail_subject: ev.mail_subject.slice(0, 300),
      });
      if (!res.ok) {
        const message = res.code === "NOT_CONNECTED" ? "Google Calendar isn't connected. Connect it in Settings, then try again." : res.message;
        setAdd({ kind: "error", message });
      } else if (res.data.status === "created") setAdd({ kind: "created", link: res.data.html_link ?? null });
      else if (res.data.status === "already_exists") setAdd({ kind: "exists", link: res.data.html_link ?? null });
      else setAdd({ kind: "error", message: res.data.message || "Couldn't add this event. Please try again." });
    } finally {
      inFlight.current = false;
    }
  }

  const cat = CATEGORY[ev.category] ?? CATEGORY.other;
  const sender = ev.mail_sender || "the mail";
  const mailUrl = safeHttpUrl(ev.open_url);
  const sourceText = (
    <>
      From: <span className="text-foreground/90">{sender}</span>
      {ev.mail_subject && <> · {ev.mail_subject}</>}
    </>
  );

  let action: React.ReactNode;
  if (add.kind === "pending") {
    action = (
      <Button size="sm" variant="primary" disabled>
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Adding…
      </Button>
    );
  } else if (add.kind === "created" || add.kind === "exists") {
    action = (
      <p className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium text-success">
          <CalendarCheck className="h-4 w-4" aria-hidden />
          {add.kind === "created" ? (
            <>Added <span aria-hidden>✓</span></>
          ) : (
            "Already in your calendar"
          )}
        </span>
        <CalendarLink href={add.link} />
      </p>
    );
  } else if (card.demo) {
    action = (
      <Button size="sm" variant="outline" disabled>
        Demo data
      </Button>
    );
  } else if (!hasClearDate) {
    action = (
      <Button size="sm" variant="outline" disabled>
        Date unclear
      </Button>
    );
  } else if (canAdd) {
    action = (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button size="sm" variant="primary" onClick={onAdd}>
          {add.kind === "error" ? <RotateCw className="h-3.5 w-3.5" aria-hidden /> : <CalendarPlus className="h-3.5 w-3.5" aria-hidden />}
          {add.kind === "error" ? "Try again" : "Add to Google Calendar"}
        </Button>
        {add.kind === "error" && <span className="text-sm text-danger">{add.message}</span>}
      </div>
    );
  } else {
    action = (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button size="sm" variant="outline" onClick={() => openSettings("connectors")}>
          <CalendarPlus className="h-3.5 w-3.5" aria-hidden /> Connect Google Calendar
        </Button>
        <span className="text-xs text-muted-foreground">to add events like this one</span>
      </div>
    );
  }

  return (
    <li data-testid="event-card" className="rounded-xl border bg-card p-3.5">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "rounded-md px-2 py-0.5 text-xs font-semibold",
            cat.tone === "warning" ? "bg-warning/15 text-warning" : "bg-accent-soft text-accent-text",
          )}
        >
          {cat.label}
        </span>
        <SourceLabel label={card.source_label} className="ml-auto" />
      </div>
      <h4 className="mt-2 text-[15px] font-medium leading-snug">{ev.title}</h4>

      <div className="mt-2 space-y-1 text-sm">
        <p className="flex items-start gap-2">
          <CalendarClock className={cn("mt-0.5 h-4 w-4 shrink-0", hasClearDate ? "text-muted-foreground" : "text-warning")} aria-hidden />
          <span className="min-w-0">
            <span className="sr-only">When: </span>
            {hasClearDate ? (
              <span className="font-medium">{istEventWhen(ev.start!, ev.end, ev.all_day)}</span>
            ) : (
              <>
                <span className="font-medium text-warning">Date unclear — check the mail</span>
                {ev.date_text && <span className="text-muted-foreground"> (it says “{ev.date_text}”)</span>}
              </>
            )}
          </span>
        </p>
        {ev.venue && (
          <p className="flex items-start gap-2">
            <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0"><span className="sr-only">Venue: </span>{ev.venue}</span>
          </p>
        )}
        {ev.organizer && (
          <p className="flex items-start gap-2">
            <UserRound className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0"><span className="sr-only">Organizer: </span>{ev.organizer}</span>
          </p>
        )}
      </div>

      {ev.confidence < LOW_CONFIDENCE && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-warning">
          <Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden /> Low confidence: double-check the details in the mail.
        </p>
      )}

      <p className="mt-2.5 text-xs leading-snug text-muted-foreground">
        {mailUrl ? (
          <a href={mailUrl} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-start gap-1.5 underline-offset-4 hover:text-foreground hover:underline">
            <Mail className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="line-clamp-2 min-w-0 break-words">{sourceText}</span>
            <ExternalLink className="mt-px h-3 w-3 shrink-0" aria-hidden />
          </a>
        ) : (
          <span className="inline-flex max-w-full items-start gap-1.5">
            <Mail className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="line-clamp-2 min-w-0 break-words">{sourceText}</span>
          </span>
        )}
      </p>

      {/* The result is announced politely. The wrapper has a fixed minimum height so the card never jumps. */}
      <div aria-live="polite" className="mt-3 flex min-h-8 items-center border-t pt-3">
        {action}
      </div>
    </li>
  );
}

// ---------- mail card ----------

function MailCardView({ card }: { card: MailCard }) {
  const m = card.mail;
  const url = safeHttpUrl(m.open_url);
  const who = m.sender_name || m.sender_email || "Unknown sender";
  return (
    <li data-testid="mail-card" className={CARD}>
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={m.sender_email || undefined}>
          <span className="font-medium text-foreground/90">{who}</span> · {istDateTime(m.date)}
        </p>
        <SourceLabel label={card.source_label} />
      </div>
      <p className="mt-1.5 text-[15px] font-medium leading-snug">{m.subject || "(no subject)"}</p>
      {m.snippet && <p className="mt-1 line-clamp-3 break-words text-sm text-muted-foreground">{m.snippet}</p>}
      {(m.has_attachments || url) && (
        <div className="mt-2 flex items-center gap-4 text-xs">
          {m.has_attachments && (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Paperclip className="h-3 w-3" aria-hidden /> Has attachments
            </span>
          )}
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-text underline-offset-4 hover:underline">
              Open in webmail <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          )}
        </div>
      )}
    </li>
  );
}

// ---------- ASC: timetable, courses, profile, fees, history, course details ----------

const WEEKDAYS: AscWeekday[] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const WEEKDAY_NAME: Record<AscWeekday, string> = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" };
const KIND_LABEL = { lecture: "Lecture", tutorial: "Tutorial", lab: "Lab", other: "Class" } as const;

function SlotRow({ card }: { card: AscSlotCard }) {
  const s = card.slot;
  return (
    <li data-testid="slot-card" className={cn(CARD, "flex gap-3")}>
      <div className="w-[4.75rem] shrink-0 text-sm tabular-nums">
        <span className="block font-semibold">{hhmmTo12h(s.start)}</span>
        <span className="block text-xs text-muted-foreground">{hhmmTo12h(s.end)}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <CourseChip code={s.course_code} />
          <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{KIND_LABEL[s.kind]}</span>
          <SourceLabel label={card.source_label} className="ml-auto" />
        </div>
        <p className="mt-1.5 text-[15px] font-medium leading-snug">{s.course_title || s.course_code}</p>
        {s.instructor && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            <UserRound className="h-3 w-3 shrink-0" aria-hidden /> <span className="min-w-0 truncate">{s.instructor}</span>
          </p>
        )}
        {(s.venue || s.slot) && (
          <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            {s.venue && (
              <>
                <MapPin className="h-3 w-3 shrink-0" aria-hidden /> <span className="min-w-0 truncate">{s.venue}</span>
              </>
            )}
            {s.venue && s.slot && <span aria-hidden>·</span>}
            {s.slot && <span className="shrink-0">Slot {s.slot}</span>}
          </p>
        )}
      </div>
    </li>
  );
}

/** The week or day, grouped by day: by date when the answer is for one day, else by weekday. */
function Timetable({ cards }: { cards: AscSlotCard[] }) {
  const groups = new Map<string, { sort: number; heading: string; items: AscSlotCard[] }>();
  for (const c of cards) {
    const key = c.on_date ?? c.slot.day;
    const g = groups.get(key) ?? {
      sort: c.on_date ? Date.parse(c.on_date) : WEEKDAYS.indexOf(c.slot.day),
      heading: c.on_date ? dayHeadingFromKey(c.on_date) : WEEKDAY_NAME[c.slot.day],
      items: [],
    };
    g.items.push(c);
    groups.set(key, g);
  }
  const ordered = [...groups.entries()].sort((a, b) => a[1].sort - b[1].sort);
  return (
    <section aria-label="Timetable" className="space-y-4">
      {ordered.map(([key, g]) => (
        <div key={key}>
          <h3 className={HEADING}>
            <CalendarClock className="h-3.5 w-3.5" aria-hidden /> {g.heading}
          </h3>
          <ul className="space-y-2">
            {[...g.items].sort((a, b) => a.slot.start.localeCompare(b.slot.start)).map((c, i) => (
              <SlotRow key={`${c.id}-${i}`} card={c} />
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

const STATUS_TONE: Record<AscCourse["status"], string> = {
  registered: "bg-success-soft text-success",
  approved: "bg-success-soft text-success",
  pending: "bg-warning-soft text-warning",
  dropped: "bg-danger-soft text-danger",
  audit: "bg-muted text-foreground",
  other: "bg-muted text-foreground",
};

function CourseRow({ card }: { card: AscCourseCard }) {
  const c = card.course;
  const main = [c.credits != null ? `${c.credits} ${c.credits === 1 ? "credit" : "credits"}` : null, c.slot ? `Slot ${c.slot}` : null, c.instructor].filter(Boolean);
  // The extra fields ASC gives for some views: shown small, only when present.
  const extra = [c.tag ? `Tag ${c.tag}` : null, c.credit_audit, c.course_type, c.venue, c.division ? `Division ${c.division}` : null].filter(Boolean);
  return (
    <li data-testid="course-card" className={CARD}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CourseChip code={c.code} />
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold capitalize", STATUS_TONE[c.status])}>{c.status}</span>
        <SourceLabel label={card.source_label} className="ml-auto" />
      </div>
      <p className="mt-1.5 text-[15px] font-medium leading-snug">{c.title || c.code}</p>
      {main.length > 0 && <p className="mt-0.5 break-words text-xs text-muted-foreground">{main.join(" · ")}</p>}
      {extra.length > 0 && <p className="mt-0.5 break-words text-xs text-muted-foreground">{extra.join(" · ")}</p>}
    </li>
  );
}

/** A long list (running courses can be 50+) shows the first rows and a "Show all N" toggle. */
const COURSES_SHOWN = 10;

function Courses({ cards }: { cards: AscCourseCard[] }) {
  const [all, setAll] = useState(false);
  const listId = useId();
  const long = cards.length > COURSES_SHOWN;
  const shown = long && !all ? cards.slice(0, COURSES_SHOWN) : cards;
  return (
    <section aria-label="Courses">
      <h3 className={HEADING}>
        <GraduationCap className="h-3.5 w-3.5" aria-hidden /> Courses
        {long && <span className="font-normal normal-case tracking-normal">· {cards.length}</span>}
      </h3>
      <ul id={listId} className="grid gap-2 sm:grid-cols-2">
        {shown.map((c) => (
          <CourseRow key={c.id} card={c} />
        ))}
      </ul>
      {long && (
        <Button size="sm" variant="outline" className="mt-2.5" aria-expanded={all} aria-controls={listId} onClick={() => setAll((v) => !v)}>
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", all && "rotate-180")} aria-hidden />
          {all ? "Show fewer" : `Show all ${cards.length}`}
        </Button>
      )}
    </section>
  );
}

function ProfileView({ card }: { card: AscProfileCard }) {
  const p = card.profile;
  const rows: [string, string][] = [
    ["Department", p.department],
    ["Program", p.program],
    ["Status", p.status],
    ["Validity", p.validity],
    ["Academic standing", p.academic_standing],
    ["Advisors", p.advisors.join(", ")],
  ];
  return (
    <section aria-label="Profile">
      <h3 className={HEADING}>
        <UserRound className="h-3.5 w-3.5" aria-hidden /> Profile
      </h3>
      <div data-testid="profile-card" className={CARD}>
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 truncate text-[15px] font-medium leading-snug">{p.program || p.department || "Your ASC profile"}</p>
          <SourceLabel label={card.source_label} />
        </div>
        <dl className="mt-2 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">
          {rows
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="min-w-0 break-words font-medium">{v}</dd>
              </div>
            ))}
        </dl>
      </div>
    </section>
  );
}

/** Paid is green, due is amber; any other word ASC uses stays neutral. The word is always shown, never just a colour. */
function feeTone(status?: string | null): string {
  const s = (status ?? "").toLowerCase();
  if (/\b(paid|received|cleared|nil|completed)\b/.test(s)) return "bg-success-soft text-success";
  if (/\b(due|unpaid|pending|overdue|outstanding)\b/.test(s)) return "bg-warning-soft text-warning";
  return "bg-muted text-foreground";
}

function FeeStatus({ cards }: { cards: AscFeeCard[] }) {
  return (
    <section aria-label="Fee status">
      <h3 className={HEADING}>
        <Wallet className="h-3.5 w-3.5" aria-hidden /> Fee status
      </h3>
      <ul className="space-y-2">
        {cards.map((c) => (
          <li key={c.id} data-testid="fee-card" className={CARD}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <p className="min-w-0 flex-1 text-[15px] font-medium leading-snug">{c.fee.label}</p>
              {c.fee.status && (
                <span data-testid="fee-status" className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", feeTone(c.fee.status))}>
                  {c.fee.status}
                </span>
              )}
              <SourceLabel label={c.source_label} />
            </div>
            {(c.fee.amount || c.fee.due_date) && (
              <p className="mt-1 break-words text-xs text-muted-foreground">
                {c.fee.amount && <span className="font-medium text-foreground/90">{c.fee.amount}</span>}
                {c.fee.amount && c.fee.due_date && <span aria-hidden> · </span>}
                {c.fee.due_date && <>Due {c.fee.due_date}</>}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

const SEMESTER_LABEL: Record<AscSemesterName, string> = { autumn: "Autumn", spring: "Spring", summer: "Summer", winter: "Winter" };
const SEMESTER_ORDER: AscSemesterName[] = ["autumn", "spring", "summer", "winter"];

/** 2026 -> "2026-27". */
const academicYear = (y: number) => `${y}-${String((y + 1) % 100).padStart(2, "0")}`;

/** A small year x semester grid. "Offered" and "Not offered" are words (with an icon), not only a colour. */
function HistoryView({ card }: { card: AscHistoryCard }) {
  const years = [...new Set(card.offerings.map((o) => o.year))].sort((a, b) => b - a);
  // Autumn and Spring always; Summer and Winter only when ASC has a row for them.
  const sems = SEMESTER_ORDER.filter((s) => s === "autumn" || s === "spring" || card.offerings.some((o) => o.semester === s));
  const cell = (year: number, sem: AscSemesterName) => card.offerings.find((o) => o.year === year && o.semester === sem);
  return (
    <section aria-label="Offering history">
      <h3 className={HEADING}>
        <History className="h-3.5 w-3.5" aria-hidden /> When it runs
      </h3>
      <div data-testid="history-card" className={CARD}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <CourseChip code={card.course_code} />
          <SourceLabel label={card.source_label} className="ml-auto" />
        </div>
        {card.title && <p className="mt-1.5 text-[15px] font-medium leading-snug">{card.title}</p>}
        {years.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">No offerings found on ASC.</p>
        ) : (
          <div className="mt-2.5 overflow-x-auto">
            <table className="w-full min-w-[15rem] border-separate border-spacing-y-1 text-sm">
              <caption className="sr-only">Years in which {card.course_code} was offered, by semester</caption>
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th scope="col" className="pr-3 font-medium">Year</th>
                  {sems.map((s) => (
                    <th key={s} scope="col" className="px-1 font-medium">{SEMESTER_LABEL[s]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {years.map((y) => (
                  <tr key={y}>
                    <th scope="row" className="pr-3 text-left font-medium tabular-nums">{academicYear(y)}</th>
                    {sems.map((s) => {
                      const o = cell(y, s);
                      return (
                        <td key={s} className="px-1">
                          {o ? (
                            <span
                              data-testid={o.offered ? "offered" : "not-offered"}
                              className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-xs font-medium", o.offered ? "bg-success-soft text-success" : "bg-muted text-muted-foreground")}
                            >
                              {o.offered ? <Check className="h-3 w-3" aria-hidden /> : <Minus className="h-3 w-3" aria-hidden />}
                              {o.offered ? "Offered" : "Not offered"}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              <span aria-hidden>·</span>
                              <span className="sr-only">Not checked</span>
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function DetailView({ card }: { card: AscDetailCard }) {
  const d = card.detail;
  const [open, setOpen] = useState(false);
  const syllabusId = useId();
  const extra = Object.entries(d.extra ?? {}).filter(([, v]) => v);
  const meta = [d.credits != null ? `${d.credits} ${d.credits === 1 ? "credit" : "credits"}` : null, d.department || null].filter(Boolean);
  return (
    <section aria-label="Course details">
      <h3 className={HEADING}>
        <BookOpen className="h-3.5 w-3.5" aria-hidden /> Course details
      </h3>
      <div data-testid="detail-card" className={CARD}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <CourseChip code={d.code} />
          <SourceLabel label={card.source_label} className="ml-auto" />
        </div>
        <p className="mt-1.5 text-[15px] font-medium leading-snug">{d.title || d.code}</p>
        {meta.length > 0 && <p className="mt-0.5 text-xs text-muted-foreground">{meta.join(" · ")}</p>}

        <div className="mt-2.5">
          <h4 className="text-xs font-medium text-muted-foreground">Prerequisites</h4>
          {d.prerequisites.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {d.prerequisites.map((p) => (
                <li key={p} data-testid="prereq">
                  <CourseChip code={p} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-0.5 text-sm">None listed</p>
          )}
        </div>

        {extra.length > 0 && (
          <dl className="mt-2.5 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
            {extra.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="min-w-0 break-words">{v}</dd>
              </div>
            ))}
          </dl>
        )}

        {d.syllabus && (
          <div className="mt-3 border-t pt-3">
            <Button size="sm" variant="outline" aria-expanded={open} aria-controls={syllabusId} onClick={() => setOpen((v) => !v)}>
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden />
              {open ? "Hide syllabus" : "Show syllabus"}
            </Button>
            {open && (
              <p id={syllabusId} data-testid="syllabus" className="mt-2.5 whitespace-pre-line break-words text-sm leading-relaxed text-foreground/90">
                {d.syllabus}
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// ---------- the whole group ----------

/** Everything the `cards` event carried, in a fixed order: events, mail, profile, timetable, courses, fees, history, details. */
export function PersonalCards({ cards }: { cards: Card[] }) {
  if (cards.length === 0) return null;
  const events = cards.filter((c): c is EventCard => c.type === "event");
  const mails = cards.filter((c): c is MailCard => c.type === "mail");
  const slots = cards.filter((c): c is AscSlotCard => c.type === "asc_slot");
  const courses = cards.filter((c): c is AscCourseCard => c.type === "asc_course");
  const profiles = cards.filter((c): c is AscProfileCard => c.type === "asc_profile");
  const fees = cards.filter((c): c is AscFeeCard => c.type === "asc_fee");
  const histories = cards.filter((c): c is AscHistoryCard => c.type === "asc_history");
  const details = cards.filter((c): c is AscDetailCard => c.type === "asc_detail");

  return (
    <div className="animate-fade-up space-y-4" data-testid="personal-cards">
      {cards.some((c) => c.demo) && <DemoBanner />}
      {events.length > 0 && (
        <section aria-label="Events from your mail">
          <h3 className={HEADING}>
            <CalendarClock className="h-3.5 w-3.5" aria-hidden /> From your mail
          </h3>
          <ul className="space-y-2.5">
            {events.map((c) => (
              <EventCardView key={c.id} card={c} />
            ))}
          </ul>
        </section>
      )}
      {mails.length > 0 && (
        <section aria-label="Mail results">
          <h3 className={HEADING}>
            <Mail className="h-3.5 w-3.5" aria-hidden /> Mail
          </h3>
          <ul className="space-y-2">
            {mails.map((c) => (
              <MailCardView key={c.id} card={c} />
            ))}
          </ul>
        </section>
      )}
      {profiles.map((c) => (
        <ProfileView key={c.id} card={c} />
      ))}
      {slots.length > 0 && <Timetable cards={slots} />}
      {courses.length > 0 && <Courses cards={courses} />}
      {fees.length > 0 && <FeeStatus cards={fees} />}
      {histories.map((c) => (
        <HistoryView key={c.id} card={c} />
      ))}
      {details.map((c) => (
        <DetailView key={c.id} card={c} />
      ))}
    </div>
  );
}
