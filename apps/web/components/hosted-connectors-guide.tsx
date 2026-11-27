"use client";
// Settings -> "Connectors" in HOSTED mode: instructions only.
//
// Webmail, ASC and Google Calendar run only in the local app (docs/CONTRACT.md section 11), because the
// hosted server never stores mail, ASC or Google logins. So this file renders three cards that say so and
// explain how to connect in the local app. It makes no network request and asks for no credential.
import { useId, useState } from "react";
import { Calendar, ChevronDown, ExternalLink, GraduationCap, Mail, type LucideIcon } from "lucide-react";
import { CONNECTOR_FLAGS } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ConnectorName } from "@/lib/types";

const REPO_URL = "https://github.com/biprabhanu/iitb-campus-assistant";
const REPO_CLONE = "git clone https://github.com/biprabhanu/iitb-campus-assistant";
const LOCAL_URL = "http://127.0.0.1:3000";

function Code({ children }: { children: React.ReactNode }) {
  return <code className="break-all rounded-md border bg-background px-1.5 py-0.5 font-mono text-[13px]">{children}</code>;
}

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 font-medium text-accent-text underline-offset-4 hover:underline">
      {children} <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
    </a>
  );
}

interface Meta {
  title: string;
  icon: LucideIcon;
  /** Why this card is not usable here. */
  reason: string;
  /** What it does in the local app. */
  blurb: string;
  /** The steps after the app is running and Settings -> Connectors is open. */
  connect: React.ReactNode[];
}

const META: Record<ConnectorName, Meta> = {
  webmail: {
    title: "IITB Webmail",
    icon: Mail,
    blurb: "Read-only. Finds institute events and deadlines in your mail. CampusPilot never sends, moves or deletes a mail.",
    reason: "This hosted site never stores your mail login.",
    connect: [
      <>
        Create an access token for mail: go to{" "}
        <Ext href="https://sso.iitb.ac.in">sso.iitb.ac.in</Ext> → Manage account → Access tokens → Emails.
      </>,
      <>
        On the Webmail card press <strong>Connect</strong>, then enter your IITB LDAP ID and that token. Use the token, not your LDAP password.
      </>,
      <>The token is saved in the macOS Keychain on your Mac. Mail is read only, and only the local model sees it.</>,
    ],
  },
  asc: {
    title: "ASC",
    icon: GraduationCap,
    blurb: "Read-only. Shows your timetable, courses, registration and fee status. Grades are never read.",
    reason: "This hosted site never stores your ASC login.",
    connect: [
      <>You need to be on the campus network or the IITB VPN, because ASC is an internal portal.</>,
      <>
        On the ASC card press <strong>Connect</strong>, then enter your IITB LDAP ID and LDAP password.
      </>,
      <>
        CampusPilot reads your timetable, courses, registration, profile and fee status. Grades are never read. Answers about your ASC data use only the local model.
      </>,
    ],
  },
  gcal: {
    title: "Google Calendar",
    icon: Calendar,
    blurb: "CampusPilot only creates the events you click Add on. It never adds anything on its own.",
    reason: "This hosted site never stores your Google sign-in.",
    connect: [
      <>
        In the <Ext href="https://console.cloud.google.com/apis/credentials">Google Cloud Console</Ext> create an OAuth client of type <strong>Desktop app</strong>, and turn on the Google Calendar API.
      </>,
      <>
        Download the client JSON and save it as <Code>~/.campuspilot/google_client.json</Code>. Keep it out of the repository.
      </>,
      <>
        On the Google Calendar card press <strong>Connect Google Calendar</strong> and sign in in the new tab.
      </>,
      <>An event is added only when you click <strong>Add</strong> on an event card. Nothing is added twice.</>,
    ],
  },
};

/** The steps every connector shares: get the local app, turn the connector on, open Settings. */
function sharedSteps(name: ConnectorName): React.ReactNode[] {
  return [
    <>
      Get the local app: run <Code>{REPO_CLONE}</Code> (or open it on <Ext href={REPO_URL}>GitHub</Ext>), then <Code>make setup</Code> inside the folder.
    </>,
    <>
      In the <Code>.env</Code> file set <Code>{CONNECTOR_FLAGS[name]}=true</Code>.
    </>,
    <>
      Run <Code>make dev</Code>, then open <Code>{LOCAL_URL}</Code> and go to Settings → Connectors.
    </>,
  ];
}

function GuideCard({ name }: { name: ConnectorName }) {
  const meta = META[name];
  const Icon = meta.icon;
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const steps = [...sharedSteps(name), ...meta.connect];

  return (
    <li data-testid={`hosted-connector-${name}`} className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-3">
        <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-text">
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <h4 className="min-w-0 flex-1 text-[15px] font-semibold">{meta.title}</h4>
        <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" aria-hidden />
          Local app only
        </span>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{meta.blurb}</p>
      <p className="mt-2 text-sm">{meta.reason} Use the local app to connect it.</p>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        className="mt-3 inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg text-sm font-medium text-accent-text underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        How to connect
        <ChevronDown className={cn("h-4 w-4 transition-transform duration-150", open && "rotate-180")} aria-hidden />
      </button>
      <div id={panelId} hidden={!open}>
        {open && (
          <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm leading-relaxed marker:text-muted-foreground">
            {steps.map((s, i) => (
              <li key={i} className="pl-1">{s}</li>
            ))}
          </ol>
        )}
      </div>
    </li>
  );
}

export function HostedConnectorsGuide() {
  return (
    <section aria-labelledby="hs-connectors-h">
      <h3 id="hs-connectors-h" className="text-sm font-semibold">Connectors</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Webmail, ASC and Google Calendar work only in the local app on your own computer. Moodle works here: paste your Moodle calendar link in the Moodle section above.
      </p>
      <ul className="mt-3 space-y-3">
        {(["webmail", "asc", "gcal"] as const).map((n) => (
          <GuideCard key={n} name={n} />
        ))}
      </ul>
    </section>
  );
}
