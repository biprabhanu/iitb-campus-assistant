"use client";
import { useState } from "react";
import { Check, MessageSquare, Pencil, Plus, Settings, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { groupConversations } from "@/lib/history";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/lib/types";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  mobileOpen: boolean;
  desktopOpen: boolean;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
}

/** One row in the chat list, with inline rename and a two-step delete. */
function ChatRow({
  conv,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  conv: Conversation;
  active: boolean;
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const [mode, setMode] = useState<"view" | "rename" | "confirm">("view");
  const [draft, setDraft] = useState(conv.title);

  if (mode === "rename") {
    const save = () => {
      onRename(draft);
      setMode("view");
    };
    return (
      <input
        autoFocus
        aria-label="Rename chat"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") setMode("view");
        }}
        className="h-9 w-full rounded-lg border border-primary bg-background px-2.5 text-sm outline-none"
      />
    );
  }

  if (mode === "confirm") {
    return (
      <div className="flex h-9 items-center gap-1 rounded-lg bg-danger-soft pl-2.5 pr-1 text-sm">
        <span className="flex-1 truncate text-danger">Delete this chat?</span>
        <button aria-label="Confirm delete" onClick={onDelete} className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-danger hover:bg-danger/15">
          <Check className="h-4 w-4" />
        </button>
        <button aria-label="Cancel delete" onClick={() => setMode("view")} className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" />
        </button>
      </div>
    );
  }

  const iconBtn =
    "flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-border hover:text-foreground";
  return (
    <div className={cn("group/row relative flex h-9 items-center rounded-lg transition-colors duration-150", active ? "bg-muted" : "hover:bg-muted/70")}>
      <button
        type="button"
        onClick={onSelect}
        aria-current={active ? "page" : undefined}
        className="flex h-full min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-left text-sm"
      >
        <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate">{conv.title}</span>
      </button>
      <div className="absolute right-1 flex items-center gap-0.5 rounded-md bg-muted pl-1 opacity-0 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        <button aria-label={`Rename ${conv.title}`} className={iconBtn} onClick={() => { setDraft(conv.title); setMode("rename"); }}>
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button aria-label={`Delete ${conv.title}`} className={iconBtn} onClick={() => setMode("confirm")}>
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export function Sidebar(props: SidebarProps) {
  const { conversations, activeId, mobileOpen, desktopOpen, onClose, onNew, onSelect, onRename, onDelete, onOpenSettings } = props;
  const groups = groupConversations(conversations);

  return (
    <>
      {/* Dim the page behind the drawer on mobile */}
      <div
        aria-hidden
        onClick={onClose}
        className={cn("fixed inset-0 z-30 bg-black/60 transition-opacity duration-200 md:hidden", mobileOpen ? "opacity-100" : "pointer-events-none opacity-0")}
      />
      <aside
        aria-label="Chat history"
        data-testid="sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[260px] shrink-0 flex-col border-r bg-sidebar transition-[transform,margin,visibility] duration-200 md:static md:translate-x-0",
          mobileOpen ? "translate-x-0" : "invisible -translate-x-full",
          desktopOpen ? "md:visible md:ml-0" : "md:invisible md:-ml-[260px]",
        )}
      >
        <div className="p-3">
          <Button variant="outline" className="w-full justify-start rounded-xl" onClick={onNew}>
            <Plus className="h-4 w-4" aria-hidden /> New chat
          </Button>
        </div>

        <nav aria-label="Conversations" className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {groups.length === 0 && (
            <p className="px-2.5 py-3 text-sm text-muted-foreground">Your chats will show up here. They stay in this browser only.</p>
          )}
          {groups.map((g) => (
            <div key={g.name} className="mb-3">
              <h2 className="px-2.5 pb-1 pt-2 text-xs font-medium text-muted-foreground">{g.name}</h2>
              <div className="space-y-0.5">
                {g.items.map((c) => (
                  <ChatRow
                    key={c.id}
                    conv={c}
                    active={c.id === activeId}
                    onSelect={() => onSelect(c.id)}
                    onRename={(t) => onRename(c.id, t)}
                    onDelete={() => onDelete(c.id)}
                  />
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t p-2">
          <button
            type="button"
            onClick={onOpenSettings}
            className="flex h-10 w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Settings className="h-4 w-4" aria-hidden /> Settings
          </button>
        </div>
      </aside>
    </>
  );
}
