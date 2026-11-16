import React, { useEffect, useRef, useState } from "react";
import {
  Terminal as TerminalIcon,
  Play,
  Square,
  Trash2,
  RotateCcw,
  X,
  Maximize2,
  Minimize2,
  ChevronRight,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import {
  createTerminalSession,
  listTerminalSessions,
  runTerminalCommand,
  readTerminalOutputDelta,
  stopTerminalSession,
  respondTerminalApproval,
  type TerminalSessionInfo,
  type TerminalOutputLine,
} from "@/lib/terminal-api";

interface TerminalPanelProps {
  isOpen: boolean;
  onClose: () => void;
  defaultWorkspace?: string;
}

export function TerminalPanel({ isOpen, onClose, defaultWorkspace }: TerminalPanelProps) {
  const [session, setSession] = useState<TerminalSessionInfo | null>(null);
  const [outputLines, setOutputLines] = useState<TerminalOutputLine[]>([]);
  const [commandInput, setCommandInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [pendingApproval, setPendingApproval] = useState<{
    id: string;
    command: string;
  } | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  const consoleEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const nextSeqRef = useRef<number>(0);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Initialize or fetch session when panel opens
  useEffect(() => {
    if (!isOpen) return;

    let active = true;

    async function initSession() {
      if (session) return;
      setIsInitializing(true);
      try {
        const existing = await listTerminalSessions();
        if (active && existing.length > 0) {
          setSession(existing[0]);
          setOutputLines([
            {
              seq: 0,
              text: `Connected to existing session [${existing[0].session_id.slice(0, 8)}] in ${existing[0].workspace_path}`,
              stream: "system",
            },
          ]);
        } else {
          const created = await createTerminalSession(defaultWorkspace);
          if (active) {
            setSession(created);
            setOutputLines([
              {
                seq: 0,
                text: `Initialized persistent Stroke terminal session [${created.session_id.slice(0, 8)}]`,
                stream: "system",
              },
            ]);
          }
        }
      } catch (err: unknown) {
        if (active) {
          const errMsg = err instanceof Error ? err.message : String(err);
          setOutputLines([
            {
              seq: 0,
              text: `Error initializing terminal: ${errMsg}`,
              stream: "stderr",
            },
          ]);
        }
      } finally {
        if (active) setIsInitializing(false);
      }
    }

    initSession();

    return () => {
      active = false;
    };
  }, [isOpen]);

  // Delta polling loop for output streaming
  useEffect(() => {
    if (!isOpen || !session?.session_id) return;

    async function poll() {
      if (!session?.session_id) return;
      try {
        const delta = await readTerminalOutputDelta(session.session_id, nextSeqRef.current);
        if (delta.lines.length > 0) {
          nextSeqRef.current = delta.next_seq;
          setOutputLines((prev) => [...prev, ...delta.lines]);
        }
        setIsRunning(delta.is_running);
      } catch {
        // Silently skip transient polling drops
      }
    }

    pollingRef.current = setInterval(poll, 600);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [isOpen, session?.session_id]);

  // Auto-scroll to bottom of console
  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [outputLines.length]);

  // Focus input on open
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [isOpen]);

  async function handleExecute(cmdToRun?: string) {
    const cmd = (cmdToRun !== undefined ? cmdToRun : commandInput).trim();
    if (!cmd || !session?.session_id || isRunning) return;

    // Append to local history
    setHistory((prev) => [cmd, ...prev.filter((h) => h !== cmd)]);
    setHistoryIndex(-1);
    setCommandInput("");

    // Append user input to console log
    setOutputLines((prev) => [
      ...prev,
      {
        seq: nextSeqRef.current++,
        text: `$ ${cmd}`,
        stream: "system",
      },
    ]);

    setIsRunning(true);
    try {
      const res = await runTerminalCommand(session.session_id, cmd);
      if (res.requires_approval && res.approval_id) {
        setPendingApproval({ id: res.approval_id, command: cmd });
        setOutputLines((prev) => [
          ...prev,
          {
            seq: nextSeqRef.current++,
            text: `[SECURITY] Command requires approval: '${cmd}'`,
            stream: "system",
          },
        ]);
      } else if (res.status === "error") {
        setOutputLines((prev) => [
          ...prev,
          {
            seq: nextSeqRef.current++,
            text: res.message || "Command execution error",
            stream: "stderr",
          },
        ]);
      } else {
        if (res.stdout) {
          setOutputLines((prev) => [
            ...prev,
            { seq: nextSeqRef.current++, text: res.stdout!, stream: "stdout" },
          ]);
        }
        if (res.stderr) {
          setOutputLines((prev) => [
            ...prev,
            { seq: nextSeqRef.current++, text: res.stderr!, stream: "stderr" },
          ]);
        }
        setOutputLines((prev) => [
          ...prev,
          {
            seq: nextSeqRef.current++,
            text: `Process finished with exit code ${res.exit_code ?? 0} (${((res.duration_sec ?? 0) * 1000).toFixed(0)}ms)`,
            stream: "system",
          },
        ]);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setOutputLines((prev) => [
        ...prev,
        {
          seq: nextSeqRef.current++,
          text: `Execution failed: ${errMsg}`,
          stream: "stderr",
        },
      ]);
    } finally {
      setIsRunning(false);
    }
  }

  async function handleApproval(approved: boolean) {
    if (!pendingApproval) return;
    const { id, command } = pendingApproval;
    setPendingApproval(null);

    setOutputLines((prev) => [
      ...prev,
      {
        seq: nextSeqRef.current++,
        text: approved ? `[APPROVED] Executing '${command}'...` : `[DENIED] Blocked '${command}'`,
        stream: "system",
      },
    ]);

    await respondTerminalApproval(id, approved);
  }

  async function handleStop() {
    if (!session?.session_id) return;
    await stopTerminalSession(session.session_id);
    setIsRunning(false);
    setOutputLines((prev) => [
      ...prev,
      {
        seq: nextSeqRef.current++,
        text: "^C (Process terminated)",
        stream: "system",
      },
    ]);
  }

  async function handleRestart() {
    setOutputLines([]);
    nextSeqRef.current = 0;
    setIsInitializing(true);
    try {
      if (session?.session_id) {
        await stopTerminalSession(session.session_id);
      }
      const created = await createTerminalSession(defaultWorkspace);
      setSession(created);
      setOutputLines([
        {
          seq: 0,
          text: `Restarted terminal session [${created.session_id.slice(0, 8)}] in ${created.workspace_path}`,
          stream: "system",
        },
      ]);
    } finally {
      setIsInitializing(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      handleExecute();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (history.length > 0) {
        const nextIdx = Math.min(historyIndex + 1, history.length - 1);
        setHistoryIndex(nextIdx);
        setCommandInput(history[nextIdx]);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex > 0) {
        const nextIdx = historyIndex - 1;
        setHistoryIndex(nextIdx);
        setCommandInput(history[nextIdx]);
      } else if (historyIndex === 0) {
        setHistoryIndex(-1);
        setCommandInput("");
      }
    }
  }

  if (!isOpen) return null;

  return (
    <div
      className={`border-t border-border/80 bg-background flex flex-col transition-all duration-200 select-none shadow-lg z-30 ${
        isExpanded ? "h-96" : "h-64 sm:h-72"
      }`}
    >
      {/* Terminal Title Bar */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border/70 bg-muted/40 px-3 text-xs">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 font-medium text-foreground">
            <TerminalIcon className="h-3.5 w-3.5 text-primary" />
            <span>Terminal</span>
          </div>

          {session && (
            <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
              <span className="flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span className="truncate max-w-[120px]">{session.session_id.slice(0, 8)}</span>
              {session.workspace_path && (
                <span className="hidden md:inline rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground/80 border border-border/40">
                  {session.workspace_path.split("/").slice(-2).join("/")}
                </span>
              )}
            </div>
          )}

          {isRunning && (
            <span className="flex items-center gap-1 font-mono text-[10px] text-amber-500 bg-amber-500/10 px-1.5 py-0.2 rounded border border-amber-500/20">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Running
            </span>
          )}
        </div>

        {/* Quick controls */}
        <div className="flex items-center gap-1">
          {isRunning ? (
            <button
              type="button"
              onClick={handleStop}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-destructive hover:bg-destructive/10 transition-colors"
              title="Stop running command (Ctrl+C)"
            >
              <Square className="h-3 w-3 fill-current" />
              <span className="hidden sm:inline">Kill</span>
            </button>
          ) : null}

          <button
            type="button"
            onClick={() => setOutputLines([])}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title="Clear output"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>

          <button
            type="button"
            onClick={handleRestart}
            disabled={isInitializing}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title="Restart terminal session"
          >
            <RotateCcw className={`h-3.5 w-3.5 ${isInitializing ? "animate-spin" : ""}`} />
          </button>

          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title={isExpanded ? "Collapse height" : "Expand height"}
          >
            {isExpanded ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </button>

          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            title="Close terminal"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Security Approval Banner (if command was intercepted) */}
      {pendingApproval && (
        <div className="flex items-center justify-between border-b border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-500">
          <div className="flex items-center gap-1.5 truncate">
            <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              Approve command execution:{" "}
              <code className="font-mono font-bold text-foreground">{pendingApproval.command}</code>
              ?
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-2">
            <button
              type="button"
              onClick={() => handleApproval(true)}
              className="rounded bg-emerald-600 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-emerald-500 transition-colors"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => handleApproval(false)}
              className="rounded bg-destructive px-2 py-0.5 text-[10px] font-medium text-white hover:bg-destructive/80 transition-colors"
            >
              Deny
            </button>
          </div>
        </div>
      )}

      {/* Terminal Screen Console */}
      <div className="flex-1 overflow-y-auto bg-zinc-950 p-2.5 font-mono text-[11px] leading-relaxed select-text text-zinc-300">
        {outputLines.length === 0 ? (
          <div className="text-zinc-500 select-none py-2 text-center text-xs">
            Stroke Terminal ready. Type a command below or select a quick action.
          </div>
        ) : (
          outputLines.map((line, idx) => (
            <div
              key={idx}
              className={`whitespace-pre-wrap break-all ${
                line.stream === "system"
                  ? "text-zinc-500 italic"
                  : line.stream === "stderr"
                    ? "text-rose-400"
                    : "text-zinc-200"
              }`}
            >
              {line.text}
            </div>
          ))
        )}
        <div ref={consoleEndRef} />
      </div>

      {/* Interactive Command Input & Quick Presets */}
      <div className="border-t border-border/70 bg-card/60 p-2">
        <div className="flex items-center gap-2">
          {/* Quick preset buttons */}
          <div className="hidden sm:flex items-center gap-1 text-[10px] font-mono text-muted-foreground mr-1">
            <button
              type="button"
              onClick={() => handleExecute("git status -s")}
              className="rounded bg-muted px-1.5 py-0.5 hover:text-foreground transition-colors"
            >
              git status
            </button>
            <button
              type="button"
              onClick={() => handleExecute("pytest -q")}
              className="rounded bg-muted px-1.5 py-0.5 hover:text-foreground transition-colors"
            >
              pytest
            </button>
            <button
              type="button"
              onClick={() => handleExecute("python3 --version")}
              className="rounded bg-muted px-1.5 py-0.5 hover:text-foreground transition-colors"
            >
              python3
            </button>
          </div>

          {/* Prompt line */}
          <div className="flex flex-1 items-center gap-1.5 rounded-lg border border-border/80 bg-background px-2 py-1 focus-within:border-primary/60">
            <span className="font-mono text-xs text-primary font-bold select-none">$</span>
            <input
              ref={inputRef}
              type="text"
              value={commandInput}
              onChange={(e) => setCommandInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isRunning || isInitializing}
              placeholder={
                isRunning ? "Command is executing..." : "Type command and press Enter..."
              }
              className="w-full bg-transparent font-mono text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => handleExecute()}
              disabled={!commandInput.trim() || isRunning}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
              title="Run command (Enter)"
            >
              <Play className="h-3 w-3 fill-current" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
