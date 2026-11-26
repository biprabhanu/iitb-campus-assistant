"use client";
import { useEffect, useState } from "react";

/** Whole seconds left until `startedAt + seconds`, ticking once a second. 0 when done or when there is no wait. */
export function useCountdown(startedAt: number | undefined, seconds: number | null | undefined): number {
  const total = seconds && seconds > 0 ? seconds : 0;
  const compute = () => (total ? Math.max(0, Math.ceil(total - (Date.now() - (startedAt ?? Date.now())) / 1000)) : 0);
  const [left, setLeft] = useState(compute);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLeft(compute());
    if (!total) return;
    const t = setInterval(() => {
      const v = compute();
      setLeft(v);
      if (v <= 0) clearInterval(t);
    }, 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startedAt, total]);
  return left;
}
