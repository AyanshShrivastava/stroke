/**
 * ARCHITECTURE NOTICE:
 * This TanStack Router client represents an experimental web view with mock replies.
 * The production desktop client for Stroke is canonicalized in desktop.py (FastAPI backend +
 * PyWebView Cyberpunk matrix interface at http://127.0.0.1:8501) with local GGUF neural inference.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ArrowUp, Archive, Cpu } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AppShell } from "@/components/keyboard/AppShell";
import { compactMessages, fakeReply, getChat, loadIngest, newMsg, upsertChat, type Chat } from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/chat/$chatId")({
  head: () => ({ meta: [{ title: "Chat — Stroke" }, { name: "description", content: "Work with the Builder Core agent." }] }),
  component: ChatPage,
});

function ChatPage() {
  const { chatId } = Route.useParams();
  return <AppShell activeId={chatId}><ChatWindow key={chatId} chatId={chatId} /></AppShell>;
}

type Note = { id: string; content: string; created_at: string };

function ChatWindow({ chatId }: { chatId: string }) {
  const [chat, setChat] = useState<Chat | null>(() => getChat(chatId) ?? null);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const [nextSync, setNextSync] = useState(30);
  const chatRef = useRef(chat);
  chatRef.current = chat;
  const taRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { taRef.current?.focus(); }, [thinking]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chat?.messages.length, thinking]);

  useEffect(() => {
    supabase.from("archive_notes").select("id,content,created_at").eq("chat_id", chatId).order("created_at", { ascending: false })
      .then(({ data, error }) => { if (error) console.error(error); else setNotes(data ?? []); });
  }, [chatId]);

  // Agent 2 — Archivist: compacts new messages every 30s and syncs to Cloud.
  useEffect(() => {
    let left = 30;
    const t = setInterval(async () => {
      left -= 1; setNextSync(left);
      if (left > 0) return;
      left = 30; setNextSync(30);
      const c = chatRef.current;
      if (!c) return;
      const fresh = c.messages.slice(c.archivedUpTo);
      const content = compactMessages(fresh);
      if (!content) return;
      const { data, error } = await supabase.from("archive_notes").insert({ chat_id: c.id, content }).select("id,content,created_at").single();
      if (error) { toast.error("Archivist sync failed"); return; }
      const updated = { ...c, archivedUpTo: c.messages.length };
      upsertChat(updated); setChat(updated);
      setNotes((n) => [data, ...n]);
    }, 1000);
    return () => clearInterval(t);
  }, []);

  if (!chat) return <div className="p-10 text-muted-foreground">Chat not found. <Link to="/chat" className="text-primary">Open latest</Link></div>;

  function send() {
    const text = input.trim();
    if (!text || thinking || !chat) return;
    const userMsg = newMsg("user", text);
    const next = { ...chat, title: chat.messages.length ? chat.title : text.slice(0, 40), updatedAt: Date.now(), messages: [...chat.messages, userMsg] };
    setChat(next); upsertChat(next); setInput(""); setThinking(true);
    setTimeout(() => {
      const c = chatRef.current!;
      const done = { ...c, updatedAt: Date.now(), messages: [...c.messages, newMsg("builder", fakeReply(text, loadIngest()))] };
      setChat(done); upsertChat(done); setThinking(false);
    }, 900);
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {chat.messages.length === 0 && (
              <div className="pt-20 text-center">
                <Cpu className="mx-auto h-10 w-10 text-primary" />
                <h2 className="mt-4 text-2xl font-bold">Builder Core is ready</h2>
                <p className="mt-2 text-sm text-muted-foreground">Ask for Luau VFX, TweenService curves, or any Python / C++ / JS work.</p>
              </div>
            )}
            {chat.messages.map((m) => m.role === "user" ? (
              <div key={m.id} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-primary-foreground">{m.text}</div>
            ) : (
              <div key={m.id} className="flex gap-3"><div className="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-md border border-border bg-secondary"><Cpu className="h-4 w-4 text-primary" /></div><Rich text={m.text} /></div>
            ))}
            {thinking && <div className="font-mono text-sm text-muted-foreground animate-pulse">Builder Core is thinking…</div>}
            <div ref={endRef} />
          </div>
        </div>
        <div className="border-t border-border p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-input bg-card p-2">
            <Textarea ref={taRef} value={input} onChange={(e) => setInput(e.target.value)} placeholder="Message Builder Core…" rows={1}
              className="max-h-40 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <Button size="icon" onClick={send} disabled={!input.trim() || thinking} aria-label="Send"><ArrowUp className="h-4 w-4" /></Button>
          </div>
        </div>
      </div>
      <aside className="hidden w-72 flex-col border-l border-border bg-sidebar lg:flex">
        <div className="flex items-center gap-2 border-b border-border p-3">
          <Archive className="h-4 w-4 text-accent" /><span className="text-sm font-semibold">Archivist</span>
          <span className="ml-auto font-mono text-xs text-muted-foreground">sync in {nextSync}s</span>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-3">
          {notes.length === 0 && <p className="text-xs text-muted-foreground">Rules and decisions from this chat will appear here, saved to your Cloud profile.</p>}
          {notes.map((n) => (
            <div key={n.id} className="rounded-md border border-border bg-card p-2">
              <div className="font-mono text-[10px] text-muted-foreground">{new Date(n.created_at).toLocaleTimeString()}</div>
              <pre className="mt-1 whitespace-pre-wrap font-mono text-xs">{n.content}</pre>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

function Rich({ text }: { text: string }) {
  const parts = text.split(/```(\w*)\n([\s\S]*?)```/g);
  const out = [];
  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i]) out.push(<p key={i} className="whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: esc(parts[i] ?? "").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/_(.+?)_/g, "<em>$1</em>") }} />);
    if (parts[i + 2] !== undefined) out.push(<pre key={i + 1} className="overflow-x-auto rounded-lg border border-border bg-card p-3 font-mono text-xs"><code>{parts[i + 2]}</code></pre>);
  }
  return <div className="min-w-0 flex-1 space-y-3 text-sm leading-relaxed">{out}</div>;
}
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
