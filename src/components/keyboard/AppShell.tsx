import { Link, useNavigate, useRouter } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  SlidersHorizontal,
  LogOut,
  Menu,
  X,
  MessageSquare,
  HardDrive,
  Cpu,
  Bot,
} from "lucide-react";
import { auth, signOut as firebaseSignOut } from "@/lib/firebase";
import { KeyLogo } from "./KeyLogo";
import { ThemeToggle } from "./ThemeToggle";
import { Progress } from "@/components/ui/progress";
import {
  createChat,
  deleteChat,
  loadChats,
  getStorageDiagnostics,
  wipeCache,
  type Chat,
} from "@/lib/keyboard-store";
import type { StorageDiagnostics } from "@/lib/idb-storage";

export function useChats() {
  const [chats, setChats] = useState<Chat[]>([]);
  useEffect(() => {
    const r = () => setChats(loadChats());
    r();
    window.addEventListener("keyboard:chats", r);
    return () => window.removeEventListener("keyboard:chats", r);
  }, []);
  return chats;
}

export function StorageMeter() {
  const chats = useChats();
  const [diag, setDiag] = useState<StorageDiagnostics | null>(null);

  useEffect(() => {
    getStorageDiagnostics().then((d) => setDiag(d));
  }, [chats]);

  return (
    <div className="space-y-1.5 rounded-lg border border-sidebar-border/60 bg-sidebar-accent/30 p-2.5">
      <div className="flex items-center justify-between font-mono text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <HardDrive className="h-3 w-3" />
          <span>Local Storage</span>
        </span>
        <span>
          {diag ? diag.usageFormatted : "Estimating…"}
          {diag && diag.quotaReported ? ` / ${diag.quotaFormatted}` : ""}
        </span>
      </div>
      <Progress value={diag ? Math.max(1, diag.usagePercent) : 1} className="h-1" />
      <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono">
        <span>Engine: {diag?.engine || "IndexedDB"}</span>
        <Link to="/integrations" className="hover:text-foreground underline">
          Export / Clear
        </Link>
      </div>
    </div>
  );
}

export function AppShell({ activeId, children }: { activeId?: string; children: ReactNode }) {
  const chats = useChats();
  const navigate = useNavigate();
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onClose = () => wipeCache();
    window.addEventListener("pagehide", onClose);
    return () => window.removeEventListener("pagehide", onClose);
  }, []);

  async function signOut() {
    await qc.cancelQueries();
    qc.clear();
    wipeCache();
    await firebaseSignOut(auth);
    navigate({ to: "/auth", replace: true });
    router.invalidate();
  }

  function handleNewChat() {
    const c = createChat();
    setOpen(false);
    navigate({ to: "/chat/$chatId", params: { chatId: c.id } });
  }

  const sidebar = (
    <aside className="flex h-full w-64 flex-col gap-2.5 border-r border-sidebar-border bg-sidebar p-3 text-sidebar-foreground select-none">
      {/* Brand Header */}
      <div className="flex items-center justify-between px-1 py-1">
        <div className="flex items-center gap-2">
          <KeyLogo size="sm" />
          <span className="font-semibold text-sm tracking-tight text-foreground">Stroke</span>
        </div>
        <button
          className="rounded p-1 text-muted-foreground hover:text-foreground md:hidden"
          onClick={() => setOpen(false)}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* New Chat Button */}
      <button
        type="button"
        onClick={handleNewChat}
        className="flex w-full items-center justify-between rounded-lg border border-sidebar-border bg-background px-3 py-2 text-xs font-medium text-foreground shadow-xs hover:bg-sidebar-accent transition-colors"
      >
        <span className="flex items-center gap-2">
          <Plus className="h-3.5 w-3.5 text-primary" />
          <span>New Chat</span>
        </span>
        <kbd className="font-mono text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
          ⌘K
        </kbd>
      </button>

      {/* Conversations List */}
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
        <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Recent Chats
        </div>
        {chats.length === 0 ? (
          <div className="px-2 py-4 text-center text-xs text-muted-foreground">
            No chats yet. Start a new one!
          </div>
        ) : (
          chats.map((c) => {
            const isActive = c.id === activeId;
            return (
              <div
                key={c.id}
                className={`group flex items-center justify-between rounded-lg px-2 py-1.5 transition-colors ${
                  isActive
                    ? "bg-sidebar-accent text-foreground font-medium"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
                }`}
              >
                <Link
                  to="/chat/$chatId"
                  params={{ chatId: c.id }}
                  onClick={() => setOpen(false)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-xs"
                >
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-70" />
                  <span className="truncate">{c.title || "Untitled Chat"}</span>
                </Link>
                <button
                  type="button"
                  aria-label="Delete chat"
                  className="ml-1 opacity-0 group-hover:opacity-100 rounded p-1 hover:text-destructive transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteChat(c.id);
                    if (c.id === activeId) navigate({ to: "/chat" });
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Storage Status */}
      <StorageMeter />

      {/* Bottom Action Bar */}
      <div className="space-y-1 pt-1 border-t border-sidebar-border/60">
        <div className="flex items-center justify-between">
          <ThemeToggle />
          <div className="flex items-center gap-1">
            <Link
              to="/agents"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="Parallel Multi-Agent Team"
            >
              <Bot className="h-3.5 w-3.5" />
              <span>Agents</span>
            </Link>
            <Link
              to="/models"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="AI Models & BYOK Providers"
            >
              <Cpu className="h-3.5 w-3.5" />
              <span>Models</span>
            </Link>
            <Link
              to="/integrations"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="Settings & Integrations"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              <span>Settings</span>
            </Link>
          </div>
        </div>

        <button
          type="button"
          onClick={signOut}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-destructive transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      {/* Desktop Sidebar */}
      <div className="hidden md:block h-full shrink-0">{sidebar}</div>

      {/* Mobile Sidebar Overlay */}
      {open && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="relative z-50 h-full">{sidebar}</div>
          <div
            className="flex-1 bg-background/80 backdrop-blur-xs"
            onClick={() => setOpen(false)}
          />
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
        {/* Mobile Top Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5 md:hidden">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open navigation menu"
              className="rounded p-1 text-muted-foreground hover:text-foreground"
            >
              <Menu className="h-5 w-5" />
            </button>
            <KeyLogo size="sm" />
            <span className="font-semibold text-sm">Stroke</span>
          </div>
          <button
            type="button"
            onClick={handleNewChat}
            className="rounded p-1 text-primary hover:bg-muted"
            title="New Chat"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>

        {children}
      </div>
    </div>
  );
}
