import { useEffect, useState, useCallback, useRef } from "react";
import {
  Bot,
  Search,
  ListTodo,
  Code2,
  CheckCircle2,
  ShieldCheck,
  Wrench,
  Play,
  Square,
  RefreshCw,
  FileCode2,
  Lock,
  Layers,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import {
  runParallelAgentJob,
  listParallelAgentJobs,
  getParallelAgentJob,
  cancelParallelAgentJob,
  streamParallelAgentJob,
  type ParallelAgentJob,
  type ParallelAgentRole,
} from "@/lib/keyboard-store";

const ROLE_METADATA: Record<
  ParallelAgentRole,
  { label: string; description: string; icon: typeof Search; color: string }
> = {
  researcher: {
    label: "Researcher",
    description: "Explores codebase, symbols, and dependencies",
    icon: Search,
    color: "text-blue-400 bg-blue-500/10 border-blue-500/30",
  },
  planner: {
    label: "Planner",
    description: "Formulates architectural implementation plan",
    icon: ListTodo,
    color: "text-purple-400 bg-purple-500/10 border-purple-500/30",
  },
  developer: {
    label: "Developer",
    description: "Implements assigned changes with file ownership",
    icon: Code2,
    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  },
  tester: {
    label: "Tester",
    description: "Executes automated syntax, AST, and tests",
    icon: CheckCircle2,
    color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/30",
  },
  reviewer: {
    label: "Reviewer",
    description: "Independently audits quality, security & standards",
    icon: ShieldCheck,
    color: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  },
  debugger: {
    label: "Debugger",
    description: "Diagnoses verified issues and applies fixes",
    icon: Wrench,
    color: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  },
  orchestrator: {
    label: "Orchestrator",
    description: "Coordinates workflow graph and safety gate",
    icon: Layers,
    color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/30",
  },
};

export function ParallelAgentManager() {
  const [userGoal, setUserGoal] = useState("");
  const [useSandbox, setUseSandbox] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);
  const [jobs, setJobs] = useState<ParallelAgentJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<ParallelAgentJob | null>(null);
  const [selectedRole, setSelectedRole] = useState<ParallelAgentRole>("developer");
  const [activeTab, setActiveTab] = useState<"artifacts" | "logs" | "files">("artifacts");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const list = await listParallelAgentJobs();
      setJobs(list);
      if (list.length > 0 && !activeJobId) {
        setActiveJobId(list[0].job_id);
      }
    } catch {
      // quiet
    }
  }, [activeJobId]);

  const refreshActiveJob = useCallback(async (jobId: string) => {
    try {
      const job = await getParallelAgentJob(jobId);
      if (job) {
        setActiveJob(job);
      }
    } catch {
      // quiet
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  useEffect(() => {
    if (!activeJobId) {
      setActiveJob(null);
      return;
    }

    refreshActiveJob(activeJobId);

    // Setup live SSE stream for active job if running
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
    }
    const abortCtrl = new AbortController();
    streamAbortRef.current = abortCtrl;

    streamParallelAgentJob(
      activeJobId,
      () => {
        refreshActiveJob(activeJobId);
      },
      () => {
        refreshActiveJob(activeJobId);
        fetchJobs();
      },
      abortCtrl.signal,
    );

    return () => {
      abortCtrl.abort();
    };
  }, [activeJobId, refreshActiveJob, fetchJobs]);

  const handleLaunch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userGoal.trim() || isLaunching) return;

    setIsLaunching(true);
    setErrorMsg(null);

    try {
      const res = await runParallelAgentJob({
        user_goal: userGoal.trim(),
        use_isolated_sandbox: useSandbox,
      });
      setUserGoal("");
      setActiveJobId(res.job_id);
      setActiveJob(res.job);
      await fetchJobs();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to launch multi-agent job");
    } finally {
      setIsLaunching(false);
    }
  };

  const handleCancel = async () => {
    if (!activeJobId) return;
    try {
      await cancelParallelAgentJob(activeJobId);
      await refreshActiveJob(activeJobId);
      await fetchJobs();
    } catch {
      // quiet
    }
  };

  const selectedAgent = activeJob?.agents?.[selectedRole];

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-col gap-1 border-b border-border/40 pb-5 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg bg-primary/10 p-2 text-primary border border-primary/20">
              <Bot className="h-5 w-5" />
            </div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              Parallel Multi-Agent System
            </h1>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Coordinated coding environment with specialized agents executing tasks via configured
            BYOK providers.
          </p>
        </div>
        <div className="flex items-center gap-2 pt-2 md:pt-0">
          <button
            type="button"
            onClick={() => {
              if (activeJobId) refreshActiveJob(activeJobId);
              fetchJobs();
            }}
            className="flex items-center gap-1.5 rounded-lg border border-border/60 bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/60 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Launch Job Card */}
      <div className="rounded-xl border border-border/60 bg-card p-5 shadow-sm">
        <form onSubmit={handleLaunch} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="userGoal"
              className="text-xs font-medium text-foreground flex items-center gap-1.5"
            >
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              <span>Deploy Multi-Agent Coding Team</span>
            </label>
            <div className="flex gap-2">
              <input
                id="userGoal"
                type="text"
                value={userGoal}
                onChange={(e) => setUserGoal(e.target.value)}
                placeholder="e.g. Build spatial hitbox system with persistent debounce and OverlapParams..."
                className="flex-1 rounded-lg border border-border/80 bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                disabled={isLaunching}
              />
              <button
                type="submit"
                disabled={isLaunching || !userGoal.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {isLaunching ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    <span>Deploying...</span>
                  </>
                ) : (
                  <>
                    <Play className="h-3.5 w-3.5 fill-current" />
                    <span>Deploy Agents</span>
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={useSandbox}
                onChange={(e) => setUseSandbox(e.target.checked)}
                className="rounded border-border"
              />
              <span>Run in isolated workspace sandbox (safe copy with change reconciliation)</span>
            </label>
          </div>

          {errorMsg && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {errorMsg}
            </div>
          )}
        </form>
      </div>

      {/* Main Workspace Layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* Left Sidebar: Job History */}
        <div className="space-y-2 lg:col-span-1">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
            Jobs History
          </h2>
          <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
            {jobs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/60 p-4 text-center text-xs text-muted-foreground">
                No jobs dispatched yet.
              </div>
            ) : (
              jobs.map((j) => (
                <button
                  type="button"
                  key={j.job_id}
                  onClick={() => setActiveJobId(j.job_id)}
                  className={`flex w-full flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors ${
                    activeJobId === j.job_id
                      ? "border-primary/50 bg-primary/5"
                      : "border-border/50 bg-card/60 hover:bg-muted/40"
                  }`}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="font-mono text-[10px] text-muted-foreground">{j.job_id}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${
                        j.status === "completed"
                          ? "bg-emerald-500/10 text-emerald-400"
                          : j.status === "running"
                            ? "bg-amber-500/10 text-amber-400 animate-pulse"
                            : j.status === "failed"
                              ? "bg-rose-500/10 text-rose-400"
                              : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {j.status}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-xs font-medium text-foreground">{j.user_goal}</p>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right Area: Active Job Pipeline and Agent Inspector */}
        <div className="space-y-5 lg:col-span-3">
          {activeJob ? (
            <>
              {/* Job Status Banner */}
              <div className="flex flex-col gap-2 rounded-xl border border-border/60 bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-foreground">{activeJob.user_goal}</h2>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ${
                        activeJob.status === "completed"
                          ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                          : activeJob.status === "running"
                            ? "bg-amber-500/15 text-amber-400 border border-amber-500/30 animate-pulse"
                            : activeJob.status === "failed"
                              ? "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                              : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {activeJob.status}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-[11px] text-muted-foreground font-mono">
                    <span>ID: {activeJob.job_id}</span>
                    <span>Workspace: {activeJob.workspace_path}</span>
                  </div>
                </div>

                {activeJob.status === "running" && (
                  <button
                    type="button"
                    onClick={handleCancel}
                    className="flex items-center gap-1.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs text-destructive hover:bg-destructive/20 transition-colors"
                  >
                    <Square className="h-3.5 w-3.5 fill-current" />
                    <span>Cancel Job</span>
                  </button>
                )}
              </div>

              {/* 6 Specialized Agents Pipeline Grid */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6">
                {(
                  [
                    "researcher",
                    "planner",
                    "developer",
                    "tester",
                    "reviewer",
                    "debugger",
                  ] as ParallelAgentRole[]
                ).map((role) => {
                  const meta = ROLE_METADATA[role];
                  const agent = activeJob.agents?.[role];
                  const Icon = meta.icon;
                  const isSelected = selectedRole === role;
                  const status = agent?.status || "idle";

                  return (
                    <button
                      type="button"
                      key={role}
                      onClick={() => setSelectedRole(role)}
                      className={`flex flex-col rounded-xl border p-3 text-left transition-all ${
                        isSelected
                          ? "border-primary bg-primary/10 shadow-sm"
                          : "border-border/60 bg-card hover:border-border"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className={`rounded-lg p-1.5 border ${meta.color}`}>
                          <Icon className="h-4 w-4" />
                        </div>
                        <span
                          className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                            status === "completed"
                              ? "text-emerald-400 bg-emerald-500/10"
                              : status === "running"
                                ? "text-amber-400 bg-amber-500/10 animate-pulse"
                                : status === "failed"
                                  ? "text-rose-400 bg-rose-500/10"
                                  : "text-muted-foreground bg-muted/40"
                          }`}
                        >
                          {status}
                        </span>
                      </div>
                      <span className="mt-2 text-xs font-semibold text-foreground">
                        {meta.label}
                      </span>
                      <span className="text-[10px] text-muted-foreground line-clamp-1">
                        {agent?.status_message || meta.description}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Selected Agent Detailed View */}
              {selectedAgent ? (
                <div className="rounded-xl border border-border/60 bg-card p-5 space-y-4">
                  {/* Agent Header */}
                  <div className="flex flex-col gap-2 border-b border-border/40 pb-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">
                        {selectedAgent.name}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${
                          selectedAgent.status === "completed"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : selectedAgent.status === "running"
                              ? "bg-amber-500/10 text-amber-400 animate-pulse"
                              : selectedAgent.status === "failed"
                                ? "bg-rose-500/10 text-rose-400"
                                : "bg-muted text-muted-foreground"
                        }`}
                      >
                        {selectedAgent.status}
                      </span>
                    </div>

                    {/* Inspector Tabs */}
                    <div className="flex items-center gap-1 rounded-lg border border-border/60 bg-muted/30 p-0.5 text-xs">
                      <button
                        type="button"
                        onClick={() => setActiveTab("artifacts")}
                        className={`rounded px-2.5 py-1 transition-colors ${
                          activeTab === "artifacts"
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        Artifacts
                      </button>
                      <button
                        type="button"
                        onClick={() => setActiveTab("logs")}
                        className={`rounded px-2.5 py-1 transition-colors ${
                          activeTab === "logs"
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        Logs ({selectedAgent.logs_count})
                      </button>
                      <button
                        type="button"
                        onClick={() => setActiveTab("files")}
                        className={`rounded px-2.5 py-1 transition-colors ${
                          activeTab === "files"
                            ? "bg-background text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        Files Locked ({selectedAgent.owned_files.length})
                      </button>
                    </div>
                  </div>

                  {/* Tab 1: Artifacts */}
                  {activeTab === "artifacts" && (
                    <div className="space-y-3">
                      {selectedAgent.output_artifacts &&
                      Object.keys(selectedAgent.output_artifacts).length > 0 ? (
                        <div className="rounded-lg border border-border/50 bg-background/50 p-4">
                          <pre className="overflow-x-auto text-xs text-foreground/90 font-mono whitespace-pre-wrap leading-relaxed">
                            {JSON.stringify(selectedAgent.output_artifacts, null, 2)}
                          </pre>
                        </div>
                      ) : (
                        <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-xs text-muted-foreground">
                          No output artifacts generated yet. The agent is waiting or running.
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab 2: Logs */}
                  {activeTab === "logs" && (
                    <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                      {selectedAgent.recent_logs && selectedAgent.recent_logs.length > 0 ? (
                        selectedAgent.recent_logs.map((log, idx) => (
                          <div
                            key={idx}
                            className="flex items-start gap-2.5 rounded-lg border border-border/40 bg-background/40 p-2.5 text-xs font-mono"
                          >
                            <span
                              className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase shrink-0 ${
                                log.level === "ERROR"
                                  ? "bg-rose-500/10 text-rose-400"
                                  : log.level === "WARN"
                                    ? "bg-amber-500/10 text-amber-400"
                                    : log.level === "PROGRESS"
                                      ? "bg-primary/10 text-primary"
                                      : log.level === "TOOL"
                                        ? "bg-cyan-500/10 text-cyan-400"
                                        : "bg-muted text-muted-foreground"
                              }`}
                            >
                              {log.level}
                            </span>
                            <span className="text-foreground/90 break-words flex-1">
                              {log.message}
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-xs text-muted-foreground">
                          No execution logs recorded yet.
                        </div>
                      )}
                    </div>
                  )}

                  {/* Tab 3: Owned Files */}
                  {activeTab === "files" && (
                    <div className="space-y-2">
                      {selectedAgent.owned_files && selectedAgent.owned_files.length > 0 ? (
                        <div className="divide-y divide-border/40 rounded-lg border border-border/50 bg-background/40">
                          {selectedAgent.owned_files.map((file) => (
                            <div
                              key={file}
                              className="flex items-center justify-between p-3 text-xs"
                            >
                              <div className="flex items-center gap-2 text-foreground font-mono">
                                <FileCode2 className="h-4 w-4 text-primary" />
                                <span>{file}</span>
                              </div>
                              <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400 font-medium">
                                <Lock className="h-3 w-3" />
                                <span>Ownership Locked</span>
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-lg border border-dashed border-border/60 p-8 text-center text-xs text-muted-foreground">
                          This agent does not currently hold exclusive ownership locks on any files.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : null}

              {/* Final Verification Gate Results (if available) */}
              {activeJob.final_verification &&
                Object.keys(activeJob.final_verification).length > 0 && (
                  <div className="rounded-xl border border-border/60 bg-card p-4 space-y-2">
                    <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                      <ShieldCheck className="h-4 w-4 text-emerald-400" />
                      <span>Final Verification Gate & Workspace Reconciliation</span>
                    </div>
                    <pre className="overflow-x-auto rounded-lg border border-border/40 bg-background/50 p-3 text-xs font-mono text-muted-foreground">
                      {JSON.stringify(activeJob.final_verification, null, 2)}
                    </pre>
                  </div>
                )}
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-border/60 p-12 text-center space-y-3">
              <div className="mx-auto w-10 h-10 rounded-full bg-muted/60 flex items-center justify-center text-muted-foreground">
                <ChevronRight className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">
                No Active Multi-Agent Job Selected
              </h3>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                Enter an engineering goal above to launch the parallel multi-agent team or select an
                existing job from the history.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
