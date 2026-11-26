"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { FileText } from "lucide-react";
import { checkedAgo, cn, domainOf } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

const COLLAPSED_COUNT = 4; // show this many cards, then a "+N" card

function SourceCard({ source, number }: { source: SourceItem; number: number }) {
  const domain = domainOf(source.url);
  const ago = checkedAgo(source.checked_at);
  return (
    <a
      href={source.activity_url || source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex h-full flex-col gap-2 rounded-xl border bg-card p-3 transition-colors duration-150 hover:border-primary/60 hover:bg-muted"
    >
      <span className="flex items-start gap-2.5">
        <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-xs font-semibold text-accent-text">
          {source.issuer.trim().charAt(0).toUpperCase() || "?"}
        </span>
        <span className="line-clamp-2 text-sm font-medium leading-[1.35] text-foreground">{source.title}</span>
      </span>
      <span className="mt-auto block min-w-0 text-xs leading-snug">
        <span className="block truncate text-foreground/90">
          {source.issuer}
          {domain && <span className="text-muted-foreground"> · {domain}</span>}
        </span>
        <span className="mt-0.5 flex items-center justify-between gap-2 text-muted-foreground">
          <span className="truncate">{ago ?? source.locator ?? ""}</span>
          {number > 0 && <span className="cite-chip shrink-0" aria-label={`Cited as source ${number}`}>{number}</span>}
        </span>
      </span>
    </a>
  );
}

/** Horizontally scrolling cards above the answer (Perplexity-style). */
export function SourcesRow({ sources, citations }: { sources: SourceItem[]; citations: string[] }) {
  const listRef = useRef<HTMLUListElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [fade, setFade] = useState({ left: false, right: false });

  // Show a fade at an edge only while there is more to scroll in that direction.
  const measure = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    setFade({ left: el.scrollLeft > 4, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
  }, []);

  useEffect(() => {
    measure();
    const el = listRef.current;
    if (!el) return;
    const obs = new ResizeObserver(measure);
    obs.observe(el);
    return () => obs.disconnect();
  }, [measure, sources.length, expanded]);

  if (sources.length === 0) return null;
  const hidden = expanded ? 0 : Math.max(0, sources.length - COLLAPSED_COUNT);
  const shown = hidden ? sources.slice(0, COLLAPSED_COUNT) : sources;

  return (
    <section aria-label="Sources" className="animate-fade-up">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <FileText className="h-3.5 w-3.5" aria-hidden /> Sources
      </h3>
      <div className="relative">
        <ul
          ref={listRef}
          onScroll={measure}
          className="scroll-thin flex snap-x snap-mandatory scroll-px-1 gap-2.5 overflow-x-auto p-1 pb-2.5 -m-1"
        >
          {shown.map((s) => (
            <li key={s.id} className="w-[15rem] shrink-0 snap-start">
              <SourceCard source={s} number={citations.indexOf(s.id) + 1} />
            </li>
          ))}
          {hidden > 0 && (
            <li className="shrink-0 snap-start">
              <button
                type="button"
                onClick={() => setExpanded(true)}
                aria-label={`Show ${hidden} more sources`}
                className="flex h-full min-w-16 cursor-pointer items-center justify-center rounded-xl border border-dashed bg-card px-4 text-sm font-semibold text-muted-foreground transition-colors duration-150 hover:border-primary/60 hover:text-foreground"
              >
                +{hidden}
              </button>
            </li>
          )}
        </ul>
        {/* Soft edges that hint there is more to scroll */}
        <span aria-hidden className={cn("pointer-events-none absolute inset-y-0 -left-1 w-8 bg-gradient-to-r from-background to-transparent transition-opacity duration-150", fade.left ? "opacity-100" : "opacity-0")} />
        <span aria-hidden className={cn("pointer-events-none absolute inset-y-0 -right-1 w-8 bg-gradient-to-l from-background to-transparent transition-opacity duration-150", fade.right ? "opacity-100" : "opacity-0")} />
      </div>
    </section>
  );
}
