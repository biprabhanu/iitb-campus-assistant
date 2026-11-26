"use client";
// A tiny context so deep components (like the demo-data banner) can open Settings
// without passing a callback through every layer.
import { createContext, useContext } from "react";

interface AppActions {
  openSettings: () => void;
}

const AppActionsContext = createContext<AppActions>({ openSettings: () => {} });

export const AppActionsProvider = AppActionsContext.Provider;
export const useAppActions = () => useContext(AppActionsContext);
