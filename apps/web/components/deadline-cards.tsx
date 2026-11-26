"use client";
import { CalendarClock, ExternalLink, FlaskConical } from "lucide-react";
import { useAppActions } from "@/components/app-actions";
import { SourceLabel } from "@/components/source-label";
import { Button } from "@/components/ui/button";
import { cn, courseColorIndex, istDayLabel, istDateTime, relativeDue } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

const WEEK_MS = 7 * 86_400_000;

/** "6 deadlines in the next 7 days · 1 due today" */
function summarise(items: SourceItem[]): string {
  const now = Date.now();
  const today = istDayLabel(new Date(now).toISOString(), now).key;
  const total = items.length;
  const inWeek = items.filter((i) => Date.parse(i.due_at!) - now <= WEEK_MS).length;
  const dueToday = items.filter((i) => istDayLabel(i.due_at!, now).key === today).length;
  const noun = (n: number) => `${n} ${n === 1 ? "deadline" : "deadlines"}`;
  let text = inWeek === total ? `${noun(total)} in the next 7 days` : `${noun(total)} · ${inWeek} in the next 7 days`;
  if (dueToday > 0) text += ` · ${dueToday} due today`;
  return text;
}

/** One calm notice for the whole group, instead of a "Demo data" chip on every card. */
function DemoBanner() {
  const { openSettings, hosted } = useAppActions();
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-warning/30 bg-card px-3.5 py-2.5 sm:flex-row sm:items-center sm:gap-3">
      <p className="flex min-w-0 flex-1 items-start gap-2.5 text-sm leading-snug">
        <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
        <span>
          <strong className="font-semibold">Demo data</strong>
          <span className="text-muted-foreground"> — {hosted ? "add your Moodle token or calendar link" : "connect Moodle"} in Settings to see your real deadlines</span>
        </span>
      </p>
      <Button size="sm" variant="outline" onClick={() => openSettings("moodle")} className="self-start max-sm:ml-[26px] sm:self-auto">
        Open Settings
      </Button>
    </div>
  );
}

/** Moodle deadlines grouped by day (in IST). Red when due in under 24 hours. */
export function DeadlineCards({ items, hideSummary = false }: { items: SourceItem[]; hideSummary?: boolean }) {
  if (items.length === 0) return null;
  const sorted = [...items].sort((a, b) => Date.parse(a.due_at!) - Date.parse(b.due_at!));
  const groups: { key: string; label: string; items: SourceItem[] }[] = [];
  for (const item of sorted) {
    const { key, label } = istDayLabel(item.due_at!);
    const g = groups.find((x) => x.key === key);
    if (g) g.items.push(item);
    else groups.push({ key, label, items: [item] });
  }

  return (
    <section aria-label="Deadlines" className="animate-fade-up space-y-3">
      {items.some((i) => i.demo) && <DemoBanner />}
      {!hideSummary && <p className="text-sm font-medium text-foreground">{summarise(sorted)}</p>}
      <div className="space-y-4">
        {groups.map((g) => (
          <div key={g.key}>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden /> {g.label}
            </h3>
            <ul className="space-y-2">
              {g.items.map((d) => {
                const rel = relativeDue(d.due_at!);
                return (
                  <li key={d.id} className="flex items-center gap-x-4 rounded-xl border bg-card px-3.5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {d.course && (
                          <span className={cn("course-chip rounded-md px-2 py-0.5 text-xs font-semibold", `course-${courseColorIndex(d.course)}`)}>
                            {d.course}
                          </span>
                        )}
                        <span className="min-w-0 truncate text-xs text-muted-foreground">{istDateTime(d.due_at!)}</span>
                        <SourceLabel label="Moodle" />
                      </div>
                      <p className="mt-1.5 text-[15px] font-medium leading-snug">{d.title}</p>
                    </div>
                    {/* Desktop: the pill and the link share one line. Mobile: stacked and right-aligned. */}
                    <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-4">
                      <span
                        className={cn(
                          "whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold",
                          rel.urgent ? "bg-danger-soft text-danger" : "bg-muted text-foreground",
                        )}
                      >
                        {rel.text}
                      </span>
                      <a
                        href={d.activity_url || d.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-accent-text underline-offset-4 hover:underline"
                      >
                        Open in Moodle <ExternalLink className="h-3 w-3" aria-hidden />
                      </a>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
