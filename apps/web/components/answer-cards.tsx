"use client";
// Cards drawn for special answer kinds: a clarifying question, an abstention and an error.
import { AlertTriangle, Clock, ExternalLink, HelpCircle, KeyRound, RotateCw, ShieldQuestion, WifiOff, type LucideIcon } from "lucide-react";
import { useAppActions } from "@/components/app-actions";
import { Button } from "@/components/ui/button";
import { useCountdown } from "@/hooks/use-countdown";
import { providerLabel } from "@/lib/providers";
import { cn } from "@/lib/utils";
import type { ErrorEvent, FollowUp, OfficeLink } from "@/lib/types";

/** A highlighted question with quick-reply chips. */
export function ClarifyCard({ followUp, onPick, disabled }: { followUp: FollowUp; onPick: (text: string) => void; disabled: boolean }) {
  return (
    <div className="animate-fade-up rounded-2xl border border-primary/40 bg-accent-soft/70 p-4">
      <p className="flex items-start gap-2 text-[15px] font-medium text-foreground">
        <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-accent-text" aria-hidden />
        {followUp.question}
      </p>
      {followUp.options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Quick replies">
          {followUp.options.map((o) => (
            <button
              key={o}
              type="button"
              disabled={disabled}
              onClick={() => onPick(o)}
              className="cursor-pointer rounded-full border border-primary/50 bg-background px-3.5 py-1.5 text-sm font-medium text-accent-text transition-colors duration-150 hover:bg-primary hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {o}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function LinkList({ links }: { links: OfficeLink[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-2">
      {links.map((l) => (
        <li key={l.url}>
          <a
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3.5 py-1.5 text-sm font-medium text-accent-text transition-colors duration-150 hover:bg-muted"
          >
            {l.title}
            {l.issuer && <span className="font-normal text-muted-foreground max-sm:hidden">· {l.issuer}</span>}
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        </li>
      ))}
    </ul>
  );
}

/** The icon in a tinted rounded square that heads a notice card. */
function NoticeIcon({ icon: Icon, tone }: { icon: LucideIcon; tone: "warning" | "danger" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
        tone === "warning" ? "bg-warning/15 text-warning" : "bg-danger/15 text-danger",
      )}
    >
      <Icon className="h-[18px] w-[18px]" />
    </span>
  );
}

/** Calm notice for "I couldn't verify this", with the office or portal link. */
export function AbstainCard({ links, children }: { links: OfficeLink[]; children: React.ReactNode }) {
  return (
    <div className="animate-fade-up flex gap-3 rounded-2xl border border-warning/30 bg-card p-4 shadow-sm">
      <NoticeIcon icon={ShieldQuestion} tone="warning" />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-semibold leading-8">Couldn&apos;t verify this</p>
        <div className="text-[15px] text-foreground/90">{children}</div>
        {links.length > 0 && (
          <>
            <p className="mt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Check with the office</p>
            <LinkList links={links} />
          </>
        )}
      </div>
    </div>
  );
}

// Official pages we can always point to when the model cannot answer.
const FALLBACK_LINKS: OfficeLink[] = [
  { title: "IIT Bombay home page", url: "https://www.iitb.ac.in", issuer: "IIT Bombay" },
  { title: "Academic Office", url: "https://acad.iitb.ac.in", issuer: "IIT Bombay" },
];

interface ErrorLook {
  title: string;
  icon: LucideIcon;
  /** Show a "Change key" button (hosted, when the student's key is the problem or the way out). */
  changeKey?: "add" | "change";
  /** Can the same request simply be sent again? */
  retry: boolean;
}

/** Title, icon and buttons for each error code. `name` is the provider's label ("Groq"). */
function lookFor(code: ErrorEvent["code"], name: string): ErrorLook {
  switch (code) {
    case "MODEL_KEY_REQUIRED":
      return { title: "Add your AI key to start", icon: KeyRound, changeKey: "add", retry: false };
    case "PROVIDER_KEY_REJECTED":
      return { title: `${name} rejected your key`, icon: KeyRound, changeKey: "change", retry: false };
    case "PROVIDER_RATE_LIMITED":
      return { title: `You've hit ${name}'s limit`, icon: Clock, changeKey: "change", retry: true };
    case "PROVIDER_TIMEOUT":
      return { title: `${name} took too long`, icon: Clock, retry: true };
    case "PROVIDER_ERROR":
      return { title: `${name} had a problem`, icon: AlertTriangle, retry: true };
    case "RATE_LIMITED":
      return { title: "Too many requests", icon: Clock, retry: true };
    case "MODEL_OFFLINE":
    case "NETWORK":
      return { title: "The assistant is offline", icon: WifiOff, retry: true };
    default:
      return { title: "Something went wrong", icon: AlertTriangle, retry: true };
  }
}

/** Friendly error state. Hosted-mode codes name the provider and offer "Change key"; waits show a countdown. */
export function ErrorCard({ error, onRetry, disabled }: { error: ErrorEvent; onRetry?: () => void; disabled?: boolean }) {
  const { openSettings, providers } = useAppActions();
  const offline = error.code === "MODEL_OFFLINE" || error.code === "NETWORK";
  const name = providerLabel(error.provider, providers);
  const look = lookFor(error.code, name);
  const left = useCountdown(error.at, error.retry_after_s);
  const waiting = left > 0;
  return (
    <div role="alert" data-testid="error-card" data-code={error.code} className="animate-fade-up flex gap-3 rounded-2xl border border-danger/30 bg-card p-4 shadow-sm">
      <NoticeIcon icon={look.icon} tone="danger" />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-semibold leading-8">{look.title}</p>
        <p className="text-[15px] text-foreground/90">
          {/* show `backticked` text as inline code */}
          {error.message.split("`").map((part, i) =>
            i % 2 ? (
              <code key={i} className="rounded-md border bg-background px-1.5 py-0.5 font-mono text-[13px]">
                {part}
              </code>
            ) : (
              part
            ),
          )}
        </p>
        {waiting && (
          <p className="mt-1.5 text-sm text-muted-foreground">
            You can try again in <span className="font-semibold tabular-nums text-foreground">{left} s</span>.
          </p>
        )}
        {offline && (
          <>
            <p className="mt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Meanwhile, the official pages</p>
            <LinkList links={FALLBACK_LINKS} />
          </>
        )}
        {((onRetry && look.retry) || look.changeKey) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {look.changeKey && (
              <Button size="sm" variant={look.retry ? "outline" : "primary"} onClick={() => openSettings("model")}>
                <KeyRound className="h-3.5 w-3.5" aria-hidden /> {look.changeKey === "add" ? "Add key" : "Change key"}
              </Button>
            )}
            {onRetry && look.retry && (
              <Button size="sm" variant="outline" onClick={onRetry} disabled={disabled || waiting}>
                <RotateCw className="h-3.5 w-3.5" aria-hidden /> Try again
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
