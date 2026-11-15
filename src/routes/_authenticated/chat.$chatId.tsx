/**
 * ARCHITECTURE NOTICE:
 * Consolidated React/TanStack client interface communicating with the authoritative
 * Python FastAPI backend at http://127.0.0.1:8501 (via /api/ai/chat and system endpoints).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Archive,
  Cpu,
  Copy,
  Check,
  PanelRightClose,
  PanelRightOpen,
  Sparkles,
  Layers,
  Wrench,
  Bot,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { AppShell } from "@/components/keyboard/AppShell";
import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { Composer } from "@/components/chat/Composer";
import {
  compactMessages,
  fetchAiFull,
  getChat,
  newMsg,
  upsertChat,
  saveUserPreferences,
  type Chat,
  type ChatMsg,
  type Attachment,
} from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/chat/$chatId")({
  head: () => ({
    meta: [
      { title: "Chat — Stroke" },
      { name: "description", content: "Work with the Builder Core agent." },
    ],
  }),
  component: ChatPage,
});

function ChatPage() {
  const { chatId } = Route.useParams();
  return (
    <AppShell activeId={chatId}>
      <ChatWindow key={chatId} chatId={chatId} />
    </AppShell>
  );
}

type Note = { id: string; content: string; created_at: string };

function ChatWindow({ chatId }: { chatId: string }) {
  const [chat, setChat] = useState<Chat | null>(() => getChat(chatId) ?? null);
  const [thinking, setThinking] = useState(false);
  const [liveElapsed, setLiveElapsed] = useState(0);
  const [notes, setNotes] = useState<Note[]>([]);
  const [nextSync, setNextSync] = useState(30);
  const [showArchivist, setShowArchivist] = useState(false);
  const [selectedModel, setSelectedModel] = useState<string>(() => chat?.model || "llama3.2-local");
  const [reasoningLevel, setReasoningLevel] = useState<string>(
    () => chat?.reasoningLevel || "medium",
  );

  const chatRef = useRef(chat);
  chatRef.current = chat;
  const abortControllerRef = useRef<AbortController | null>(null);
  const syncInProgressRef = useRef(false);
  const endRef = useRef<HTMLDivElement>(null);

  // Auto scroll to latest message
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.length, thinking]);

  // Live timer while thinking
  useEffect(() => {
    if (!thinking) {
      setLiveElapsed(0);
      return;
    }
    const start = Date.now();
    const interval = setInterval(() => {
      setLiveElapsed((Date.now() - start) / 1000);
    }, 100);
    return () => clearInterval(interval);
  }, [thinking]);

  // Load local archive notes
  useEffect(() => {
    const c = chatRef.current;
    if (c && c.notes) {
      setNotes(c.notes);
    }
  }, [chatId]);

  // Agent 2 — Archivist: background rules sync using stable message ID cursor
  useEffect(() => {
    let left = 30;
    const t = setInterval(async () => {
      left -= 1;
      setNextSync(left);
      if (left > 0) return;
      left = 30;
      setNextSync(30);

      const c = chatRef.current;
      if (!c || syncInProgressRef.current) return;

      // Extract unarchived messages using stable ID cursor
      let fresh: ChatMsg[] = [];
      if (!c.lastArchivedId) {
        fresh = c.messages;
      } else {
        const lastIdx = c.messages.findIndex((m) => m.id === c.lastArchivedId);
        fresh = lastIdx >= 0 ? c.messages.slice(lastIdx + 1) : c.messages;
      }

      if (fresh.length === 0) return;

      const result = compactMessages(fresh, c.notes || []);
      if (!result) return;

      syncInProgressRef.current = true;
      try {
        const newNote: Note = {
          id: `note-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          content: result.content,
          created_at: new Date().toISOString(),
        };

        const lastProcessedId =
          result.archivedIds[result.archivedIds.length - 1] || fresh[fresh.length - 1].id;

        const updated: Chat = {
          ...c,
          lastArchivedId: lastProcessedId,
          archivedMessageIds: Array.from(
            new Set([...(c.archivedMessageIds || []), ...result.archivedIds]),
          ),
          notes: [newNote, ...(c.notes || [])],
        };

        upsertChat(updated);
        setChat(updated);
        setNotes((n) => [newNote, ...n]);
      } catch {
        // Silently skip if persistence fails
      } finally {
        syncInProgressRef.current = false;
      }
    }, 1000);
    return () => clearInterval(t);
  }, [notes]);

  function handleModelChange(modelId: string) {
    setSelectedModel(modelId);
    saveUserPreferences({ model: modelId, reasoningLevel });
    if (chat) {
      const updated = { ...chat, model: modelId };
      setChat(updated);
      upsertChat(updated);
    }
  }

  function handleReasoningChange(level: string) {
    setReasoningLevel(level);
    saveUserPreferences({ model: selectedModel, reasoningLevel: level });
    if (chat) {
      const updated = { ...chat, reasoningLevel: level };
      setChat(updated);
      upsertChat(updated);
    }
  }

  function handleStop() {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setThinking(false);
    toast.info("Inference generation stopped.");
  }

  async function handleSend(text: string, attachments: Attachment[]) {
    if (!chat || thinking) return;

    const userMsg = newMsg("user", text, { attachments });
    const nextChat: Chat = {
      ...chat,
      title: chat.messages.length === 0 ? text.slice(0, 36) || "New Conversation" : chat.title,
      updatedAt: Date.now(),
      messages: [...chat.messages, userMsg],
      model: selectedModel,
      reasoningLevel,
    };

    setChat(nextChat);
    upsertChat(nextChat);
    setThinking(true);

    try {
      const res = await fetchAiFull({
        prompt: text,
        history: nextChat.messages,
        model: selectedModel,
        reasoningLevel,
        attachments,
        sessionId: chatId,
      });

      const current = chatRef.current || nextChat;

      if (res.status === "error") {
        const errorMsg: ChatMsg = newMsg("builder", "", {
          status: "error",
          errorMessage: res.errorMessage || "Backend returned an inference error.",
          executionSteps: res.execution_steps,
          taskState: "failed",
          model: selectedModel,
        });
        const finalChat = {
          ...current,
          updatedAt: Date.now(),
          messages: [...current.messages, errorMsg],
        };
        setChat(finalChat);
        upsertChat(finalChat);
        toast.error(res.errorMessage || "Failed to query Stroke backend");
        return;
      }

      const builderMsg: ChatMsg = newMsg("builder", res.message, {
        status: "sent",
        executionSteps: res.execution_steps,
        codingLoop: res.coding_loop,
        taskId: res.task_id,
        taskState: res.task_state,
        taskBudget: res.task_budget,
        durationSeconds: res.duration_seconds,
        model: res.model || selectedModel,
        provider: res.provider,
        sources: res.sources,
        godTierVfxLearned: res.god_tier_vfx_learned,
        learnedVfxName: res.learned_vfx_name,
      });

      const finalChat = {
        ...current,
        updatedAt: Date.now(),
        messages: [...current.messages, builderMsg],
      };
      setChat(finalChat);
      upsertChat(finalChat);

      if (res.god_tier_vfx_learned && res.learned_vfx_name) {
        toast.success(`God-Tier VFX pattern learned: ${res.learned_vfx_name}`);
      }
    } catch (err) {
      toast.error("Failed to query Stroke backend");
    } finally {
      setThinking(false);
    }
  }

  async function handleRetry(errorMsgId: string) {
    if (!chat || thinking) return;
    const msgs = chat.messages;
    const errIdx = msgs.findIndex((m) => m.id === errorMsgId);
    if (errIdx < 0) return;

    let userPrompt = "";
    let atts: Attachment[] = [];
    for (let i = errIdx - 1; i >= 0; i--) {
      if (msgs[i].role === "user") {
        userPrompt = msgs[i].text;
        atts = msgs[i].attachments || [];
        break;
      }
    }

    if (!userPrompt) {
      toast.error("Cannot retry: preceding user prompt not found.");
      return;
    }

    // Clean out the failed error message
    const cleanedMsgs = msgs.filter((m) => m.id !== errorMsgId);
    const updated = {
      ...chat,
      messages: cleanedMsgs,
      updatedAt: Date.now(),
    };
    setChat(updated);
    upsertChat(updated);

    // Re-execute
    setThinking(true);
    try {
      const res = await fetchAiFull({
        prompt: userPrompt,
        history: cleanedMsgs,
        model: selectedModel,
        reasoningLevel,
        attachments: atts,
        sessionId: chatId,
      });

      if (res.status === "error") {
        const errRetryMsg: ChatMsg = newMsg("builder", "", {
          status: "error",
          errorMessage: res.errorMessage || "Retry failed: backend returned error.",
          executionSteps: res.execution_steps,
          taskState: "failed",
          model: selectedModel,
        });
        const finalErrChat = {
          ...updated,
          updatedAt: Date.now(),
          messages: [...cleanedMsgs, errRetryMsg],
        };
        setChat(finalErrChat);
        upsertChat(finalErrChat);
        toast.error(res.errorMessage || "Retry failed");
        return;
      }

      const builderMsg: ChatMsg = newMsg("builder", res.message, {
        status: "sent",
        executionSteps: res.execution_steps,
        codingLoop: res.coding_loop,
        taskId: res.task_id,
        taskState: res.task_state,
        taskBudget: res.task_budget,
        durationSeconds: res.duration_seconds,
        model: res.model || selectedModel,
        provider: res.provider,
        sources: res.sources,
        godTierVfxLearned: res.god_tier_vfx_learned,
        learnedVfxName: res.learned_vfx_name,
      });

      const finalSuccess = {
        ...updated,
        updatedAt: Date.now(),
        messages: [...cleanedMsgs, builderMsg],
      };
      setChat(finalSuccess);
      upsertChat(finalSuccess);
    } catch {
      toast.error("Retry failed");
    } finally {
      setThinking(false);
    }
  }

  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center p-10 text-muted-foreground text-sm">
        Chat not found.{" "}
        <Link to="/chat" className="ml-1 text-primary hover:underline">
          Return to latest
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
      {/* Main Conversation Stream */}
      <div className="flex min-w-0 flex-1 flex-col h-full bg-background">
        {/* Subtle Top Header */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-border/70 px-4">
          <div className="flex items-center gap-2 overflow-hidden">
            <span className="truncate text-xs font-medium text-foreground">
              {chat.title || "New Chat"}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground border border-border/60 rounded px-1.5 py-0.2">
              {selectedModel}
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setShowArchivist(!showArchivist)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
                showArchivist
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
              title="Toggle Archivist rules panel"
            >
              <Archive className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Archivist</span>
              {notes.length > 0 && (
                <span className="rounded-full bg-primary/20 px-1.5 py-0.2 font-mono text-[10px] text-primary">
                  {notes.length}
                </span>
              )}
            </button>
          </div>
        </div>

        {/* Message History Canvas */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {chat.messages.length === 0 && (
              <div className="pt-20 text-center select-none">
                <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card shadow-xs">
                  <Sparkles className="h-6 w-6 text-primary" />
                </div>
                <h2 className="mt-4 text-xl font-semibold tracking-tight text-foreground">
                  Stroke Builder Core
                </h2>
                <p className="mt-1 text-xs text-muted-foreground max-w-md mx-auto">
                  High-performance AI engineering agent for Roblox Studio Luau, full-stack
                  architectures, and autonomous tool workflows.
                </p>

                {/* Quick starter prompts */}
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2 text-left max-w-xl mx-auto">
                  <button
                    type="button"
                    onClick={() =>
                      handleSend(
                        "Create a production-grade Luau TweenService camera shake and lighting VFX script with clean modular cleanup.",
                        [],
                      )
                    }
                    className="group rounded-xl border border-border/80 bg-card/60 p-3 hover:border-primary/50 hover:bg-card transition-all text-xs"
                  >
                    <div className="font-medium text-foreground group-hover:text-primary flex items-center gap-1.5">
                      <Sparkles className="h-3.5 w-3.5 text-primary" />
                      TweenService Camera VFX
                    </div>
                    <div className="mt-1 text-muted-foreground text-[11px]">
                      Camera shake, lighting flashes, and spring curves.
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() =>
                      handleSend(
                        "Inspect current workspace file hierarchy and report active Roblox project health.",
                        [],
                      )
                    }
                    className="group rounded-xl border border-border/80 bg-card/60 p-3 hover:border-primary/50 hover:bg-card transition-all text-xs"
                  >
                    <div className="font-medium text-foreground group-hover:text-primary flex items-center gap-1.5">
                      <Layers className="h-3.5 w-3.5 text-indigo-500" />
                      Inspect Workspace Health
                    </div>
                    <div className="mt-1 text-muted-foreground text-[11px]">
                      Analyzes project structure, scripts, and integrity.
                    </div>
                  </button>
                </div>
              </div>
            )}

            {/* Rendered Messages */}
            {chat.messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl bg-secondary px-4 py-2.5 text-foreground text-sm leading-relaxed border border-border/60 shadow-2xs">
                    {m.attachments && m.attachments.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {m.attachments.map((att, i) => (
                          <span
                            key={i}
                            className="inline-flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground border border-border/40"
                          >
                            {att.name}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="whitespace-pre-wrap">{m.text}</div>
                  </div>
                </div>
              ) : (
                <div key={m.id} className="flex items-start gap-3">
                  <div
                    className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border shadow-2xs ${
                      m.status === "error"
                        ? "border-destructive/40 bg-destructive/10 text-destructive"
                        : "border-border/70 bg-card text-primary"
                    }`}
                  >
                    {m.status === "error" ? (
                      <AlertCircle className="h-3.5 w-3.5" />
                    ) : (
                      <Cpu className="h-3.5 w-3.5" />
                    )}
                  </div>

                  {m.status === "error" ? (
                    <div className="min-w-0 flex-1 rounded-xl border border-destructive/30 bg-destructive/5 p-3.5 text-xs text-foreground space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-destructive flex items-center gap-1.5">
                          Inference Communication Failure
                        </span>
                        <span className="font-mono text-[10px] text-destructive uppercase bg-destructive/10 px-1.5 py-0.2 rounded">
                          Failed
                        </span>
                      </div>
                      <p className="font-mono text-[11px] text-muted-foreground leading-relaxed">
                        {m.errorMessage || "The model inference call could not be completed."}
                      </p>
                      {m.executionSteps && m.executionSteps.length > 0 && (
                        <ActivityFeed steps={m.executionSteps} taskState="failed" />
                      )}
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={() => handleRetry(m.id)}
                          disabled={thinking}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted text-foreground transition-colors shadow-2xs cursor-pointer"
                        >
                          <RefreshCw className="h-3 w-3" />
                          <span>Retry Message</span>
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="min-w-0 flex-1 space-y-2">
                      {/* Live Thinking / Activity Feed Attached to Assistant Message */}
                      <ActivityFeed
                        steps={m.executionSteps}
                        codingLoop={m.codingLoop}
                        durationSeconds={m.durationSeconds}
                        taskState={m.taskState}
                      />

                      {/* Rich Response Body */}
                      <Rich text={m.text} />
                    </div>
                  )}
                </div>
              ),
            )}

            {/* Live Thinking Status Placeholder */}
            {thinking && (
              <div className="flex items-start gap-3">
                <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-border bg-card text-primary">
                  <Cpu className="h-3.5 w-3.5 animate-spin text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <ActivityFeed isLiveThinking liveElapsedSeconds={liveElapsed} />
                </div>
              </div>
            )}

            <div ref={endRef} />
          </div>
        </div>

        {/* Minimalist Floating Composer Dock */}
        <div className="shrink-0 p-3 pt-0">
          <Composer
            onSend={handleSend}
            onStop={handleStop}
            isGenerating={thinking}
            selectedModel={selectedModel}
            onSelectModel={handleModelChange}
            reasoningLevel={reasoningLevel}
            onSelectReasoning={handleReasoningChange}
            placeholder="Ask Builder Core for Luau scripts, VFX, refactoring, or tools…"
          />
        </div>
      </div>

      {/* Toggleable Slide-over Archivist Sidebar */}
      {showArchivist && (
        <aside className="flex w-72 shrink-0 flex-col border-l border-border bg-sidebar select-none transition-all duration-200">
          <div className="flex h-12 items-center justify-between border-b border-border px-3">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              <Archive className="h-4 w-4 text-primary" />
              <span>Archivist Notes</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-muted-foreground">sync {nextSync}s</span>
              <button
                type="button"
                onClick={() => setShowArchivist(false)}
                className="rounded p-1 text-muted-foreground hover:text-foreground"
                title="Close notes panel"
              >
                <PanelRightClose className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
            {notes.length === 0 ? (
              <div className="p-4 text-center text-xs text-muted-foreground">
                <p>No extracted rules yet.</p>
                <p className="mt-1 text-[11px] opacity-75">
                  Rules and architecture decisions from this session are automatically compacted
                  here.
                </p>
              </div>
            ) : (
              notes.map((n) => (
                <div
                  key={n.id}
                  className="rounded-lg border border-border/80 bg-card p-2.5 text-xs shadow-2xs"
                >
                  <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground mb-1">
                    <span>ARCHIVED RULE</span>
                    <span>{new Date(n.created_at).toLocaleTimeString()}</span>
                  </div>
                  <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-foreground">
                    {n.content}
                  </pre>
                </div>
              ))
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

// Minimalist code block with 1-click copy & syntax badge
function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);

  function copyCode() {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-border/80 bg-card shadow-xs">
      <div className="flex items-center justify-between border-b border-border/60 bg-muted/40 px-3 py-1.5 text-[11px] font-mono text-muted-foreground">
        <span>{lang || "code"}</span>
        <button
          type="button"
          onClick={copyCode}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 hover:bg-muted hover:text-foreground transition-colors"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3 text-emerald-500" />
              <span className="text-emerald-500">Copied</span>
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <div className="overflow-x-auto p-3.5 font-mono text-xs leading-relaxed text-foreground">
        <code>{code}</code>
      </div>
    </div>
  );
}

// Markdown renderer with rich formatting and CodeBlock integration
function Rich({ text }: { text: string }) {
  const parts = text.split(/```(\w*)\n([\s\S]*?)```/g);
  const out = [];

  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i]) {
      out.push(
        <div
          key={i}
          className="whitespace-pre-wrap leading-relaxed text-sm text-foreground/90 space-y-2"
          dangerouslySetInnerHTML={{
            __html: esc(parts[i] ?? "")
              .replace(
                /\*\*(.+?)\*\*/g,
                "<strong class='text-foreground font-semibold'>$1</strong>",
              )
              .replace(
                /`([^`]+)`/g,
                "<code class='rounded bg-muted px-1.5 py-0.5 font-mono text-xs border border-border/40'>$1</code>",
              )
              .replace(/_(.+?)_/g, "<em>$1</em>"),
          }}
        />,
      );
    }
    if (parts[i + 2] !== undefined) {
      out.push(<CodeBlock key={i + 1} lang={parts[i + 1] || "luau"} code={parts[i + 2]} />);
    }
  }
  return <div className="min-w-0 flex-1 space-y-2 text-sm leading-relaxed">{out}</div>;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
