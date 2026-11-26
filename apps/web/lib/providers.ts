// Provider facts the UI needs. The live list comes from GET /v1/status (`providers`);
// this table is only a fallback for labels when the list is not there yet.
import type { ProviderInfo } from "./types";

export const FALLBACK_PROVIDERS: ProviderInfo[] = [
  { id: "groq", label: "Groq", router_model: "llama-3.1-8b-instant", answer_model: "llama-3.3-70b-versatile", key_url: "https://console.groq.com/keys", recommended: true, free_tier: true, note: "Recommended. Free, no card needed." },
  { id: "gemini", label: "Google Gemini", router_model: "gemini-2.5-flash-lite", answer_model: "gemini-2.5-flash", key_url: "https://aistudio.google.com/app/apikey", free_tier: true, note: "Google's free tier may use your prompts to improve its products; Groq is recommended." },
  { id: "openai", label: "OpenAI", router_model: "gpt-4.1-nano", answer_model: "gpt-4.1-mini", key_url: "https://platform.openai.com/api-keys", note: "Paid; billed to your OpenAI account." },
  { id: "openrouter", label: "OpenRouter", router_model: "meta-llama/llama-3.3-70b-instruct:free", answer_model: "meta-llama/llama-3.3-70b-instruct:free", key_url: "https://openrouter.ai/settings/keys", note: "Free models have low daily limits." },
];

/** The provider list to show: the server's when it sent one, else the fallback. */
export function providerList(fromServer?: ProviderInfo[]): ProviderInfo[] {
  return fromServer && fromServer.length > 0 ? fromServer : FALLBACK_PROVIDERS;
}

export function providerLabel(id: string | null | undefined, list: ProviderInfo[]): string {
  if (!id) return "your AI provider";
  return list.find((p) => p.id === id)?.label ?? FALLBACK_PROVIDERS.find((p) => p.id === id)?.label ?? id;
}

/** Short label for the header pill ("Groq", "Gemini"). */
export function shortProviderLabel(id: string, list: ProviderInfo[]): string {
  return providerLabel(id, list).replace(/^Google /, "");
}

/** Only ever link to an https address; the list is ours, but a link is cheap to guard. */
export function safeHttpsUrl(url: string | undefined | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** "console.groq.com" for the guide text. */
export function hostOf(url: string | null): string {
  try {
    return url ? new URL(url).host : "";
  } catch {
    return "";
  }
}
