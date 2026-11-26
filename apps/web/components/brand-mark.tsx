import { Compass } from "lucide-react";
import { cn } from "@/lib/utils";

/** The CampusPilot mark: a compass in an indigo rounded square. */
export function BrandMark({ className, iconClassName }: { className?: string; iconClassName?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-flex shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm", className)}
    >
      <Compass className={cn("h-4 w-4", iconClassName)} />
    </span>
  );
}
