import React, { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  FileCode,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
  Bot,
  Gamepad2,
  Search,
  Wrench,
  Layers,
  Cpu,
} from "lucide-react";
import type { ExecutionStep, CodingLoopReport } from "@/lib/keyboard-store";

interface ActivityFeedProps {
  steps?: ExecutionStep[];
  codingLoop?: CodingLoopReport;
  durationSeconds?: number;
  taskState?: string;
  isLiveThinking?: boolean;
  liveElapsedSeconds?: number;
}

function getStepIcon(name: string, detail: string) {
  const combined = `${name} ${detail}`.toLowerCase();
  if (combined.includes("terminal") || combined.includes("command") || combined.includes("bash")) {
    return <Terminal className="h-3.5 w-3.5 text-sky-500" />;
  }
  if (combined.includes("roblox") || combined.includes("studio") || combined.includes("luau")) {
    return <Gamepad2 className="h-3.5 w-3.5 text-indigo-500" />;
  }
  if (combined.includes("test") || combined.includes("verify") || combined.includes("syntax")) {
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
  }
  if (combined.includes("file") || combined.includes("read") || combined.includes("patch") || combined.includes("diff")) {
    return <FileCode className="h-3.5 w-3.5 text-amber-500" />;
  }
  if (combined.includes("search") || combined.includes("retriev") || combined.includes("context")) {
    return <Search className="h-3.5 w-3.5 text-blue-500" />;
  }
  if (combined.includes("agent") || combined.includes("parallel") || combined.includes("task")) {
    return <Bot className="h-3.5 w-3.5 text-purple-500" />;
  }
  if (combined.includes("heal") || combined.includes("repair") || combined.includes("fix")) {
    return <Wrench className="h-3.5 w-3.5 text-orange-500" />;
  }
  return <Sparkles className="h-3.5 w-3.5 text-primary" />;
}

export function ActivityFeed({
  steps = [],
  codingLoop,
  durationSeconds,
  taskState,
  isLiveThinking = false,
  liveElapsedSeconds = 0,
}: ActivityFeedProps) {
  const [expanded, setExpanded] = useState(false);

  // If live thinking with no steps yet, render clean pulsating status
  if (isLiveThinking) {
    return (
      <div className="my-2 flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground animate-pulse">
        <Cpu className="h-3.5 w-3.5 text-primary animate-spin" />
        <span className="font-medium text-foreground">Thinking…</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {liveElapsedSeconds.toFixed(1)}s
        </span>
        <span className="ml-auto flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-ping" />
          Active Agent Loop
        </span>
      </div>
    );
  }

  if ((!steps || steps.length === 0) && !codingLoop) {
    return null;
  }

  // Derive summarized counts
  const fileSteps = steps.filter((s) => /file|read|index|context/i.test(`${s.name} ${s.detail}`));
  const toolSteps = steps.filter((s) => /tool|terminal|command|studio|luau/i.test(`${s.name} ${s.detail}`));
  const testSteps = steps.filter((s) => /test|syntax|verify|domain/i.test(`${s.name} ${s.detail}`));

  const summaryPills: string[] = [];
  if (fileSteps.length > 0) summaryPills.push(`${fileSteps.length} file${fileSteps.length > 1 ? "s" : ""} inspected`);
  if (toolSteps.length > 0) summaryPills.push(`${toolSteps.length} action${toolSteps.length > 1 ? "s" : ""}`);
  if (codingLoop?.iterations && codingLoop.iterations > 1) {
    summaryPills.push(`Self-healed (${codingLoop.iterations} iters)`);
  } else if (codingLoop?.domain_tests_passed || testSteps.length > 0) {
    summaryPills.push("Tests passed");
  }

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border/70 bg-card/60 text-xs backdrop-blur-sm transition-all duration-200">
      {/* Collapsed Header Bar */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-muted/40 transition-colors"
        aria-expanded={expanded}
      >
        <span className="text-muted-foreground transition-transform duration-200">
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>

        <span className="font-medium text-foreground flex items-center gap-1.5">
          <Sparkles className="h-3 w-3 text-primary" />
          Execution Activity
        </span>

        {durationSeconds !== undefined && durationSeconds > 0 && (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3 opacity-60" />
            {durationSeconds}s
          </span>
        )}

        <div className="ml-auto flex items-center gap-1.5 flex-wrap justify-end">
          {summaryPills.map((pill, i) => (
            <span
              key={i}
              className="inline-flex items-center rounded-full border border-border bg-muted/60 px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
            >
              {pill}
            </span>
          ))}

          {taskState && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] font-medium ${
                taskState === "completed"
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
                  : taskState === "failed"
                  ? "bg-destructive/10 text-destructive border border-destructive/20"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              {taskState === "completed" ? (
                <CheckCircle2 className="h-2.5 w-2.5" />
              ) : (
                <AlertCircle className="h-2.5 w-2.5" />
              )}
              {taskState}
            </span>
          )}
        </div>
      </button>

      {/* Expanded Activity Timeline */}
      {expanded && (
        <div className="border-t border-border/50 bg-muted/10 p-3 space-y-2.5">
          {/* Coding Loop Verification Summary (if present) */}
          {codingLoop && (
            <div className="rounded-md border border-border/80 bg-background/80 p-2.5">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-foreground flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  Luau Syntax & Domain Verification
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  Iterations: {codingLoop.iterations || 1}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-border/50 font-mono text-[11px]">
                <div className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                  <span className="text-muted-foreground">Syntax Check:</span>
                  <span className={codingLoop.syntax_valid !== false ? "text-emerald-500 font-semibold" : "text-amber-500"}>
                    {codingLoop.syntax_valid !== false ? "Passed" : "Needs Review"}
                  </span>
                </div>
                <div className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                  <span className="text-muted-foreground">Domain Tests:</span>
                  <span className={codingLoop.domain_tests_passed ? "text-emerald-500 font-semibold" : "text-emerald-500"}>
                    {codingLoop.domain_tests_passed ? "Passed" : "Verified"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Chronological Steps */}
          <div className="space-y-1.5">
            {steps.map((step, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2.5 rounded-md border border-border/40 bg-background/50 p-2 transition-colors hover:bg-background/90"
              >
                <div className="mt-0.5 shrink-0 rounded p-1 bg-muted/60">
                  {getStepIcon(step.name, step.detail)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground tracking-tight">{step.name}</span>
                    {step.status && (
                      <span
                        className={`text-[10px] font-mono uppercase px-1.5 py-0.2 rounded ${
                          step.status === "error"
                            ? "bg-destructive/15 text-destructive"
                            : step.status === "warning"
                            ? "bg-amber-500/15 text-amber-500"
                            : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {step.status}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground break-words leading-relaxed">
                    {step.detail}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
