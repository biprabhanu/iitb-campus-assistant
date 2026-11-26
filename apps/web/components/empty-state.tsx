"use client";
import { BookOpen, CalendarDays, Clock, Wrench, type LucideIcon } from "lucide-react";

// The four starter questions. The text sent is exactly the label.
const SUGGESTIONS: { label: string; icon: LucideIcon; tint: string }[] = [
  { label: "Academic calendar", icon: CalendarDays, tint: "text-sky-600 dark:text-sky-300 bg-sky-500/10" },
  { label: "What's due this week?", icon: Clock, tint: "text-amber-700 dark:text-amber-300 bg-amber-500/10" },
  { label: "Report a hostel maintenance issue", icon: Wrench, tint: "text-emerald-700 dark:text-emerald-300 bg-emerald-500/10" },
  { label: "Code of conduct basics", icon: BookOpen, tint: "text-violet-700 dark:text-violet-300 bg-violet-500/10" },
];

/** Greeting plus a 2x2 grid of suggestion cards. Clicking one sends it. */
export function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-[760px] flex-col items-center justify-center px-4 pb-8 pt-6 text-center">
      <h1 className="animate-fade-up bg-gradient-to-r from-indigo-600 via-violet-600 to-sky-600 bg-clip-text pb-1 text-balance text-3xl font-semibold leading-tight tracking-tight text-transparent dark:from-indigo-300 dark:via-violet-300 dark:to-sky-300 sm:text-5xl">
        What do you need on campus today?
      </h1>
      <p className="animate-fade-up mt-3 max-w-md text-muted-foreground [animation-delay:60ms]">
        Ask about IIT Bombay rules, dates and offices, or check your Moodle deadlines. Answers come with sources.
      </p>
      <div className="mt-8 grid w-full grid-cols-1 gap-3 min-[480px]:grid-cols-2">
        {SUGGESTIONS.map(({ label, icon: Icon, tint }, i) => (
          <button
            key={label}
            type="button"
            onClick={() => onPick(label)}
            style={{ animationDelay: `${120 + i * 50}ms` }}
            className="animate-fade-up group flex cursor-pointer items-center gap-3 rounded-2xl border bg-card p-4 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-primary/60 hover:bg-muted"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tint}`}>
              <Icon className="h-5 w-5" aria-hidden />
            </span>
            <span className="text-[15px] font-medium leading-snug">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
