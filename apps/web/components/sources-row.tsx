"use client";
import { FileText } from "lucide-react";
import { checkedAgo } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

/** Horizontally scrolling cards above the answer (Perplexity-style). */
export function SourcesRow({ sources, citations }: { sources: SourceItem[]; citations: string[] }) {
  if (sources.length === 0) return null;
  return (
    <section aria-label="Sources" className="animate-fade-up">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <FileText className="h-3.5 w-3.5" aria-hidden /> Sources
      </h3>
      <ul className="scroll-thin -mx-1 flex snap-x gap-2.5 overflow-x-auto px-1 pb-2">
        {sources.map((s) => {
          const n = citations.indexOf(s.id) + 1;
          return (
            <li key={s.id} className="w-[13.5rem] shrink-0 snap-start">
              <a
                href={s.activity_url || s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex h-full flex-col gap-2 rounded-xl border bg-card p-3 transition-colors duration-150 hover:border-primary/60 hover:bg-muted"
              >
                <span className="line-clamp-2 min-h-[2.6rem] text-sm font-medium leading-snug text-foreground">{s.title}</span>
                <span className="mt-auto flex items-center gap-2">
                  <span
                    aria-hidden
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-soft text-xs font-semibold text-accent-text"
                  >
                    {s.issuer.trim().charAt(0).toUpperCase() || "?"}
                  </span>
                  <span className="min-w-0 text-xs leading-tight">
                    <span className="block truncate text-foreground/90">{s.issuer}</span>
                    <span className="block truncate text-muted-foreground">{checkedAgo(s.checked_at) ?? s.locator ?? ""}</span>
                  </span>
                  {n > 0 && (
                    <span className="ml-auto rounded-md bg-muted px-1.5 text-[0.7rem] font-semibold text-muted-foreground group-hover:bg-card">{n}</span>
                  )}
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
