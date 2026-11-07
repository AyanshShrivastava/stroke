import { Link, useNavigate, useRouter } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Plug, LogOut, Menu, X } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { KeyLogo } from "./KeyLogo";
import { createChat, deleteChat, loadChats, localBytes, storageStatus, formatBytes, STORAGE_CAP_BYTES, wipeCache, type Chat } from "@/lib/keyboard-store";

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
  const [bytes, setBytes] = useState(0);
  useEffect(() => setBytes(localBytes()), [chats]);
  const s = storageStatus(bytes);
  return (
    <div className="space-y-2 rounded-lg border border-sidebar-border p-3">
      <div className="flex justify-between font-mono text-xs text-muted-foreground">
        <span>Local storage</span>
        <span>{formatBytes(bytes)} / {formatBytes(STORAGE_CAP_BYTES)}</span>
      </div>
      <Progress value={Math.max(0.5, s.ratio * 100)} className="h-1.5" />
      {s.warn && <p className="text-xs text-destructive">Near the 1 GB cap — offload history to Cloud in Integrations.</p>}
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
    // Termination wipe: remove the cache indicator when the app closes.
    const onClose = () => wipeCache();
    window.addEventListener("pagehide", onClose);
    return () => window.removeEventListener("pagehide", onClose);
  }, []);

  async function signOut() {
    await qc.cancelQueries();
    qc.clear();
    wipeCache();
    await supabase.auth.signOut();
    navigate({ to: "/auth", replace: true });
    router.invalidate();
  }

  const sidebar = (
    <aside className="flex h-full w-72 flex-col gap-3 border-r border-sidebar-border bg-sidebar p-3 text-sidebar-foreground">
      <div className="flex items-center gap-2 px-1 py-2">
        <KeyLogo /><span className="font-bold">Stroke</span>
        <button className="ml-auto md:hidden" onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
      </div>
      <Button className="justify-start font-mono" onClick={() => { const c = createChat(); setOpen(false); navigate({ to: "/chat/$chatId", params: { chatId: c.id } }); }}>
        <Plus className="h-4 w-4" /> New chat
      </Button>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {chats.map((c) => (
          <div key={c.id} className={`group flex items-center rounded-md ${c.id === activeId ? "bg-sidebar-accent" : "hover:bg-sidebar-accent"}`}>
            <Link to="/chat/$chatId" params={{ chatId: c.id }} onClick={() => setOpen(false)} className="flex-1 truncate px-3 py-2 text-sm">{c.title}</Link>
            <button aria-label="Delete chat" className="px-2 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100"
              onClick={() => { deleteChat(c.id); if (c.id === activeId) navigate({ to: "/chat" }); }}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
      <StorageMeter />
      <Link to="/integrations" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-sidebar-accent"><Plug className="h-4 w-4" /> Integrations</Link>
      <button onClick={signOut} className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-sidebar-accent"><LogOut className="h-4 w-4" /> Sign out</button>
    </aside>
  );

  return (
    <div className="flex h-screen bg-background">
      <div className="hidden md:block">{sidebar}</div>
      {open && <div className="fixed inset-0 z-40 flex md:hidden">{sidebar}<div className="flex-1 bg-background/70" onClick={() => setOpen(false)} /></div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border p-3 md:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <span className="font-bold">Stroke</span>
        </div>
        {children}
      </div>
    </div>
  );
}
