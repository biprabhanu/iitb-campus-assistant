"use client";
import { useState } from "react";
import { AlertCircle, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolEvent } from "@/lib/types";

/** Collapsible "what I did" list built from `tool` events. The active step shimmers. */
export function StepsTimeline({ steps, working }: { steps: ToolEvent[]; working: boolean }) {
  const [open, setOpen] = useState(true);
  if (steps.length === 0) return null;
  const active = steps.find((s) => s.state === "start");
  const summary = working && active ? active.label : `${steps.length} ${steps.length === 1 ? "step" : "steps"}`;

  return (
    <div className="text-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-1.5 py-1 text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("h-4 w-4 transition-transform duration-150", !open && "-rotate-90")} aria-hidden />
        <span className={cn(working && active && "shimmer-text")}>{summary}</span>
      </button>
      {open && (
        <ol className="ml-[11px] mt-1 space-y-1.5 border-l pl-4">
          {steps.map((s) => (
            <li key={s.name} className="flex items-center gap-2 text-[13px]">
              {s.state === "done" && <Check className="h-3.5 w-3.5 text-success" aria-label="done" />}
              {s.state === "error" && <AlertCircle className="h-3.5 w-3.5 text-danger" aria-label="failed" />}
              {s.state === "start" && <span className="h-2 w-2 animate-[pulse-dot_1.2s_ease-in-out_infinite] rounded-full bg-primary" aria-label="in progress" />}
              <span className={cn(s.state === "start" ? "shimmer-text" : "text-muted-foreground")}>{s.label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
