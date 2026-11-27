"use client";
// Settings -> "Connectors" (local mode only): IITB Webmail, ASC and Google Calendar.
//
// Rules this file follows (docs/CONTRACT.md section 11):
// - A password is sent once. It is cleared from state the moment the request starts,
//   and it is never put in localStorage, a URL or the console. (ASC has no one-time code step.)
// - The server decides what is connected; this UI only shows the state it reports.
// - Webmail and ASC are read-only. The only write in the whole app is the calendar event a student
//   clicks "Add" on (see personal-cards.tsx).
import { useEffect, useRef, useState } from "react";
import { AlertCircle, Calendar, ExternalLink, FlaskConical, GraduationCap, Loader2, Mail, RefreshCw, ShieldCheck, Wifi, type LucideIcon } from "lucide-react";
import { SecretInput } from "@/components/secret-input";
import { Button } from "@/components/ui/button";
import { ascLogin, ascLogout, CONNECTOR_FLAGS, gcalConnect, gcalDisconnect, refreshAsc, webmailLogin, webmailLogout, type ApiResult } from "@/lib/api";
import type { ConnectorsState } from "@/hooks/use-connectors";
import { cn, relativePast, safeHttpUrl } from "@/lib/utils";
import type { ConnectorName, ConnectorState, ConnectorStatus } from "@/lib/types";

interface Meta {
  title: string;
  icon: LucideIcon;
  blurb: string;
  /** Needs the campus network or the IITB VPN (Webmail and ASC talk to IITB's servers). */
  campusOnly: boolean;
}

const META: Record<ConnectorName, Meta> = {
  webmail: {
    title: "IITB Webmail",
    icon: Mail,
    blurb: "Read-only. Finds institute events and deadlines in your mail. CampusPilot never sends, moves or deletes a mail.",
    campusOnly: true,
  },
  asc: {
    title: "ASC",
    icon: GraduationCap,
    blurb: "Read-only. Shows your timetable, courses, registration, profile and fee status. Grades are never read. Nothing is registered or changed for you.",
    campusOnly: true,
  },
  gcal: {
    title: "Google Calendar",
    icon: Calendar,
    blurb: "CampusPilot only creates the events you click Add on. It never adds anything on its own.",
    campusOnly: false,
  },
};

// Same tones as the status pill in the header, so the colours mean the same thing everywhere.
const TONE = {
  green: { dot: "bg-success", pill: "text-success bg-success-soft border-success/30" },
  amber: { dot: "bg-warning", pill: "text-warning bg-warning-soft border-warning/30" },
  red: { dot: "bg-danger", pill: "text-danger bg-danger-soft border-danger/30" },
  neutral: { dot: "bg-muted-foreground", pill: "text-muted-foreground bg-muted border-border" },
} as const;

const PILL: Record<ConnectorState, { label: string; tone: keyof typeof TONE }> = {
  connected: { label: "Connected", tone: "green" },
  not_connected: { label: "Not connected", tone: "neutral" },
  needs_otp: { label: "Needs code", tone: "amber" },
  error: { label: "Error", tone: "red" },
  disabled: { label: "Turned off", tone: "neutral" },
};

const INPUT =
  "h-11 w-full rounded-xl border border-input bg-background px-3.5 text-sm outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground focus:border-primary focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_25%,transparent)]";

function Code({ children }: { children: React.ReactNode }) {
  return <code className="rounded-md border bg-background px-1.5 py-0.5 font-mono text-[13px]">{children}</code>;
}

// ---------- one connector card ----------

function ConnectorCard({ name, status, onChange }: { name: ConnectorName; status: ConnectorStatus; onChange: (s: ConnectorStatus) => void }) {
  const meta = META[name];
  const Icon = meta.icon;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<null | "login" | "disconnect" | "google" | "refresh">(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState(""); // read out by screen readers (visually hidden)
  const [confirming, setConfirming] = useState(false);
  const [formOpen, setFormOpen] = useState(false); // the username / password form stays folded until "Connect" is pressed
  const [google, setGoogle] = useState<{ url: string; blocked: boolean } | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeading = useRef(false);
  const abortGoogle = useRef<AbortController | null>(null);

  // After a connect or disconnect the form that had focus disappears: put focus on the card title instead.
  useEffect(() => {
    if (focusHeading.current) {
      focusHeading.current = false;
      headingRef.current?.focus();
    }
  });
  // Stop waiting for Google when Settings closes.
  useEffect(() => () => abortGoogle.current?.abort(), []);

  const state = status.state;
  const isGoogle = name === "gcal";
  const isWebmail = name === "webmail";
  const canLogin = !isGoogle && (state === "not_connected" || state === "error" || state === "needs_otp");

  function done(next: ConnectorStatus, text: string) {
    setFormOpen(false);
    onChange(next);
    setAnnounce(text);
    focusHeading.current = true;
  }

  async function login(e: React.FormEvent) {
    e.preventDefault();
    const user = username.trim();
    const pass = password;
    if (!user || !pass || busy) return;
    setPassword(""); // the password lives in state only until this request starts
    setBusy("login");
    setError(null);
    const res: ApiResult<ConnectorStatus> = await (name === "asc" ? ascLogin : webmailLogin)({ username: user, password: pass });
    setBusy(null);
    if (!res.ok) return setError(res.message);
    if (res.data.state === "connected") {
      setUsername("");
      done(res.data, `${meta.title} connected.`);
    } else {
      onChange(res.data);
      setError(res.data.message || "Couldn't connect. Please try again.");
    }
  }

  /** ASC only: read the personal pages again now. The server answers with the new `refreshed_at`. */
  async function refresh() {
    if (busy) return;
    setBusy("refresh");
    setError(null);
    const res = await refreshAsc();
    setBusy(null);
    if (!res.ok) return setError(res.message);
    onChange(res.data);
    setAnnounce("ASC data updated.");
  }

  async function disconnect() {
    setBusy("disconnect");
    setError(null);
    const res = await (name === "asc" ? ascLogout : name === "webmail" ? webmailLogout : gcalDisconnect)();
    setBusy(null);
    setConfirming(false);
    if (!res.ok) return setError(res.message);
    setGoogle(null);
    done(res.data, `${meta.title} disconnected.`);
  }

  async function connectGoogle() {
    if (busy) return;
    const ctl = new AbortController();
    abortGoogle.current = ctl;
    setBusy("google");
    setError(null);
    setGoogle(null);
    const res = await gcalConnect({ signal: ctl.signal, onOpened: (url, blocked) => setGoogle({ url, blocked }) });
    if (abortGoogle.current === ctl) abortGoogle.current = null;
    if (ctl.signal.aborted) return; // cancelled, or Settings closed
    setBusy(null);
    setGoogle(null);
    if (!res.ok) return setError(res.message);
    done(res.data, "Google Calendar connected.");
  }

  function cancelGoogle() {
    abortGoogle.current?.abort();
    abortGoogle.current = null;
    setBusy(null);
    setGoogle(null);
  }

  // Disconnect asks first. The confirmation takes the full row; Cancel gets focus (the safe choice).
  const disconnectUi = confirming ? (
    <div className="flex w-full flex-wrap items-center gap-2 rounded-lg bg-muted px-3 py-2">
      <span className="min-w-0 flex-1 basis-48 text-sm">
        Disconnect {meta.title}? {isGoogle ? "Access is revoked at Google." : "Your saved login is deleted from the Keychain."}
      </span>
      <Button variant="danger" size="sm" onClick={disconnect} disabled={busy !== null}>
        {busy === "disconnect" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />} Yes, disconnect
      </Button>
      <Button variant="ghost" size="sm" autoFocus disabled={busy !== null} onClick={() => setConfirming(false)}>
        Cancel
      </Button>
    </div>
  ) : (
    <Button variant="danger" size="sm" onClick={() => setConfirming(true)} aria-label={`Disconnect ${meta.title}`}>
      Disconnect
    </Button>
  );

  const pill = PILL[state];
  const tone = TONE[pill.tone];
  const googleUrl = safeHttpUrl(google?.url);

  return (
    <li data-testid={`connector-${name}`} className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-3">
        <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <h4 ref={headingRef} tabIndex={-1} className="min-w-0 flex-1 text-[15px] font-semibold outline-none">
          {meta.title}
        </h4>
        <span className={cn("inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium", tone.pill)}>
          <span className={cn("h-1.5 w-1.5 rounded-full", tone.dot)} aria-hidden />
          {pill.label}
        </span>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{meta.blurb}</p>
      <p role="status" className="sr-only">{announce}</p>

      {status.demo && state !== "disabled" && (
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-warning/30 px-2 py-0.5 text-xs font-medium text-warning">
          <FlaskConical className="h-3.5 w-3.5" aria-hidden /> Demo data
        </p>
      )}

      {state === "disabled" && (
        <p className="mt-3 text-sm">
          Turned off. Set <Code>{CONNECTOR_FLAGS[name]}=true</Code> in <Code>.env</Code> and restart the API.
        </p>
      )}

      {/* Connected: who it is, and Disconnect on the same line (it wraps under on a phone). */}
      {state === "connected" && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <p className="min-w-0 text-sm">
            Connected{status.account ? <> as <strong className="break-all font-semibold">{status.account}</strong></> : null}
            {status.demo ? <span className="text-muted-foreground"> (sample data)</span> : null}
          </p>
          {disconnectUi}
        </div>
      )}

      {/* ASC: read the personal pages again on demand (the snapshot is also refreshed every 6 hours). */}
      {state === "connected" && name === "asc" && (
        <div className="mt-3 border-t pt-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Button variant="outline" size="sm" onClick={refresh} disabled={busy !== null}>
              {busy === "refresh" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden />}
              {busy === "refresh" ? "Refreshing…" : "Refresh ASC data"}
            </Button>
            {relativePast(status.refreshed_at) && (
              <span data-testid="asc-updated" className="text-xs text-muted-foreground">
                Updated {relativePast(status.refreshed_at)}
              </span>
            )}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Your ASC data is only shared with the local model.</p>
        </div>
      )}

      {state === "error" && status.message && (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {status.message}
        </p>
      )}

      {/* Webmail / ASC: a Connect button first; the form opens in place so the dialog stays short. */}
      {canLogin && !formOpen && (
        <div className="mt-3">
          <Button variant="primary" onClick={() => setFormOpen(true)} aria-label={`${state === "error" ? "Reconnect" : "Connect"} ${meta.title}`}>
            {state === "error" ? "Reconnect" : "Connect"}
          </Button>
        </div>
      )}

      {/* The form. The password field is masked and never autofilled. */}
      {canLogin && formOpen && (
        <form onSubmit={login} className="mt-3 space-y-3" aria-label={`${meta.title} login`}>
          <div>
            <label htmlFor={`${name}-user`} className="mb-1.5 block text-sm font-medium">LDAP ID</label>
            <input
              id={`${name}-user`}
              type="text"
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="your LDAP id, e.g. 24b0000"
              className={INPUT}
            />
          </div>
          {isWebmail ? (
            <div>
              {/* IITB mail does not accept the LDAP password: it needs an SSO access token for Emails.
                  (The API field is still called `password`; only the wording differs.) */}
              <SecretInput id="webmail-password" label="SSO access token (Emails)" noun="token" value={password} onChange={setPassword} describedBy="webmail-token-help" />
              <p id="webmail-token-help" className="mt-1.5 text-xs text-muted-foreground">
                Create one at{" "}
                <a href="https://sso.iitb.ac.in" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-medium text-accent-text underline-offset-4 hover:underline">
                  sso.iitb.ac.in <ExternalLink className="h-3 w-3" aria-hidden />
                </a>{" "}
                → Manage account → Access tokens → Emails. It&apos;s not your LDAP password.
              </p>
            </div>
          ) : (
            <SecretInput id={`${name}-password`} label="LDAP password" noun="password" value={password} onChange={setPassword} />
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={!username.trim() || !password || busy !== null}>
              {busy === "login" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
              {busy === "login" ? "Checking…" : "Connect"}
            </Button>
            <Button
              variant="ghost"
              disabled={busy !== null}
              onClick={() => {
                setFormOpen(false);
                setUsername("");
                setPassword("");
                setError(null);
              }}
            >
              Cancel
            </Button>
          </div>
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
            <span>Sent once to your local CampusPilot server and stored in your Mac&apos;s Keychain. Never sent anywhere else.</span>
          </p>
        </form>
      )}

      {/* Google: sign in in a new tab, then wait for the API to report it connected. */}
      {isGoogle && (state === "not_connected" || state === "error") && (
        <div className="mt-3">
          {busy === "google" ? (
            <div className="space-y-2">
              <p className="flex items-center gap-2 text-sm">
                <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden /> Waiting for Google. Finish in the new tab, then come back here.
              </p>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <Button variant="ghost" size="sm" onClick={cancelGoogle}>Cancel</Button>
                {googleUrl && (
                  <a href={googleUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-accent-text underline-offset-4 hover:underline">
                    {google?.blocked ? "The tab didn't open? Open Google sign-in" : "Open Google sign-in again"} <ExternalLink className="h-3 w-3" aria-hidden />
                  </a>
                )}
              </div>
            </div>
          ) : (
            <Button variant="primary" onClick={connectGoogle} disabled={busy !== null}>
              Connect Google Calendar
            </Button>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {/* A saved login that no longer works can still be removed. */}
      {state === "error" && !isGoogle && <div className="mt-3">{disconnectUi}</div>}
    </li>
  );
}

// ---------- the section ----------

/** Loads the live state when Settings opens, then lists the three connectors. Hidden by the caller in hosted mode. */
export function ConnectorsSection({ connectors }: { connectors: ConnectorsState }) {
  const { data, load, refresh, apply } = connectors;
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // An older API without these endpoints: nothing to show, and nothing to fix.
  if (load === "unavailable") return null;

  return (
    <section aria-labelledby="connectors-h">
      <h3 id="connectors-h" tabIndex={-1} className="text-sm font-semibold outline-none">Connectors</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Optional. Let CampusPilot read your IITB mail and ASC, and add events to your Google Calendar. This runs only on this Mac.
      </p>
      <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
        <Wifi className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>Webmail and ASC only work on the campus network or the IITB VPN.</span>
      </p>

      {!data && load !== "error" && (
        <div className="mt-3 space-y-3" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-[7.5rem] w-full rounded-xl" />
          ))}
          <span className="sr-only">Loading connectors</span>
        </div>
      )}

      {!data && load === "error" && (
        <div role="alert" className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
          <span className="min-w-0 flex-1">Couldn&apos;t load the connectors. Is the CampusPilot API running?</span>
          <Button size="sm" variant="outline" onClick={() => void refresh()}>Try again</Button>
        </div>
      )}

      {data && (
        <ul className="mt-3 space-y-3">
          {(["webmail", "asc", "gcal"] as const).map((n) => (
            <ConnectorCard key={n} name={n} status={data[n]} onChange={apply} />
          ))}
        </ul>
      )}
    </section>
  );
}
