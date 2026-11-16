import React, { useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  Brain,
  Terminal,
  FileCode,
  Check,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
  Copy,
  ExternalLink,
  Bot,
  Gamepad2,
  Search,
  Wrench,
  Loader2,
} from "lucide-react";
import type { ExecutionStep, CodingLoopReport } from "@/lib/keyboard-store";

interface ActivityFeedProps {
  steps?: ExecutionStep[];
  codingLoop?: CodingLoopReport;
  durationSeconds?: number;
  taskState?: string;
  isLiveThinking?: boolean;
  liveElapsedSeconds?: number;
  thinkingContent?: string;
}

/**
 * Formats a raw step into clean display properties:
 * - Kind: "thought" | "file" | "command" | "test" | "general"
 * - Label: concise display text (e.g. "Thought for 12s", "Analyzed requirements.txt")
 * - Line badge: "#L1-35" if applicable
 * - Expandable details: full thought text, stdout, or error
 */
function parseStepDisplay(step: ExecutionStep, idx: number) {
  const name = step.name || "";
  const detail = step.detail || "";
  const lower = `${name} ${detail}`.toLowerCase();

  // 1. Thought / Reasoning step
  if (lower.includes("thought") || lower.includes("reason") || step.type === "reasoning") {
    const durMatch = detail.match(/(\d+(?:\.\d+)?)\s*s/);
    const dur = durMatch ? `${durMatch[1]}s` : "few seconds";
    return {
      kind: "thought" as const,
      label: name.toLowerCase().includes("thought for") ? name : `Thought for ${dur}`,
      badge: null,
      file: null,
      lines: null,
      detail: detail.replace(/thought for \d+s:?/i, "").trim() || detail,
    };
  }

  // 2. File / Code inspection step
  const fileMatch = detail.match(/([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)(?:#L?(\d+)(?:-(\d+))?)?/);
  if (
    lower.includes("analyz") ||
    lower.includes("inspect") ||
    lower.includes("read") ||
    lower.includes("file") ||
    fileMatch
  ) {
    const fileName = fileMatch ? fileMatch[1].split("/").pop() : "project files";
    const lineRange =
      fileMatch && fileMatch[2]
        ? `#L${fileMatch[2]}${fileMatch[3] ? `-${fileMatch[3]}` : ""}`
        : null;
    return {
      kind: "file" as const,
      label: `Analyzed ${fileName}`,
      badge: lineRange,
      file: fileMatch ? fileMatch[1] : null,
      lines: lineRange,
      detail: detail,
    };
  }

  // 3. Test / Verification step
  if (lower.includes("test") || lower.includes("verify") || lower.includes("syntax")) {
    return {
      kind: "test" as const,
      label: name || "Verified assertions",
      badge: null,
      file: null,
      lines: null,
      detail: detail,
    };
  }

  // 4. Command / Tool execution step
  if (
    lower.includes("run") ||
    lower.includes("check") ||
    lower.includes("command") ||
    lower.includes("terminal")
  ) {
    return {
      kind: "command" as const,
      label: name || detail.slice(0, 50),
      badge: null,
      file: null,
      lines: null,
      detail: detail,
    };
  }

  return {
    kind: "general" as const,
    label: name || detail.slice(0, 50),
    badge: null,
    file: null,
    lines: null,
    detail: detail,
  };
}

export function ActivityFeed({
  steps = [],
  codingLoop,
  durationSeconds,
  taskState,
  isLiveThinking = false,
  liveElapsedSeconds = 0,
  thinkingContent,
}: ActivityFeedProps) {
  // Main parent expanded state (default closed for clean minimal view, or auto-open when live)
  const [parentExpanded, setParentExpanded] = useState<boolean>(isLiveThinking);
  const [subGroupExpanded, setSubGroupExpanded] = useState<boolean>(true);
  // Track open detail view for individual steps
  const [expandedStepIndex, setExpandedStepIndex] = useState<number | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  function toggleStep(idx: number) {
    setExpandedStepIndex(expandedStepIndex === idx ? null : idx);
  }

  function handleCopy(text: string, idx: number, e: React.MouseEvent) {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopiedIndex(idx);
    setTimeout(() => setCopiedIndex(null), 2000);
  }

  // Format total duration header (e.g. "Worked for 5m", "Worked for 12s", "Thinking for 4.2s")
  function formatWorkedDuration(): string {
    if (isLiveThinking) {
      return `Thinking for ${liveElapsedSeconds.toFixed(1)}s`;
    }
    if (!durationSeconds || durationSeconds <= 0) {
      return "Explored files, ran commands";
    }
    if (durationSeconds >= 60) {
      const mins = Math.floor(durationSeconds / 60);
      const secs = Math.round(durationSeconds % 60);
      return `Worked for ${mins}m${secs > 0 ? ` ${secs}s` : ""}`;
    }
    return `Worked for ${Math.round(durationSeconds)}s`;
  }

  // Live thinking state without finalized steps
  if (isLiveThinking && (!steps || steps.length === 0)) {
    return (
      <div className="my-2.5 flex items-center gap-2 text-xs text-muted-foreground select-none">
        <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10">
          <Loader2 className="h-3 w-3 animate-spin text-primary" />
        </div>
        <span className="font-mono text-[12px] font-medium text-foreground">Thinking…</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {liveElapsedSeconds.toFixed(1)}s
        </span>
        <span className="text-[10px] uppercase font-mono tracking-wider text-muted-foreground/80 border border-border/50 rounded px-1.5 py-0.5">
          Active Agent Loop
        </span>
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse ml-1" />
      </div>
    );
  }

  if ((!steps || steps.length === 0) && !codingLoop && !thinkingContent) {
    return null;
  }

  return (
    <div className="my-2 select-none font-sans text-xs">
      {/* 1. Parent Collapsible Header (Worked for Xm / Xs) */}
      <button
        type="button"
        onClick={() => setParentExpanded(!parentExpanded)}
        className="group inline-flex items-center gap-1.5 py-1 text-xs font-normal text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        aria-expanded={parentExpanded}
      >
        <span className="transition-colors group-hover:text-foreground">
          {formatWorkedDuration()}
        </span>
        <span className="transition-transform duration-150">
          {parentExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 opacity-70" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 opacity-70" />
          )}
        </span>
      </button>

      {/* 2. Hierarchical Tree Stream */}
      {parentExpanded && (
        <div className="relative mt-1 ml-1.5 pl-3 border-l border-border/60 space-y-1 animate-in fade-in duration-200">
          {/* Collapsible Sub-Group Header */}
          <div className="pt-0.5">
            <button
              type="button"
              onClick={() => setSubGroupExpanded(!subGroupExpanded)}
              className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground/90 hover:text-foreground transition-colors cursor-pointer"
            >
              <span>Explored files, ran commands</span>
              {subGroupExpanded ? (
                <ChevronDown className="h-3 w-3 opacity-60" />
              ) : (
                <ChevronRight className="h-3 w-3 opacity-60" />
              )}
            </button>
          </div>

          {/* Chronological Step Items */}
          {subGroupExpanded && (
            <div className="space-y-0.5 pt-0.5 pl-1.5">
              {steps.map((step, idx) => {
                const parsed = parseStepDisplay(step, idx);
                const isExpanded = expandedStepIndex === idx;
                const hasDetail = Boolean(parsed.detail && parsed.detail.trim().length > 0);

                return (
                  <div key={idx} className="group/item">
                    {/* Step Row */}
                    <div
                      onClick={() => hasDetail && toggleStep(idx)}
                      className={`inline-flex items-center gap-1.5 py-0.5 text-[11px] rounded transition-colors ${
                        hasDetail ? "cursor-pointer hover:text-foreground" : "cursor-default"
                      } ${isExpanded ? "text-foreground font-medium" : "text-muted-foreground"}`}
                    >
                      {/* Step Icon according to kind */}
                      {parsed.kind === "thought" ? (
                        <Brain className="h-3 w-3 text-indigo-400 shrink-0 opacity-80" />
                      ) : parsed.kind === "file" ? (
                        <FileCode className="h-3 w-3 text-emerald-400 shrink-0 opacity-80" />
                      ) : parsed.kind === "test" ? (
                        <CheckCircle2 className="h-3 w-3 text-sky-400 shrink-0 opacity-80" />
                      ) : (
                        <Terminal className="h-3 w-3 text-amber-400 shrink-0 opacity-80" />
                      )}

                      {/* Step Label */}
                      <span className="tracking-tight">{parsed.label}</span>

                      {/* File Line Range Pill (#L1-35) */}
                      {parsed.badge && (
                        <span className="inline-flex items-center font-mono text-[10px] text-muted-foreground bg-muted/60 px-1 py-0.2 rounded border border-border/40">
                          {parsed.badge}
                        </span>
                      )}

                      {/* Expand Chevron (if details exist) */}
                      {hasDetail && (
                        <span className="text-muted-foreground/60 group-hover/item:text-foreground transition-transform">
                          {isExpanded ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                        </span>
                      )}
                    </div>

                    {/* Expanded Detail Box */}
                    {isExpanded && hasDetail && (
                      <div className="my-1.5 ml-4 max-w-2xl rounded-md border border-border/70 bg-card/80 p-2.5 text-[11px] font-mono leading-relaxed text-foreground shadow-2xs">
                        <div className="flex items-center justify-between pb-1 mb-1 border-b border-border/50 text-[10px] text-muted-foreground">
                          <span className="uppercase tracking-wider">
                            {parsed.kind === "thought" ? "Chain of Thought" : "Execution Log"}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => handleCopy(parsed.detail, idx, e)}
                            className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                          >
                            {copiedIndex === idx ? (
                              <>
                                <Check className="h-2.5 w-2.5 text-emerald-500" />
                                <span className="text-emerald-500 font-sans">Copied</span>
                              </>
                            ) : (
                              <>
                                <Copy className="h-2.5 w-2.5" />
                                <span className="font-sans">Copy</span>
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="whitespace-pre-wrap break-words select-text opacity-90 max-h-60 overflow-y-auto">
                          {parsed.detail}
                        </pre>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Coding Loop Self-Healing Summary (if applicable) */}
              {codingLoop && (
                <div className="pt-1">
                  <div className="inline-flex items-center gap-1.5 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                    <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />
                    <span>
                      Luau syntax & tests verified
                      {codingLoop.iterations > 1 ? ` (${codingLoop.iterations} iterations)` : ""}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
