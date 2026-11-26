"use client";
import { useState } from "react";
import { Loader2, Moon, WifiOff } from "lucide-react";
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

/**
 * Hosted mode: the free server sleeps when idle. While it wakes we say so (and keep retrying in the
 * background); if it never answers we offer a Retry button.
 */
export function HostedServerNotice({ state, onRetryWake, onRetryStatus }: { state: StatusState; onRetryWake: () => void; onRetryStatus: () => Promise<void> }) {
  const [checking, setChecking] = useState(false);
  const { wake, reachable, checked } = state;

  if (wake === "waking") {
    return (
      <div className="pb-2">
        <div role="status" data-testid="waking-notice" className="flex items-center gap-2.5 rounded-xl border border-warning/35 bg-card px-3 py-2.5 text-[13px] leading-snug">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-warning" aria-hidden />
          <p className="min-w-0 flex-1 text-muted-foreground">
            <strong className="font-semibold text-foreground">Waking the server</strong>, up to about a minute… You can type your question meanwhile.
          </p>
        </div>
      </div>
    );
  }

  const failed = wake === "failed";
  if (!failed && !(checked && !reachable)) return null;

  async function retry() {
    setChecking(true);
    try {
      if (failed) onRetryWake();
      else await onRetryStatus();
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="pb-2">
      <div role="alert" data-testid="server-failed-notice" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-xl border border-danger/30 bg-card px-3 py-2 text-[13px] leading-snug">
        {failed ? <Moon className="h-4 w-4 shrink-0 text-danger" aria-hidden /> : <WifiOff className="h-4 w-4 shrink-0 text-danger" aria-hidden />}
        <p className="min-w-0 flex-1 basis-56 text-muted-foreground">
          {failed ? (
            <>
              <strong className="font-semibold text-foreground">The server is taking longer than usual to wake.</strong> Give it a moment, then retry.
            </>
          ) : (
            <>
              <strong className="font-semibold text-foreground">Can&apos;t reach the server</strong> — check your connection, then retry. Official links still work.
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
          Retry
        </button>
      </div>
    </div>
  );
}
