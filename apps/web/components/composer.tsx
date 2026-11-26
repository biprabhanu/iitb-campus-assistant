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
  notice,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  focusKey: string | null; // changes when the user switches chat, so we refocus
  notice?: React.ReactNode; // slim notice shown just above the box (e.g. "Model offline")
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

  // Focus the box for keyboard and mouse users. On phones we skip it, so the keyboard doesn't pop up uninvited.
  useEffect(() => {
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) ref.current?.focus();
  }, [focusKey]);

  function submit() {
    const text = value.trim();
    if (!text || streaming) return;
    onSend(text);
    setValue("");
  }

  const canSend = value.trim().length > 0;

  return (
    // Solid background, plus a 32 px fade above it so messages never run into the box.
    <div className="relative z-10 bg-background pb-[max(0.5rem,env(safe-area-inset-bottom))] before:pointer-events-none before:absolute before:inset-x-0 before:-top-8 before:h-8 before:bg-gradient-to-t before:from-background before:to-transparent">
      <div className="mx-auto w-full max-w-[760px] px-3 sm:px-4">
        {notice}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="flex items-end gap-2 rounded-[1.75rem] border border-input bg-card py-2 pl-5 pr-2 shadow-[0_1px_2px_rgb(0_0_0/0.08),0_6px_20px_-8px_rgb(0_0_0/0.25)] transition-[border-color,box-shadow] duration-150 focus-within:border-primary focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_28%,transparent),0_6px_20px_-8px_rgb(0_0_0/0.25)]"
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
        <p className="px-2 pb-2 pt-2 text-center text-[11.5px] leading-snug text-muted-foreground">
          <span className="sm:hidden">Independent student prototype · not an official IITB service</span>
          <span className="hidden sm:inline">
            CampusPilot is an independent student prototype, not an official IIT Bombay service. Verify anything important with the official source.
          </span>
        </p>
      </div>
    </div>
  );
}
