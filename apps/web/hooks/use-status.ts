"use client";
// Polls GET /v1/status every 30 s. Also refreshes on demand (e.g. after connecting Moodle).
import { useCallback, useEffect, useState } from "react";
import { getStatus } from "@/lib/api";
import type { StatusResponse } from "@/lib/types";

const POLL_MS = 30_000;

export type StatusState = { status: StatusResponse | null; reachable: boolean; checked: boolean };

export function useStatus() {
  const [state, setState] = useState<StatusState>({ status: null, reachable: true, checked: false });

  const refresh = useCallback(async () => {
    try {
      const status = await getStatus();
      setState({ status, reachable: true, checked: true });
    } catch {
      // Keep the last known status, but mark the server unreachable.
      setState((s) => ({ ...s, reachable: false, checked: true }));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);

  return { ...state, refresh };
}
