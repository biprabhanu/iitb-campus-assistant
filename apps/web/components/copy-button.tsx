"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

/** Copies `text` to the clipboard and shows a check mark for a moment. */
export function CopyButton({ text, label = "Copy", className, showLabel = false }: { text: string; label?: string; className?: string; showLabel?: boolean }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: nothing to do */
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? "Copied" : label}
      className={cn(
        "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground",
        className,
      )}
    >
      {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
      {showLabel && <span>{copied ? "Copied" : label}</span>}
    </button>
  );
}
