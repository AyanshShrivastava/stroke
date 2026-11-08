"""
================================================================================
STROKE // PRIVATE BACKGROUND TERMINAL EXECUTION ENGINE
================================================================================
Architecture Specifications:
  1. Internal-Only Execution:
     - No user-facing terminal UI, tabs, panels, or consoles.
     - Runs silently in the background, accessible strictly via internal AI tools.
  2. Multiple Independent Sessions:
     - Unique session IDs (e.g., term-xxxxxxxx).
     - Isolated working directories, process states, and ring-buffered outputs.
  3. Security & Sandboxing:
     - Execution strictly confined to project workspace; traversal outside workspace is blocked.
     - Structured command invocation (shell=False) preventing shell injection.
     - Allowlist for safe routine dev commands (python, luau, git status, linters, tests).
     - Explicit approval gating for privileged, destructive, or network-altering actions.
     - Automatic secret redaction for API keys, tokens, and credentials.
  4. Process Lifecycle & Resource Controls:
     - Configurable timeouts (default 20s, max 60s), output-size caps (256KB / 2000 lines).
     - Immediate process cancellation and session reaping.
================================================================================
"""

import os
import sys
import re
import json
import time
import uuid
import signal
import threading
import subprocess
from collections import deque
from typing import Dict, List, Any, Optional, Tuple

# Default canonical workspace boundary
DEFAULT_WORKSPACE = os.path.dirname(os.path.abspath(__file__))
MAX_SESSIONS = 10
MAX_OUTPUT_LINES = 2000
MAX_OUTPUT_BYTES = 256 * 1024  # 256 KB
DEFAULT_TIMEOUT_SEC = 20
MAX_TIMEOUT_SEC = 60

# ==============================================================================
# 1. SECRET REDACTION ENGINE
# ==============================================================================

REDACTION_PATTERNS = [
    # GitHub Tokens
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{82}"), "[REDACTED_GITHUB_PAT]"),
    # Google / Firebase API Keys
    (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "[REDACTED_GOOGLE_API_KEY]"),
    # JWT Bearer Tokens
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+"), "Bearer [REDACTED_JWT]"),
    # Private Key Blocks
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    # Generic Secret Patterns (e.g. password=..., secret=...)
    (re.compile(r"(?i)(password|secret|apikey|api_key|token|auth_token)\s*[:=]\s*['\"]?([^\s'\"]{8,})['\"]?"), r"\1=[REDACTED_SECRET]"),
]

def redact_sensitive_data(text: str) -> str:
    """Redacts sensitive authentication tokens, keys, and credentials from command output."""
    if not text:
        return ""
    redacted = text
    for pattern, replacement in REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


# ==============================================================================
# 2. COMMAND SECURITY & ALLOWLIST POLICY
# ==============================================================================

SAFE_ROUTINE_COMMANDS = {
    # Python & Testing
    "python", "python3", "pytest", "unittest", "mypy", "ruff", "flake8", "pylint",
    # Luau & Lua
    "luau", "lua", "luau-analyze", "selene", "stylua", "luacheck",
    # Node & TypeScript (Read / Test)
    "node", "tsc", "eslint", "prettier", "vitest",
    # System Inspection & Read-Only Utilities
    "ls", "dir", "pwd", "cat", "head", "tail", "grep", "find", "echo", "which",
    # Git Read-Only
    "git"
}

# Subcommands for git and package managers that are auto-allowed vs requiring approval
GIT_ALLOWED_SUBCOMMANDS = {"status", "diff", "log", "branch", "show", "rev-parse", "describe", "tag", "check-ignore"}
GIT_APPROVAL_SUBCOMMANDS = {"push", "commit", "reset", "clean", "checkout", "revert", "rebase", "merge"}

DESTRUCTIVE_COMMANDS = {
    "rm", "del", "rmdir", "unlink", "format", "dd", "mkfs", "chmod", "chown", "sudo", "su", "kill", "pkill"
}

PACKAGE_MANAGERS = {"npm", "pip", "pip3", "cargo", "bun", "pnpm", "yarn"}


class SecurityDecision:
    ALLOWED = "allowed"
    REQUIRES_APPROVAL = "requires_approval"
    DENIED = "denied"


def evaluate_command_security(command: str, args: List[str]) -> Tuple[str, str]:
    """
    Evaluates whether a command is safe for routine background execution,
    requires explicit user confirmation, or is strictly denied.
    Returns (decision, rationale).
    """
    clean_cmd = os.path.basename(command).lower()
    
    # Strip common extension (.exe) on Windows
    if clean_cmd.endswith(".exe"):
        clean_cmd = clean_cmd[:-4]

    # 1. Deny dangerous root/privilege commands
    if clean_cmd in ("sudo", "su", "dd", "mkfs"):
        return SecurityDecision.DENIED, f"Privileged command '{clean_cmd}' is prohibited by Stroke security policy."

    # 2. Check destructive deletion utilities
    if clean_cmd in DESTRUCTIVE_COMMANDS:
        target = " ".join(args) if args else "this file/directory"
        return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to delete {target}? [Allow] [Decline]"

    # 3. Check Git operations
    if clean_cmd == "git":
        subcmd = args[0].lower() if args else "status"
        if subcmd in GIT_ALLOWED_SUBCOMMANDS:
            return SecurityDecision.ALLOWED, "Routine Git read-only inspection."
        if subcmd in GIT_APPROVAL_SUBCOMMANDS:
            return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to run git {subcmd}? [Allow] [Decline]"
        return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to run git {subcmd}? [Allow] [Decline]"

    # 4. Check Package Managers (install/update require approval; test/list allowed)
    if clean_cmd in PACKAGE_MANAGERS:
        subcmd = args[0].lower() if args else ""
        if subcmd in ("test", "run", "list", "show", "--version", "-v"):
            return SecurityDecision.ALLOWED, f"Package manager diagnostics '{clean_cmd} {subcmd}'."
        if subcmd in ("install", "add"):
            pkgs = " ".join(args[1:]) if len(args) > 1 else "required packages"
            return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to install {pkgs}? [Allow] [Decline]"
        if subcmd in ("update", "upgrade"):
            target = " ".join(args[1:]) if len(args) > 1 else f"{clean_cmd} to the latest version"
            return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to update {target}? [Allow] [Decline]"
        if subcmd in ("remove", "uninstall"):
            pkgs = " ".join(args[1:]) if len(args) > 1 else "this package"
            return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to delete {pkgs}? [Allow] [Decline]"
        return SecurityDecision.REQUIRES_APPROVAL, f"Do you want to run {clean_cmd} {' '.join(args)}? [Allow] [Decline]"

    # 5. Check Routine Allowed Commands
    if clean_cmd in SAFE_ROUTINE_COMMANDS:
        return SecurityDecision.ALLOWED, f"Approved routine development command: {clean_cmd}."

    # Default: Unknown commands require user authorization for safety
    return SecurityDecision.REQUIRES_APPROVAL, f"Unlisted command '{clean_cmd}' requires user authorization."


# ==============================================================================
# 3. BACKGROUND TERMINAL SESSION
# ==============================================================================

class TerminalSession:
    """
    Represents an isolated, silent background terminal session.
    Manages process execution, ring-buffer output logging, and working directory state.
    """

    def __init__(self, session_id: str, workspace_path: str):
        self.session_id = session_id
        self.workspace_path = os.path.realpath(workspace_path)
        self.cwd = self.workspace_path
        self.state = "idle"  # idle, running, completed, failed, terminated, timed_out, waiting_approval
        self.created_at = time.time()
        self.last_activity_at = time.time()
        
        # Bounded ring buffers
        self.output_lines: deque = deque(maxlen=MAX_OUTPUT_LINES)
        self.total_output_bytes = 0
        self.lock = threading.Lock()
        
        # Process handles
        self.current_process: Optional[subprocess.Popen] = None
        self.last_exit_code: Optional[int] = None
        self.last_command: Optional[str] = None
        self.last_command_info: Optional[Dict[str, Any]] = None
        self.last_duration_ms: Optional[float] = None
        self.pending_approval: Optional[Dict[str, Any]] = None

    def _append_output(self, stream_name: str, text: str):
        """Thread-safe append of redacted stream output lines."""
        if not text:
            return
        redacted = redact_sensitive_data(text)
        with self.lock:
            for line in redacted.splitlines():
                formatted_line = f"[{stream_name}] {line}"
                self.output_lines.append(formatted_line)
                self.total_output_bytes += len(formatted_line.encode("utf-8"))

    def validate_working_directory(self, target_path: str) -> str:
        """Ensures the working directory remains strictly inside the workspace boundary."""
        if os.path.isabs(target_path):
            canonical = os.path.realpath(target_path)
        else:
            canonical = os.path.realpath(os.path.join(self.cwd, target_path))

        # Boundary check: Canonical path must start with workspace path
        if not (canonical == self.workspace_path or canonical.startswith(self.workspace_path + os.sep)):
            raise PermissionError(f"Directory traversal denied: '{target_path}' is outside designated workspace '{self.workspace_path}'.")
        if not os.path.isdir(canonical):
            raise FileNotFoundError(f"Directory not found: '{canonical}'.")
        return canonical

    def change_directory(self, new_dir: str):
        """Changes the session's active working directory within the workspace."""
        validated = self.validate_working_directory(new_dir)
        self.cwd = validated
        self._append_output("system", f"Working directory updated to: {self.cwd}")

    def execute_command(self, command: str, args: List[str], timeout_sec: int = DEFAULT_TIMEOUT_SEC, is_background: bool = False) -> Dict[str, Any]:
        """
        Executes a command silently in the background with strict sandboxing and timeouts.
        Returns a structured dictionary with stdout, stderr, exit_code, and execution metadata.
        Supports both synchronous and asynchronous (background server/daemon) execution.
        """
        self.last_activity_at = time.time()
        start_time = time.time()
        
        # Clamp timeout
        timeout = max(1, min(timeout_sec, MAX_TIMEOUT_SEC))

        # Handle built-in 'cd' directly to maintain session directory state
        if command == "cd":
            target = args[0] if args else self.workspace_path
            try:
                self.change_directory(target)
                self.last_exit_code = 0
                return {
                    "session_id": self.session_id,
                    "command": "cd",
                    "executable": "cd",
                    "arguments": args,
                    "args": args,
                    "cwd": self.cwd,
                    "exit_code": 0,
                    "stdout": f"Changed working directory to {self.cwd}",
                    "stderr": "",
                    "duration_ms": 1.0,
                    "state": "completed",
                    "timed_out": False,
                    "is_background": False
                }
            except Exception as e:
                self.last_exit_code = 1
                return {
                    "session_id": self.session_id,
                    "command": "cd",
                    "executable": "cd",
                    "arguments": args,
                    "args": args,
                    "cwd": self.cwd,
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": str(e),
                    "duration_ms": 1.0,
                    "state": "failed",
                    "timed_out": False,
                    "is_background": False
                }

        # Resolve command binary (prefer sys.executable for python, venv binaries, local node bin, and system paths)
        extra_search_dirs = [
            os.path.join(self.workspace_path, "venv", "bin"),
            os.path.expanduser("~/.local/node/bin"),
            os.path.expanduser("~/.aftman/bin"),
            os.path.expanduser("~/.rokit/bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]
        cmd_path = command
        if command in ("python", "python3"):
            if sys.executable and os.path.exists(sys.executable):
                cmd_path = sys.executable

        if cmd_path == command:
            for d in extra_search_dirs:
                candidate = os.path.join(d, command)
                if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                    cmd_path = candidate
                    break

        if cmd_path == command:
            import shutil
            found = shutil.which(command)
            if found:
                cmd_path = found

        # Verify command security policy
        decision, rationale = evaluate_command_security(command, args)
        if decision == SecurityDecision.DENIED:
            self._append_output("security", f"BLOCKED: {rationale}")
            self.last_exit_code = 126
            return {
                "session_id": self.session_id,
                "command": command,
                "executable": command,
                "arguments": args,
                "args": args,
                "cwd": self.cwd,
                "exit_code": 126,
                "stdout": "",
                "stderr": f"CommandExecutionDenied: {rationale}",
                "duration_ms": 0.0,
                "state": "failed",
                "timed_out": False,
                "is_background": False
            }

        if decision == SecurityDecision.REQUIRES_APPROVAL:
            # Store pending approval request
            approval_id = f"appr-{uuid.uuid4().hex[:8]}"
            self.state = "waiting_approval"
            self.pending_approval = {
                "approval_id": approval_id,
                "command": command,
                "args": args,
                "rationale": rationale,
                "created_at": time.time(),
                "is_background": is_background
            }
            self._append_output("security", f"APPROVAL REQUIRED: {rationale} (Token: {approval_id})")
            return {
                "session_id": self.session_id,
                "status": "requires_approval",
                "approval_id": approval_id,
                "command": command,
                "executable": command,
                "arguments": args,
                "args": args,
                "rationale": rationale,
                "message": f"{rationale}",
                "is_background": is_background
            }

        # Safe for routine execution: Launch real background process
        full_argv = [cmd_path] + [str(a) for a in args]
        self.state = "running"
        self.last_command = " ".join(full_argv)
        self._append_output("system", f"EXEC: {self.last_command} (cwd: {self.cwd})")

        try:
            env = os.environ.copy()
            extra_path_str = ":".join(d for d in extra_search_dirs if os.path.isdir(d))
            env["PATH"] = f"{extra_path_str}:{env.get('PATH', '')}"

            # shell=False ensures structured arguments and prevents shell injection
            proc = subprocess.Popen(
                full_argv,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                shell=False,
                env=env
            )
            self.current_process = proc

            if is_background:
                # Persistent background process (e.g. test web server)
                def _stream_output():
                    try:
                        for line in iter(proc.stdout.readline, b''):
                            if not line:
                                break
                            decoded = redact_sensitive_data(line.decode("utf-8", errors="replace").rstrip())
                            self._append_output("stdout", decoded)
                    except Exception:
                        pass
                    try:
                        for line in iter(proc.stderr.readline, b''):
                            if not line:
                                break
                            decoded = redact_sensitive_data(line.decode("utf-8", errors="replace").rstrip())
                            self._append_output("stderr", decoded)
                    except Exception:
                        pass

                stream_thread = threading.Thread(target=_stream_output, daemon=True)
                stream_thread.start()
                self.state = "running"
                return {
                    "session_id": self.session_id,
                    "command": command,
                    "executable": command,
                    "arguments": args,
                    "args": args,
                    "cwd": self.cwd,
                    "exit_code": None,
                    "pid": proc.pid,
                    "stdout": f"Background process started with PID {proc.pid}",
                    "stderr": "",
                    "duration_ms": round((time.time() - start_time) * 1000, 2),
                    "state": "running",
                    "timed_out": False,
                    "is_background": True,
                    "timeout_sec": timeout
                }

            timed_out = False
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
                self.state = "completed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired:
                # Terminate and reap process
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate()
                exit_code = -signal.SIGKILL
                self.state = "timed_out"
                timed_out = True
                self._append_output("system", f"TIMEOUT: Command exceeded limit of {timeout}s.")

            stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            # Redact secrets
            clean_stdout = redact_sensitive_data(stdout_text)
            clean_stderr = redact_sensitive_data(stderr_text)

            self._append_output("stdout", clean_stdout)
            self._append_output("stderr", clean_stderr)

            # Context Protection: cap returned streams to prevent overwhelming LLM context
            max_context_chars = 4000
            model_stdout = clean_stdout
            if len(clean_stdout) > max_context_chars:
                model_stdout = clean_stdout[:max_context_chars] + f"\n\n[... Output truncated ({len(clean_stdout)} total bytes). Use terminal_read_output(tail_lines=N) to inspect more ...]"

            model_stderr = clean_stderr
            if len(clean_stderr) > max_context_chars:
                model_stderr = clean_stderr[:max_context_chars] + f"\n\n[... Error output truncated ({len(clean_stderr)} total bytes) ...]"

            duration_ms = round((time.time() - start_time) * 1000, 2)
            self.last_exit_code = exit_code
            self.last_duration_ms = duration_ms
            self.last_command_info = {
                "command": command,
                "args": list(args),
                "timeout_sec": timeout,
                "is_background": is_background
            }

            return {
                "session_id": self.session_id,
                "command": command,
                "executable": command,
                "arguments": args,
                "args": args,
                "cwd": self.cwd,
                "exit_code": exit_code,
                "stdout": model_stdout,
                "stderr": model_stderr,
                "raw_stdout_bytes": len(clean_stdout.encode("utf-8")),
                "raw_stderr_bytes": len(clean_stderr.encode("utf-8")),
                "duration_ms": duration_ms,
                "state": self.state,
                "timed_out": timed_out,
                "is_background": False,
                "timeout_sec": timeout
            }

        except FileNotFoundError:
            self.state = "failed"
            self.last_exit_code = 127
            msg = f"Binary not found: '{command}' in environment or workspace."
            self._append_output("stderr", msg)
            return {
                "session_id": self.session_id,
                "command": command,
                "executable": command,
                "arguments": args,
                "args": args,
                "cwd": self.cwd,
                "exit_code": 127,
                "stdout": "",
                "stderr": msg,
                "duration_ms": round((time.time() - start_time) * 1000, 2),
                "state": "failed",
                "timed_out": False,
                "is_background": False
            }
        except Exception as exc:
            self.state = "failed"
            self.last_exit_code = 1
            msg = f"ProcessExecutionError: {str(exc)}"
            self._append_output("stderr", msg)
            return {
                "session_id": self.session_id,
                "command": command,
                "executable": command,
                "arguments": args,
                "args": args,
                "cwd": self.cwd,
                "exit_code": 1,
                "stdout": "",
                "stderr": msg,
                "duration_ms": round((time.time() - start_time) * 1000, 2),
                "state": "failed",
                "timed_out": False,
                "is_background": False
            }
        finally:
            if not is_background:
                self.current_process = None

    def read_output(self, tail_lines: Optional[int] = None) -> List[str]:
        """Returns the chronological captured output lines, defaulting to last 50 lines to prevent overwhelming model context."""
        with self.lock:
            limit = tail_lines if (tail_lines is not None and tail_lines > 0) else 50
            total = len(self.output_lines)
            if total > limit:
                truncated_notice = f"[... Output truncated: {total - limit} older lines omitted. Showing most recent {limit} lines ...]"
                return [truncated_notice] + list(self.output_lines)[-limit:]
            return list(self.output_lines)

    def stop(self) -> Dict[str, Any]:
        """Terminates any active running process in this session."""
        killed = False
        if self.current_process:
            if self.current_process.poll() is None:
                try:
                    self.current_process.terminate()
                    try:
                        self.current_process.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        self.current_process.kill()
                        self.current_process.wait(timeout=1.0)
                    killed = True
                except Exception:
                    pass
            try:
                if self.current_process.stdout:
                    self.current_process.stdout.close()
            except Exception:
                pass
            try:
                if self.current_process.stderr:
                    self.current_process.stderr.close()
            except Exception:
                pass
            self.current_process = None
        self.state = "terminated"
        self._append_output("system", "Session process terminated.")
        return {
            "session_id": self.session_id,
            "status": "terminated",
            "state": "terminated",
            "process_killed": killed
        }

    def restart(self) -> Dict[str, Any]:
        """Terminates active process and restarts the last executed command with its original arguments."""
        self.stop()
        if not self.last_command_info:
            return {
                "session_id": self.session_id,
                "status": "error",
                "message": "No previous command executed in this session to restart."
            }
        info = self.last_command_info
        self._append_output("system", f"RESTART: Re-executing '{info['command']}' {' '.join(str(a) for a in info['args'])}")
        return self.execute_command(
            command=info["command"],
            args=info["args"],
            timeout_sec=info["timeout_sec"],
            is_background=info["is_background"]
        )

    def get_status(self) -> Dict[str, Any]:
        """Returns the live status summary of the session."""
        has_active = bool(self.current_process and self.current_process.poll() is None)
        if not has_active and self.current_process and self.state == "running":
            self.state = "completed" if self.current_process.poll() == 0 else "failed"
            self.last_exit_code = self.current_process.poll()
        return {
            "session_id": self.session_id,
            "workspace_path": self.workspace_path,
            "cwd": self.cwd,
            "state": self.state,
            "has_active_process": has_active,
            "last_command": self.last_command,
            "last_exit_code": self.last_exit_code,
            "last_duration_ms": self.last_duration_ms,
            "output_lines_count": len(self.output_lines),
            "pending_approval": bool(self.pending_approval),
            "idle_seconds": round(time.time() - self.last_activity_at, 1)
        }


# ==============================================================================
# 4. TERMINAL MANAGER (INTERNAL AI TOOLS REGISTRY)
# ==============================================================================

class TerminalManager:
    """
    Singleton Manager for background terminal sessions.
    Exposes the 6 internal AI tools:
      - create_terminal(workspace_path)
      - run_command(session_id, command, args)
      - read_terminal_output(session_id)
      - get_terminal_status(session_id)
      - list_terminals()
      - stop_terminal(session_id)
    """
    _sessions: Dict[str, TerminalSession] = {}
    _lock = threading.Lock()

    @classmethod
    def create_terminal(cls, workspace_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Tool: create_terminal(workspace_path)
        Creates a new independent background terminal session.
        """
        with cls._lock:
            # Enforce max sessions limit
            if len(cls._sessions) >= MAX_SESSIONS:
                # Reap oldest completed/idle session
                oldest_id = min(cls._sessions.keys(), key=lambda k: cls._sessions[k].last_activity_at)
                cls._sessions[oldest_id].stop()
                del cls._sessions[oldest_id]

            target_ws = workspace_path or DEFAULT_WORKSPACE
            canonical_ws = os.path.realpath(target_ws)
            if not os.path.exists(canonical_ws):
                raise FileNotFoundError(f"Target workspace does not exist: {canonical_ws}")

            session_id = f"term-{uuid.uuid4().hex[:8]}"
            session = TerminalSession(session_id, canonical_ws)
            cls._sessions[session_id] = session

            return {
                "status": "created",
                "session_id": session_id,
                "workspace_path": canonical_ws,
                "cwd": canonical_ws,
                "message": f"Silent background terminal session '{session_id}' initialized in {canonical_ws}."
            }

    @classmethod
    def run_command(
        cls,
        session_id: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        is_background: bool = False,
        executable: Optional[str] = None,
        arguments: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Tool: run_command / terminal_run
        Executes an approved dev command inside the target session.
        Accepts command/executable and args/arguments aliases.
        """
        session = cls._sessions.get(session_id)
        if not session:
            # Auto-create fallback session if ID not found
            created = cls.create_terminal()
            session = cls._sessions[created["session_id"]]
            session_id = created["session_id"]

        cmd = command or executable or "python"
        args_list = args if args is not None else (arguments or [])
        return session.execute_command(cmd, args_list, timeout_sec=timeout_sec, is_background=is_background)

    @classmethod
    def read_terminal_output(cls, session_id: str, tail_lines: Optional[int] = None) -> Dict[str, Any]:
        """
        Tool: read_terminal_output / terminal_read_output
        Reads the captured output of the session.
        """
        session = cls._sessions.get(session_id)
        if not session:
            return {"status": "error", "message": f"Session '{session_id}' not found."}
        lines = session.read_output(tail_lines=tail_lines)
        return {
            "session_id": session_id,
            "lines_count": len(lines),
            "output": "\n".join(lines),
            "stdout": "\n".join(lines)
        }

    @classmethod
    def get_terminal_status(cls, session_id: str) -> Dict[str, Any]:
        """
        Tool: get_terminal_status / terminal_get_status
        Returns current state, active process, and exit code.
        """
        session = cls._sessions.get(session_id)
        if not session:
            return {"status": "error", "message": f"Session '{session_id}' not found."}
        return session.get_status()

    @classmethod
    def list_terminals(cls) -> List[Dict[str, Any]]:
        """
        Tool: list_terminals / terminal_list_sessions
        Lists all active background terminal sessions.
        """
        with cls._lock:
            return [s.get_status() for s in cls._sessions.values()]

    @classmethod
    def stop_terminal(cls, session_id: str) -> Dict[str, Any]:
        """
        Tool: stop_terminal / terminal_stop
        Terminates the background session and reclaims resources.
        """
        with cls._lock:
            session = cls._sessions.get(session_id)
            if not session:
                return {"status": "error", "message": f"Session '{session_id}' not found."}
            res = session.stop()
            del cls._sessions[session_id]
            return res

    # ==========================================================================
    # CANONICAL TOOL METHOD ALIASES (EXACT NAMES SPECIFIED IN AI SPECIFICATION)
    # ==========================================================================
    @classmethod
    def terminal_create_session(cls, workspace_path: Optional[str] = None) -> Dict[str, Any]:
        """Tool: terminal_create_session(workspace_path)"""
        return cls.create_terminal(workspace_path=workspace_path)

    @classmethod
    def terminal_run(
        cls,
        session_id: str,
        executable: str,
        arguments: Optional[List[str]] = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        is_background: bool = False
    ) -> Dict[str, Any]:
        """Tool: terminal_run(session_id, executable, arguments)"""
        return cls.run_command(
            session_id=session_id,
            command=executable,
            args=arguments,
            timeout_sec=timeout_sec,
            is_background=is_background
        )

    @classmethod
    def terminal_read_output(cls, session_id: str, tail_lines: Optional[int] = None) -> Dict[str, Any]:
        """Tool: terminal_read_output(session_id)"""
        return cls.read_terminal_output(session_id=session_id, tail_lines=tail_lines)

    @classmethod
    def terminal_get_status(cls, session_id: str) -> Dict[str, Any]:
        """Tool: terminal_get_status(session_id)"""
        return cls.get_terminal_status(session_id=session_id)

    @classmethod
    def terminal_stop(cls, session_id: str) -> Dict[str, Any]:
        """Tool: terminal_stop(session_id)"""
        return cls.stop_terminal(session_id=session_id)

    @classmethod
    def restart_terminal(cls, session_id: str) -> Dict[str, Any]:
        """
        Tool: restart_terminal / terminal_restart
        Restarts the last command executed in the background session.
        """
        with cls._lock:
            session = cls._sessions.get(session_id)
            if not session:
                return {"status": "error", "message": f"Session '{session_id}' not found."}
            return session.restart()

    @classmethod
    def terminal_restart(cls, session_id: str) -> Dict[str, Any]:
        """Tool: terminal_restart(session_id)"""
        return cls.restart_terminal(session_id=session_id)

    @classmethod
    def terminal_list_sessions(cls) -> List[Dict[str, Any]]:
        """Tool: terminal_list_sessions()"""
        return cls.list_terminals()

    @classmethod
    def respond_to_approval(cls, approval_id: str, approved: bool) -> Dict[str, Any]:
        """Permits or denies a pending privileged command."""
        with cls._lock:
            for session in cls._sessions.values():
                if session.pending_approval and session.pending_approval.get("approval_id") == approval_id:
                    pending = session.pending_approval
                    session.pending_approval = None
                    if not approved:
                        session.state = "failed"
                        session.last_exit_code = 126
                        return {"status": "denied", "message": f"User denied execution of '{pending['command']}'."}
                    
                    # Approved: execute directly
                    is_bg = pending.get("is_background", False)
                    return session.execute_command(pending["command"], pending["args"], is_background=is_bg)
            return {"status": "error", "message": f"No pending approval matching token '{approval_id}'."}


# ==============================================================================
# 5. AI TOOL DISPATCHER & PARSER FOR LOCAL LLM REASONING
# ==============================================================================

class ToolDispatcher:
    """
    Validates, routes, and executes internal AI tool invocations.
    Works seamlessly with native OpenAI function schemas, raw JSON strings,
    JSON markdown blocks, XML <tool_call> tags, and structured pythonic calls emitted by local LLMs.
    """
    SUPPORTED_TOOLS = {
        "terminal_create_session",
        "terminal_run",
        "terminal_read_output",
        "terminal_get_status",
        "terminal_stop",
        "terminal_restart",
        "terminal_list_sessions",
        "create_terminal",
        "run_command",
        "read_terminal_output",
        "get_terminal_status",
        "stop_terminal",
        "restart_terminal",
        "list_terminals",
    }

    @classmethod
    def dispatch(cls, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Routes a tool call to the native background implementation."""
        args = arguments or {}
        name = tool_name.strip()

        if name in ("terminal_create_session", "create_terminal"):
            ws = args.get("workspace_path")
            return TerminalManager.terminal_create_session(workspace_path=ws)

        elif name in ("terminal_run", "run_command"):
            session_id = args.get("session_id", "")
            cmd = args.get("executable") or args.get("command") or "python"
            cmd_args = args.get("arguments") or args.get("args") or []
            timeout_sec = args.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
            is_bg = args.get("is_background", False)
            return TerminalManager.terminal_run(
                session_id=session_id,
                executable=cmd,
                arguments=cmd_args,
                timeout_sec=timeout_sec,
                is_background=is_bg
            )

        elif name in ("terminal_read_output", "read_terminal_output"):
            session_id = args.get("session_id", "")
            tail = args.get("tail_lines")
            return TerminalManager.terminal_read_output(session_id=session_id, tail_lines=tail)

        elif name in ("terminal_get_status", "get_terminal_status"):
            session_id = args.get("session_id", "")
            return TerminalManager.terminal_get_status(session_id=session_id)

        elif name in ("terminal_stop", "stop_terminal"):
            session_id = args.get("session_id", "")
            return TerminalManager.terminal_stop(session_id=session_id)

        elif name in ("terminal_restart", "restart_terminal"):
            session_id = args.get("session_id", "")
            return TerminalManager.terminal_restart(session_id=session_id)

        elif name in ("terminal_list_sessions", "list_terminals"):
            return {"terminals": TerminalManager.terminal_list_sessions()}

        return {"status": "error", "message": f"Unknown terminal tool '{tool_name}'."}

    @classmethod
    def parse_and_execute_calls(cls, text: str) -> List[Dict[str, Any]]:
        """
        Inspects raw LLM output for tool calling formats and executes them silently.
        Supports raw JSON, JSON markdown blocks, and <tool_call> XML tags.
        """
        results = []
        if not text:
            return results

        # 1. Direct raw JSON parse
        cleaned_text = text.strip()
        if (cleaned_text.startswith("{") and cleaned_text.endswith("}")) or (cleaned_text.startswith("[") and cleaned_text.endswith("]")):
            try:
                data = json.loads(cleaned_text)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        tool_name = item.get("tool") or item.get("name") or item.get("function")
                        if tool_name in cls.SUPPORTED_TOOLS:
                            args = item.get("parameters") or item.get("arguments") or item.get("args") or {}
                            res = cls.dispatch(tool_name, args)
                            results.append({"tool": tool_name, "arguments": args, "result": res})
                if results:
                    return results
            except Exception:
                pass

        # 2. Parse JSON blocks with "tool" or "name"
        json_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
        for match in re.finditer(json_pattern, text):
            try:
                data = json.loads(match.group(1))
                tool_name = data.get("tool") or data.get("name") or data.get("function")
                if tool_name in cls.SUPPORTED_TOOLS:
                    args = data.get("parameters") or data.get("arguments") or data.get("args") or {}
                    res = cls.dispatch(tool_name, args)
                    results.append({"tool": tool_name, "arguments": args, "result": res})
            except Exception:
                pass

        # 3. Parse <tool_call> tags
        tag_pattern = r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>"
        for match in re.finditer(tag_pattern, text):
            try:
                data = json.loads(match.group(1))
                tool_name = data.get("name") or data.get("tool")
                if tool_name in cls.SUPPORTED_TOOLS:
                    args = data.get("arguments") or data.get("parameters") or {}
                    res = cls.dispatch(tool_name, args)
                    results.append({"tool": tool_name, "arguments": args, "result": res})
            except Exception:
                pass

        # 4. Regex fallback: embedded JSON objects containing a supported tool name
        if not results:
            obj_pattern = r"\{[^{}]*?\"(?:name|tool|function)\"\s*:\s*\"([a-zA-Z0-9_-]+)\"[^{}]*?\}"
            for match in re.finditer(obj_pattern, text):
                try:
                    tool_name = match.group(1)
                    if tool_name in cls.SUPPORTED_TOOLS:
                        data = json.loads(match.group(0))
                        args = data.get("parameters") or data.get("arguments") or data.get("args") or {}
                        res = cls.dispatch(tool_name, args)
                        results.append({"tool": tool_name, "arguments": args, "result": res})
                except Exception:
                    pass

        return results


# ==============================================================================
# 6. AI TOOL CALLING INTERFACE SCHEMAS (OPENAI & INTERNAL)
# ==============================================================================

def get_terminal_openai_tool_schemas() -> List[Dict[str, Any]]:
    """Returns OpenAI function-calling format schemas for the 6 internal terminal tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "terminal_create_session",
                "description": "Initializes a silent, private background terminal session in the project or scratch workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workspace_path": {
                            "type": "string",
                            "description": "Optional project root path. Defaults to active workspace."
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_run",
                "description": "Executes a development check, compiler (e.g. py_compile), linter, test runner, or background process in the background terminal session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The unique terminal session ID."
                        },
                        "executable": {
                            "type": "string",
                            "description": "Executable name or command (e.g. 'python', 'git', 'luau-analyze', 'pytest')."
                        },
                        "arguments": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of structured command arguments (e.g. ['-m', 'py_compile', 'test.py'])."
                        },
                        "timeout_sec": {
                            "type": "integer",
                            "description": "Timeout in seconds (default 20, max 60)."
                        },
                        "is_background": {
                            "type": "boolean",
                            "description": "Set to True to start a long-running background process (e.g. local test server) without blocking."
                        }
                    },
                    "required": ["session_id", "executable"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_read_output",
                "description": "Reads captured stdout/stderr lines from the private background terminal session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The terminal session ID."
                        },
                        "tail_lines": {
                            "type": "integer",
                            "description": "Number of recent lines to retrieve."
                        }
                    },
                    "required": ["session_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_get_status",
                "description": "Checks the process state, working directory, and exit code of a terminal session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The terminal session ID."
                        }
                    },
                    "required": ["session_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_stop",
                "description": "Terminates any active running background process in the session and frees resources.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The terminal session ID."
                        }
                    },
                    "required": ["session_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_restart",
                "description": "Restarts the last executed command in the background terminal session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "The terminal session ID."
                        }
                    },
                    "required": ["session_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "terminal_list_sessions",
                "description": "Lists all active private background terminal sessions.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    ]


def get_terminal_tools_schema() -> List[Dict[str, Any]]:
    """Returns the internal tool schemas exposed to Stroke's AI agent."""
    return [
        {
            "name": "create_terminal",
            "description": "Initializes a silent, private background terminal session in the project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_path": {
                        "type": "string",
                        "description": "Optional project root path. Defaults to active workspace."
                    }
                }
            }
        },
        {
            "name": "run_command",
            "description": "Executes a development check, compiler, test runner, or background process in the background terminal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The unique terminal session ID."
                    },
                    "executable": {
                        "type": "string",
                        "description": "Executable name or command (e.g. 'python', 'git', 'luau-analyze', 'pytest')."
                    },
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of structured command arguments (e.g. ['-m', 'py_compile', 'main.py'])."
                    },
                    "timeout_sec": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 20, max 60)."
                    },
                    "is_background": {
                        "type": "boolean",
                        "description": "Set to True to start a background process without blocking."
                    }
                },
                "required": ["session_id", "executable"]
            }
        },
        {
            "name": "read_terminal_output",
            "description": "Reads the captured stdout/stderr output lines from a background terminal session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The terminal session ID."
                    },
                    "tail_lines": {
                        "type": "integer",
                        "description": "Number of recent lines to retrieve (default all)."
                    }
                },
                "required": ["session_id"]
            }
        },
        {
            "name": "get_terminal_status",
            "description": "Checks the process state, working directory, and exit code of a terminal session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The terminal session ID."
                    }
                },
                "required": ["session_id"]
            }
        },
        {
            "name": "list_terminals",
            "description": "Lists all active background terminal sessions.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "stop_terminal",
            "description": "Terminates any running processes in the session and reclaims resources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The terminal session ID."
                    }
                },
                "required": ["session_id"]
            }
        }
    ]
