"use client";
// Polls GET /v1/status every 30 s and works out whether the server is local or hosted.
// On a hosted server that may be asleep (free tiers sleep when idle) it also runs the "waking" check:
// /health must answer within 3 s, otherwise we show "Waking the server" and retry with exponential
// backoff for up to about 90 s (docs/CONTRACT.md §10.7).
import { useCallback, useEffect, useRef, useState } from "react";
import { getStatus, pingHealth } from "@/lib/api";
import { API_IS_LOOPBACK, mockCold } from "@/lib/config";
import { cacheDeployMode, cachedDeployMode } from "@/lib/credentials";
import type { DeployMode, StatusResponse } from "@/lib/types";

const POLL_MS = 30_000;
const FIRST_PING_MS = 3_000;
const ATTEMPT_MS = 4_000;
const WAKE_BUDGET_MS = 90_000;

export type Wake = "ready" | "waking" | "failed";
export type StatusState = {
  status: StatusResponse | null;
  reachable: boolean;
  checked: boolean;
  wake: Wake;
  /** null = not known yet (no answer from the server and nothing remembered from an earlier visit). */
  deployMode: DeployMode | null;
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function useStatus() {
  const [state, setState] = useState<StatusState>({ status: null, reachable: true, checked: false, wake: "ready", deployMode: null });
  const run = useRef(0);
  const wakeRef = useRef<Wake>("ready");
  const cancelBoot = useCallback(() => {
    run.current++; // stops a boot loop that is still running
  }, []);
  const setWake = useCallback((wake: Wake) => {
    wakeRef.current = wake;
    setState((s) => ({ ...s, wake }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await getStatus();
      const deployMode: DeployMode = status.deploy_mode ?? "local";
      cacheDeployMode(deployMode);
      setState((s) => ({ ...s, status, reachable: true, checked: true, deployMode }));
    } catch {
      // Keep the last known status, but mark the server unreachable.
      setState((s) => ({ ...s, reachable: false, checked: true }));
    }
  }, []);

  /** Is the server awake? If it doesn't answer quickly, keep trying with growing pauses. */
  const boot = useCallback(async () => {
    const id = ++run.current;
    const alive = () => run.current === id;
    setWake("ready");

    if (await pingHealth(FIRST_PING_MS)) {
      if (alive()) await refresh();
      return;
    }
    if (!alive()) return;
    // A local-mode server on this very computer is not asleep, it is not started: the offline notice
    // covers that. A hosted-mode server (seen on an earlier visit) can sleep wherever it runs.
    if (API_IS_LOOPBACK && cachedDeployMode() !== "hosted" && !mockCold()) {
      await refresh();
      return;
    }
    setWake("waking");
    const budget = mockCold() === "fail" ? 5_000 : WAKE_BUDGET_MS;
    const t0 = Date.now();
    let pause = 1_000;
    while (alive() && Date.now() - t0 < budget) {
      await sleep(pause);
      pause = Math.min(pause * 2, 10_000);
      if (!alive()) return;
      if (await pingHealth(ATTEMPT_MS)) {
        setWake("ready");
        await refresh();
        return;
      }
    }
    if (alive()) {
      setWake("failed");
      setState((s) => ({ ...s, checked: true, reachable: false }));
    }
  }, [refresh, setWake]);

  useEffect(() => {
    // What kind of server was this last time? Makes the first paint right (no flash of the wrong screen).
    const cached = cachedDeployMode();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (cached) setState((s) => (s.deployMode ? s : { ...s, deployMode: cached }));
    void boot();
    const t = setInterval(() => {
      if (wakeRef.current === "ready") void refresh();
    }, POLL_MS);
    return () => {
      clearInterval(t);
      cancelBoot();
    };
  }, [boot, refresh, cancelBoot]);

  return { ...state, refresh, retryWake: boot };
}
