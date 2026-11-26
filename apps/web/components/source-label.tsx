// The small chip every card wears so the student always sees where an item came from.
import { BookOpen, GraduationCap, Landmark, Mail, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SourceLabel as Label } from "@/lib/types";

const ICONS: Record<Label, LucideIcon> = {
  Webmail: Mail,
  ASC: GraduationCap,
  Moodle: BookOpen,
  "Official page": Landmark,
};

/** Outlined and quiet on purpose: it must not compete with the course chips or the cite chips. */
export function SourceLabel({ label, className }: { label: Label; className?: string }) {
  const Icon = ICONS[label];
  return (
    <span
      data-testid="source-label"
      className={cn(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md border bg-background px-1.5 py-0.5 text-[11px] font-medium leading-none text-muted-foreground",
        className,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}
