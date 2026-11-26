"use client";
import { ExternalLink } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { checkedAgo, domainOf } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

// Keep the preview clear of the sticky header (top) and the composer (bottom) so it flips
// to the other side instead of covering them. It opens below the chip first, so it does
// not sit on top of the sources row above the answer.
const PREVIEW_PADDING = { top: 72, bottom: 150, left: 12, right: 12 };

/** The small numbered chip inside an answer. Hover or keyboard focus shows a preview card. */
export function CitationChip({ number, source }: { number: string; source: SourceItem }) {
  const href = source.activity_url || source.url;
  const domain = domainOf(source.url);
  const meta = [source.issuer, domain, source.locator].filter(Boolean).join(" · ");
  const preview = (
    <div className="space-y-1">
      <p className="text-sm font-medium leading-snug text-foreground">{source.title}</p>
      <p className="text-muted-foreground">
        {meta}
        {checkedAgo(source.checked_at) ? ` · ${checkedAgo(source.checked_at)}` : ""}
      </p>
      {source.snippet && <p className="line-clamp-4 text-foreground/80">{source.snippet}</p>}
      <p className="flex items-center gap-1 pt-0.5 text-accent-text">
        Open source <ExternalLink className="h-3 w-3" aria-hidden />
      </p>
    </div>
  );
  return (
    <Tooltip content={preview} side="bottom" collisionPadding={PREVIEW_PADDING}>
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Source ${number}: ${source.title}`}
        className="cite cite-chip mx-0.5 -translate-y-px align-baseline"
      >
        {number}
      </a>
    </Tooltip>
  );
}
