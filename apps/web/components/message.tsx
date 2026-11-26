"use client";
import { memo } from "react";
import { RotateCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { AbstainCard, ClarifyCard, ErrorCard } from "@/components/answer-cards";
import { CopyButton } from "@/components/copy-button";
import { DeadlineCards } from "@/components/deadline-cards";
import { Markdown } from "@/components/markdown";
import { SourcesRow } from "@/components/sources-row";
import { StepsTimeline } from "@/components/steps-timeline";
import { Tooltip } from "@/components/ui/tooltip";
import { cn, prepareCitations } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

/** The student's message: a right-aligned bubble. */
export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="animate-fade-up flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-muted px-4 py-2.5 text-[15px]">{message.content}</p>
    </div>
  );
}

interface AssistantProps {
  message: ChatMessage;
  streaming: boolean; // this very message is streaming now
  waking: boolean;
  busy: boolean; // any message is streaming (disables quick replies and regenerate)
  isLast: boolean;
  onQuickReply: (text: string) => void;
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, value: "up" | "down") => void;
}

function AssistantMessageImpl({ message, streaming, waking, busy, isLast, onQuickReply, onRegenerate, onFeedback }: AssistantProps) {
  const { content, sources = [], steps = [], done, error } = message;
  const citations = done?.citations ?? []; // only validated ids ever become chips
  const deadlines = sources.filter((s) => s.kind === "moodle" && s.due_at);
  const docSources = sources.filter((s) => !(s.kind === "moodle" && s.due_at));
  const kind = done?.answer_kind ?? "answer";
  const waitingForText = streaming && !content;
  const text = <Markdown text={content} citations={citations} sources={sources} />;

  let body: React.ReactNode = null;
  if (kind === "clarify" && done?.follow_up) {
    body = <ClarifyCard followUp={done.follow_up} onPick={onQuickReply} disabled={busy || !isLast} />;
  } else if (kind === "abstain") {
    body = <AbstainCard links={done?.office_links ?? []}>{text}</AbstainCard>;
  } else if (content) {
    body = text;
  }

  return (
    <article className={cn("animate-fade-up space-y-3", streaming && "is-streaming")} aria-label="Assistant answer">
      <StepsTimeline steps={steps} working={streaming} />

      {waking && waitingForText && (
        <p className="flex items-center gap-2 rounded-xl border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-warning" role="status">
          <span className="h-2 w-2 animate-[pulse-dot_1.2s_ease-in-out_infinite] rounded-full bg-warning" aria-hidden />
          Waking up the model, about 10 s
        </p>
      )}
      {waitingForText && !waking && steps.length === 0 && <p className="shimmer-text w-fit text-sm">Thinking…</p>}

      <SourcesRow sources={docSources} citations={citations} />
      <DeadlineCards items={deadlines} />

      <div aria-live="polite" aria-busy={streaming} className="text-[15.5px] leading-relaxed">
        {body}
      </div>

      {message.status === "stopped" && <p className="text-xs italic text-muted-foreground">Stopped.</p>}

      {error && <ErrorCard error={error} onRetry={() => onRegenerate(message.id)} disabled={busy} />}

      {done && done.freshness === "needs_review" && (
        <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
          Some of these sources are over a year old. Check the official page before relying on them.
        </p>
      )}
      {done && done.limitations.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
          {done.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}

      {!streaming && (content || error) && (
        <div
          className={cn(
            "-ml-2 flex items-center gap-0.5 transition-opacity duration-150",
            "[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/msg:opacity-100 [@media(hover:hover)]:focus-within:opacity-100",
            isLast && "[@media(hover:hover)]:opacity-100",
          )}
        >
          {content && <CopyButton text={prepareCitations(content, [])} label="Copy answer" />}
          <Tooltip content="Regenerate" side="top">
            <button
              type="button"
              aria-label="Regenerate answer"
              disabled={busy}
              onClick={() => onRegenerate(message.id)}
              className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCw className="h-4 w-4" />
            </button>
          </Tooltip>
          {(content ? (["up", "down"] as const) : []).map((v) => {
            const Icon = v === "up" ? ThumbsUp : ThumbsDown;
            const on = message.feedback === v;
            return (
              <Tooltip key={v} content={v === "up" ? "Good answer" : "Not helpful"} side="top">
                <button
                  type="button"
                  aria-label={v === "up" ? "Good answer" : "Not helpful"}
                  aria-pressed={on}
                  onClick={() => onFeedback(message.id, v)}
                  className={cn(
                    "inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg transition-colors hover:bg-muted",
                    on ? "text-accent-text" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className={cn("h-4 w-4", on && "fill-current")} />
                </button>
              </Tooltip>
            );
          })}
        </div>
      )}
    </article>
  );
}

export const AssistantMessage = memo(AssistantMessageImpl);
