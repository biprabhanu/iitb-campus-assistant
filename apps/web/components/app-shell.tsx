"use client";
import { useCallback, useMemo, useState } from "react";
import { AppActionsProvider } from "@/components/app-actions";
import { ChatView } from "@/components/chat-view";
import { Composer } from "@/components/composer";
import { Header } from "@/components/header";
import { OfflineNotice } from "@/components/offline-notice";
import { SettingsDialog } from "@/components/settings-dialog";
import { Sidebar } from "@/components/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useChat } from "@/hooks/use-chat";
import { useStatus } from "@/hooks/use-status";

/** Wires the sidebar, header, message column, composer and settings together. */
export function AppShell() {
  const chat = useChat();
  const status = useStatus();
  const [settingsOpen, setSettingsOpen] = useState(false);
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
  const openSettings = useCallback(() => setSettingsOpen(true), []);

  const actions = useMemo(() => ({ openSettings }), [openSettings]);

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
            setSettingsOpen(true);
            closeMobile();
          }}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header state={status} waking={chat.waking} onToggleSidebar={toggleSidebar} onOpenSettings={openSettings} />
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
            />
            <Composer
              onSend={chat.send}
              onStop={chat.stop}
              streaming={chat.isStreaming}
              focusKey={chat.activeId}
              notice={<OfflineNotice state={status} onRetry={status.refresh} />}
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
      />
      </AppActionsProvider>
    </TooltipProvider>
  );
}
