"use client";
// Renders the model's answer as markdown. Safety: no raw HTML is ever rendered
// (we do not use rehype-raw), and links open in a new tab with noopener.
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
}

function MarkdownImpl({ text, citations, sources }: MarkdownProps) {
  const prepared = prepareCitations(text, citations);
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
