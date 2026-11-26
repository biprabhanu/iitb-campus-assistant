"use client";
// The welcome card shown in hosted mode until a key is saved. It replaces the empty state.
import { useState } from "react";
import { Lock } from "lucide-react";
import { KeyGuide, ProviderNote, ProviderSelect, TestButton, TestResult, type TestOutcome } from "@/components/key-fields";
import { SecretInput } from "@/components/secret-input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { checkLlm } from "@/lib/api";
import { validateKey, type LlmCreds } from "@/lib/credentials";
import { cn } from "@/lib/utils";
import type { ProviderInfo } from "@/lib/types";

export function llmOutcome(r: { ok: boolean; message?: string | null; retry_after_s?: number | null }, label: string): TestOutcome {
  if (r.ok) return { ok: true, text: `Your ${label} key works.` };
  const base = r.message || `${label} did not accept the key.`;
  const wait = r.retry_after_s && !/\d/.test(base) ? ` Try again in ${r.retry_after_s} s.` : "";
  return { ok: false, text: base + wait };
}

export function KeyCard({
  providers,
  onSave,
  initialRemember,
}: {
  providers: ProviderInfo[];
  onSave: (creds: LlmCreds, remember: boolean) => void;
  initialRemember: boolean;
}) {
  const defaultId = (providers.find((p) => p.recommended) ?? providers[0])?.id ?? "groq";
  const [provider, setProvider] = useState(defaultId);
  const [key, setKey] = useState("");
  const [remember, setRemember] = useState(initialRemember);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestOutcome | null>(null);
  // The guide starts open only on screens big enough to also show the Save button without scrolling;
  // the card only renders in the browser, so reading the viewport here is safe.
  const [wide] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 640px) and (min-height: 1000px)").matches,
  );

  const chosen = providers.find((p) => p.id === provider);
  const label = chosen?.label ?? provider;

  function edit<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setResult(null);
      setError(null);
    };
  }

  async function test() {
    const problem = validateKey(key);
    if (problem) return setError(problem);
    setBusy(true);
    setResult(null);
    const r = await checkLlm({ provider, key: key.trim() });
    setBusy(false);
    setResult(llmOutcome(r, label));
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    const problem = validateKey(key);
    if (problem) return setError(problem);
    onSave({ provider, key: key.trim() }, remember);
    setKey(""); // the card is about to disappear; do not keep the key in this component
  }

  return (
    <div className="relative mx-auto flex min-h-full w-full max-w-[560px] flex-col items-center px-4 pb-10 pt-6">
      <div aria-hidden className="hero-glow pointer-events-none absolute left-1/2 top-[2%] h-[420px] w-[min(760px,100%)] -translate-x-1/2" />
      <section aria-labelledby="key-card-h" data-testid="key-card" className="animate-fade-up relative my-auto w-full">
        <h1
          id="key-card-h"
          className="bg-gradient-to-r from-indigo-600 via-violet-600 to-sky-600 bg-clip-text pb-1 text-center text-balance text-[1.7rem] font-semibold leading-tight tracking-tight text-transparent dark:from-indigo-300 dark:via-violet-300 dark:to-sky-300 sm:text-[2.1rem]"
        >
          CampusPilot runs on your own AI key. It&apos;s free with Groq.
        </h1>
        <p className="mx-auto mt-3 max-w-md text-balance text-center text-muted-foreground">
          Pick a provider, paste a key, and ask away. Answers still come with official sources.
        </p>

        <form onSubmit={save} className="mt-7 space-y-4 rounded-2xl border bg-card p-4 shadow-sm sm:p-5" noValidate>
          <ProviderSelect id="kc-provider" value={provider} onChange={edit(setProvider)} providers={providers} />
          <ProviderNote provider={chosen} />
          <SecretInput
            id="kc-key"
            label={`${label} API key`}
            value={key}
            onChange={edit(setKey)}
            placeholder="Paste your key"
            invalid={!!error}
            describedBy={error ? "kc-error" : undefined}
          />
          {error && (
            <p id="kc-error" role="alert" className="-mt-2 text-sm text-danger">
              {error}
            </p>
          )}
          <KeyGuide provider={chosen} defaultOpen={provider === "groq" && wide} key={provider} />
          <Switch
            id="kc-remember"
            checked={remember}
            onCheckedChange={setRemember}
            label="Remember on this device"
            description={remember ? "Kept in this browser until you forget it." : "Off: forgotten when you close this tab."}
          />
          <p className="flex items-start gap-2 text-xs leading-snug text-muted-foreground">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>Your key stays in your browser. It is sent only with your own requests and the server never stores it.</span>
          </p>
          <TestResult id="kc-result" result={result} />
          <div className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end")}>
            <TestButton busy={busy} onClick={test} disabled={!key.trim()} />
            <Button type="submit" variant="primary" disabled={!key.trim() || busy}>
              Save and start chatting
            </Button>
          </div>
        </form>

      </section>
    </div>
  );
}
