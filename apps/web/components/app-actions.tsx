"use client";
// A tiny context so deep components (the demo-data banner, error cards, event cards) can open Settings
// and learn the mode without passing props through every layer.
import { createContext, useContext } from "react";
import type { ConnectorsState } from "@/hooks/use-connectors";
import type { ProviderInfo } from "@/lib/types";

// "connectors" is the local-mode Connectors section (Webmail, ASC, Google Calendar).
export type SettingsSection = "model" | "moodle" | "connectors";

interface AppActions {
  /** Open Settings. In hosted mode `section` says which part the student needs. */
  openSettings: (section?: SettingsSection) => void;
  hosted: boolean;
  providers: ProviderInfo[];
  /** Live state of the v2 connectors. Idle (and never requested) in hosted mode. */
  connectors: ConnectorsState | null;
}

const AppActionsContext = createContext<AppActions>({ openSettings: () => {}, hosted: false, providers: [], connectors: null });

export const AppActionsProvider = AppActionsContext.Provider;
export const useAppActions = () => useContext(AppActionsContext);
