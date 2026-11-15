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
  Folder,
  Settings,
  ChevronRight,
  Search,
  PanelLeftClose,
  PanelLeft,
  Loader2,
  Terminal,
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

function formatRelativeTime(ts?: number): string {
  if (!ts) return "";
  const diffSec = Math.floor((Date.now() - ts) / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
  const days = Math.floor(diffSec / 86400);
  return `${days}d`;
}

export function StorageMeter() {
  const chats = useChats();
  const [diag, setDiag] = useState<StorageDiagnostics | null>(null);

  useEffect(() => {
    getStorageDiagnostics().then((d) => setDiag(d));
  }, [chats]);

  return (
    <div className="space-y-1.5 rounded-lg border border-sidebar-border/60 bg-sidebar-accent/20 p-2.5">
      <div className="flex items-center justify-between font-mono text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <HardDrive className="h-3 w-3 opacity-70" />
          <span>Local Storage</span>
        </span>
        <span>
          {diag ? diag.usageFormatted : "Estimating…"}
        </span>
      </div>
      <Progress value={diag ? Math.max(1, diag.usagePercent) : 1} className="h-1" />
      <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono">
        <span>{diag?.engine || "IndexedDB"}</span>
        <Link to="/integrations" className="hover:text-foreground underline">
          Details
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
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearch, setShowSearch] = useState(false);

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

  const filteredChats = searchQuery.trim()
    ? chats.filter((c) => (c.title || "").toLowerCase().includes(searchQuery.toLowerCase()))
    : chats;

  const sidebar = (
    <aside className="flex h-full w-64 flex-col gap-2 border-r border-sidebar-border bg-sidebar p-2.5 text-sidebar-foreground select-none font-sans">
      {/* 1. Brand & Quick Controls */}
      <div className="flex items-center justify-between px-1.5 py-1">
        <div className="flex items-center gap-2">
          <KeyLogo size="sm" />
          <span className="font-semibold text-xs tracking-tight text-foreground">Stroke</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setShowSearch(!showSearch)}
            className="rounded p-1 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Search conversations"
          >
            <Search className="h-3.5 w-3.5" />
          </button>
          <button
            className="rounded p-1 text-muted-foreground hover:text-foreground md:hidden cursor-pointer"
            onClick={() => setOpen(false)}
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Quick Search Bar (Collapsible) */}
      {showSearch && (
        <div className="px-1 py-0.5 animate-in fade-in duration-150">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search chats…"
            className="w-full rounded-md border border-sidebar-border bg-background px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </div>
      )}

      {/* 2. New Conversation Capsule Button */}
      <button
        type="button"
        onClick={handleNewChat}
        className="flex w-full items-center justify-between rounded-lg border border-sidebar-border/80 bg-background/80 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-sidebar-accent transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-2">
          <Plus className="h-3.5 w-3.5 opacity-80" />
          <span>New Conversation</span>
        </span>
        <kbd className="font-mono text-[9px] text-muted-foreground bg-muted/60 px-1 py-0.2 rounded border border-border/40">
          ⌘K
        </kbd>
      </button>

      {/* 3. Projects Section */}
      <div className="px-1 pt-1">
        <div className="flex items-center justify-between py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <span>Projects</span>
        </div>
        <div className="mt-0.5 rounded-lg border border-sidebar-border/40 bg-sidebar-accent/15 px-2 py-1.5 text-xs">
          <div className="flex items-center gap-1.5 text-foreground font-medium">
            <Folder className="h-3.5 w-3.5 text-primary opacity-80" />
            <span className="truncate">stroke</span>
          </div>
          <div className="mt-0.5 text-[10px] text-muted-foreground font-mono truncate">
            Desktop AI Workspace
          </div>
        </div>
      </div>

      {/* 4. Conversations List Section */}
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1 pt-1">
        <div className="flex items-center justify-between py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <span>Conversations</span>
          <button
            type="button"
            onClick={handleNewChat}
            className="rounded p-0.5 hover:text-foreground text-muted-foreground cursor-pointer"
            title="Create conversation"
          >
            <Plus className="h-3 w-3" />
          </button>
        </div>

        {filteredChats.length === 0 ? (
          <div className="py-6 text-center text-xs text-muted-foreground">
            {searchQuery ? "No matching conversations." : "No conversations yet."}
          </div>
        ) : (
          filteredChats.map((c) => {
            const isActive = c.id === activeId;
            const isSyncing = c.isSyncing;
            return (
              <div
                key={c.id}
                className={`group flex items-center justify-between rounded-md px-2 py-1.5 text-xs transition-colors ${
                  isActive
                    ? "bg-sidebar-accent text-foreground font-medium"
                    : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground"
                }`}
              >
                <Link
                  to="/chat/$chatId"
                  params={{ chatId: c.id }}
                  onClick={() => setOpen(false)}
                  className="flex min-w-0 flex-1 items-center gap-2"
                >
                  {isSyncing ? (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
                  ) : (
                    <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  )}
                  <span className="truncate">{c.title || "Untitled Session"}</span>
                </Link>

                <div className="flex items-center gap-1 shrink-0 ml-1">
                  <span className="font-mono text-[10px] text-muted-foreground/70 group-hover:hidden">
                    {formatRelativeTime(c.updatedAt)}
                  </span>
                  <button
                    type="button"
                    aria-label="Delete chat"
                    className="hidden group-hover:inline-flex rounded p-0.5 hover:text-destructive transition-colors cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteChat(c.id);
                      if (c.id === activeId) navigate({ to: "/chat" });
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 5. Storage Meter */}
      <StorageMeter />

      {/* 6. Bottom Navigation & Action Bar */}
      <div className="space-y-1 pt-1 border-t border-sidebar-border/60">
        <div className="flex items-center justify-between">
          <ThemeToggle />
          <div className="flex items-center gap-1">
            <Link
              to="/agents"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="Parallel Agent Orchestrator"
            >
              <Bot className="h-3.5 w-3.5 opacity-80" />
              <span>Agents</span>
            </Link>
            <Link
              to="/models"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="AI Models & BYOK Keys"
            >
              <Cpu className="h-3.5 w-3.5 opacity-80" />
              <span>Models</span>
            </Link>
            <Link
              to="/integrations"
              onClick={() => setOpen(false)}
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
              title="Settings & Integrations"
            >
              <Settings className="h-3.5 w-3.5 opacity-80" />
              <span>Settings</span>
            </Link>
          </div>
        </div>

        <button
          type="button"
          onClick={signOut}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-sidebar-accent hover:text-destructive transition-colors cursor-pointer"
        >
          <LogOut className="h-3.5 w-3.5 opacity-70" />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground font-sans">
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
        <div className="flex items-center justify-between border-b border-border px-3 py-2 md:hidden">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open navigation menu"
              className="rounded p-1 text-muted-foreground hover:text-foreground cursor-pointer"
            >
              <Menu className="h-5 w-5" />
            </button>
            <KeyLogo size="sm" />
            <span className="font-semibold text-xs">Stroke</span>
          </div>
          <button
            type="button"
            onClick={handleNewChat}
            className="rounded p-1 text-primary hover:bg-muted cursor-pointer"
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
