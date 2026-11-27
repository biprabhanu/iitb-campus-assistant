"use client";
// Settings body for hosted mode. Same layout as the local Settings: AI key, Moodle, Connectors (a guide
// only), Model status, then the data kept in this browser with "Forget everything".
import { useState } from "react";
import { ShieldCheck, Trash2 } from "lucide-react";
import { KeyGuide, ProviderNote, ProviderSelect, TestButton, TestResult, type TestOutcome } from "@/components/key-fields";
import { llmOutcome } from "@/components/key-card";
import { HostedConnectorsGuide } from "@/components/hosted-connectors-guide";
import { SecretInput } from "@/components/secret-input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { checkLlm, checkMoodle } from "@/lib/api";
import { parseMoodleInput, validateKey, validateModel, MOODLE_ICAL_PREFIX } from "@/lib/credentials";
import { cn } from "@/lib/utils";
import type { Credentials } from "@/hooks/use-credentials";
import type { StatusState } from "@/hooks/use-status";
import type { ProviderInfo } from "@/lib/types";

function SectionHeading({ id, children, note }: { id: string; children: React.ReactNode; note?: string }) {
  return (
    <div>
      <h3 id={id} className="text-sm font-semibold">{children}</h3>
      {note && <p className="mt-1 text-sm text-muted-foreground">{note}</p>}
    </div>
  );
}

function ModelSection({ creds, providers }: { creds: Credentials; providers: ProviderInfo[] }) {
  const saved = creds.llm;
  const [provider, setProvider] = useState(saved?.provider ?? (providers.find((p) => p.recommended) ?? providers[0])?.id ?? "groq");
  const [key, setKey] = useState(saved?.key ?? "");
  const [model, setModel] = useState(saved?.model ?? "");
  const [advanced, setAdvanced] = useState(!!saved?.model);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);

  const chosen = providers.find((p) => p.id === provider);
  const label = chosen?.label ?? provider;
  const dirty = !saved || saved.provider !== provider || saved.key !== key.trim() || (saved.model ?? "") !== model.trim();

  function touch() {
    setResult(null);
    setError(null);
  }

  /** Validate the draft; returns the creds, or null after showing what is wrong. */
  function draft() {
    const k = validateKey(key);
    const m = validateModel(model);
    setError(k);
    setModelError(m);
    if (k || m) return null;
    return { provider, key: key.trim(), ...(model.trim() ? { model: model.trim() } : {}) };
  }

  async function test() {
    const c = draft();
    if (!c) return;
    setBusy(true);
    setResult(null);
    const r = await checkLlm(c);
    setBusy(false);
    setResult(llmOutcome(r, label));
  }

  function save() {
    const c = draft();
    if (!c) return;
    creds.saveLlm(c);
    setResult({ ok: true, text: "Saved." });
  }

  return (
    <section aria-labelledby="hs-model-h">
      <SectionHeading id="hs-model-h" note="CampusPilot answers with your own AI key. Groq is free and recommended.">
        AI key
      </SectionHeading>
      <div className="mt-3 space-y-4">
      <ProviderSelect id="hs-provider" value={provider} onChange={(v) => (setProvider(v), touch())} providers={providers} />
      <ProviderNote provider={chosen} />
      <SecretInput
        id="hs-key"
        label={`${label} API key`}
        value={key}
        onChange={(v) => (setKey(v), touch())}
        placeholder="Paste your key"
        invalid={!!error}
        describedBy={error ? "hs-key-error" : undefined}
      />
      {error && <p id="hs-key-error" role="alert" className="-mt-2 text-sm text-danger">{error}</p>}
      <KeyGuide provider={chosen} key={provider} />

      <div>
        <button
          type="button"
          onClick={() => setAdvanced((a) => !a)}
          aria-expanded={advanced}
          aria-controls="hs-advanced"
          className="cursor-pointer text-sm font-medium text-accent-text underline-offset-4 hover:underline"
        >
          Advanced: use a different model
        </button>
        {advanced && (
          <div id="hs-advanced" className="mt-2.5 space-y-1.5">
            <label htmlFor="hs-model" className="block text-sm font-medium">Model override <span className="font-normal text-muted-foreground">(optional)</span></label>
            <input
              id="hs-model"
              value={model}
              onChange={(e) => (setModel(e.target.value), setModelError(null), setResult(null))}
              placeholder={chosen?.answer_model ?? "model name"}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={!!modelError || undefined}
              aria-describedby="hs-model-hint"
              className={cn(
                "h-11 w-full rounded-xl border bg-background px-3.5 font-mono text-sm outline-none transition-[border-color,box-shadow] duration-150 placeholder:font-sans placeholder:text-muted-foreground focus:border-primary focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_25%,transparent)]",
                modelError ? "border-danger" : "border-input",
              )}
            />
            <p id="hs-model-hint" className={cn("text-xs leading-snug", modelError ? "text-danger" : "text-muted-foreground")} role={modelError ? "alert" : undefined}>
              {modelError ?? `Used for every step. Leave empty for the defaults${chosen ? ` (${chosen.router_model}, ${chosen.answer_model})` : ""}.`}
            </p>
          </div>
        )}
      </div>

      <Switch
        id="hs-remember-llm"
        checked={creds.remember.llm}
        onCheckedChange={(on) => creds.setRemember("llm", on)}
        label="Remember on this device"
        description={creds.remember.llm ? "Kept in this browser until you forget it." : "Off: forgotten when you close this tab."}
      />
      <TestResult id="hs-result" result={result} />
      <div className="flex flex-wrap gap-2">
        <TestButton busy={busy} onClick={test} disabled={!key.trim()} />
        <Button variant="primary" onClick={save} disabled={busy || !key.trim() || !dirty}>Save key</Button>
        {saved && (
          <Button variant="ghost" onClick={() => (creds.clearLlm(), setKey(""), setModel(""), setResult({ ok: true, text: "Key removed from this browser." }))}>
            Remove key
          </Button>
        )}
      </div>
      </div>
    </section>
  );
}

function MoodleSection({ creds }: { creds: Credentials }) {
  const saved = creds.moodle;
  const [value, setValue] = useState(saved?.token ?? saved?.icalUrl ?? "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const savedValue = saved?.token ?? saved?.icalUrl ?? "";

  function check() {
    const p = parseMoodleInput(value);
    setError(p.error);
    return p.creds;
  }

  async function test() {
    const c = check();
    if (!c) return;
    setBusy(true);
    setResult(null);
    const r = await checkMoodle(c);
    setBusy(false);
    setResult({
      ok: r.ok,
      text: r.ok && r.user_fullname ? `${r.message} Signed in as ${r.user_fullname}.` : r.message || (r.ok ? "Moodle accepted it." : "Moodle did not accept that."),
    });
  }

  function save() {
    const c = check();
    if (!c) return;
    creds.saveMoodle(c);
    setResult({ ok: true, text: "Saved. Your deadlines will now come from your own Moodle." });
  }

  return (
    <section aria-labelledby="hs-moodle-h">
      <SectionHeading id="hs-moodle-h" note="Optional. Paste your Moodle calendar link. In Moodle: Calendar → Export calendar → All events, Recent and next 60 days → Get calendar URL. Without it you see demo data. The link works like a password.">
        Moodle
      </SectionHeading>
      <div className="mt-3 space-y-4">
      <SecretInput
        id="hs-moodle"
        noun="value"
        label="Moodle calendar link"
        value={value}
        onChange={(v) => (setValue(v), setResult(null), setError(null))}
        placeholder={`A link starting ${MOODLE_ICAL_PREFIX}`}
        invalid={!!error}
        describedBy={error ? "hs-moodle-error" : "hs-moodle-note"}
      />
      {error && <p id="hs-moodle-error" role="alert" className="-mt-2 text-sm text-danger">{error}</p>}
      <p id="hs-moodle-note" className="flex items-start gap-1.5 text-xs leading-snug text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
        Moodle content is shown only to you. It is never sent to the AI model.
      </p>
      <Switch
        id="hs-remember-moodle"
        checked={creds.remember.moodle}
        onCheckedChange={(on) => creds.setRemember("moodle", on)}
        label="Remember on this device"
        description={creds.remember.moodle ? "Kept in this browser until you forget it." : "Off: forgotten when you close this tab."}
      />
      <TestResult id="hs-moodle-result" result={result} />
      <div className="flex flex-wrap gap-2">
        <TestButton busy={busy} onClick={test} disabled={!value.trim()} label="Test Moodle" />
        <Button variant="primary" onClick={save} disabled={busy || !value.trim() || value.trim() === savedValue}>Save Moodle</Button>
        {saved && (
          <Button variant="ghost" onClick={() => (creds.clearMoodle(), setValue(""), setResult({ ok: true, text: "Moodle removed from this browser." }))}>
            Remove Moodle
          </Button>
        )}
      </div>
      </div>
    </section>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("truncate text-right font-medium", tone === "good" && "text-success", tone === "bad" && "text-danger", tone === "warn" && "text-warning")}>
        {value}
      </dd>
    </div>
  );
}

export function HostedSettings({
  creds,
  providers,
  state,
  onForgetAll,
}: {
  creds: Credentials;
  providers: ProviderInfo[];
  state: StatusState;
  onForgetAll: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const { status, reachable } = state;
  const providerLabel = creds.llm ? (providers.find((p) => p.id === creds.llm?.provider)?.label ?? creds.llm.provider) : null;
  return (
    <div className="space-y-6">
      <ModelSection creds={creds} providers={providers} />
      <MoodleSection creds={creds} />
      {/* Instructions only: no connector request is made and no connector login is asked for in hosted mode. */}
      <HostedConnectorsGuide />

      <section aria-labelledby="hs-status-h">
        <h3 id="hs-status-h" className="text-sm font-semibold">Model status</h3>
        <dl className="mt-1 divide-y">
          <Row label="Server" value={reachable ? "Reachable" : "Unreachable"} tone={reachable ? "good" : "bad"} />
          <Row label="AI provider" value={providerLabel ? `${providerLabel} (your key)` : "No key saved"} tone={providerLabel ? "good" : "warn"} />
          <Row label="Moodle" value={creds.moodle ? `Saved in this browser (${creds.moodle.token ? "token" : "calendar link"})` : "Not connected (showing demo data)"} tone={creds.moodle ? "good" : "warn"} />
          <Row label="Sources indexed" value={status ? String(status.sources_indexed) : "Unknown"} />
          {status?.index_version && <Row label="Index version" value={status.index_version} />}
        </dl>
      </section>

      <section aria-labelledby="hs-data-h">
        <SectionHeading id="hs-data-h" note="Your keys and your chats live only in this browser. Forgetting clears keys, Moodle credentials and chat history.">
          Local data
        </SectionHeading>
        {confirm ? (
          <div role="alertdialog" aria-label="Confirm forgetting everything" className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2.5">
            <span className="text-sm">Forget your keys, Moodle credentials and all chats on this device?</span>
            <Button variant="danger" size="sm" onClick={onForgetAll} autoFocus>Yes, forget everything</Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirm(false)}>Cancel</Button>
          </div>
        ) : (
          <Button variant="danger" size="sm" className="mt-3" onClick={() => setConfirm(true)}>
            <Trash2 className="h-3.5 w-3.5" aria-hidden /> Forget everything
          </Button>
        )}
      </section>
    </div>
  );
}
