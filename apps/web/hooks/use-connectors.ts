"use client";
// The live state of the three v2 connectors (Webmail, ASC, Google Calendar), shared by Settings and
// the event cards. Local mode only: in hosted mode `enabled` is false and nothing is ever requested.
//
// It does not poll. It loads when Settings opens (`refresh`) or when a card needs to know whether
// Google Calendar is connected (`ensureLoaded`), and Settings pushes in each change it makes (`apply`).
import { useCallback, useMemo, useRef, useState } from "react";
import { getConnectors } from "@/lib/api";
import type { ConnectorsResponse, ConnectorStatus } from "@/lib/types";

export type ConnectorsLoad = "idle" | "loading" | "ready" | "unavailable" | "error";

export interface ConnectorsState {
  /** null until the first answer. */
  data: ConnectorsResponse | null;
  load: ConnectorsLoad;
  refresh: () => Promise<void>;
  /** Load once if nothing has been loaded yet (cards call this; it never repeats). */
  ensureLoaded: () => void;
  /** Put one connector's new status (from a login, logout or OTP reply) into the shared state. */
  apply: (status: ConnectorStatus) => void;
}

export function useConnectors(enabled: boolean): ConnectorsState {
  const [data, setData] = useState<ConnectorsResponse | null>(null);
  const [load, setLoad] = useState<ConnectorsLoad>("idle");
  const started = useRef(false);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    started.current = true;
    setLoad((l) => (l === "ready" ? l : "loading"));
    const res = await getConnectors();
    if (res.ok) {
      setData(res.data);
      setLoad("ready");
    } else {
      // 404 = an older API without these endpoints: Settings hides the section instead of showing an error.
      setLoad(res.status === 404 ? "unavailable" : "error");
    }
  }, [enabled]);

  const ensureLoaded = useCallback(() => {
    if (enabled && !started.current) void refresh();
  }, [enabled, refresh]);

  const apply = useCallback((status: ConnectorStatus) => {
    setData((d) => (d ? { ...d, [status.name]: status } : d));
  }, []);

  return useMemo(() => ({ data, load, refresh, ensureLoaded, apply }), [data, load, refresh, ensureLoaded, apply]);
}
