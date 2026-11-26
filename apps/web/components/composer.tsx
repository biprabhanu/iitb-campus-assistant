"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

const MAX_CHARS = 2000; // matches the API limit
const MAX_HEIGHT = 200;

/** Pill-shaped composer. Enter sends, Shift+Enter adds a new line, Send turns into Stop. */
export function Composer({
  onSend,
  onStop,
  streaming,
  focusKey,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  focusKey: string | null; // changes when the user switches chat, so we refocus
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to a limit.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  useEffect(() => {
    ref.current?.focus();
  }, [focusKey]);

  function submit() {
    const text = value.trim();
    if (!text || streaming) return;
    onSend(text);
    setValue("");
  }

  const canSend = value.trim().length > 0;

  return (
    <div className="mx-auto w-full max-w-[760px] px-3 sm:px-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex items-end gap-2 rounded-[1.75rem] border bg-card py-2 pl-5 pr-2 shadow-sm transition-colors duration-150 focus-within:border-primary"
      >
        <label htmlFor="composer" className="sr-only">
          Message CampusPilot
        </label>
        <textarea
          id="composer"
          ref={ref}
          rows={1}
          value={value}
          maxLength={MAX_CHARS}
          placeholder="Ask about campus life, rules or deadlines"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          className="scroll-thin max-h-[200px] min-h-[40px] flex-1 resize-none self-center bg-transparent py-2 text-[15px] leading-6 outline-none placeholder:text-muted-foreground focus-visible:outline-none"
        />
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-foreground text-background transition-opacity duration-150 hover:opacity-85"
          >
            <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send message"
            className={cn(
              "flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors duration-150",
              canSend ? "cursor-pointer bg-primary text-primary-foreground hover:bg-[#4338ca]" : "cursor-not-allowed bg-muted text-muted-foreground",
            )}
          >
            <ArrowUp className="h-5 w-5" aria-hidden />
          </button>
        )}
      </form>
      <p className="px-2 pb-3 pt-2 text-center text-[11.5px] leading-snug text-muted-foreground">
        CampusPilot is an independent student prototype, not an official IIT Bombay service. Verify anything important with the official source.
      </p>
    </div>
  );
}
