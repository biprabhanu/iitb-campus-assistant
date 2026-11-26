"use client";
// Small pieces shared by the welcome key card and the hosted Settings: provider dropdown,
// the 3-step guide, the provider note and the inline result of a "Test" button.
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Info, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { hostOf, safeHttpsUrl } from "@/lib/providers";
import { cn } from "@/lib/utils";
import type { ProviderInfo } from "@/lib/types";

export function ProviderSelect({
  id,
  value,
  onChange,
  providers,
}: {
  id: string;
  value: string;
  onChange: (id: string) => void;
  providers: ProviderInfo[];
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium">AI provider</label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-11 w-full cursor-pointer appearance-none rounded-xl border border-input bg-background pl-3.5 pr-10 text-sm outline-none transition-[border-color,box-shadow] duration-150 focus:border-primary focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_25%,transparent)]"
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
              {p.recommended ? " (Recommended, free)" : p.free_tier ? " (free tier)" : ""}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      </div>
    </div>
  );
}

/** One line about the chosen provider. The Gemini privacy note is drawn as a warning. */
export function ProviderNote({ provider }: { provider: ProviderInfo | undefined }) {
  if (!provider?.note) return null;
  const warn = provider.id === "gemini";
  const Icon = warn ? AlertTriangle : Info;
  return (
    <p
      className={cn(
        "flex items-start gap-2 rounded-lg px-3 py-2 text-[13px] leading-snug",
        warn ? "bg-warning-soft text-foreground" : "text-muted-foreground",
      )}
    >
      <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", warn ? "text-warning" : "text-muted-foreground")} aria-hidden />
      <span>{provider.note}</span>
    </p>
  );
}

/** Collapsible "how do I get a key" guide with the provider's official link. */
export function KeyGuide({ provider, defaultOpen = false }: { provider: ProviderInfo | undefined; defaultOpen?: boolean }) {
  const url = safeHttpsUrl(provider?.key_url);
  const name = provider?.label ?? "your provider";
  const host = hostOf(url);
  const free = provider?.recommended || provider?.free_tier;
  return (
    <details open={defaultOpen} className="group rounded-xl border bg-background/60 [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-3.5 py-2.5 text-sm font-medium outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <span>How do I get {free ? "a free " : "a "}{name} key?</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden />
      </summary>
      <ol className="space-y-2.5 border-t px-3.5 pb-3.5 pt-3 text-sm">
        {[
          <>
            Open{" "}
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-accent-text underline underline-offset-4">
                {host}
                <ExternalLink className="h-3 w-3" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ) : (
              <span className="font-medium">the {name} console</span>
            )}{" "}
            and sign in.
          </>,
          <>
            Go to <strong className="font-semibold">API Keys</strong> and choose <strong className="font-semibold">Create API key</strong>.
          </>,
          <>Copy the key and paste it in the box above.</>,
        ].map((step, i) => (
          <li key={i} className="flex gap-3">
            <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-text" aria-hidden>
              {i + 1}
            </span>
            <span className="min-w-0 leading-snug text-muted-foreground [&_strong]:text-foreground">{step}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

export interface TestOutcome {
  ok: boolean;
  text: string;
}

/** The inline result of a Test button. Success is polite, failure is an alert. */
export function TestResult({ id, result }: { id: string; result: TestOutcome | null }) {
  if (!result) return null;
  const Icon = result.ok ? CheckCircle2 : AlertTriangle;
  return (
    <p
      id={id}
      role={result.ok ? "status" : "alert"}
      className={cn(
        "animate-fade-up flex items-start gap-2 rounded-lg px-3 py-2 text-sm leading-snug",
        result.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger",
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">{result.text}</span>
    </p>
  );
}

export function TestButton({ busy, disabled, onClick, label = "Test key" }: { busy: boolean; disabled?: boolean; onClick: () => void; label?: string }) {
  return (
    <Button variant="outline" onClick={onClick} disabled={busy || disabled}>
      {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {busy ? "Testing…" : label}
    </Button>
  );
}
