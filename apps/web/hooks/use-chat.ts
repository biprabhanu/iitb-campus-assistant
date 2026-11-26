"use client";
// All chat state in one place: the conversation list, the active chat and the
// streaming of one answer at a time.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearConversations, historyForApi, loadConversations, newId, saveConversations } from "@/lib/history";
import { streamChat, type RequestAuth } from "@/lib/sse";
import type { ChatMessage, Conversation } from "@/lib/types";

const WAKE_AFTER_MS = 3000; // first token slower than this => "Waking up the model"

export interface ChatOptions {
  /** Hosted mode: send the student's own key, keep the request body small. */
  hosted: boolean;
  auth: RequestAuth;
}

export function useChat({ hosted, auth }: ChatOptions) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const convRef = useRef<Conversation[]>([]);
  useEffect(() => {
    convRef.current = conversations; // latest list for event handlers
  }, [conversations]);
  // Latest key and mode, read when a request starts (so a key saved a moment ago is used).
  const optsRef = useRef({ hosted, auth });
  useEffect(() => {
    optsRef.current = { hosted, auth };
  }, [hosted, auth]);

  // Load saved chats once, in the browser (never during server rendering).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setConversations(loadConversations());
    setLoaded(true);
  }, []);

  // Save to localStorage shortly after any change.
  useEffect(() => {
    if (!loaded) return;
    const t = setTimeout(() => saveConversations(conversations), 300);
    return () => clearTimeout(t);
  }, [conversations, loaded]);

  const active = useMemo(() => conversations.find((c) => c.id === activeId) ?? null, [conversations, activeId]);
  const messages = active?.messages ?? [];
  const isStreaming = streamingId !== null;

  const patchMessage = useCallback((convId: string, msgId: string, fn: (m: ChatMessage) => ChatMessage) => {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === convId ? { ...c, updatedAt: Date.now(), messages: c.messages.map((m) => (m.id === msgId ? fn(m) : m)) } : c,
      ),
    );
  }, []);

  /** Run one request and stream the reply into the assistant message `assistantId`. */
  const runTurn = useCallback(
    async (convId: string, assistantId: string, userText: string, priorMessages: ChatMessage[]) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setStreamingId(assistantId);
      setWaking(false);
      let gotToken = false;
      const wakeTimer = setTimeout(() => !gotToken && setWaking(true), WAKE_AFTER_MS);

      try {
        const { hosted: isHosted, auth: requestAuth } = optsRef.current;
        const events = streamChat(
          { message: userText, history: historyForApi(priorMessages, { hosted: isHosted, message: userText }) },
          controller.signal,
          isHosted ? requestAuth : undefined,
        );
        for await (const ev of events) {
          if (controller.signal.aborted) break;
          switch (ev.event) {
            case "tool":
              patchMessage(convId, assistantId, (m) => {
                const steps = [...(m.steps ?? [])];
                const i = steps.findIndex((s) => s.name === ev.data.name);
                if (i >= 0) steps[i] = ev.data;
                else steps.push(ev.data);
                return { ...m, steps };
              });
              break;
            case "sources":
              patchMessage(convId, assistantId, (m) => ({ ...m, sources: ev.data }));
              break;
            case "token":
              if (!gotToken) {
                gotToken = true;
                setWaking(false);
              }
              patchMessage(convId, assistantId, (m) => ({ ...m, content: m.content + ev.data.text }));
              break;
            case "done":
              patchMessage(convId, assistantId, (m) => ({ ...m, done: ev.data, status: "complete" }));
              break;
            case "error":
              patchMessage(convId, assistantId, (m) => ({
                ...m,
                // Name the provider even if the server did not (we know which key we sent).
                error: { ...ev.data, provider: ev.data.provider ?? (optsRef.current.hosted ? optsRef.current.auth.llm?.provider : null) ?? null, at: ev.data.at ?? Date.now() },
                status: "error",
              }));
              break;
            default:
              break; // "status" is not needed by the UI yet
          }
        }
      } finally {
        clearTimeout(wakeTimer);
        setWaking(false);
        setStreamingId(null);
        abortRef.current = null;
        // Anything still marked streaming was stopped by the user or ended without "done".
        patchMessage(convId, assistantId, (m) =>
          m.status === "streaming" ? { ...m, status: controller.signal.aborted ? "stopped" : "complete" } : m,
        );
      }
    },
    [patchMessage],
  );

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || abortRef.current) return;

      const now = Date.now();
      const userMsg: ChatMessage = { id: newId(), role: "user", content: trimmed, createdAt: now };
      const assistantMsg: ChatMessage = { id: newId(), role: "assistant", content: "", createdAt: now, status: "streaming", steps: [] };

      let convId = activeId;
      let prior: ChatMessage[] = [];
      if (convId && convRef.current.some((c) => c.id === convId)) {
        prior = convRef.current.find((c) => c.id === convId)!.messages;
        const id = convId;
        setConversations((p) =>
          p.map((c) => (c.id === id ? { ...c, updatedAt: now, messages: [...c.messages, userMsg, assistantMsg] } : c)),
        );
      } else {
        convId = newId();
        const fresh: Conversation = {
          id: convId,
          title: trimmed.length > 42 ? `${trimmed.slice(0, 40)}…` : trimmed,
          createdAt: now,
          updatedAt: now,
          messages: [userMsg, assistantMsg],
        };
        setConversations((p) => [fresh, ...p]);
        setActiveId(convId);
      }
      void runTurn(convId, assistantMsg.id, trimmed, prior);
    },
    [activeId, runTurn],
  );

  /** Ask the same question again, replacing the chosen answer (and anything after it). */
  const regenerate = useCallback(
    (assistantMessageId: string) => {
      if (!activeId || abortRef.current) return;
      const conv = convRef.current.find((c) => c.id === activeId);
      if (!conv) return;
      const idx = conv.messages.findIndex((m) => m.id === assistantMessageId);
      const userMsg = conv.messages[idx - 1];
      if (idx < 1 || userMsg?.role !== "user") return;

      const prior = conv.messages.slice(0, idx - 1);
      const fresh: ChatMessage = { id: newId(), role: "assistant", content: "", createdAt: Date.now(), status: "streaming", steps: [] };
      setConversations((p) =>
        p.map((c) => (c.id === activeId ? { ...c, updatedAt: Date.now(), messages: [...conv.messages.slice(0, idx), fresh] } : c)),
      );
      void runTurn(activeId, fresh.id, userMsg.content, prior);
    },
    [activeId, runTurn],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setActiveId(null);
  }, []);

  const selectChat = useCallback((id: string) => {
    abortRef.current?.abort();
    setActiveId(id);
  }, []);

  const renameChat = useCallback((id: string, title: string) => {
    const t = title.trim();
    if (!t) return;
    setConversations((p) => p.map((c) => (c.id === id ? { ...c, title: t.slice(0, 80) } : c)));
  }, []);

  const deleteChat = useCallback(
    (id: string) => {
      if (id === activeId) abortRef.current?.abort();
      setConversations((p) => p.filter((c) => c.id !== id));
      if (id === activeId) setActiveId(null);
    },
    [activeId],
  );

  const clearAll = useCallback(() => {
    abortRef.current?.abort();
    setConversations([]);
    setActiveId(null);
    clearConversations();
  }, []);

  const setFeedback = useCallback(
    (msgId: string, value: "up" | "down") => {
      if (!activeId) return;
      patchMessage(activeId, msgId, (m) => ({ ...m, feedback: m.feedback === value ? undefined : value }));
    },
    [activeId, patchMessage],
  );

  return {
    conversations,
    activeId,
    messages,
    loaded,
    isStreaming,
    streamingId,
    waking,
    send,
    stop,
    regenerate,
    newChat,
    selectChat,
    renameChat,
    deleteChat,
    clearAll,
    setFeedback,
  };
}
