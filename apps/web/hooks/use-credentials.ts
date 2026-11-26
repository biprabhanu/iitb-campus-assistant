"use client";
// The student's own key and Moodle credentials (hosted mode), plus the two "Remember on this device" switches.
// Read once in the browser after mount (never during server rendering).
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  forgetSection,
  loadStored,
  moveSection,
  saveSection,
  type LlmCreds,
  type MoodleCreds,
  type Section,
  type Stored,
} from "@/lib/credentials";

export interface Credentials {
  loaded: boolean;
  llm: LlmCreds | null;
  moodle: MoodleCreds | null;
  remember: Record<Section, boolean>;
  /** Save a section. `remember` decides sessionStorage (false) or localStorage (true). */
  saveLlm: (v: LlmCreds, remember?: boolean) => void;
  saveMoodle: (v: MoodleCreds, remember?: boolean) => void;
  clearLlm: () => void;
  clearMoodle: () => void;
  setRemember: (section: Section, on: boolean) => void;
  /** Clear both sections. (Chat history is cleared by the caller.) */
  forgetAll: () => void;
}

const EMPTY: Stored = { llm: null, moodle: null, remember: { llm: false, moodle: false } };

export function useCredentials(): Credentials {
  const [state, setState] = useState<Stored>(EMPTY);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(loadStored());
    setLoaded(true);
  }, []);

  const saveLlm = useCallback((v: LlmCreds, remember?: boolean) => {
    setState((s) => {
      const r = remember ?? s.remember.llm;
      saveSection("llm", v, r);
      return { ...s, llm: v, remember: { ...s.remember, llm: r } };
    });
  }, []);

  const saveMoodle = useCallback((v: MoodleCreds, remember?: boolean) => {
    setState((s) => {
      const r = remember ?? s.remember.moodle;
      saveSection("moodle", v, r);
      return { ...s, moodle: v, remember: { ...s.remember, moodle: r } };
    });
  }, []);

  const clearLlm = useCallback(() => {
    forgetSection("llm");
    setState((s) => ({ ...s, llm: null }));
  }, []);

  const clearMoodle = useCallback(() => {
    forgetSection("moodle");
    setState((s) => ({ ...s, moodle: null }));
  }, []);

  const setRemember = useCallback((section: Section, on: boolean) => {
    setState((s) => {
      moveSection(section, s[section], on); // moves the saved value to the other storage
      return { ...s, remember: { ...s.remember, [section]: on } };
    });
  }, []);

  const forgetAll = useCallback(() => {
    forgetSection("llm");
    forgetSection("moodle");
    setState(EMPTY);
  }, []);

  return useMemo(
    () => ({ loaded, llm: state.llm, moodle: state.moodle, remember: state.remember, saveLlm, saveMoodle, clearLlm, clearMoodle, setRemember, forgetAll }),
    [loaded, state, saveLlm, saveMoodle, clearLlm, clearMoodle, setRemember, forgetAll],
  );
}
