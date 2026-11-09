use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use regex::Regex;
use serde::{Deserialize, Serialize};
use tokio::io::AsyncReadExt;
use tokio::process::Command;
use uuid::Uuid;
use lazy_static::lazy_static;

const MAX_OUTPUT_LINES: usize = 2000;
const DEFAULT_TIMEOUT_SECS: u64 = 20;
const MAX_TIMEOUT_SECS: u64 = 60;
const MAX_SESSIONS: usize = 10;

lazy_static! {
    static ref PAT_GITHUB: Regex = Regex::new(r"ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}").unwrap();
    static ref PAT_GOOGLE: Regex = Regex::new(r"AIza[0-9A-Za-z-_]{35}").unwrap();
    static ref PAT_JWT: Regex = Regex::new(r"Bearer\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+").unwrap();
    static ref PAT_PRIVKEY: Regex = Regex::new(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----").unwrap();
    static ref PAT_SECRET: Regex = Regex::new(r"(?i)(password|secret|apikey|api_key|token|auth_token)\s*[:=]\s*['\x22]?([^\s'\x22]{8,})['\x22]?").unwrap();
}

pub fn redact_sensitive_data(input: &str) -> String {
    let mut s = PAT_GITHUB.replace_all(input, "[REDACTED_GITHUB_PAT]").to_string();
    s = PAT_GOOGLE.replace_all(&s, "[REDACTED_GOOGLE_API_KEY]").to_string();
    s = PAT_JWT.replace_all(&s, "Bearer [REDACTED_JWT]").to_string();
    s = PAT_PRIVKEY.replace_all(&s, "[REDACTED_PRIVATE_KEY]").to_string();
    s = PAT_SECRET.replace_all(&s, "$1=[REDACTED_SECRET]").to_string();
    s
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum SecurityDecision {
    Allowed,
    RequiresApproval,
    Denied,
}

pub fn evaluate_command_security(command: &str, args: &[String]) -> (SecurityDecision, String) {
    let binary = Path::new(command)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(command)
        .to_lowercase();

    // 1. Strictly Prohibited
    if matches!(binary.as_str(), "sudo" | "su" | "dd" | "mkfs") {
        return (
            SecurityDecision::Denied,
            format!("Privileged binary '{}' is prohibited by Stroke security policy.", binary),
        );
    }

    // 2. Destructive Commands
    if matches!(
        binary.as_str(),
        "rm" | "del" | "rmdir" | "unlink" | "format" | "chmod" | "chown" | "kill" | "pkill"
    ) {
        return (
            SecurityDecision::RequiresApproval,
            format!(
                "Destructive operation '{} {}' requires user authorization.",
                binary,
                args.join(" ")
            ),
        );
    }

    // 3. Git Operations
    if binary == "git" {
        let subcmd = args.first().map(|s| s.as_str()).unwrap_or("status").to_lowercase();
        if matches!(
            subcmd.as_str(),
            "status" | "diff" | "log" | "branch" | "show" | "rev-parse" | "describe" | "tag"
        ) {
            return (SecurityDecision::Allowed, "Routine Git read-only inspection.".to_string());
        }
        return (
            SecurityDecision::RequiresApproval,
            format!("Git operation 'git {}' requires user confirmation.", subcmd),
        );
    }

    // 4. Package Managers
    if matches!(
        binary.as_str(),
        "npm" | "pip" | "pip3" | "cargo" | "bun" | "pnpm" | "yarn"
    ) {
        let subcmd = args.first().map(|s| s.as_str()).unwrap_or("").to_lowercase();
        if matches!(subcmd.as_str(), "test" | "run" | "list" | "show" | "--version" | "-v") {
            return (
                SecurityDecision::Allowed,
                format!("Package manager diagnostic '{} {}'.", binary, subcmd),
            );
        }
        return (
            SecurityDecision::RequiresApproval,
            format!("Package modification '{} {}' requires user authorization.", binary, subcmd),
        );
    }

    // 5. Approved Routine Development Commands
    if matches!(
        binary.as_str(),
        "python" | "python3" | "pytest" | "unittest" | "mypy" | "ruff" | "flake8"
            | "pylint" | "luau" | "lua" | "luau-analyze" | "selene" | "stylua" | "luacheck"
            | "node" | "tsc" | "eslint" | "prettier" | "vitest"
            | "ls" | "pwd" | "cat" | "head" | "tail" | "grep" | "find" | "echo" | "which"
    ) {
        return (
            SecurityDecision::Allowed,
            format!("Approved routine development tool: {}.", binary),
        );
    }

    // Default Unknown
    (
        SecurityDecision::RequiresApproval,
        format!("Unlisted command '{}' requires user authorization.", binary),
    )
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PendingApproval {
    pub approval_id: String,
    pub command: String,
    pub args: Vec<String>,
    pub rationale: String,
    pub created_at: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionStatus {
    pub session_id: String,
    pub workspace_path: String,
    pub cwd: String,
    pub state: String,
    pub has_active_process: bool,
    pub last_command: Option<String>,
    pub last_exit_code: Option<i32>,
    pub last_duration_ms: Option<f64>,
    pub output_lines_count: usize,
    pub pending_approval: bool,
    pub idle_seconds: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandOutputResult {
    pub session_id: String,
    pub command: String,
    pub args: Vec<String>,
    pub cwd: String,
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub duration_ms: f64,
    pub state: String,
    pub status: Option<String>,
    pub approval_id: Option<String>,
    pub rationale: Option<String>,
    pub message: Option<String>,
}

pub struct TerminalSession {
    pub session_id: String,
    pub workspace_path: PathBuf,
    pub cwd: PathBuf,
    pub state: String,
    pub last_activity: Instant,
    pub output_lines: VecDeque<String>,
    pub last_exit_code: Option<i32>,
    pub last_command: Option<String>,
    pub last_duration_ms: Option<f64>,
    pub pending_approval: Option<PendingApproval>,
    pub active_pid: Option<u32>,
}

impl TerminalSession {
    pub fn new(session_id: String, workspace_path: PathBuf) -> Self {
        Self {
            session_id,
            cwd: workspace_path.clone(),
            workspace_path,
            state: "idle".to_string(),
            last_activity: Instant::now(),
            output_lines: VecDeque::with_capacity(MAX_OUTPUT_LINES),
            last_exit_code: None,
            last_command: None,
            last_duration_ms: None,
            pending_approval: None,
            active_pid: None,
        }
    }

    pub fn append_output(&mut self, stream: &str, text: &str) {
        let clean = redact_sensitive_data(text);
        for line in clean.lines() {
            if self.output_lines.len() >= MAX_OUTPUT_LINES {
                self.output_lines.pop_front();
            }
            self.output_lines.push_back(format!("[{}] {}", stream, line));
        }
    }

    pub fn validate_and_change_dir(&mut self, target: &str) -> Result<PathBuf, String> {
        let candidate = if Path::new(target).is_absolute() {
            PathBuf::from(target)
        } else {
            self.cwd.join(target)
        };

        let canonical = candidate
            .canonicalize()
            .map_err(|e| format!("Directory not found: {}", e))?;

        if !canonical.starts_with(&self.workspace_path) {
            return Err(format!(
                "Directory traversal denied: '{:?}' is outside workspace '{:?}'",
                canonical, self.workspace_path
            ));
        }

        self.cwd = canonical.clone();
        self.append_output("system", &format!("Working directory updated to {:?}", self.cwd));
        Ok(canonical)
    }

    pub async fn execute(
        &mut self,
        command: &str,
        args: &[String],
        timeout_sec: u64,
    ) -> CommandOutputResult {
        self.last_activity = Instant::now();
        let start_time = Instant::now();
        let timeout_duration = Duration::from_secs(timeout_sec.clamp(1, MAX_TIMEOUT_SECS));

        // Built-in 'cd'
        if command == "cd" {
            let target = args.first().map(|s| s.as_str()).unwrap_or(".");
            match self.validate_and_change_dir(target) {
                Ok(_) => {
                    self.last_exit_code = Some(0);
                    return CommandOutputResult {
                        session_id: self.session_id.clone(),
                        command: "cd".to_string(),
                        args: args.to_vec(),
                        cwd: self.cwd.to_string_lossy().to_string(),
                        exit_code: 0,
                        stdout: format!("Changed working directory to {:?}", self.cwd),
                        stderr: String::new(),
                        duration_ms: 1.0,
                        state: "completed".to_string(),
                        status: None,
                        approval_id: None,
                        rationale: None,
                        message: None,
                    };
                }
                Err(e) => {
                    self.last_exit_code = Some(1);
                    return CommandOutputResult {
                        session_id: self.session_id.clone(),
                        command: "cd".to_string(),
                        args: args.to_vec(),
                        cwd: self.cwd.to_string_lossy().to_string(),
                        exit_code: 1,
                        stdout: String::new(),
                        stderr: e,
                        duration_ms: 1.0,
                        state: "failed".to_string(),
                        status: None,
                        approval_id: None,
                        rationale: None,
                        message: None,
                    };
                }
            }
        }

        // Security check
        let (decision, rationale) = evaluate_command_security(command, args);
        if decision == SecurityDecision::Denied {
            self.append_output("security", &format!("BLOCKED: {}", rationale));
            self.last_exit_code = Some(126);
            return CommandOutputResult {
                session_id: self.session_id.clone(),
                command: command.to_string(),
                args: args.to_vec(),
                cwd: self.cwd.to_string_lossy().to_string(),
                exit_code: 126,
                stdout: String::new(),
                stderr: format!("CommandExecutionDenied: {}", rationale),
                duration_ms: 0.0,
                state: "failed".to_string(),
                status: Some("denied".to_string()),
                approval_id: None,
                rationale: Some(rationale.clone()),
                message: Some(rationale),
            };
        }

        if decision == SecurityDecision::RequiresApproval {
            let approval_id = format!("appr-{}", &Uuid::new_v4().to_string()[..8]);
            self.state = "waiting_approval".to_string();
            let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
            self.pending_approval = Some(PendingApproval {
                approval_id: approval_id.clone(),
                command: command.to_string(),
                args: args.to_vec(),
                rationale: rationale.clone(),
                created_at: now,
            });
            self.append_output("security", &format!("APPROVAL REQUIRED: {} (Token: {})", rationale, approval_id));

            return CommandOutputResult {
                session_id: self.session_id.clone(),
                command: command.to_string(),
                args: args.to_vec(),
                cwd: self.cwd.to_string_lossy().to_string(),
                exit_code: 0,
                stdout: String::new(),
                stderr: String::new(),
                duration_ms: 0.0,
                state: "waiting_approval".to_string(),
                status: Some("requires_approval".to_string()),
                approval_id: Some(approval_id),
                rationale: Some(rationale.clone()),
                message: Some(format!("Action requires user authorization: {}.", rationale)),
            };
        }

        // Check if command is in workspace venv/bin
        let venv_candidate = self.workspace_path.join("venv").join("bin").join(command);
        let exec_cmd = if venv_candidate.exists() {
            venv_candidate.to_string_lossy().to_string()
        } else {
            command.to_string()
        };

        self.state = "running".to_string();
        self.last_command = Some(format!("{} {}", exec_cmd, args.join(" ")));
        self.append_output("system", &format!("EXEC: {} (cwd: {:?})", self.last_command.as_ref().unwrap(), self.cwd));

        let mut child = match Command::new(&exec_cmd)
            .args(args)
            .current_dir(&self.cwd)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                self.state = "failed".to_string();
                self.last_exit_code = Some(127);
                let err_msg = format!("SpawnError: Binary '{}' could not be executed: {}", exec_cmd, e);
                self.append_output("stderr", &err_msg);
                return CommandOutputResult {
                    session_id: self.session_id.clone(),
                    command: command.to_string(),
                    args: args.to_vec(),
                    cwd: self.cwd.to_string_lossy().to_string(),
                    exit_code: 127,
                    stdout: String::new(),
                    stderr: err_msg,
                    duration_ms: start_time.elapsed().as_secs_f64() * 1000.0,
                    state: "failed".to_string(),
                    status: None,
                    approval_id: None,
                    rationale: None,
                    message: None,
                };
            }
        };

        self.active_pid = child.id();
        let mut stdout_str = String::new();
        let mut stderr_str = String::new();

        let run_future = async {
            let mut out_take = child.stdout.take();
            let mut err_take = child.stderr.take();

            let out_fut = async {
                if let Some(mut stdout) = out_take {
                    let _ = stdout.read_to_string(&mut stdout_str).await;
                }
            };
            let err_fut = async {
                if let Some(mut stderr) = err_take {
                    let _ = stderr.read_to_string(&mut stderr_str).await;
                }
            };
            tokio::join!(out_fut, err_fut);
            child.wait().await
        };

        let (exit_code, state) = match tokio::time::timeout(timeout_duration, run_future).await {
            Ok(Ok(status)) => {
                let code = status.code().unwrap_or(0);
                (code, if code == 0 { "completed".to_string() } else { "failed".to_string() })
            }
            Ok(Err(e)) => {
                let _ = child.kill().await;
                (-1, format!("error: {}", e))
            }
            Err(_) => {
                let _ = child.kill().await;
                self.append_output("system", &format!("TIMEOUT: Process exceeded {}s.", timeout_sec));
                (-9, "timed_out".to_string())
            }
        };

        self.active_pid = None;
        let clean_stdout = redact_sensitive_data(&stdout_str);
        let clean_stderr = redact_sensitive_data(&stderr_str);

        self.append_output("stdout", &clean_stdout);
        self.append_output("stderr", &clean_stderr);

        let duration_ms = (start_time.elapsed().as_secs_f64() * 1000.0).round();
        self.state = state.clone();
        self.last_exit_code = Some(exit_code);
        self.last_duration_ms = Some(duration_ms);

        CommandOutputResult {
            session_id: self.session_id.clone(),
            command: command.to_string(),
            args: args.to_vec(),
            cwd: self.cwd.to_string_lossy().to_string(),
            exit_code,
            stdout: clean_stdout,
            stderr: clean_stderr,
            duration_ms,
            state,
            status: None,
            approval_id: None,
            rationale: None,
            message: None,
        }
    }

    pub fn get_status(&self) -> SessionStatus {
        SessionStatus {
            session_id: self.session_id.clone(),
            workspace_path: self.workspace_path.to_string_lossy().to_string(),
            cwd: self.cwd.to_string_lossy().to_string(),
            state: self.state.clone(),
            has_active_process: self.state == "running",
            last_command: self.last_command.clone(),
            last_exit_code: self.last_exit_code,
            last_duration_ms: self.last_duration_ms,
            output_lines_count: self.output_lines.len(),
            pending_approval: self.pending_approval.is_some(),
            idle_seconds: self.last_activity.elapsed().as_secs_f64(),
        }
    }
}

pub struct TerminalManager {
    sessions: Arc<Mutex<HashMap<String, TerminalSession>>>,
    default_workspace: PathBuf,
}

impl TerminalManager {
    pub fn new<P: AsRef<Path>>(workspace: P) -> Self {
        Self {
            sessions: Arc::new(Mutex::new(HashMap::new())),
            default_workspace: workspace.as_ref().to_path_buf(),
        }
    }

    pub fn create_terminal(&self, workspace_path: Option<String>) -> Result<serde_json::Value, String> {
        let mut map = self.sessions.lock().unwrap();

        if map.len() >= MAX_SESSIONS {
            // Reap oldest session
            if let Some(oldest_key) = map.iter().min_by_key(|(_, s)| s.last_activity).map(|(k, _)| k.clone()) {
                map.remove(&oldest_key);
            }
        }

        let target_ws = match workspace_path {
            Some(w) => PathBuf::from(w).canonicalize().map_err(|e| e.to_string())?,
            None => self.default_workspace.canonicalize().unwrap_or_else(|_| self.default_workspace.clone()),
        };

        let session_id = format!("term-{}", &Uuid::new_v4().to_string()[..8]);
        let session = TerminalSession::new(session_id.clone(), target_ws.clone());
        map.insert(session_id.clone(), session);

        Ok(serde_json::json!({
            "status": "created",
            "session_id": session_id,
            "workspace_path": target_ws.to_string_lossy(),
            "cwd": target_ws.to_string_lossy(),
            "message": format!("Silent background terminal session initialized.")
        }))
    }

    pub async fn run_command(
        &self,
        session_id: &str,
        command: &str,
        args: Vec<String>,
        timeout_sec: Option<u64>,
    ) -> Result<CommandOutputResult, String> {
        // Find session or auto-create
        let mut session = {
            let mut map = self.sessions.lock().unwrap();
            if !map.contains_key(session_id) {
                let ws = self.default_workspace.canonicalize().unwrap_or_else(|_| self.default_workspace.clone());
                map.insert(session_id.to_string(), TerminalSession::new(session_id.to_string(), ws));
            }
            map.remove(session_id).unwrap()
        };

        let result = session.execute(command, &args, timeout_sec.unwrap_or(DEFAULT_TIMEOUT_SECS)).await;

        {
            let mut map = self.sessions.lock().unwrap();
            map.insert(session_id.to_string(), session);
        }

        Ok(result)
    }

    pub fn read_output(&self, session_id: &str, tail_lines: Option<usize>) -> Result<serde_json::Value, String> {
        let map = self.sessions.lock().unwrap();
        let session = map.get(session_id).ok_or_else(|| format!("Session '{}' not found", session_id))?;
        let lines: Vec<String> = if let Some(tail) = tail_lines {
            session.output_lines.iter().rev().take(tail).cloned().collect::<Vec<_>>().into_iter().rev().collect()
        } else {
            session.output_lines.iter().cloned().collect()
        };

        Ok(serde_json::json!({
            "session_id": session_id,
            "lines_count": lines.len(),
            "output": lines.join("\n")
        }))
    }

    pub fn get_status(&self, session_id: &str) -> Result<SessionStatus, String> {
        let map = self.sessions.lock().unwrap();
        let session = map.get(session_id).ok_or_else(|| format!("Session '{}' not found", session_id))?;
        Ok(session.get_status())
    }

    pub fn list_terminals(&self) -> Vec<SessionStatus> {
        let map = self.sessions.lock().unwrap();
        map.values().map(|s| s.get_status()).collect()
    }

    pub fn stop_terminal(&self, session_id: &str) -> Result<serde_json::Value, String> {
        let mut map = self.sessions.lock().unwrap();
        let session = map.get_mut(session_id).ok_or_else(|| format!("Session '{}' not found", session_id))?;
        if let Some(pid) = session.active_pid.take() {
            #[cfg(unix)]
            {
                let _ = std::process::Command::new("kill").args(["-9", &pid.to_string()]).output();
            }
            #[cfg(windows)]
            {
                let _ = std::process::Command::new("taskkill").args(["/F", "/PID", &pid.to_string()]).output();
            }
        }
        session.state = "terminated".to_string();
        session.append_output("system", "Session process terminated.");
        map.remove(session_id);
        Ok(serde_json::json!({
            "session_id": session_id,
            "status": "terminated"
        }))
    }

    pub async fn respond_to_approval(&self, approval_id: &str, approved: bool) -> Result<CommandOutputResult, String> {
        let mut target_data: Option<(String, PendingApproval)> = None;
        {
            let map = self.sessions.lock().unwrap();
            for (id, session) in map.iter() {
                if let Some(ref pending) = session.pending_approval {
                    if pending.approval_id == approval_id {
                        target_data = Some((id.clone(), pending.clone()));
                        break;
                    }
                }
            }
        }

        let (session_id, pending) = target_data.ok_or_else(|| format!("No approval request found matching '{}'", approval_id))?;

        if !approved {
            let mut map = self.sessions.lock().unwrap();
            if let Some(session) = map.get_mut(&session_id) {
                session.pending_approval = None;
                session.state = "failed".to_string();
                session.last_exit_code = Some(126);
            }
            return Ok(CommandOutputResult {
                session_id,
                command: pending.command,
                args: pending.args,
                cwd: String::new(),
                exit_code: 126,
                stdout: String::new(),
                stderr: "Execution denied by user.".to_string(),
                duration_ms: 0.0,
                state: "failed".to_string(),
                status: Some("denied".to_string()),
                approval_id: None,
                rationale: None,
                message: Some("User denied execution authorization.".to_string()),
            });
        }

        // Approved - execute directly
        self.run_command(&session_id, &pending.command, pending.args, Some(DEFAULT_TIMEOUT_SECS)).await
    }
}
