"use client";
import { BookOpen, CalendarDays, Clock, Wrench, type LucideIcon } from "lucide-react";

// The four starter questions. The text sent is exactly the label.
const SUGGESTIONS: { label: string; hint: string; icon: LucideIcon; tint: string }[] = [
  { label: "Academic calendar", hint: "Semester dates, exams and holidays", icon: CalendarDays, tint: "text-sky-700 dark:text-sky-300 bg-sky-500/10" },
  { label: "What's due this week?", hint: "Assignments from your Moodle courses", icon: Clock, tint: "text-amber-700 dark:text-amber-300 bg-amber-500/10" },
  { label: "Report a hostel maintenance issue", hint: "Where and how to raise a complaint", icon: Wrench, tint: "text-emerald-700 dark:text-emerald-300 bg-emerald-500/10" },
  { label: "Code of conduct basics", hint: "The DoSA rules in brief", icon: BookOpen, tint: "text-violet-700 dark:text-violet-300 bg-violet-500/10" },
];

/** Greeting plus a 2x2 grid of suggestion cards. Clicking one sends it. */
export function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="relative mx-auto flex min-h-full w-full max-w-[760px] flex-col items-center justify-center px-4 pb-10 pt-6 text-center">
      {/* A soft indigo glow behind the greeting. Static, so nothing to turn off for reduced motion. */}
      <div aria-hidden className="hero-glow pointer-events-none absolute left-1/2 top-[2%] h-[460px] w-[min(820px,100%)] -translate-x-1/2" />
      <h1 className="animate-fade-up relative bg-gradient-to-r from-indigo-600 via-violet-600 to-sky-600 bg-clip-text pb-1 text-balance text-3xl font-semibold leading-tight tracking-tight text-transparent dark:from-indigo-300 dark:via-violet-300 dark:to-sky-300 sm:text-5xl">
        What do you need on campus today?
      </h1>
      <p className="animate-fade-up relative mt-3 max-w-md text-muted-foreground [animation-delay:60ms]">
        Ask about IIT Bombay rules, dates and offices, or check your Moodle deadlines. Answers come with sources.
      </p>
      <div className="relative mt-8 grid w-full grid-cols-1 gap-3 min-[480px]:grid-cols-2">
        {SUGGESTIONS.map(({ label, hint, icon: Icon, tint }, i) => (
          <button
            key={label}
            type="button"
            onClick={() => onPick(label)}
            style={{ animationDelay: `${120 + i * 50}ms` }}
            className="animate-fade-up group flex cursor-pointer items-center gap-3 rounded-2xl border bg-card p-4 text-left shadow-sm transition-all duration-150 hover:-translate-y-0.5 hover:border-primary/60 hover:bg-muted"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tint}`}>
              <Icon className="h-5 w-5" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-medium leading-snug">{label}</span>
              <span className="mt-0.5 block text-[13px] leading-snug text-muted-foreground">{hint}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
