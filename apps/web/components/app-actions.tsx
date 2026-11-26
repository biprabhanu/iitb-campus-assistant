"use client";
// A tiny context so deep components (the demo-data banner, error cards) can open Settings and
// learn the mode without passing props through every layer.
import { createContext, useContext } from "react";
import type { ProviderInfo } from "@/lib/types";

export type SettingsSection = "model" | "moodle";

interface AppActions {
  /** Open Settings. In hosted mode `section` says which part the student needs. */
  openSettings: (section?: SettingsSection) => void;
  hosted: boolean;
  providers: ProviderInfo[];
}

const AppActionsContext = createContext<AppActions>({ openSettings: () => {}, hosted: false, providers: [] });

export const AppActionsProvider = AppActionsContext.Provider;
export const useAppActions = () => useContext(AppActionsContext);
