# Stroke Production-Ready Terminal Infrastructure

## 1. Overview & Architecture

Stroke's internal background terminal system (`terminal_service.py`) provides an autonomous, sandboxed execution environment designed for high-concurrency coding agents, parallel agent orchestration, and live development verification. 

Unlike naive subshell executors or stateless CLI runners, Stroke's terminal features **persistent stateful sessions**, **strict process lifecycle management**, **real-time streaming without output duplication**, **process group isolation**, and **multi-agent workspace protection**.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Stroke AI Orchestrator                          │
│  (Parent Orchestrator / Parallel Agents: Researcher, Dev, Tester, etc.) │
└──────────────┬───────────────────────────┬─────────────────────────────┘
               │ Dedicated Session A       │ Dedicated Session B
               ▼                           ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│  Terminal Session (term-A)   │ │  Terminal Session (term-B)   │
│  • Session Env: {KEY: VAL}   │ │  • Session Env: {KEY: VAL}   │
│  • Active CWD: /path/to/ws   │ │  • Active CWD: /path/to/ws   │
│  • Process Group (POSIX)     │ │  • Process Group (POSIX)     │
│  • Ring Buffer: 256 KB cap   │ │  • Ring Buffer: 256 KB cap   │
│  • Chronological Exec Log    │ │  • Chronological Exec Log    │
└──────────────┬───────────────┘ └──────────────┬───────────────┘
               │ Real-Time Line Streaming       │
               ▼                                ▼
┌───────────────────────────────────────────────────────────────┐
│        Server-Sent Events (SSE) & REST History Endpoints      │
│     • GET /terminal/{id}/stream  • GET /terminal/{id}/history │
└───────────────────────────────────────────────────────────────┘
```

---

## 2. Core Capabilities & Production Hardening

### 2.1 Persistent Session Environment (`export` & `unset`)
- **Session-Scoped Variables**: Each session maintains an independent `self.session_env: Dict[str, str]` dictionary. Variables set via built-in `export KEY=VALUE` persist across subsequent commands in that session without polluting the parent operating system or other sessions.
- **Child Process Inheritance**: When launching child processes (`subprocess.Popen`), the session environment is merged into the sanitized child environment: `env.update(self.session_env)`.
- **Variable Unsetting**: Built-in `unset KEY` removes keys from `session_env`.
- **Isolation Guarantee**: Session A exports never leak to Session B, verified by test `test_02_persistent_session_environment_export_and_unset`.

### 2.2 Working Directory Tracking (`cd`, `cd -`, `cd ~`)
- **Stateful Directory History**: Tracks `self.cwd` and `self.prev_cwd`.
- **Toggle Navigation**: Supports `cd -` to return to the previous working directory, and `cd ~` for home navigation.
- **Strict Boundary Enforcement**: Every directory change validates canonical paths against approved workspace roots (`workspace_service.is_allowed_workspace_root`). Any attempt to traverse outside approved workspaces (e.g. `cd /`, `cd ../../../..`) is blocked with an explicit security failure without modifying `self.cwd`.

### 2.3 Real-Time Streaming & Output Ring Buffers
- **Immediate Line-by-Line Streaming**: Synchronous and background executions read child process stdout/stderr line-by-line via `pipe.readline` and immediately append redacted lines to the session ring buffer (`self._append_output(stream_name, decoded)`).
- **Duplicate Suppression**: Eliminates redundant post-execution buffer appends. Every stdout/stderr line is captured once and streamed live to delta listeners.
- **Bounded Memory Capping**: Output ring buffers cap memory usage at 256 KB (`MAX_OUTPUT_BYTES = 256 * 1024`) and individual lines at 4,000 characters to prevent memory exhaustion or denial-of-service from runaway scripts.
- **Sensitive Data Redaction**: Automatic scrubbing of API keys, bearer tokens, private keys, and passwords before storing lines in memory or streaming over SSE.

### 2.4 Process Cancellation & Lifecycle State Preservation
- **Process Group Termination**: POSIX process groups are created via `start_new_session=True`. When a session is cancelled or stopped (`TerminalSession.stop()`), the entire process tree is terminated (`SIGTERM` followed by `SIGKILL` escalation), preventing orphaned child processes.
- **State Integrity**: Cancellation preserves `self.state = "terminated"`. Process exit unblocking guards prevent overwriting `"terminated"` with `"failed"`.
- **Reaped Session Retention**: Terminated sessions are moved to a bounded LRU history deque (`_reaped_history`), allowing post-mortem inspection of output buffers and execution logs even after process termination.

### 2.5 Multi-Agent & Parallel Task Isolation
- **Dedicated Sessions**: `parallel_agent_system.py` (`BaseAgentRunner`) and `agent_orchestrator.py` (`AgentTask`) associate dedicated `terminal_session_id`s with each running agent and task.
- **Zero Cross-Agent Collateral**: Stopping, failing, or cancelling Agent A reaps only Agent A's process group and terminal session. Concurrently running tasks and agents (e.g. Agent B, background daemons) continue executing with zero interference, verified in `test_07_multi_session_and_parallel_agent_isolation`.
- **Automatic Resource Reclaiming**: Agent runners and tasks register `finally` cleanup handlers to guarantee session termination upon completion or unexpected exceptions.

---

## 3. REST API & Streaming Endpoints

| Endpoint | Method | Authentication | Description |
|---|---|---|---|
| `/terminal/create` | `POST` | Bearer Token / Internal Key | Initializes a silent, isolated background terminal session |
| `/terminal/run` | `POST` | Bearer Token / Internal Key | Executes an allowlisted or pre-approved command |
| `/terminal/{id}/output` | `GET` | Bearer Token / Internal Key | Retrieves captured output lines with optional `tail` filter |
| `/terminal/{id}/status` | `GET` | Bearer Token / Internal Key | Retrieves live execution status, cwd, exit code, and active PID |
| `/terminal/{id}/history` | `GET` | Bearer Token / Internal Key | Returns chronological command execution log for the session |
| `/terminal/{id}/stream` | `GET` | Bearer Token / Internal Key | Server-Sent Events (SSE) streaming endpoint for live output lines |
| `/terminal/{id}/stop` | `POST` | Bearer Token / Internal Key | Terminates the active process group and reclaims resources |
| `/terminal/{id}/restart` | `POST` | Bearer Token / Internal Key | Restarts the session's last executed command |
| `/terminal/list` | `GET` | Bearer Token / Internal Key | Lists active background terminal sessions |
| `/terminal/output/delta` | `GET` | Bearer Token / Internal Key | Polls incremental lines since a given sequence number |
| `/terminal/approval/respond` | `POST` | Bearer Token / Internal Key | Atomically permits or denies a pending privileged command |

---

## 4. Verification & Regression Test Results

### 4.1 Production Terminal Suite (`test_terminal_production.py`)
```
test_01_max_timeout_and_config .................................... PASSED [  9%]
test_02_persistent_session_environment_export_and_unset ........... PASSED [ 18%]
test_03_directory_tracking_and_boundary_enforcement ............... PASSED [ 27%]
test_04_execution_history_tracking ................................ PASSED [ 36%]
test_05_synchronous_real_time_streaming_no_duplicates ............. PASSED [ 45%]
test_06_process_cancellation_preserves_terminated_state ........... PASSED [ 54%]
test_07_multi_session_and_parallel_agent_isolation ................ PASSED [ 63%]
test_08_http_history_endpoint ..................................... PASSED [ 72%]
test_09_http_stream_sse_endpoint .................................. PASSED [ 81%]
test_10_parallel_agent_runner_terminal_isolation .................. PASSED [ 90%]
test_11_orchestrator_task_terminal_isolation_and_cancellation ..... PASSED [100%]
============================== 11 passed in 10.09s ==============================
```

### 4.2 Comprehensive Terminal Tests (5 Test Suites)
- `test_terminal_production.py` (11 tests): PASSED
- `test_terminal_api.py` (2 tests): PASSED
- `test_terminal_security_and_lifecycle.py` (16 tests): PASSED
- `test_terminal_stress.py` (9 tests): PASSED
- `test_terminal_system.py` (16 tests): PASSED
- **Total Terminal Tests: 54 PASSED (100%)**

### 4.3 Repository-Wide Regressions
- **Backend Pytest Suite**: 431 passed, 0 failed, 5 warnings in 47.34s (100% pass rate)
- **Frontend Vitest Suite**: 17 passed, 0 failed in 420ms (100% pass rate)
- **Frontend Production Build**: `npm run build` compiled successfully (100% pass rate)
