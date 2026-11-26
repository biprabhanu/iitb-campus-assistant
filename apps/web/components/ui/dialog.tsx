"use client";
import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;

export function DialogContent({
  className,
  title,
  description,
  initialFocusId,
  children,
}: {
  className?: string;
  title: string;
  description?: string;
  /** id of the element to focus when the dialog opens (default: the first focusable one). */
  initialFocusId?: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="animate-fade-up fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
      <DialogPrimitive.Content
        onOpenAutoFocus={
          initialFocusId
            ? (e) => {
                const el = document.getElementById(initialFocusId);
                if (el) {
                  e.preventDefault();
                  el.focus();
                }
              }
            : undefined
        }
        className={cn(
          "animate-fade-up fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border bg-background p-5 shadow-2xl sm:p-6",
          className,
        )}
      >
        <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
        <DialogPrimitive.Description className="mt-1 text-sm text-muted-foreground">
          {description ?? ""}
        </DialogPrimitive.Description>
        <DialogPrimitive.Close
          aria-label="Close"
          className="absolute right-3 top-3 inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </DialogPrimitive.Close>
        <div className="mt-5">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
