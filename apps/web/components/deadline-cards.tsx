"use client";
import { CalendarClock, ExternalLink } from "lucide-react";
import { cn, istDayLabel, istDateTime, relativeDue } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

/** Moodle deadlines grouped by day (in IST). Red when due in under 24 hours. */
export function DeadlineCards({ items }: { items: SourceItem[] }) {
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
    <section aria-label="Deadlines" className="animate-fade-up space-y-4">
      {groups.map((g) => (
        <div key={g.key}>
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <CalendarClock className="h-3.5 w-3.5" aria-hidden /> {g.label}
          </h3>
          <ul className="space-y-2">
            {g.items.map((d) => {
              const rel = relativeDue(d.due_at!);
              return (
                <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border bg-card p-3.5 sm:flex-nowrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {d.course && (
                        <span className="rounded-md bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent-text">{d.course}</span>
                      )}
                      {d.demo && (
                        <span className="rounded-md border border-warning/40 bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning">
                          Demo data
                        </span>
                      )}
                    </div>
                    <p className="mt-1.5 text-[15px] font-medium leading-snug">{d.title}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{istDateTime(d.due_at!)}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5 max-sm:ml-auto">
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                        rel.urgent ? "bg-danger-soft text-danger" : "bg-muted text-foreground",
                      )}
                    >
                      {rel.text}
                    </span>
                    <a
                      href={d.activity_url || d.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs font-medium text-accent-text underline-offset-4 hover:underline"
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
    </section>
  );
}
