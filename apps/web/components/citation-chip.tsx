"use client";
import { ExternalLink } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { checkedAgo } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

/** The small numbered chip inside an answer. Hover or focus shows a preview card. */
export function CitationChip({ number, source }: { number: string; source: SourceItem }) {
  const href = source.activity_url || source.url;
  const preview = (
    <div className="space-y-1">
      <p className="text-sm font-medium leading-snug text-foreground">{source.title}</p>
      <p className="text-muted-foreground">
        {source.issuer}
        {source.locator ? ` · ${source.locator}` : ""}
        {checkedAgo(source.checked_at) ? ` · ${checkedAgo(source.checked_at)}` : ""}
      </p>
      {source.snippet && <p className="line-clamp-4 text-foreground/80">{source.snippet}</p>}
      <p className="flex items-center gap-1 pt-0.5 text-accent-text">
        Open source <ExternalLink className="h-3 w-3" />
      </p>
    </div>
  );
  return (
    <Tooltip content={preview} side="top">
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Source ${number}: ${source.title}`}
        className="cite mx-0.5 inline-flex h-[1.35rem] min-w-[1.35rem] -translate-y-px items-center justify-center rounded-md bg-accent-soft px-1 align-baseline text-[0.72rem] font-semibold leading-none text-accent-text no-underline transition-colors duration-150 hover:bg-primary hover:text-primary-foreground"
      >
        {number}
      </a>
    </Tooltip>
  );
}
