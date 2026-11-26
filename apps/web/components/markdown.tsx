"use client";
// Renders the model's answer as markdown. Safety: no raw HTML is ever rendered
// (we do not use rehype-raw), and a link is clickable ONLY if its URL is one we gave the
// model (a source, a Moodle activity or an office link). Any other URL the model writes is
// shown as plain text, so a made-up or malicious link can never be clicked.
import { Children, isValidElement, memo, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CitationChip } from "@/components/citation-chip";
import { CopyButton } from "@/components/copy-button";
import { prepareCitations } from "@/lib/utils";
import type { SourceItem } from "@/lib/types";

/** Plain text of a React node tree (used for the code copy button). */
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const code = textOf(children).replace(/\n$/, "");
  const lang = Children.toArray(children)
    .map((c) => (isValidElement<{ className?: string }>(c) ? /language-(\w+)/.exec(c.props.className ?? "")?.[1] : undefined))
    .find(Boolean);
  return (
    <div className="my-4 overflow-hidden rounded-xl border bg-muted/60">
      <div className="flex items-center justify-between border-b px-3 py-1">
        <span className="text-xs text-muted-foreground">{lang ?? "code"}</span>
        <CopyButton text={code} label="Copy code" showLabel />
      </div>
      <pre className="scroll-thin overflow-x-auto p-3 font-mono text-[13px] leading-relaxed">{children}</pre>
    </div>
  );
}

interface MarkdownProps {
  text: string;
  /** Validated citation ids (done.citations). Empty while streaming, so no chips show yet. */
  citations: string[];
  sources: SourceItem[];
  /** More URLs that may be linked, e.g. the office links of an abstention. */
  extraUrls?: string[];
}

/** Compare URLs loosely: ignore a trailing slash and the #fragment. */
function normalizeUrl(url: string): string {
  return url.split("#")[0].replace(/\/+$/, "");
}

function MarkdownImpl({ text, citations, sources, extraUrls = [] }: MarkdownProps) {
  const prepared = prepareCitations(text, citations);
  const allowed = new Set(
    [...sources.flatMap((s) => [s.url, s.activity_url ?? ""]), ...extraUrls].filter(Boolean).map(normalizeUrl),
  );
  return (
    <div className="prose-answer break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (url.startsWith("cite:") ? url : defaultUrlTransform(url))}
        components={{
          a({ href, children }) {
            if (href?.startsWith("cite:")) {
              const source = sources.find((s) => s.id === href.slice(5));
              if (!source) return null;
              return <CitationChip number={textOf(children)} source={source} />;
            }
            if (!href || !allowed.has(normalizeUrl(href))) {
              return <span className="font-medium">{children}</span>; // not a URL we provided
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div className="scroll-thin my-4 overflow-x-auto rounded-xl border">
              <table>{children}</table>
            </div>
          ),
          img: () => null, // never load remote images from model text
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
