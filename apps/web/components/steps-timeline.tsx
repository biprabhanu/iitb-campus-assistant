"use client";
import { useState } from "react";
import { AlertCircle, Check, ChevronDown } from "lucide-react";
import { cn, doneLabel } from "@/lib/utils";
import type { ToolEvent } from "@/lib/types";

/** One step with its status icon. The step that is running shimmers. */
function StepRow({ step }: { step: ToolEvent }) {
  return (
    <li className="flex min-h-6 items-center gap-2 text-[13px]">
      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
        {step.state === "done" && <Check className="h-3.5 w-3.5 text-success" aria-label="done" />}
        {step.state === "error" && <AlertCircle className="h-3.5 w-3.5 text-danger" aria-label="failed" />}
        {step.state === "start" && <span className="h-2 w-2 animate-[pulse-dot_1.2s_ease-in-out_infinite] rounded-full bg-primary" aria-label="in progress" />}
      </span>
      <span className={cn(step.state === "start" ? "shimmer-text" : "text-muted-foreground")}>{step.state === "done" ? doneLabel(step.name, step.label) : step.label}</span>
    </li>
  );
}

/**
 * "What I did", built from `tool` events.
 * - While the answer is being prepared, the steps are listed and the running one shimmers.
 * - Once it is done, they fold into one quiet line ("Searched campus documents") that opens on click.
 */
export function StepsTimeline({ steps, working }: { steps: ToolEvent[]; working: boolean }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;

  if (working) {
    return (
      <ol className="-ml-1.5 space-y-0.5 px-1.5 py-1" aria-label="Progress">
        {steps.map((s) => (
          <StepRow key={s.name} step={s} />
        ))}
      </ol>
    );
  }

  const failed = steps.some((s) => s.state === "error");
  const first = steps[0];
  return (
    <div className="text-sm">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="-ml-1.5 inline-flex min-h-8 cursor-pointer items-center gap-1.5 rounded-lg px-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        {failed ? <AlertCircle className="h-3.5 w-3.5 text-danger" aria-hidden /> : <Check className="h-3.5 w-3.5 text-success" aria-hidden />}
        <span>{doneLabel(first.name, first.label)}</span>
        {steps.length > 1 && <span>· {steps.length} steps</span>}
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform duration-150", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <ol className="-ml-1.5 mt-0.5 space-y-0.5 px-1.5 pb-1">
          {steps.map((s) => (
            <StepRow key={s.name} step={s} />
          ))}
        </ol>
      )}
    </div>
  );
}
