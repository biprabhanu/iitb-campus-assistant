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

export function saveConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(conversations));
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

/** The last 20 finished turns, as the API expects them (role + content only). */
export function historyForApi(messages: ChatMessage[]): ChatTurn[] {
  return messages
    .filter((m) => m.content.trim() && m.status !== "error")
    .slice(-MAX_HISTORY_TURNS)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 8000) }));
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
