"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { AssistantMessage, UserMessage } from "@/components/message";
import type { ChatMessage } from "@/lib/types";

interface ChatViewProps {
  chatId: string | null;
  messages: ChatMessage[];
  loaded: boolean;
  streamingId: string | null;
  waking: boolean;
  onSend: (text: string) => void;
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, value: "up" | "down") => void;
  /** Shown instead of the suggestion cards when there are no messages (e.g. the hosted key card). */
  emptyContent?: React.ReactNode;
}

const NEAR_BOTTOM_PX = 80;

/** The scrolling message column. Auto-scroll pauses when the user scrolls up. */
export function ChatView({ chatId, messages, loaded, streamingId, waking, onSend, onRegenerate, onFeedback, emptyContent }: ChatViewProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true); // should new content keep us pinned to the bottom?
  const [showJump, setShowJump] = useState(false);
  const emptyRef = useRef(true);
  useEffect(() => {
    emptyRef.current = messages.length === 0;
  }, [messages.length]);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current;
    // No messages: the welcome / key card is showing, so keep its top (the headline) in view.
    if (el) el.scrollTo({ top: emptyRef.current ? 0 : el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stick.current = distance < NEAR_BOTTOM_PX;
    setShowJump(distance > 240);
  }

  // Switching chats: go to the bottom.
  useEffect(() => {
    stick.current = true;
    scrollToBottom();
  }, [chatId, scrollToBottom]);

  // A new message was added (the user just sent something): follow it.
  const count = messages.length;
  useEffect(() => {
    stick.current = true;
    scrollToBottom();
  }, [count, scrollToBottom]);

  // Streaming updates: stay at the bottom unless the user scrolled away.
  useEffect(() => {
    if (stick.current) scrollToBottom();
  }, [messages, waking, scrollToBottom]);

  const empty = loaded && messages.length === 0;
  const lastIndex = messages.length - 1;

  return (
    <div className="relative min-h-0 flex-1">
      <div ref={scrollRef} onScroll={onScroll} className="scroll-thin absolute inset-0 overflow-y-auto overflow-x-hidden" data-testid="scroll-area">
        {empty ? (
          emptyContent ?? <EmptyState onPick={onSend} />
        ) : (
          <div className="mx-auto w-full max-w-[760px] space-y-8 px-4 pb-12 pt-6" role="log" aria-label="Conversation">
            {messages.map((m, i) => (
              <div key={m.id} className="group/msg">
                {m.role === "user" ? (
                  <UserMessage message={m} />
                ) : (
                  <AssistantMessage
                    message={m}
                    streaming={m.id === streamingId}
                    waking={waking && m.id === streamingId}
                    busy={streamingId !== null}
                    isLast={i === lastIndex}
                    onQuickReply={onSend}
                    onRegenerate={onRegenerate}
                    onFeedback={onFeedback}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {showJump && (
        <button
          type="button"
          onClick={() => {
            stick.current = true;
            scrollToBottom(true);
          }}
          className="animate-fade-up absolute bottom-10 left-1/2 z-20 inline-flex -translate-x-1/2 cursor-pointer items-center gap-1.5 rounded-full border bg-card px-3.5 py-1.5 text-sm font-medium shadow-lg transition-colors duration-150 hover:bg-muted"
        >
          <ArrowDown className="h-4 w-4" aria-hidden /> Jump to latest
        </button>
      )}
    </div>
  );
}
