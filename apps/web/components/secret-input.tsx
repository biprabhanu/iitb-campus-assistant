"use client";
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";

/** A masked text field with a show/hide button. Never autofilled, never spell-checked. */
export function SecretInput({
  id,
  label,
  value,
  onChange,
  placeholder,
  invalid,
  describedBy,
  autoFocus,
  noun = "key",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  invalid?: boolean;
  describedBy?: string;
  autoFocus?: boolean;
  noun?: string; // "key" or "token": used in the button label
}) {
  const [shown, setShown] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">{label}</label>
      <div
        className={cn(
          "flex h-11 items-center rounded-xl border bg-background transition-[border-color,box-shadow] duration-150 focus-within:border-primary focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_25%,transparent)]",
          invalid ? "border-danger" : "border-input",
        )}
      >
        <input
          id={id}
          type={shown ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          autoFocus={autoFocus}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className="h-full min-w-0 flex-1 bg-transparent pl-3.5 pr-1 font-mono text-sm outline-none placeholder:font-sans placeholder:text-muted-foreground focus-visible:outline-none"
        />
        <button
          type="button"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? `Hide ${noun}` : `Show ${noun}`}
          aria-pressed={shown}
          className="mr-1 inline-flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {shown ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </button>
      </div>
    </div>
  );
}
