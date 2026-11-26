// Conversations live in this browser's localStorage only. Chat text is never sent
// anywhere except POST /v1/chat. Every storage call is wrapped in try/catch because
// storage can be blocked (private windows) or full.
import type { ChatMessage, ChatTurn, Conversation } from "./types";

const KEY = "campuspilot.conversations.v1";
export const MAX_HISTORY_TURNS = 20;

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((c) => c && typeof c.id === "string" && Array.isArray(c.messages))
      .map((c: Conversation) => ({
        ...c,
        // A reply that was streaming when the tab closed can never finish.
        messages: c.messages.map((m) => (m.status === "streaming" ? { ...m, status: "stopped" as const } : m)),
      }));
  } catch {
    return [];
  }
}

/**
 * Cards from the v2 connectors hold mail snippets and grades. They stay in memory only: they are not
 * written to localStorage, so nothing from the student's mail or ASC sits in the browser after a
 * reload. The message remembers that it had cards, and the chat tells the student to ask again.
 */
function withoutCards(c: Conversation): Conversation {
  if (!c.messages.some((m) => m.cards?.length)) return c;
  return { ...c, messages: c.messages.map((m) => (m.cards?.length ? { ...m, cards: undefined, cardsOmitted: true } : m)) };
}

export function saveConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(conversations.map(withoutCards)));
  } catch {
    /* storage full or blocked: the app keeps working in memory */
  }
}

export function clearConversations(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Hosted mode keeps the request body under the server's 8 KB limit (docs/CONTRACT.md §10.2). */
export const HOSTED_HISTORY_TURNS = 6;
export const HOSTED_TURN_CHARS = 600;
export const HOSTED_BODY_BYTES = 7_000; // the limit is 8,192; leave room for the JSON itself

const bytes = (v: unknown) => new TextEncoder().encode(JSON.stringify(v)).length;

/**
 * Finished turns as the API expects them: role, content and (for assistant turns) the answer kind.
 * Local: the last 20 turns. Hosted: the last 6 turns, each trimmed to about 600 characters, and older
 * turns are dropped while the whole body (with `message`) is still too big.
 */
export function historyForApi(messages: ChatMessage[], opts: { hosted?: boolean; message?: string } = {}): ChatTurn[] {
  const finished = messages.filter((m) => m.content.trim() && m.status !== "error");
  const toTurn = (m: ChatMessage, max: number): ChatTurn => {
    const kind = m.role === "assistant" ? (m.done?.answer_kind ?? "answer") : undefined;
    return { role: m.role, content: m.content.slice(0, max), ...(kind ? { kind } : {}) };
  };
  if (!opts.hosted) return finished.slice(-MAX_HISTORY_TURNS).map((m) => toTurn(m, 8000));

  let turns = finished.slice(-HOSTED_HISTORY_TURNS).map((m) => toTurn(m, HOSTED_TURN_CHARS));
  while (turns.length > 0 && bytes({ message: opts.message ?? "", history: turns }) > HOSTED_BODY_BYTES) {
    turns = turns.slice(1); // drop the oldest first
  }
  return turns;
}

export type GroupName = "Today" | "Yesterday" | "Earlier";

/** Sort newest first and bucket into Today / Yesterday / Earlier. */
export function groupConversations(list: Conversation[], now = new Date()): { name: GroupName; items: Conversation[] }[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86_400_000;
  const groups: Record<GroupName, Conversation[]> = { Today: [], Yesterday: [], Earlier: [] };
  for (const c of [...list].sort((a, b) => b.updatedAt - a.updatedAt)) {
    if (c.updatedAt >= startOfToday) groups.Today.push(c);
    else if (c.updatedAt >= startOfToday - day) groups.Yesterday.push(c);
    else groups.Earlier.push(c);
  }
  return (["Today", "Yesterday", "Earlier"] as GroupName[])
    .map((name) => ({ name, items: groups[name] }))
    .filter((g) => g.items.length > 0);
}

// Thumbs up/down are kept on the message itself (no text is attached or sent).
export function newId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}
