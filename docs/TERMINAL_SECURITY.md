# Stroke AI // Terminal Security and Process Lifecycle Specification

## 1. Executive Summary

Stroke is an autonomous AI programming environment that runs commands, tests, and builds locally on the developer's workstation. Because code generation models may emit commands that access the filesystem, interact with package managers, run interpreters, or trigger destructive side effects, Stroke enforces a strict Zero-Trust execution model.

This specification documents the terminal security architecture, atomic server-side approval protocol, process lifecycle controls, secret sanitization engine, and platform isolation model implemented in `terminal_service.py` and `main.py`.

---

## 2. Threat Model & Security Invariants

### 2.1 Threat Vectors Addressed
1. **Model Prompt Injection / Hallucination**: AI model generated commands attempting arbitrary command execution (`curl | sh`), deletion (`rm -rf /`), or privilege escalation (`sudo`).
2. **Loopback Confusion & CSRF**: Malicious websites or local browser scripts sending unauthenticated HTTP requests to `http://127.0.0.1:5000/terminal/run` or `/terminal/create`.
3. **Approval Hijacking & Replay**: Malicious clients forging approval flags (`approved=true`), replaying captured approval tokens, or approving actions across disparate sessions or users.
4. **Credential & Secret Exfiltration**: Child processes inheriting backend environment variables (Firebase service keys, GitHub PATs, Resend tokens, or encryption keys) or emitting them to `stdout`/`stderr`.
5. **Denial of Service / Unbounded Resource Consumption**: Infinite loops filling system memory with terminal logs, orphan processes surviving daemon shutdown, or rogue processes consuming file descriptors.

### 2.2 Core Security Invariants
* **Zero Administrator Policy**: Stroke runs exclusively as a standard unprivileged user. Commands requiring `sudo`, `su`, or UAC elevation are permanently **DENIED** and cannot run even with user approval.
* **Absolute No-Delete Policy**: Any AI-initiated command that contains file deletion utilities (`rm`, `del`, `rmdir`, `shred`, `git clean`, `git reset --hard`) or programmatic deletion methods (`os.remove`, `shutil.rmtree`) is strictly **DENIED**.
* **Zero-Trust Loopback Access**: Localhost network presence is not proof of identity. Every terminal API call requires either an internal per-launch shared secret or a cryptographically verified Firebase ID token.
* **One-Time Server-Side Approvals**: Approval records are generated server-side with strict cryptographic binding (UID, session ID, working directory, executable, argv, and 300-second TTL) and consumed atomically with anti-replay guarantees.
* **Sanitized Child Environment**: Child processes run in a strictly whitelisted environment. Backend secrets are completely stripped before subprocess invocation.
* **Bounded Output Ring Buffer**: Output streams are capped at 256 KB per process with older lines evicted, preventing pipe buffer deadlocks and memory exhaustion.
* **Process Tree Reclamation**: Child process trees are tracked in dedicated process groups and forcefully terminated on timeout, cancellation, or application exit.

---

## 3. Server-Side Atomic Approval Protocol

### 3.1 Elimination of Client-Controlled Bypasses
Legacy implementations accepted client-supplied boolean flags (e.g., `approved: true` in JSON payloads) or relied on environment switches (`STROKE_TEST_AUTO_APPROVE=1`). 

**All client-controlled approval parameters and environment bypasses have been completely removed.**
* In `terminal_service.py`, `evaluate_command_security` categorizes all commands into `ALLOWED`, `REQUIRES_APPROVAL`, or `DENIED`.
* If a command requires approval, `TerminalManager.run_command` immediately returns:
  ```json
  {
    "status": "requires_approval",
    "approval_id": "appr-8f7b2c1e4d3a",
    "command": "python",
    "args": ["-c", "import sys; ..."],
    "rationale": "Executing arbitrary inline code via 'python -c ...' requires user confirmation.",
    "expires_at": 1794710000.0
  }
  ```
* The command execution is paused. No child process is spawned until explicit, authenticated approval is granted.

### 3.2 Approval Record Data Model
Every approval request creates an immutable `ApprovalRecord` stored in the server's thread-safe registry:

```python
@dataclass
class ApprovalRecord:
    approval_id: str        # Cryptographically unique token (appr-<hex>)
    command: str            # Exact binary/executable name
    args: List[str]         # Exact argument vector
    session_id: str         # Bound terminal session ID
    cwd: str                # Exact working directory at request time
    uid: str                # Authenticated Firebase UID or internal_daemon
    rationale: str          # Human-readable policy rationale
    created_at: float       # Epoch timestamp
    expires_at: float       # Created + APPROVAL_TTL_SEC (300 seconds)
    is_background: bool     # Background vs synchronous flag
    consumed: bool = False  # Atomic consumption state
```

### 3.3 Atomic Consumption & Anti-Replay Engine
Approvals are handled via `POST /terminal/approval/respond`:
1. **Registry Lookup & Atomic Pop**: Under `_APPROVAL_LOCK`, the record is removed (`.pop()`) immediately from `_APPROVAL_REGISTRY`. If the record is missing, an error is returned: `approval_not_found_or_already_consumed`.
2. **Replay Rejection**: If `record.consumed` is true, the request fails with `approval_replayed`.
3. **Expiry Check**: If `time.time() > record.expires_at`, the token is rejected with `approval_expired`.
4. **UID Ownership Verification**: The caller's authenticated UID (derived from their Firebase ID token) must match `record.uid`. Cross-user approval attempts fail with `approval_user_mismatch`.
5. **Session & CWD Validation**: The session must still exist. If the working directory has changed between the request and the response (`session.cwd != record.cwd`), execution is rejected with `approval_cwd_mismatch`.
6. **Policy Re-Evaluation**: Even after user approval, the command is passed through `evaluate_command_security`. Commands prohibited by policy (e.g. `sudo`) are rejected with `command_prohibited`.
7. **Execution**: The command runs with `_approval_record=record`. The session verifies that the executable and argv match the record down to every argument token.

```
       [ Client Request ]
               |
      [ verify_terminal_access ] (Bearer Token / Secret)
               |
  [ evaluate_command_security ]
               |
     +---------+---------+
     |                   |
[ ALLOWED ]    [ REQUIRES_APPROVAL ] ---> Create Server ApprovalRecord (TTL: 300s)
     |                   |                     |
  Execute         Return Pending              Wait for User Confirmation
                         |                     |
                         +-------------> [ POST /terminal/approval/respond ]
                                               |
                                        [ Atomic Pop & Verify ]
                                         - Expiry Check (<= 300s)
                                         - UID Ownership Match
                                         - Session & CWD Match
                                         - Prohibited Policy Check
                                               |
                                        [ Execute Command ]
```

---

## 4. Zero-Trust Loopback Security

### 4.1 Threat Context
Because Stroke's backend runs on `http://127.0.0.1:5000`, browser-based drive-by attacks could attempt cross-origin requests to local endpoints (DNS rebinding, CSRF, or malicious extensions).

### 4.2 Endpoint Defense-in-Depth
All terminal endpoints (`/terminal/create`, `/terminal/run`, `/terminal/{session_id}/output`, `/terminal/{session_id}/status`, `/terminal/{session_id}/stop`, `/terminal/approval/respond`) enforce `verify_terminal_access`:
1. **Internal Daemon Token**: Background agent threads pass `X-Internal-Token` or `X-Stroke-Token` matching `STROKE_INTERNAL_SECRET`.
2. **Firebase Bearer Token**: Frontend and user-initiated requests must supply `Authorization: Bearer <Firebase_ID_Token>`. The token is cryptographically verified against Google's public RS256 certificates.
3. **Loopback IP Rejection**: Loopback IP (127.0.0.1) alone is explicitly rejected as proof of identity. Unauthenticated requests receive HTTP 401 Unauthorized.
4. **Host and Origin Enforcement**: CORS middleware restricts allowed origins to explicit application origins (`http://localhost:5000`, `tauri://localhost`, etc.).

---

## 5. Child Process Environment & Secret Sanitization

### 5.1 Environment Variable Whitelist
Child processes spawned by Stroke are not permitted to inherit the full host or backend environment. `get_sanitized_child_env` builds a restricted environment:

* **Allowed Variables**: `PATH`, `PATHEXT`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TERM`, `TMPDIR`, `TEMP`, `TMP`, `SYSTEMROOT`, `COMSPEC`, `WINDIR`, `APPDATA`, `LOCALAPPDATA`, `USERPROFILE`, `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME`, `NODE_ENV`, `NPM_CONFIG_COLOR`, `TERM_PROGRAM`.
* **Explicit Blacklist**: Any variable whose key contains `KEY`, `SECRET`, `TOKEN`, `PASS`, `CREDENTIAL`, `AUTH`, `CIPHER`, `DATABASE_URL`, `ADMIN`, `FIREBASE`, `GITHUB`, or `RESEND` is unconditionally stripped (unless whitelisted system paths like `PATHEXT`).
* **Hardcoded Clean Diagnostics**:
  - `PYTHONUNBUFFERED=1`
  - `PYTHONDONTWRITEBYTECODE=1`
  - `GRPC_ENABLE_FORK_SUPPORT=0`
  - `GRPC_POLL_STRATEGY=poll`

### 5.2 Cross-Platform PATH Construction
PATH variables are constructed using `os.pathsep` rather than POSIX-only colons (`:`), ensuring flawless operation on Windows (`;`) and macOS/Linux (`:`):
```python
clean_env["PATH"] = os.pathsep.join(valid_dirs + ([existing_path] if existing_path else []))
```
Search directories include:
- `workspace/venv/bin` (POSIX) and `workspace/venv/Scripts` (Windows)
- `~/.local/node/bin`
- `~/.aftman/bin`
- `~/.rokit/bin`
- System binary directories (`/usr/local/bin`, `/opt/homebrew/bin`)

### 5.3 Real-Time Secret Redaction Engine
Even if a developer prints credentials or an error trace outputs tokens, `redact_sensitive_data` applies regex transformations on all captured stdout, stderr, and output deltas before they enter the ring buffer or reach the LLM:
* GitHub PATs (`ghp_...`, `github_pat_...`) -> `[REDACTED_GITHUB_PAT]`
* Google & Firebase API Keys (`AIza...`) -> `[REDACTED_GOOGLE_API_KEY]`
* JWT Bearer Tokens (`Bearer ...`) -> `Bearer [REDACTED_JWT]`
* PEM Private Keys (`-----BEGIN ... PRIVATE KEY-----`) -> `[REDACTED_PRIVATE_KEY]`
* Resend API Keys (`re_...`) -> `[REDACTED_RESEND_API_KEY]`
* Internal Stroke Secrets (`STRK_...`) -> `[REDACTED_STROKE_SECRET]`
* AI Provider Keys (`sk-...`, `sk-ant-...`) -> `[REDACTED_AI_API_KEY]`
* Generic Credentials (`password=...`, `token=...`) -> `[REDACTED_SECRET]`

---

## 6. Process Lifecycle & Concurrency Management

### 6.1 Session Capacity & Eviction Safety
* **Session Limit**: Maximum 10 concurrent active sessions (`MAX_SESSIONS = 10`).
* **Active Process Protection**: When creating an 11th session, the system evaluates all existing sessions. Only idle or completed sessions are candidates for eviction.
* **Non-Eviction Invariant**: If all 10 sessions have active running processes, creating a new session raises `RuntimeError` (`HTTP 429 Too Many Requests`). **A running process is never evicted or terminated to make room for a new session.**

### 6.2 Process Tree Termination
Subprocesses may launch children, daemon forks, or build workers. Standard `proc.kill()` leaves orphan child processes running. Stroke enforces full process tree termination:
* **POSIX (macOS / Linux)**:
  Processes are spawned in a new process group via `preexec_fn=os.setsid`. Termination calls `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`, followed by `signal.SIGKILL` if still alive after 1.5 seconds.
* **Windows**:
  Subprocesses are spawned with `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`. Termination invokes `taskkill /F /T /PID <pid>` to terminate the entire process hierarchy.
* **Automatic Cleanup**: `atexit.register(TerminalManager.cleanup_all)` guarantees that all background sessions and child processes are reaped on server exit.

### 6.3 Bounded Output Ring Buffer & Pipe Deadlock Prevention
* Standard `proc.communicate()` buffers all output into memory, creating vulnerabilities to memory exhaustion and pipe deadlocks when subprocesses emit hundreds of megabytes of logs.
* `TerminalSession._execute_subprocess` uses dual daemon threads reading stdout and stderr through non-blocking chunks into a bounded `bytearray` capped at `MAX_OUTPUT_BYTES = 256 * 1024` (256 KB).
* Once the cap is reached, additional output is drained and discarded to prevent child process pipe blocking.
* A clear truncation notice is appended: `[... Output capped at 256KB buffer limit ...]`.
* Captured lines in `self.output_lines` (collections.deque, maxlen=2000) evict oldest lines when full.

---

## 7. Real Platform Isolation vs. Application-Layer Workspace Boundary

### 7.1 The Boundary Distinction
It is critical to distinguish between Stroke's **application-layer workspace boundary** and **kernel-level operating system sandboxing**:

| Boundary Layer | Mechanism | Protection Scope | Limitations |
| :--- | :--- | :--- | :--- |
| **Application Layer (Stroke)** | Path canonicalization (`os.path.realpath`), prefix matching, allowlist validation (`is_allowed_workspace_root`), and command allowlists | Prevents AI tools from running commands outside approved project directories, prevents path traversal (`../`), denies privileged/destructive tools | Does not prevent a compiled C/Rust binary or unconstrained Python script from executing raw syscalls if the executable itself is permitted to run |
| **Standard User Permissions (OS)** | OS user account privileges (POSIX UID/GID, Windows SID) | Enforces that Stroke cannot modify OS system files, install kernel drivers, access other user directories, or modify protected system settings | Can access any file or network port that the host user account has permission to access |
| **Kernel Sandboxing (Platform)** | macOS `sandbox-exec` / App Sandbox, Linux `bwrap` (Bubblewrap) / cgroups, Windows AppContainer / Integrity Levels | Hardware and kernel enforced syscall filtering, read-only root filesystems, private temporary directories, network namespace isolation | Requires platform-specific configuration and deployment packaging |

### 7.2 Zero Administrator Policy & Privilege Escalation
Stroke explicitly rejects privilege escalation:
* Running `sudo`, `su`, or UAC prompt triggers is forbidden.
* Stroke must always execute under a standard, non-elevated user account.
* If a project task requires root privileges (e.g., installing system packages), Stroke reports the instruction to the developer for out-of-band manual execution.

### 7.3 Architecture for OS-Level Sandboxing (Defense-in-Depth Roadmap)
To bridge application-layer boundaries with hardware-enforced kernel boundaries, Stroke's execution layer is designed to support containerized / sandboxed execution wrappers:
1. **macOS**: Wrapping child execution in `sandbox-exec -p <profile>` with profiles restricting writes strictly to `DEFAULT_WORKSPACE` and `/tmp`, blocking network egress for offline tasks.
2. **Linux**: Invoking commands via `bwrap --ro-bind / / --bind <workspace> <workspace> --dev /dev --proc /proc --unshare-all`.
3. **Windows**: Spawning child processes inside Windows AppContainers or low-integrity tokens with job objects restricting memory and CPU quotas.

---

## 8. Authoritative Architecture & Tauri Retirement

In accordance with Phase 2 Architecture Consolidation:
* **Python FastAPI + PyWebView** is the single authoritative production desktop host.
* The Tauri Rust terminal (`src-tauri/src/terminal.rs`) has been **formally retired** and decoupled from production invocation.
* All terminal creation, execution, approval validation, and streaming run exclusively through `terminal_service.py`.

---

## 9. Verification & Compliance Matrix

The following test suites in the root repository enforce continuous compliance with this specification:

| Test Suite | Focus Area | Verification Status |
| :--- | :--- | :--- |
| `test_terminal_security_and_lifecycle.py` | Atomic approvals, Zero-Trust loopback, anti-replay, expiry, capacity (10 limit), process tree kill, 256KB buffer cap, environment sanitization | **16/16 PASS** |
| `test_security_audit.py` | Command allowlist, interpreter inline eval (-c/-e), workspace roots, honest tool reporting, token encryption | **16/16 PASS** |
| `test_engineering_audit.py` | Core system dependencies, data files, desktop builds, headless execution | **14/14 PASS** |
| `test_agent_loop.py` | Multi-step agent terminal tool calling, state preservation, autonomous self-correction | **13/13 PASS** |
| `test_autonomous_coding_system.py` | Process lifecycle, compiler revision loop, diagnostic capture, Studio MCP integration | **12/12 PASS** |
| `test_api_authorization_and_secrets.py` | Route-by-route RBAC, fail-closed secrets, CSRF, loopback boundaries | **26/26 PASS** |
| `test_firestore_data_model.py` | UID ownership, transaction consistency, local offline engine | **14/14 PASS** |
| `test_firebase_auth.py` | Cryptographic RS256 token verification, deprecation of legacy OTP | **12/12 PASS** |
