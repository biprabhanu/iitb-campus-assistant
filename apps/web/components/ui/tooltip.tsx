"use client";
import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

export const TooltipProvider = ({ children }: { children: React.ReactNode }) => (
  <TooltipPrimitive.Provider delayDuration={150} skipDelayDuration={300}>
    {children}
  </TooltipPrimitive.Provider>
);

/** Wraps one element and shows `content` on hover or keyboard focus. */
export function Tooltip({
  content,
  children,
  side = "bottom",
  collisionPadding = 12,
  className,
}: {
  content: React.ReactNode;
  children: React.ReactElement;
  side?: "top" | "bottom" | "left" | "right";
  /** Keep this many px between the popup and the screen edges (a number, or per side). */
  collisionPadding?: number | Partial<Record<"top" | "bottom" | "left" | "right", number>>;
  className?: string;
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={8}
          collisionPadding={collisionPadding}
          avoidCollisions
          className={cn(
            "animate-fade-up z-50 max-w-[18rem] rounded-xl border bg-card px-3 py-2 text-xs leading-relaxed text-card-foreground shadow-lg",
            className,
          )}
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
