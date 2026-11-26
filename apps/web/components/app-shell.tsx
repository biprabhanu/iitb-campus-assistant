"use client";
import { useCallback, useMemo, useState } from "react";
import { AppActionsProvider, type SettingsSection } from "@/components/app-actions";
import { ChatView } from "@/components/chat-view";
import { Composer } from "@/components/composer";
import { Header } from "@/components/header";
import { KeyCard } from "@/components/key-card";
import { HostedServerNotice, OfflineNotice } from "@/components/offline-notice";
import { SettingsDialog } from "@/components/settings-dialog";
import { Sidebar } from "@/components/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useChat } from "@/hooks/use-chat";
import { useConnectors } from "@/hooks/use-connectors";
import { useCredentials } from "@/hooks/use-credentials";
import { useStatus } from "@/hooks/use-status";
import { providerList } from "@/lib/providers";

/** Wires the sidebar, header, message column, composer and settings together. */
export function AppShell() {
  const status = useStatus();
  const creds = useCredentials();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>("model");

  // One build serves both: the server says whether it is local or hosted (the last answer is remembered).
  // A server that is still asleep on first visit can only be a hosted one (a local API is never "asleep").
  const hosted = status.deployMode === "hosted" || (status.deployMode === null && status.wake !== "ready");
  const modeKnown = status.deployMode !== null || status.checked || status.wake !== "ready";
  const providers = useMemo(() => providerList(status.status?.providers), [status.status?.providers]);
  const auth = useMemo(() => ({ llm: creds.llm, moodle: creds.moodle }), [creds.llm, creds.moodle]);
  const chat = useChat({ hosted, auth });
  const needsKey = hosted && creds.loaded && !creds.llm;
  // null = "default": closed on mobile, open on desktop.
  const [sidebar, setSidebar] = useState<boolean | null>(null);

  const mobileOpen = sidebar === true;
  const desktopOpen = sidebar !== false;

  const toggleSidebar = useCallback(() => {
    const desktop = window.matchMedia("(min-width: 768px)").matches;
    const visible = desktop ? desktopOpen : mobileOpen;
    setSidebar(!visible);
  }, [desktopOpen, mobileOpen]);

  // On mobile, picking something closes the drawer.
  const closeMobile = () => setSidebar((s) => (s === true ? null : s));
  const openSettings = useCallback((section: SettingsSection = "model") => {
    setSettingsSection(section);
    setSettingsOpen(true);
  }, []);

  // v2 connectors exist only when the server says it is a local one: hosted mode never asks for them.
  const connectors = useConnectors(status.deployMode === "local");
  const actions = useMemo(() => ({ openSettings, hosted, providers, connectors }), [openSettings, hosted, providers, connectors]);

  // What the empty chat shows: nothing until we know the mode, the key card in hosted mode, else the suggestions.
  let emptyContent: React.ReactNode;
  if (!modeKnown || (hosted && !creds.loaded)) emptyContent = <div aria-hidden className="min-h-full" />;
  else if (needsKey) emptyContent = <KeyCard providers={providers} onSave={(c, remember) => creds.saveLlm(c, remember)} initialRemember={creds.remember.llm} />;

  return (
    <TooltipProvider>
      <AppActionsProvider value={actions}>
      <div className="flex h-dvh w-full overflow-hidden bg-background">
        <Sidebar
          conversations={chat.conversations}
          activeId={chat.activeId}
          mobileOpen={mobileOpen}
          desktopOpen={desktopOpen}
          onClose={() => setSidebar(null)}
          onNew={() => {
            chat.newChat();
            closeMobile();
          }}
          onSelect={(id) => {
            chat.selectChat(id);
            closeMobile();
          }}
          onRename={chat.renameChat}
          onDelete={chat.deleteChat}
          onOpenSettings={() => {
            openSettings();
            closeMobile();
          }}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header
            state={status}
            waking={chat.waking}
            hosted={hosted}
            llm={creds.llm}
            moodle={creds.moodle}
            providers={providers}
            onToggleSidebar={toggleSidebar}
            onOpenSettings={openSettings}
          />
          <main className="flex min-h-0 flex-1 flex-col">
            <ChatView
              chatId={chat.activeId}
              messages={chat.messages}
              loaded={chat.loaded}
              streamingId={chat.streamingId}
              waking={chat.waking}
              onSend={chat.send}
              onRegenerate={chat.regenerate}
              onFeedback={chat.setFeedback}
              emptyContent={emptyContent}
            />
            <Composer
              onSend={chat.send}
              onStop={chat.stop}
              streaming={chat.isStreaming}
              focusKey={chat.activeId}
              disabled={needsKey}
              placeholder={needsKey ? "Add your AI key above to start chatting" : undefined}
              notice={
                hosted || status.wake !== "ready" ? (
                  <HostedServerNotice state={status} onRetryWake={status.retryWake} onRetryStatus={status.refresh} />
                ) : (
                  <OfflineNotice state={status} onRetry={status.refresh} />
                )
              }
            />
          </main>
        </div>
      </div>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        state={status}
        onRefreshStatus={status.refresh}
        onClearHistory={chat.clearAll}
        hosted={hosted}
        creds={creds}
        providers={providers}
        section={settingsSection}
        connectors={connectors}
        onForgetAll={() => {
          creds.forgetAll();
          chat.clearAll();
        }}
      />
      </AppActionsProvider>
    </TooltipProvider>
  );
}
