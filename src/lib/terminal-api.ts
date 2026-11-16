/**
 * Terminal API client for Stroke Developer Environment.
 * Communicates with backend endpoints:
 *   /terminal/create
 *   /terminal/run
 *   /terminal/{session_id}/output
 *   /terminal/{session_id}/status
 *   /terminal/{session_id}/stop
 *   /terminal/list
 *   /terminal/output/delta
 *   /terminal/approval/respond
 */
import { auth, getCurrentUser } from "@/lib/firebase";

export interface TerminalSessionInfo {
  session_id: string;
  workspace_path: string;
  is_running: boolean;
  pid?: number;
  created_at?: string;
  status?: string;
  command_count?: number;
}

export interface TerminalOutputLine {
  seq: number;
  text: string;
  stream: "stdout" | "stderr" | "system";
  timestamp?: number;
}

export interface RunCommandResult {
  status: "success" | "error" | "pending_approval";
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  duration_sec?: number;
  timed_out?: boolean;
  message?: string;
  approval_id?: string;
  requires_approval?: boolean;
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  try {
    const user = auth.currentUser || (await getCurrentUser());
    if (user) {
      const token = await user.getIdToken();
      headers["Authorization"] = `Bearer ${token}`;
    }
  } catch {
    // Pass without token if offline or in test mock
  }
  return headers;
}

export async function createTerminalSession(workspacePath?: string): Promise<TerminalSessionInfo> {
  const headers = await getAuthHeaders();
  const res = await fetch("/terminal/create", {
    method: "POST",
    headers,
    body: JSON.stringify(workspacePath ? { workspace_path: workspacePath } : {}),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to initialize terminal session" }));
    throw new Error(err.detail || `HTTP ${res.status}: Failed to initialize terminal`);
  }

  const data = await res.json();
  return {
    session_id: data.session_id,
    workspace_path: data.workspace_path || "",
    is_running: data.is_running ?? false,
    pid: data.pid,
  };
}

export async function listTerminalSessions(): Promise<TerminalSessionInfo[]> {
  const headers = await getAuthHeaders();
  const res = await fetch("/terminal/list", { headers });
  if (!res.ok) return [];
  const data = await res.json().catch(() => ({ terminals: [] }));
  return data.terminals || [];
}

export async function runTerminalCommand(
  sessionId: string,
  commandLine: string,
  timeoutSec: number = 30,
): Promise<RunCommandResult> {
  const headers = await getAuthHeaders();
  const tokens = commandLine.trim().split(/\s+/);
  const executable = tokens[0] || "bash";
  const args = tokens.slice(1);

  const res = await fetch("/terminal/run", {
    method: "POST",
    headers,
    body: JSON.stringify({
      session_id: sessionId,
      command: executable,
      args,
      timeout_sec: timeoutSec,
    }),
  });

  const data = await res.json().catch(() => ({ status: "error", message: `HTTP ${res.status}` }));
  return data;
}

export async function readTerminalOutputDelta(
  sessionId: string,
  sinceSeq: number = 0,
): Promise<{ lines: TerminalOutputLine[]; next_seq: number; is_running: boolean }> {
  const headers = await getAuthHeaders();
  const res = await fetch(
    `/terminal/output/delta?session_id=${encodeURIComponent(sessionId)}&since_seq=${sinceSeq}`,
    { headers },
  );

  if (!res.ok) {
    return { lines: [], next_seq: sinceSeq, is_running: false };
  }

  const data = await res.json().catch(() => ({ lines: [], next_seq: sinceSeq, is_running: false }));
  return {
    lines: (data.lines || []).map((l: Record<string, unknown>) => ({
      seq: typeof l.seq === "number" ? l.seq : 0,
      text: typeof l.text === "string" ? l.text : "",
      stream: l.stream === "stderr" ? "stderr" : "stdout",
      timestamp: typeof l.timestamp === "number" ? l.timestamp : undefined,
    })),
    next_seq: data.next_seq ?? sinceSeq,
    is_running: Boolean(data.is_running),
  };
}

export async function stopTerminalSession(sessionId: string): Promise<boolean> {
  const headers = await getAuthHeaders();
  const res = await fetch(`/terminal/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers,
  });
  return res.ok;
}

export async function respondTerminalApproval(
  approvalId: string,
  approved: boolean,
): Promise<boolean> {
  const headers = await getAuthHeaders();
  const res = await fetch("/terminal/approval/respond", {
    method: "POST",
    headers,
    body: JSON.stringify({ approval_id: approvalId, approved }),
  });
  return res.ok;
}
