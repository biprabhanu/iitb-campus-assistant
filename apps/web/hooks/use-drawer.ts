"use client";
// Behaviour for the mobile slide-over drawer: focus moves in when it opens, Tab stays inside,
// Esc closes it, and focus goes back to the button that opened it.
import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

/** true when the screen matches a CSS media query (false while rendering on the server). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", notify);
      return () => mq.removeEventListener("change", notify);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useDrawer(ref: RefObject<HTMLElement | null>, active: boolean, onClose: () => void) {
  // Keep the latest onClose in a ref, so the effect below only re-runs when the drawer opens or closes.
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  useEffect(() => {
    const drawer = ref.current;
    if (!active || !drawer) return;
    const opener = document.activeElement as HTMLElement | null;

    const items = () => Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
    // Wait a moment: the drawer is still "visibility: hidden" in the very first frame of its slide-in.
    const focusTimer = setTimeout(() => items()[0]?.focus(), 50);

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // A dropdown menu inside the drawer handles its own Escape first.
        if (document.querySelector('[role="menu"]')) return;
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const list = items();
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      const current = document.activeElement;
      if (!drawer!.contains(current)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && current === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && current === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [ref, active]);
}
