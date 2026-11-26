"use client";
import { useState } from "react";
import { Loader2, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SettingsSection } from "@/components/app-actions";
import { ConnectorsSection } from "@/components/connector-settings";
import { HostedSettings } from "@/components/hosted-settings";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { deleteMoodleCredentials, sendMoodleCredentials } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Credentials } from "@/hooks/use-credentials";
import type { ConnectorsState } from "@/hooks/use-connectors";
import type { StatusState } from "@/hooks/use-status";
import type { ProviderInfo } from "@/lib/types";

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

export function SettingsDialog({
  open,
  onOpenChange,
  state,
  onRefreshStatus,
  onClearHistory,
  hosted,
  creds,
  providers,
  section,
  connectors,
  onForgetAll,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: StatusState;
  onRefreshStatus: () => void;
  onClearHistory: () => void;
  /** Hosted mode shows the key and browser-side Moodle settings instead of the Keychain ones. */
  hosted: boolean;
  creds: Credentials;
  providers: ProviderInfo[];
  section: SettingsSection;
  /** Local mode only: the v2 connectors (Webmail, ASC, Google Calendar). */
  connectors: ConnectorsState;
  onForgetAll: () => void;
}) {
  const [secret, setSecret] = useState(""); // lives only in this component's memory
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const { status, reachable } = state;

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const value = secret.trim();
    if (!value || busy) return;
    const body = /^https?:\/\//i.test(value) ? { ical_url: value } : { token: value };
    setSecret(""); // clear right away: we never keep the token
    setBusy(true);
    setResult(null);
    try {
      const res = await sendMoodleCredentials(body);
      setResult({
        ok: res.ok,
        text: res.ok && res.user_fullname ? `${res.message} Signed in as ${res.user_fullname}.` : res.message,
      });
    } catch {
      setResult({ ok: false, text: "Couldn't reach the CampusPilot server." });
    } finally {
      setBusy(false);
      onRefreshStatus();
    }
  }

  async function disconnect() {
    setBusy(true);
    setResult(null);
    try {
      const res = await deleteMoodleCredentials();
      setResult({ ok: res.ok, text: res.message });
    } catch {
      setResult({ ok: false, text: "Couldn't reach the CampusPilot server." });
    } finally {
      setBusy(false);
      onRefreshStatus();
    }
  }

  const moodleLabel = !status
    ? "Unknown"
    : status.moodle_mode === "demo"
      ? "Not connected (showing demo data)"
      : status.moodle === "connected"
        ? `Connected (${status.moodle_mode === "ical" ? "calendar link" : "token"})`
        : status.moodle === "error"
          ? "Error"
          : "Not connected";
  const realConnection = status?.moodle === "connected" && status.moodle_mode !== "demo";

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setSecret("");
          setResult(null);
          setConfirmClear(false);
        }
        onOpenChange(o);
      }}
    >
      <DialogContent
        title="Settings"
        description={hosted ? "Your AI key and optional Moodle, kept in this browser." : "Connect Moodle, check the model and manage data kept in this browser."}
        className="max-w-xl"
        initialFocusId={
          hosted
            ? section === "moodle" ? "hs-moodle" : !creds.llm ? "hs-key" : undefined
            : section === "connectors" ? "connectors-h" : undefined // "Connect Google Calendar" on a card lands here
        }
      >
        {hosted ? (
          <HostedSettings
            creds={creds}
            providers={providers}
            state={state}
            onForgetAll={() => {
              onForgetAll();
              onOpenChange(false);
            }}
          />
        ) : (
        <div className="space-y-6">
          <section aria-labelledby="moodle-h">
            <h3 id="moodle-h" className="text-sm font-semibold">Moodle</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Paste your Moodle token or your calendar (iCal) export link. CampusPilot only reads deadlines and courses.
            </p>
            <form onSubmit={connect} className="mt-3 flex gap-2">
              <label htmlFor="moodle-secret" className="sr-only">Moodle token or iCal URL</label>
              <input
                id="moodle-secret"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder="Token or iCal URL"
                className="h-10 min-w-0 flex-1 rounded-xl border border-input bg-card px-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
              />
              <Button type="submit" variant="primary" disabled={!secret.trim() || busy}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null} Connect
              </Button>
            </form>
            <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
              Sent once to your local CampusPilot server, which keeps it in the Keychain. This browser never stores it.
            </p>
            {result && (
              <p role="status" className={cn("mt-3 rounded-lg px-3 py-2 text-sm", result.ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
                {result.text}
              </p>
            )}
            {realConnection && (
              <Button variant="danger" size="sm" className="mt-3" onClick={disconnect} disabled={busy}>
                Disconnect Moodle
              </Button>
            )}
          </section>

          {/* v2: only in local mode (this branch), so the hosted UI never mounts it or asks for connectors. */}
          <ConnectorsSection connectors={connectors} />

          <section aria-labelledby="model-h">
            <h3 id="model-h" className="text-sm font-semibold">Model status</h3>
            <dl className="mt-1 divide-y">
              <Row label="Server" value={reachable ? "Reachable" : "Unreachable"} tone={reachable ? "good" : "bad"} />
              <Row
                label="Model"
                value={status ? (status.model_online ? (status.model_loaded ? "Online, loaded" : "Online, asleep") : "Offline") : "Unknown"}
                tone={status?.model_online ? (status.model_loaded ? "good" : "warn") : "bad"}
              />
              <Row label="Model name" value={status?.model ?? "Unknown"} />
              <Row label="Moodle" value={moodleLabel} tone={realConnection ? "good" : status?.moodle_mode === "demo" ? "warn" : undefined} />
              <Row label="Sources indexed" value={status ? String(status.sources_indexed) : "Unknown"} />
              <Row label="Mode" value={status?.mode ?? "Unknown"} />
            </dl>
          </section>

          <section aria-labelledby="data-h">
            <h3 id="data-h" className="text-sm font-semibold">Local data</h3>
            <p className="mt-1 text-sm text-muted-foreground">Your chats are stored only in this browser. The server keeps no chat text.</p>
            {confirmClear ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-sm">Delete all chats from this browser?</span>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    onClearHistory();
                    setConfirmClear(false);
                    setResult({ ok: true, text: "Local history cleared." });
                  }}
                >
                  Yes, clear
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmClear(false)}>Cancel</Button>
              </div>
            ) : (
              <Button variant="outline" size="sm" className="mt-3" onClick={() => setConfirmClear(true)}>
                <Trash2 className="h-3.5 w-3.5" aria-hidden /> Clear local history
              </Button>
            )}
          </section>
        </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
