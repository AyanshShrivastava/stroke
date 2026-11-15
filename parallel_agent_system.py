"""
parallel_agent_system.py
=============================================================================
STROKE V1 — ADVANCED PARALLEL MULTI-AGENT ORCHESTRATION ARCHITECTURE
=============================================================================
Professional multi-agent coding environment with a Parent Orchestrator delegating
tasks to specialized, independent agents:
  1. Researcher: Investigates the task, codebase, files, symbols, and dependencies.
  2. Planner: Creates structured, actionable implementation plans.
  3. Developer: Implements assigned changes in isolated workspaces / locked files.
  4. Tester: Runs real static and dynamic test suites, AST checks, and compilers.
  5. Reviewer: Independently audits changes against quality, security, and requirements.
  6. Debugger: Investigates verified failures, diagnoses root causes, and applies surgical fixes.

Features:
- Genuine AI execution via configured BYOK providers (Groq, Gemini, OpenRouter, etc.).
- Independent agent contexts, isolated message histories, task statuses, logs, and role permissions.
- Concurrency protection: FileOwnershipManager prevents conflicting edits across agents.
- Isolated workspaces: TaskWorkspaceSandbox integration with safe hash reconciliation and automatic backups.
- Cancellation, retries with backoff, failure recovery loops, and final verification gate.
- Atomic state persistence in user application data and real-time SSE streaming.
- Never simulates agent activity.
=============================================================================
"""

import os
import sys
import json
import time
import uuid
import asyncio
import logging
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Set, Tuple

import paths_service
import backup_service
import file_service
import workspace_service
import isolated_workspace
from agent_orchestrator import ToolOutputObserver, is_tool_read_only
import ai_provider_service
from ai_provider_service import global_ai_provider_manager, ProviderError, ProviderRateLimitError

logger = logging.getLogger("stroke.parallel_agents")

# =============================================================================
# 1. ENUMS AND DATA STRUCTURES
# =============================================================================

class AgentRole(str, Enum):
    RESEARCHER = "researcher"
    PLANNER = "planner"
    DEVELOPER = "developer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    DEBUGGER = "debugger"
    ORCHESTRATOR = "orchestrator"


class AgentStatus(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_DEPENDENCY = "awaiting_dependency"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentLogEntry:
    timestamp: float
    level: str  # "INFO", "THOUGHT", "TOOL", "WARN", "ERROR", "PROGRESS"
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentPermissions:
    can_read_files: bool = True
    can_search_code: bool = True
    can_write_files: bool = False
    can_run_terminal: bool = False
    can_run_tests: bool = False
    can_call_mcp: bool = False
    allowed_tools: Set[str] = field(default_factory=set)
    disallowed_tools: Set[str] = field(default_factory=set)

    def is_tool_allowed(self, tool_name: str) -> Tuple[bool, str]:
        tool = tool_name.strip()
        if self.disallowed_tools and tool in self.disallowed_tools:
            return False, f"Tool '{tool}' is explicitly disallowed for this agent role."
        if self.allowed_tools and tool not in self.allowed_tools:
            return False, f"Tool '{tool}' is not permitted for this agent role."
        return True, ""

    @classmethod
    def for_role(cls, role: AgentRole) -> "AgentPermissions":
        return get_default_permissions_for_role(role)


def get_default_permissions_for_role(role: AgentRole) -> AgentPermissions:
    """Configures strict least-privilege permissions per agent role."""
    if role == AgentRole.RESEARCHER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=False,
            can_run_terminal=False,
            can_run_tests=False,
            can_call_mcp=True,
            allowed_tools={
                "read_file", "fs_read_file", "read_multiple_files", "fs_read_multiple_files",
                "list_directory", "fs_list_directory", "search_files", "fs_search_files",
                "search_in_files", "fs_search_in_files", "inspect_file", "fs_inspect_file",
                "web_search", "search_vfx_database", "studio_get_console",
                "studio_search_scripts", "script_search", "github_get_file_contents"
            },
            disallowed_tools={
                "create_file", "fs_create_file", "edit_file", "fs_edit_file",
                "apply_patch", "fs_apply_patch", "run_command", "terminal_run"
            }
        )
    elif role == AgentRole.PLANNER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=False,
            can_run_terminal=False,
            can_run_tests=False,
            can_call_mcp=False,
            allowed_tools={
                "read_file", "fs_read_file", "list_directory", "fs_list_directory",
                "search_files", "fs_search_files", "search_in_files", "fs_search_in_files"
            },
            disallowed_tools={
                "create_file", "fs_create_file", "edit_file", "fs_edit_file",
                "apply_patch", "fs_apply_patch", "run_command", "terminal_run"
            }
        )
    elif role == AgentRole.DEVELOPER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=True,
            can_run_terminal=True,
            can_run_tests=True,
            can_call_mcp=True,
            allowed_tools={
                "read_file", "fs_read_file", "list_directory", "fs_list_directory",
                "search_files", "fs_search_files", "search_in_files", "fs_search_in_files",
                "create_file", "fs_create_file", "edit_file", "fs_edit_file",
                "apply_patch", "fs_apply_patch", "inspect_file", "fs_inspect_file"
            }
        )
    elif role == AgentRole.TESTER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=False,
            can_run_terminal=True,
            can_run_tests=True,
            can_call_mcp=False,
            allowed_tools={
                "read_file", "fs_read_file", "list_directory", "fs_list_directory",
                "search_files", "fs_search_files", "search_in_files", "fs_search_in_files",
                "run_tests", "check_luau_syntax", "check_python_syntax",
                "terminal_run", "run_command"
            },
            disallowed_tools={
                "create_file", "fs_create_file", "edit_file", "fs_edit_file",
                "apply_patch", "fs_apply_patch"
            }
        )
    elif role == AgentRole.REVIEWER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=False,
            can_run_terminal=False,
            can_run_tests=False,
            can_call_mcp=False,
            allowed_tools={
                "read_file", "fs_read_file", "list_directory", "fs_list_directory",
                "search_files", "fs_search_files", "search_in_files", "fs_search_in_files",
                "inspect_file", "fs_inspect_file"
            },
            disallowed_tools={
                "create_file", "fs_create_file", "edit_file", "fs_edit_file",
                "apply_patch", "fs_apply_patch", "run_command", "terminal_run"
            }
        )
    elif role == AgentRole.DEBUGGER:
        return AgentPermissions(
            can_read_files=True,
            can_search_code=True,
            can_write_files=True,
            can_run_terminal=True,
            can_run_tests=True,
            can_call_mcp=True,
            allowed_tools={
                "read_file", "fs_read_file", "list_directory", "fs_list_directory",
                "search_files", "fs_search_files", "search_in_files", "fs_search_in_files",
                "edit_file", "fs_edit_file", "apply_patch", "fs_apply_patch",
                "run_tests", "check_luau_syntax", "check_python_syntax"
            }
        )
    return AgentPermissions()


@dataclass
class AgentContext:
    agent_id: str
    role: AgentRole
    name: str
    status: AgentStatus = AgentStatus.IDLE
    status_message: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    logs: List[AgentLogEntry] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    input_artifacts: Dict[str, Any] = field(default_factory=dict)
    output_artifacts: Dict[str, Any] = field(default_factory=dict)
    owned_files: Set[str] = field(default_factory=set)
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    permissions: AgentPermissions = field(default_factory=AgentPermissions)

    def log(self, level: str, message: str, metadata: Optional[Dict[str, Any]] = None):
        entry = AgentLogEntry(
            timestamp=time.time(),
            level=level.upper(),
            message=message,
            metadata=metadata or {}
        )
        self.logs.append(entry)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "name": self.name,
            "status": self.status.value,
            "status_message": self.status_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "logs_count": len(self.logs),
            "recent_logs": [
                {
                    "timestamp": l.timestamp,
                    "level": l.level,
                    "message": l.message,
                    "metadata": l.metadata
                }
                for l in self.logs[-30:]
            ],
            "owned_files": sorted(list(self.owned_files)),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
            "output_artifacts": self.output_artifacts,
        }


# =============================================================================
# 2. CONCURRENCY PROTECTION & FILE OWNERSHIP REGISTRY
# =============================================================================

class FileConflictError(PermissionError):
    """Raised when an agent attempts to edit a file locked by another agent."""
    pass


class FileOwnershipManager:
    """
    Thread-safe and async-safe file lock and ownership coordinator.
    Guarantees that multiple concurrent agents never clobber each other's edits.
    """

    def __init__(self):
        self._locks: Dict[str, str] = {}  # normalized_path -> agent_id
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _normalize(self, file_path: str) -> str:
        try:
            return str(Path(file_path).resolve())
        except Exception:
            return os.path.normpath(file_path)

    async def acquire_file(self, file_path: str, agent_id: str) -> bool:
        norm = self._normalize(file_path)
        async with self._get_lock():
            current_owner = self._locks.get(norm)
            if current_owner == agent_id:
                return True
            if current_owner is not None and current_owner != agent_id:
                return False
            self._locks[norm] = agent_id
            return True

    async def release_file(self, file_path: str, agent_id: str) -> bool:
        norm = self._normalize(file_path)
        async with self._get_lock():
            if self._locks.get(norm) == agent_id:
                del self._locks[norm]
                return True
            return False

    async def release_all(self, agent_id: str) -> List[str]:
        released = []
        async with self._get_lock():
            for p, owner in list(self._locks.items()):
                if owner == agent_id:
                    del self._locks[p]
                    released.append(p)
        return released

    async def get_owner(self, file_path: str) -> Optional[str]:
        norm = self._normalize(file_path)
        async with self._get_lock():
            return self._locks.get(norm)

    async def verify_can_edit(self, file_path: str, agent_id: str) -> Tuple[bool, str]:
        norm = self._normalize(file_path)
        async with self._get_lock():
            owner = self._locks.get(norm)
            if owner is None:
                # Auto-acquire if unlocked
                self._locks[norm] = agent_id
                return True, "Lock acquired"
            if owner == agent_id:
                return True, "Owner verified"
            return False, f"File '{file_path}' is locked by agent '{owner}'"


# =============================================================================
# 3. SPECIALIZED AGENT RUNNERS (AUTHENTIC AI & TOOL EXECUTION)
# =============================================================================

class BaseAgentRunner:
    """Base class for specialized agents running real AI inferences and tool executions."""

    def __init__(
        self,
        context: AgentContext,
        ownership_mgr: FileOwnershipManager,
        workspace_path: str,
        ai_provider_manager: Any = None
    ):
        self.ctx = context
        self.ownership_mgr = ownership_mgr
        self.workspace_path = workspace_path
        self.ai_manager = ai_provider_manager or global_ai_provider_manager
        self.terminal_session_id: Optional[str] = None

    def _get_system_prompt(self, user_goal: str) -> str:
        raise NotImplementedError

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validates permissions, verifies file ownership if side-effecting, and executes tool."""
        # 1. Permission check
        allowed, reason = self.ctx.permissions.is_tool_allowed(tool_name)
        if not allowed:
            self.ctx.log("WARN", f"Blocked tool '{tool_name}': {reason}")
            return {"status": "error", "message": reason}

        # 2. File ownership check for write operations
        if tool_name in ("create_file", "fs_create_file", "edit_file", "fs_edit_file", "apply_patch", "fs_apply_patch"):
            target_path = arguments.get("file_path") or arguments.get("path") or arguments.get("file")
            if target_path:
                can_edit, lock_reason = await self.ownership_mgr.verify_can_edit(str(target_path), self.ctx.agent_id)
                if not can_edit:
                    self.ctx.log("ERROR", f"File ownership conflict for '{target_path}': {lock_reason}")
                    return {
                        "status": "conflict_error",
                        "error": lock_reason,
                        "file": target_path
                    }
                self.ctx.owned_files.add(str(target_path))

        # 3. Authentic dispatch via terminal_service.ToolDispatcher
        from terminal_service import ToolDispatcher, TerminalManager
        self.ctx.log("TOOL", f"Dispatching '{tool_name}'", {"args": list(arguments.keys())})
        
        try:
            # Dedicated per-agent terminal session isolation
            if tool_name in ToolDispatcher.TERMINAL_TOOLS:
                if not arguments.get("session_id") and not arguments.get("id"):
                    if not self.terminal_session_id:
                        sess_res = TerminalManager.create_terminal(
                            workspace_path=self.workspace_path,
                            caller_uid=f"agent-{self.ctx.agent_id}"
                        )
                        self.terminal_session_id = sess_res["session_id"]
                    arguments["session_id"] = self.terminal_session_id

            # Inject workspace directory if not explicitly provided
            if "workspace" not in arguments and "dir_path" not in arguments and tool_name in ("list_directory", "search_files"):
                arguments["dir_path"] = self.workspace_path

            res = await ToolDispatcher.dispatch_async(tool_name, arguments)
            return res
        except Exception as exc:
            self.ctx.log("ERROR", f"Tool '{tool_name}' failed: {exc}")
            return {"status": "error", "message": str(exc)}

    async def run(
        self,
        user_goal: str,
        user_id: str = "default_user",
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        max_turns: int = 5,
        cancel_event: Optional[asyncio.Event] = None
    ) -> Dict[str, Any]:
        """Executes agent workflow with real AI inference, tool calls, and error handling."""
        self.ctx.started_at = time.time()
        self.ctx.status = AgentStatus.RUNNING
        self.ctx.status_message = "Executing assigned task"
        self.ctx.log("PROGRESS", f"Starting {self.ctx.role.value} execution")

        sys_prompt = self._get_system_prompt(user_goal)
        self.ctx.messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Task Objective:\n{user_goal}\n\nContext and Inputs:\n{json.dumps(self.ctx.input_artifacts, indent=2)}"}
        ]

        try:
            turns = 0
            while turns < max_turns:
                if cancel_event and cancel_event.is_set():
                    self.ctx.status = AgentStatus.CANCELLED
                    self.ctx.status_message = "Operation cancelled by user"
                    self.ctx.log("WARN", "Agent execution cancelled")
                    return {"status": "cancelled"}

                turns += 1
                self.ctx.log("PROGRESS", f"Turn {turns}/{max_turns}: Requesting AI response")

                try:
                    ai_resp = await self.ai_manager.execute_chat(
                        messages=self.ctx.messages,
                        model_id=model_id,
                        provider_id=provider_id,
                        user_id=user_id,
                        temperature=0.2
                    )
                except ProviderRateLimitError as rl:
                    self.ctx.log("WARN", f"Rate limit encountered: {rl}. Retrying after backoff...")
                    await asyncio.sleep(min(rl.retry_after_sec or 3.0, 10.0))
                    continue
                except Exception as exc:
                    self.ctx.log("ERROR", f"AI execution error: {exc}")
                    self.ctx.status = AgentStatus.FAILED
                    self.ctx.error = str(exc)
                    return {"status": "failed", "error": str(exc)}

                content = ai_resp.content or ""
                self.ctx.messages.append({"role": "assistant", "content": content})
                if content.strip():
                    self.ctx.log("THOUGHT", content[:400] + ("..." if len(content) > 400 else ""))

                # Inspect tool calls
                tool_calls = ai_resp.tool_calls or []
                if not tool_calls:
                    # Check for XML style <tool_call> in content
                    tool_calls = self._extract_xml_tool_calls(content)

                if not tool_calls:
                    # Agent completed its thinking and produced final answer
                    break

                # Execute tool calls
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        t_name = tc.get("function", {}).get("name") or tc.get("name")
                        t_raw_args = tc.get("function", {}).get("arguments") or tc.get("arguments") or {}
                    else:
                        t_name = getattr(tc, "name", "")
                        t_raw_args = getattr(tc, "arguments", {})

                    if isinstance(t_raw_args, str):
                        try:
                            t_args = json.loads(t_raw_args)
                        except Exception:
                            t_args = {}
                    else:
                        t_args = t_raw_args

                    tool_result = await self.execute_tool(t_name, t_args)
                    sanitized_str = ToolOutputObserver.sanitize(tool_name=t_name, result_data=tool_result)
                    self.ctx.messages.append({
                        "role": "user",
                        "content": f"[TOOL_RESULT for {t_name}]\n{sanitized_str}"
                    })

            # Process role-specific output artifacts
            self._extract_output_artifacts()
            self.ctx.finished_at = time.time()
            self.ctx.status = AgentStatus.COMPLETED
            self.ctx.status_message = "Completed assigned role tasks"
            self.ctx.log("PROGRESS", f"Completed {self.ctx.role.value} role successfully")
            return {
                "status": "completed",
                "role": self.ctx.role.value,
                "artifacts": self.ctx.output_artifacts
            }
        finally:
            if self.terminal_session_id:
                try:
                    from terminal_service import TerminalManager
                    TerminalManager.stop_terminal(self.terminal_session_id)
                except Exception:
                    pass

    def _extract_xml_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        import re
        calls = []
        matches = re.finditer(r"<tool_call>\s*({.*?})\s*</tool_call>", text, re.DOTALL)
        for m in matches:
            try:
                parsed = json.loads(m.group(1))
                if "name" in parsed:
                    calls.append(parsed)
            except Exception:
                pass
        return calls

    def _extract_output_artifacts(self):
        """Default fallback: captures final assistant message."""
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["summary"] = last_assistant


# -----------------------------------------------------------------------------
# 3.1 Researcher Agent
# -----------------------------------------------------------------------------
class ResearcherAgent(BaseAgentRunner):
    """Investigates the task, codebase, files, symbols, and dependencies."""

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the RESEARCHER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to thoroughly investigate the codebase and task requirements.\n"
            "INSTRUCTIONS:\n"
            "1. Read relevant files, list directories, search for functions and symbols.\n"
            "2. Identify the architecture, dependencies, conventions, and existing tests.\n"
            "3. DO NOT write or edit code. You only have read and search permissions.\n"
            "4. Provide a structured research summary detailing:\n"
            "   - Key files and their roles\n"
            "   - Dependencies and constraints\n"
            "   - Technical patterns and edge cases to consider\n"
        )

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["research_report"] = {
            "summary": last_assistant,
            "inspected_files": list(self.ctx.owned_files),
            "timestamp": time.time()
        }


# -----------------------------------------------------------------------------
# 3.2 Planner Agent
# -----------------------------------------------------------------------------
class PlannerAgent(BaseAgentRunner):
    """Creates a structured, actionable implementation plan."""

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the PLANNER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to formulate a comprehensive, step-by-step implementation plan.\n"
            "INSTRUCTIONS:\n"
            "1. Review the user objective and the Researcher's findings.\n"
            "2. Break down the task into discrete, ordered implementation steps.\n"
            "3. Explicitly list all files to create, edit, or refactor.\n"
            "4. Define verification and test requirements for each step.\n"
            "5. Structure your output with: [OBJECTIVE], [FILES_TO_MODIFY], [STEPS], [TEST_PLAN], [RISKS].\n"
        )

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["implementation_plan"] = {
            "plan_text": last_assistant,
            "created_at": time.time()
        }


# -----------------------------------------------------------------------------
# 3.3 Developer Agent
# -----------------------------------------------------------------------------
class DeveloperAgent(BaseAgentRunner):
    """Implements assigned code changes strictly adhering to the plan."""

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the DEVELOPER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to implement the assigned changes following the implementation plan.\n"
            "INSTRUCTIONS:\n"
            "1. Write clean, production-ready, robust code with zero placeholders.\n"
            "2. Use file tools ('edit_file', 'create_file', 'apply_patch') to apply changes.\n"
            "3. Respect Stroke's No-Delete policy: never delete existing files.\n"
            "4. Keep edits surgical and preserve existing non-conflicting code.\n"
            "5. Summarize every change applied and list the modified files.\n"
        )

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["development_report"] = {
            "summary": last_assistant,
            "modified_files": sorted(list(self.ctx.owned_files)),
            "timestamp": time.time()
        }


# -----------------------------------------------------------------------------
# 3.4 Tester Agent
# -----------------------------------------------------------------------------
class TesterAgent(BaseAgentRunner):
    """Runs tests and static/dynamic verification on modified code."""
    __test__ = False

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the TESTER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to verify all code changes and identify any failures.\n"
            "INSTRUCTIONS:\n"
            "1. Inspect the modified files and test coverage.\n"
            "2. Run automated syntax, AST, and domain test checks on Luau or Python code.\n"
            "3. Report passed checks, failed checks, and exact line-level errors.\n"
            "4. Be strictly evidence-bound: never report tests passed without positive verification.\n"
            "5. Conclude with a clear status: VERIFIED or FAILED.\n"
        )

    async def run_automated_checks(self, files: List[str]) -> Dict[str, Any]:
        """Runs native Luau and Python test engines on modified files."""
        passed = []
        failed = []

        from coding_loop import RobloxDomainTestRunner, LuauSyntaxValidator

        for fpath in files:
            full_p = Path(fpath)
            if not full_p.is_absolute():
                full_p = Path(self.workspace_path) / fpath
            if not full_p.exists() or not full_p.is_file():
                continue

            content = full_p.read_text(encoding="utf-8", errors="replace")
            suffix = full_p.suffix.lower()

            if suffix in (".lua", ".luau"):
                res = RobloxDomainTestRunner.test_luau_code(content, prompt="Parallel agent verification")
                for p in res.get("passed_checks", []):
                    passed.append(f"{full_p.name}: {p}")
                for f in res.get("failed_checks", []):
                    failed.append({
                        "file": str(full_p.name),
                        "check": f.get("message") if isinstance(f, dict) else str(f),
                        "line": f.get("line") if isinstance(f, dict) else 1
                    })
            elif suffix == ".py":
                res = RobloxDomainTestRunner.test_python_code(content, prompt="Parallel agent verification")
                for p in res.get("passed_checks", []):
                    passed.append(f"{full_p.name}: {p}")
                for f in res.get("failed_checks", []):
                    failed.append({
                        "file": str(full_p.name),
                        "check": f.get("message") if isinstance(f, dict) else str(f),
                        "line": f.get("line") if isinstance(f, dict) else 1
                    })

        is_verified = (len(failed) == 0 and len(passed) > 0)
        return {
            "passed_checks": passed,
            "failed_checks": failed,
            "is_verified": is_verified
        }

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["test_report"] = {
            "summary": last_assistant,
            "is_verified": "FAILED" not in last_assistant.upper(),
            "timestamp": time.time()
        }


# -----------------------------------------------------------------------------
# 3.5 Reviewer Agent
# -----------------------------------------------------------------------------
class ReviewerAgent(BaseAgentRunner):
    """Independently audits changes against quality, security, and requirements."""

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the REVIEWER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to independently critique the implementation and test results.\n"
            "INSTRUCTIONS:\n"
            "1. Inspect the modified files against the original objective and implementation plan.\n"
            "2. Check for security vulnerabilities, edge cases, anti-patterns, and regressions.\n"
            "3. Verify adherence to Stroke's architectural standards.\n"
            "4. Conclude with either: [VERDICT: APPROVED] or [VERDICT: CHANGES_REQUESTED].\n"
            "5. If changes are requested, detail actionable recommendations for the Debugger.\n"
        )

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        verdict = "APPROVED" if "CHANGES_REQUESTED" not in last_assistant.upper() else "CHANGES_REQUESTED"
        self.ctx.output_artifacts["review_report"] = {
            "verdict": verdict,
            "critique": last_assistant,
            "timestamp": time.time()
        }


# -----------------------------------------------------------------------------
# 3.6 Debugger Agent
# -----------------------------------------------------------------------------
class DebuggerAgent(BaseAgentRunner):
    """Investigates verified issues, diagnoses root causes, and applies surgical fixes."""

    def _get_system_prompt(self, user_goal: str) -> str:
        return (
            "You are the DEBUGGER AGENT in Stroke's parallel multi-agent system.\n"
            "Your responsibility is to investigate test failures and reviewer critiques, then apply fixes.\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the test failure traces and review comments provided in your inputs.\n"
            "2. Read the affected lines in the files and diagnose the exact root cause.\n"
            "3. Apply surgical, targeted fixes using 'edit_file' or 'apply_patch'.\n"
            "4. Do not introduce regressions or rewrite unrelated code.\n"
            "5. Summarize the diagnosed root causes and the specific fixes implemented.\n"
        )

    def _extract_output_artifacts(self):
        last_assistant = next((m["content"] for m in reversed(self.ctx.messages) if m.get("role") == "assistant"), "")
        self.ctx.output_artifacts["debug_report"] = {
            "summary": last_assistant,
            "fixed_files": sorted(list(self.ctx.owned_files)),
            "timestamp": time.time()
        }


# =============================================================================
# 4. PARENT MULTI-AGENT ORCHESTRATOR
# =============================================================================

@dataclass
class OrchestratorJob:
    job_id: str
    user_goal: str
    workspace_path: str
    user_uid: str = "default_user"
    status: JobStatus = JobStatus.PLANNED
    agents: Dict[AgentRole, AgentContext] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    isolated_sandbox: Optional[Dict[str, Any]] = None
    final_verification: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        evt = {
            "job_id": self.job_id,
            "type": event_type,
            "timestamp": time.time(),
            "data": data
        }
        self.events.append(evt)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "user_goal": self.user_goal,
            "workspace_path": self.workspace_path,
            "user_uid": self.user_uid,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "agents": {role.value: ctx.to_dict() for role, ctx in self.agents.items()},
            "final_verification": self.final_verification,
            "events_count": len(self.events),
            "recent_events": self.events[-20:]
        }


class MultiAgentOrchestrator:
    """
    Parent Multi-Agent Orchestrator managing parallel sub-agent execution,
    file ownership, stage progression, retries, cancellation, and safe reconciliation.
    """

    def __init__(self):
        self.jobs: Dict[str, OrchestratorJob] = {}
        self.ownership_mgr = FileOwnershipManager()
        self._cancellation_events: Dict[str, asyncio.Event] = {}
        self._cancelled_jobs: Set[str] = set()
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_or_create_cancel_event(self, job_id: str) -> asyncio.Event:
        if job_id not in self._cancellation_events:
            self._cancellation_events[job_id] = asyncio.Event()
            if job_id in self._cancelled_jobs:
                self._cancellation_events[job_id].set()
        return self._cancellation_events[job_id]

    def get_job(self, job_id: str) -> Optional[OrchestratorJob]:
        return self.jobs.get(job_id)

    def list_jobs(self, user_uid: Optional[str] = None) -> List[Dict[str, Any]]:
        jobs_list = list(self.jobs.values())
        if user_uid and user_uid != "default_user":
            jobs_list = [j for j in jobs_list if j.user_uid == user_uid]
        return [j.to_dict() for j in sorted(jobs_list, key=lambda x: x.created_at, reverse=True)]

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        self._cancelled_jobs.add(job_id)
        job.status = JobStatus.CANCELLED
        job.updated_at = time.time()
        job.emit_event("job_cancelled", {"reason": "User requested cancellation"})

        evt = self._cancellation_events.get(job_id)
        if evt:
            evt.set()

        for agent in job.agents.values():
            if agent.status in (AgentStatus.RUNNING, AgentStatus.QUEUED, AgentStatus.AWAITING_DEPENDENCY):
                agent.status = AgentStatus.CANCELLED
                agent.status_message = "Job cancelled by orchestrator"

        self._persist_jobs()
        return True

    def create_job(
        self,
        user_goal: str,
        workspace_path: str,
        user_uid: str = "default_user",
        job_id: Optional[str] = None
    ) -> OrchestratorJob:
        jid = job_id or f"pjob_{uuid.uuid4().hex[:12]}"
        clean_ws = str(Path(workspace_path).resolve())
        try:
            workspace_service.approve_workspace(clean_ws)
        except Exception:
            pass

        # Initialize all 6 specialized agent contexts
        roles = [
            AgentRole.RESEARCHER,
            AgentRole.PLANNER,
            AgentRole.DEVELOPER,
            AgentRole.TESTER,
            AgentRole.REVIEWER,
            AgentRole.DEBUGGER
        ]

        agents: Dict[AgentRole, AgentContext] = {}
        for r in roles:
            aid = f"{jid}_{r.value}"
            agents[r] = AgentContext(
                agent_id=aid,
                role=r,
                name=f"{r.value.capitalize()} Agent",
                permissions=get_default_permissions_for_role(r)
            )

        job = OrchestratorJob(
            job_id=jid,
            user_goal=user_goal.strip(),
            workspace_path=clean_ws,
            user_uid=user_uid,
            agents=agents
        )
        self.jobs[jid] = job
        job.emit_event("job_created", {"user_goal": user_goal})
        self._persist_jobs()
        return job

    async def run_job(
        self,
        job_id: str,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        use_isolated_sandbox: bool = False
    ) -> Dict[str, Any]:
        """
        Executes the parent orchestration lifecycle:
        1. Researcher investigates codebase.
        2. Planner designs step-by-step plan.
        3. Developer applies changes (with file ownership locks).
        4. Parallel Tester & Reviewer evaluate the developer output.
        5. If errors found -> Debugger fixes, then re-tests.
        6. Final verification gate & safe reconciliation.
        """
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"Job '{job_id}' not found.")

        cancel_evt = self._get_or_create_cancel_event(job_id)
        job.status = JobStatus.RUNNING
        job.updated_at = time.time()
        job.emit_event("job_started", {"status": "running"})

        active_ws = job.workspace_path

        # 0. Optional Isolated Task Sandbox
        if use_isolated_sandbox:
            try:
                sandbox_res = isolated_workspace.create_task_workspace(job.workspace_path, job.job_id)
                active_ws = sandbox_res["isolated_workspace"]
                job.isolated_sandbox = sandbox_res
                job.emit_event("sandbox_created", sandbox_res)
            except Exception as e:
                logger.warning("Could not initialize sandbox for %s: %s", job_id, e)

        try:
            # -----------------------------------------------------------------
            # STAGE 1: RESEARCH
            # -----------------------------------------------------------------
            if cancel_evt.is_set():
                return job.to_dict()

            res_ctx = job.agents[AgentRole.RESEARCHER]
            job.emit_event("stage_started", {"stage": "research", "agent": res_ctx.name})
            researcher = ResearcherAgent(res_ctx, self.ownership_mgr, active_ws)
            res_out = await researcher.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)
            job.emit_event("stage_completed", {"stage": "research", "artifacts": res_ctx.output_artifacts})

            # -----------------------------------------------------------------
            # STAGE 2: PLANNING
            # -----------------------------------------------------------------
            if cancel_evt.is_set():
                return job.to_dict()

            plan_ctx = job.agents[AgentRole.PLANNER]
            plan_ctx.input_artifacts = dict(res_ctx.output_artifacts)
            job.emit_event("stage_started", {"stage": "planning", "agent": plan_ctx.name})
            planner = PlannerAgent(plan_ctx, self.ownership_mgr, active_ws)
            plan_out = await planner.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)
            job.emit_event("stage_completed", {"stage": "planning", "artifacts": plan_ctx.output_artifacts})

            # -----------------------------------------------------------------
            # STAGE 3: DEVELOPMENT
            # -----------------------------------------------------------------
            if cancel_evt.is_set():
                return job.to_dict()

            dev_ctx = job.agents[AgentRole.DEVELOPER]
            dev_ctx.input_artifacts = {
                **res_ctx.output_artifacts,
                **plan_ctx.output_artifacts
            }
            job.emit_event("stage_started", {"stage": "development", "agent": dev_ctx.name})
            developer = DeveloperAgent(dev_ctx, self.ownership_mgr, active_ws)
            dev_out = await developer.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)
            job.emit_event("stage_completed", {"stage": "development", "artifacts": dev_ctx.output_artifacts})

            # -----------------------------------------------------------------
            # STAGE 4: PARALLEL TESTING & REVIEW
            # -----------------------------------------------------------------
            if cancel_evt.is_set():
                return job.to_dict()

            test_ctx = job.agents[AgentRole.TESTER]
            rev_ctx = job.agents[AgentRole.REVIEWER]

            test_ctx.input_artifacts = {
                "user_goal": job.user_goal,
                "modified_files": sorted(list(dev_ctx.owned_files)),
                "plan": plan_ctx.output_artifacts.get("implementation_plan", {})
            }
            rev_ctx.input_artifacts = {
                "user_goal": job.user_goal,
                "modified_files": sorted(list(dev_ctx.owned_files)),
                "plan": plan_ctx.output_artifacts.get("implementation_plan", {}),
                "development_report": dev_ctx.output_artifacts.get("development_report", {})
            }

            job.emit_event("stage_started", {"stage": "parallel_verification", "agents": [test_ctx.name, rev_ctx.name]})

            tester = TesterAgent(test_ctx, self.ownership_mgr, active_ws)
            reviewer = ReviewerAgent(rev_ctx, self.ownership_mgr, active_ws)

            # Parallel execution of Tester and Reviewer using asyncio.gather
            test_task = tester.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)
            rev_task = reviewer.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)

            test_out, rev_out = await asyncio.gather(test_task, rev_task)
            job.emit_event("stage_completed", {
                "stage": "parallel_verification",
                "test_artifacts": test_ctx.output_artifacts,
                "review_artifacts": rev_ctx.output_artifacts
            })

            # Run automated syntax & AST checks across touched files
            automated_check_results = await tester.run_automated_checks(list(dev_ctx.owned_files))

            # -----------------------------------------------------------------
            # STAGE 5: DEBUGGING & SELF-CORRECTION (IF VERIFICATION FAILED)
            # -----------------------------------------------------------------
            review_verdict = rev_ctx.output_artifacts.get("review_report", {}).get("verdict", "APPROVED")
            needs_debugging = (
                not automated_check_results.get("is_verified", True)
                or review_verdict == "CHANGES_REQUESTED"
                or not test_ctx.output_artifacts.get("test_report", {}).get("is_verified", True)
            )

            if needs_debugging and not cancel_evt.is_set():
                debug_ctx = job.agents[AgentRole.DEBUGGER]
                debug_ctx.input_artifacts = {
                    "automated_checks": automated_check_results,
                    "test_report": test_ctx.output_artifacts.get("test_report", {}),
                    "review_report": rev_ctx.output_artifacts.get("review_report", {}),
                    "modified_files": sorted(list(dev_ctx.owned_files))
                }

                job.emit_event("stage_started", {"stage": "debugging", "agent": debug_ctx.name})
                debugger = DebuggerAgent(debug_ctx, self.ownership_mgr, active_ws)
                debug_out = await debugger.run(job.user_goal, user_id=job.user_uid, model_id=model_id, provider_id=provider_id, cancel_event=cancel_evt)

                # Re-run automated tests after debugger fix
                automated_check_results = await tester.run_automated_checks(list(dev_ctx.owned_files | debug_ctx.owned_files))
                job.emit_event("stage_completed", {"stage": "debugging", "artifacts": debug_ctx.output_artifacts})

            # -----------------------------------------------------------------
            # STAGE 6: FINAL VERIFICATION & RECONCILIATION
            # -----------------------------------------------------------------
            job.status = JobStatus.VERIFYING
            job.updated_at = time.time()

            reconciliation_result = None
            if job.isolated_sandbox and active_ws != job.workspace_path:
                try:
                    reconciliation_result = isolated_workspace.apply_task_changes(
                        job.job_id,
                        description=f"Multi-agent changes for {job.job_id}"
                    )
                    job.emit_event("sandbox_reconciled", reconciliation_result)
                except Exception as rec_err:
                    logger.error("Failed to reconcile sandbox for %s: %s", job_id, rec_err)

            # Release all file locks held by all agents
            for agent in job.agents.values():
                await self.ownership_mgr.release_all(agent.agent_id)

            job.final_verification = {
                "automated_checks": automated_check_results,
                "reconciliation": reconciliation_result,
                "reviewer_verdict": rev_ctx.output_artifacts.get("review_report", {}).get("verdict", "APPROVED"),
                "verified_at": time.time()
            }

            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()
            job.updated_at = time.time()
            job.emit_event("job_completed", {"status": "completed"})
            self._persist_jobs()
            return job.to_dict()

        except Exception as exc:
            logger.exception("Multi-agent job %s encountered fatal error: %s", job_id, exc)
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.updated_at = time.time()
            job.emit_event("job_failed", {"error": str(exc)})
            # Release all locks on failure
            for agent in job.agents.values():
                await self.ownership_mgr.release_all(agent.agent_id)
            self._persist_jobs()
            return job.to_dict()

    # -------------------------------------------------------------------------
    # PERSISTENCE & AUDIT
    # -------------------------------------------------------------------------
    def _get_storage_file(self) -> Path:
        app_dir = paths_service.get_app_data_dir()
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir / "parallel_agent_jobs.json"

    def _persist_jobs(self):
        try:
            target = self._get_storage_file()
            data = {jid: j.to_dict() for jid, j in self.jobs.items()}
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as exc:
            logger.warning("Failed to persist parallel agent jobs: %s", exc)

    def load_persisted_jobs(self):
        try:
            target = self._get_storage_file()
            if not target.exists():
                return
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            for jid, jdata in data.items():
                if jid not in self.jobs:
                    # Reconstruct job
                    agents: Dict[AgentRole, AgentContext] = {}
                    for r_str, adata in jdata.get("agents", {}).items():
                        try:
                            role_enum = AgentRole(r_str)
                            agents[role_enum] = AgentContext(
                                agent_id=adata.get("agent_id", f"{jid}_{r_str}"),
                                role=role_enum,
                                name=adata.get("name", r_str),
                                status=AgentStatus(adata.get("status", "completed")),
                                status_message=adata.get("status_message", ""),
                                created_at=adata.get("created_at", time.time()),
                                output_artifacts=adata.get("output_artifacts", {})
                            )
                        except Exception:
                            pass
                    job = OrchestratorJob(
                        job_id=jid,
                        user_goal=jdata.get("user_goal", ""),
                        workspace_path=jdata.get("workspace_path", ""),
                        user_uid=jdata.get("user_uid", "default_user"),
                        status=JobStatus(jdata.get("status", "completed")),
                        agents=agents,
                        created_at=jdata.get("created_at", time.time()),
                        completed_at=jdata.get("completed_at"),
                        final_verification=jdata.get("final_verification", {})
                    )
                    self.jobs[jid] = job
        except Exception as exc:
            logger.warning("Failed to load persisted parallel agent jobs: %s", exc)


# Global Singleton Orchestrator
global_multi_agent_orchestrator = MultiAgentOrchestrator()
global_multi_agent_orchestrator.load_persisted_jobs()
