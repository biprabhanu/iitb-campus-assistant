"use client";
import { PanelLeft, UserCheck, UserX, FlaskConical, KeyRound } from "lucide-react";
import type { SettingsSection } from "@/components/app-actions";
import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { shortProviderLabel } from "@/lib/providers";
import type { LlmCreds, MoodleCreds } from "@/lib/credentials";
import type { StatusState } from "@/hooks/use-status";
import type { ProviderInfo } from "@/lib/types";

type Tone = "green" | "amber" | "red" | "neutral";
const toneClass: Record<Tone, { dot: string; pill: string }> = {
  green: { dot: "bg-success", pill: "text-success bg-success-soft border-success/30" },
  amber: { dot: "bg-warning", pill: "text-warning bg-warning-soft border-warning/30" },
  red: { dot: "bg-danger", pill: "text-danger bg-danger-soft border-danger/30" },
  neutral: { dot: "bg-muted-foreground", pill: "text-muted-foreground bg-muted border-border" },
};

/** Model status pill: online (green), waking or idle (amber), offline (red). */
function StatusPill({ state, waking }: { state: StatusState; waking: boolean }) {
  const { status, reachable, checked } = state;
  let tone: Tone = "neutral";
  let label = "Checking…";
  let short = "Checking"; // compact label for small screens
  let tip = "Checking the CampusPilot server.";

  if (checked) {
    if (!reachable || !status) {
      tone = "red";
      label = "Offline";
      short = "Offline";
      tip = "Can't reach the CampusPilot server. Make sure the API is running on this computer.";
    } else if (!status.model_online) {
      tone = "red";
      label = "Offline";
      short = "Offline";
      tip = "The CampusPilot model is offline. Check the SSH tunnel to the model server, then try again.";
    } else if (waking) {
      tone = "amber";
      label = "Waking model…";
      short = "Waking";
      tip = "The model was asleep and is loading. This takes about 10 seconds.";
    } else if (!status.model_loaded) {
      tone = "amber";
      label = "Model idle";
      short = "Idle";
      tip = "The model is reachable but asleep. It wakes up on your next message (about 10 s).";
    } else {
      tone = "green";
      label = "Model online";
      short = "Online";
      tip = `${status.model} is loaded and ready.`;
    }
  }
  const c = toneClass[tone];

  return (
    <Tooltip content={tip}>
      <span
        role="status"
        data-testid="status-pill"
        tabIndex={0}
        className={cn("inline-flex h-8 cursor-default items-center gap-2 rounded-full border px-3 text-xs font-medium", c.pill)}
      >
        <span className={cn("h-2 w-2 rounded-full", c.dot, tone === "amber" && "animate-[pulse-dot_1.2s_ease-in-out_infinite]")} aria-hidden />
        <span className="whitespace-nowrap max-[430px]:hidden">{label}</span>
        <span className="hidden whitespace-nowrap max-[430px]:inline">{short}</span>
      </span>
    </Tooltip>
  );
}

/** Hosted mode: which AI key is active. Click to open Settings. Also shows the sleeping server. */
function ProviderPill({ state, llm, providers, onClick }: { state: StatusState; llm: LlmCreds | null; providers: ProviderInfo[]; onClick: () => void }) {
  let tone: Tone = "green";
  let label: string;
  let short: string;
  let tip: string;
  if (state.wake === "waking") {
    tone = "amber";
    label = "Waking server…";
    short = "Waking";
    tip = "The free server was asleep and is starting. This takes up to about a minute.";
  } else if (state.wake === "failed") {
    tone = "red";
    label = "Server asleep";
    short = "Asleep";
    tip = "The server did not wake up yet. Use Retry below the chat.";
  } else if (!llm) {
    tone = "amber";
    label = "Add your AI key";
    short = "Add key";
    tip = "CampusPilot needs your own AI key to answer. Open Settings to add one.";
  } else {
    const name = shortProviderLabel(llm.provider, providers);
    label = `${name} · your key`;
    short = name;
    tip = `Answers use your ${name} key${llm.model ? ` (model ${llm.model})` : ""}. Click to change it.`;
  }
  const c = toneClass[tone];
  return (
    <Tooltip content={tip}>
      <button
        type="button"
        onClick={onClick}
        data-testid="provider-pill"
        aria-label={`${label}. Open settings`}
        className={cn("inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors hover:brightness-95 dark:hover:brightness-125", c.pill)}
      >
        {llm && state.wake === "ready" ? (
          <KeyRound className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <span className={cn("h-2 w-2 rounded-full", c.dot, tone === "amber" && "animate-[pulse-dot_1.2s_ease-in-out_infinite]")} aria-hidden />
        )}
        <span className="whitespace-nowrap max-[430px]:hidden">{label}</span>
        <span className="hidden whitespace-nowrap max-[430px]:inline">{short}</span>
      </button>
    </Tooltip>
  );
}

/** Moodle badge: connected / demo / not connected. Click opens Settings. */
function MoodleBadge({ state, onClick, hostedMoodle }: { state: StatusState; onClick: () => void; hostedMoodle: boolean | null }) {
  const { status } = state;
  let Icon = UserX;
  let label = "Moodle not connected";
  let short = "Off"; // compact label for small screens
  let tip = "Connect Moodle in Settings to see your real deadlines.";
  let cls = "text-muted-foreground";
  if (hostedMoodle !== null) {
    // Hosted: the credentials live in this browser, so that decides what the badge says.
    if (hostedMoodle) {
      Icon = UserCheck;
      label = "Moodle connected";
      short = "Moodle";
      tip = "Your own Moodle details are used for deadlines. They are never sent to the AI model.";
      cls = "text-success";
    } else {
      Icon = FlaskConical;
      label = "Moodle demo";
      short = "Demo";
      tip = "Showing sample Moodle data, not yours. Add your Moodle token in Settings for real deadlines.";
      cls = "text-warning";
    }
  } else if (status?.moodle_mode === "demo") {
    // Demo fixtures are served when nothing is connected (backend: moodle="not_configured").
    Icon = FlaskConical;
    label = "Moodle demo";
    short = "Demo";
    tip = "Showing sample Moodle data, not yours. Connect Moodle in Settings for real deadlines.";
    cls = "text-warning";
  } else if (status && status.moodle === "connected") {
    {
      Icon = UserCheck;
      label = "Moodle connected";
      short = "Moodle";
      tip = "Your Moodle is connected. CampusPilot only reads it.";
      cls = "text-success";
    }
  } else if (status?.moodle === "error") {
    label = "Moodle error";
    short = "Error";
    tip = "Moodle could not be reached. Open Settings to reconnect.";
    cls = "text-danger";
  }
  return (
    <Tooltip content={tip}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className={cn("inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors hover:bg-muted", cls)}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
        <span className="whitespace-nowrap sm:hidden">{short}</span>
        <span className="hidden whitespace-nowrap sm:inline">{label}</span>
      </button>
    </Tooltip>
  );
}

export function Header({
  state,
  waking,
  hosted,
  llm,
  moodle,
  providers,
  onToggleSidebar,
  onOpenSettings,
}: {
  state: StatusState;
  waking: boolean;
  hosted: boolean;
  llm: LlmCreds | null;
  moodle: MoodleCreds | null;
  providers: ProviderInfo[];
  onToggleSidebar: () => void;
  onOpenSettings: (section?: SettingsSection) => void;
}) {
  return (
    <header className="z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background/75 px-2 backdrop-blur-md sm:px-3">
      <Tooltip content="Toggle sidebar">
        <Button variant="ghost" size="icon" onClick={onToggleSidebar} aria-label="Toggle sidebar">
          <PanelLeft className="h-5 w-5" />
        </Button>
      </Tooltip>
      <div className="flex items-center gap-2">
        <BrandMark className="h-7 w-7" />
        <span className="text-[15px] font-semibold tracking-tight max-[420px]:sr-only">CampusPilot</span>
      </div>
      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        {hosted ? (
          <ProviderPill state={state} llm={llm} providers={providers} onClick={() => onOpenSettings("model")} />
        ) : (
          <StatusPill state={state} waking={waking} />
        )}
        <MoodleBadge state={state} onClick={() => onOpenSettings("moodle")} hostedMoodle={hosted ? !!(moodle?.token || moodle?.icalUrl) : null} />
        <ThemeToggle />
      </div>
    </header>
  );
}
