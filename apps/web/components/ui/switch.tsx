"use client";
import { cn } from "@/lib/utils";

/** An on/off switch. Space and Enter toggle it; the label is read with the state. */
export function Switch({
  checked,
  onCheckedChange,
  id,
  label,
  description,
}: {
  checked: boolean;
  onCheckedChange: (on: boolean) => void;
  id: string;
  label: string;
  description?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        role="switch"
        id={id}
        aria-checked={checked}
        aria-describedby={description ? `${id}-d` : undefined}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          "relative mt-0.5 inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-150",
          checked ? "border-primary bg-primary" : "border-input bg-muted",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "inline-block h-[18px] w-[18px] rounded-full bg-white shadow transition-transform duration-150",
            checked ? "translate-x-[18px]" : "translate-x-[2px]",
          )}
        />
      </button>
      <div className="min-w-0">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium leading-6">{label}</label>
        {description && <p id={`${id}-d`} className="text-xs leading-snug text-muted-foreground">{description}</p>}
      </div>
    </div>
  );
}
