"use client";
import { useState } from "react";
import { Loader2, WifiOff } from "lucide-react";
import type { StatusState } from "@/hooks/use-status";

/** Slim notice above the composer when /v1/status says the model (or the server) is offline. */
export function OfflineNotice({ state, onRetry }: { state: StatusState; onRetry: () => Promise<void> }) {
  const [checking, setChecking] = useState(false);
  const { status, reachable, checked } = state;
  const offline = checked && (!reachable || (status !== null && !status.model_online));
  if (!offline) return null;

  async function retry() {
    setChecking(true);
    try {
      await onRetry();
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="pb-2">
      <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-danger/30 bg-card px-3 py-2 text-[13px] leading-snug">
        <WifiOff className="h-4 w-4 shrink-0 text-danger" aria-hidden />
        <p className="min-w-0 flex-1 basis-56 text-muted-foreground">
          {reachable ? (
            <>
              <strong className="font-semibold text-foreground">Model offline</strong> — answers will fail until the tunnel is back. Official links still work.
            </>
          ) : (
            <>
              <strong className="font-semibold text-foreground">Server unreachable</strong> — start the CampusPilot API on this computer. Official links still work.
            </>
          )}
        </p>
        <button
          type="button"
          onClick={retry}
          disabled={checking}
          className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-lg border border-input px-2.5 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-wait disabled:opacity-70"
        >
          {checking && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
          {checking ? "Checking…" : "Retry status check"}
        </button>
      </div>
    </div>
  );
}
