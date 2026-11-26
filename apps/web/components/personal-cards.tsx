"use client";
// Cards for the v2 connectors (the `cards` SSE event): events and mail from Webmail, and the timetable,
// courses and grades from ASC. They sit under the answer text like the Moodle deadline cards, and every
// card wears a source label. Grades are hidden until the student asks to see them.
import { useEffect, useId, useRef, useState } from "react";
import {
  Award,
  CalendarCheck,
  CalendarClock,
  CalendarPlus,
  ExternalLink,
  Eye,
  EyeOff,
  FlaskConical,
  GraduationCap,
  Info,
  Loader2,
  Mail,
  MapPin,
  Paperclip,
  RotateCw,
  UserRound,
} from "lucide-react";
import { useAppActions } from "@/components/app-actions";
import { SourceLabel } from "@/components/source-label";
import { Button } from "@/components/ui/button";
import { addCalendarEvent } from "@/lib/api";
import { cn, courseColorIndex, dayHeadingFromKey, hhmmTo12h, istDateTime, istEventWhen, safeHttpUrl } from "@/lib/utils";
import type {
  AscCourse,
  AscCourseCard,
  AscGradeCard,
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

// ---------- ASC: timetable, courses, grades ----------

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
  const bits = [c.credits != null ? `${c.credits} ${c.credits === 1 ? "credit" : "credits"}` : null, c.slot ? `Slot ${c.slot}` : null, c.instructor].filter(Boolean);
  return (
    <li data-testid="course-card" className={CARD}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CourseChip code={c.code} />
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold capitalize", STATUS_TONE[c.status])}>{c.status}</span>
        <SourceLabel label={card.source_label} className="ml-auto" />
      </div>
      <p className="mt-1.5 text-[15px] font-medium leading-snug">{c.title || c.code}</p>
      {bits.length > 0 && <p className="mt-0.5 text-xs text-muted-foreground">{bits.join(" · ")}</p>}
    </li>
  );
}

/** Grades are sensitive: the real values are not even in the page until the student presses "Show grades". */
function Grades({ cards }: { cards: AscGradeCard[] }) {
  const [shown, setShown] = useState(false);
  const listId = useId();
  return (
    <section aria-label="Grades" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className={cn(HEADING, "mb-0")}>
          <Award className="h-3.5 w-3.5" aria-hidden /> Grades
        </h3>
        <Button size="sm" variant="outline" aria-controls={listId} onClick={() => setShown((s) => !s)}>
          {shown ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
          {shown ? "Hide grades" : "Show grades"}
        </Button>
      </div>
      <ul id={listId} className="space-y-2">
        {cards.map((c) => (
          <li key={c.id} data-testid="grade-card" className={cn(CARD, "flex items-center gap-3")}>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <CourseChip code={c.grade.course_code} />
                {c.grade.semester && <span className="text-xs text-muted-foreground">{c.grade.semester}</span>}
                <SourceLabel label={c.source_label} className="ml-auto" />
              </div>
              <p className="mt-1.5 text-[15px] font-medium leading-snug">{c.grade.course_title || c.grade.course_code}</p>
              {c.grade.credits != null && <p className="mt-0.5 text-xs text-muted-foreground">{c.grade.credits} {c.grade.credits === 1 ? "credit" : "credits"}</p>}
            </div>
            {shown ? (
              <span data-testid="grade-value" className="min-w-11 rounded-lg bg-accent-soft px-3 py-1.5 text-center text-base font-semibold text-accent-text">
                {c.grade.grade}
              </span>
            ) : (
              <span role="img" aria-label="Grade hidden" className="min-w-11 select-none rounded-lg bg-muted px-3 py-1.5 text-center text-base font-semibold tracking-widest text-muted-foreground">
                ••
              </span>
            )}
          </li>
        ))}
      </ul>
      {!shown && <p className="text-xs text-muted-foreground">Grades stay hidden until you ask. They come straight from ASC and are never sent to the AI model.</p>}
    </section>
  );
}

// ---------- the whole group ----------

/** Everything the `cards` event carried, in a fixed order: events, mail, timetable, courses, grades. */
export function PersonalCards({ cards }: { cards: Card[] }) {
  if (cards.length === 0) return null;
  const events = cards.filter((c): c is EventCard => c.type === "event");
  const mails = cards.filter((c): c is MailCard => c.type === "mail");
  const slots = cards.filter((c): c is AscSlotCard => c.type === "asc_slot");
  const courses = cards.filter((c): c is AscCourseCard => c.type === "asc_course");
  const grades = cards.filter((c): c is AscGradeCard => c.type === "asc_grade");

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
      {slots.length > 0 && <Timetable cards={slots} />}
      {courses.length > 0 && (
        <section aria-label="Registered courses">
          <h3 className={HEADING}>
            <GraduationCap className="h-3.5 w-3.5" aria-hidden /> Courses
          </h3>
          <ul className="grid gap-2 sm:grid-cols-2">
            {courses.map((c) => (
              <CourseRow key={c.id} card={c} />
            ))}
          </ul>
        </section>
      )}
      {grades.length > 0 && <Grades cards={grades} />}
    </div>
  );
}
