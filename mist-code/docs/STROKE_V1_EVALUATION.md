# STROKE V1 — EVALUATION, BENCHMARKS & OBSERVABILITY SPECIFICATION

## 1. Executive Summary

Stroke V1 enforces an authentic, reproducible evaluation and observability pipeline. Rather than judging system quality by how impressive an LLM answer sounds or displaying synthetic multipliers in UI dashboards, Stroke evaluates runtime performance against **12 deterministic benchmarks** and logs **structured, zero-leak telemetry** across all subsystems.

```
                           +-------------------------------------+
                           |      STROKE OBSERVABILITY HUB       |
                           |   (Thread-Safe Memory Ring Buffer)  |
                           +------------------+------------------+
                                              |
                   +--------------------------+--------------------------+
                   |                                                     |
       +-----------v-----------+                             +-----------v-----------+
       |   Channel Separation  |                             |   Multi-Tier Redaction|
       |  User-Visible Progress|                             |  PATS, JWTs, API Keys |
       |  vs Diagnostic Traces |                             |  Private Keys, OTPs   |
       +-----------------------+                             +-----------------------+
                   |                                                     |
+------------------v-----------------------------------------------------v------------------+
|                                12 RIGOROUS EVALUATION BENCHMARKS                          |
| 1. General Coding/Debugging   5. Terminal & Filesystem Tools    9. Recovery & Cancellation|
| 2. Roblox Luau & VFX Scripts  6. MCP & Studio Offline Honesty  10. Injection Resistance   |
| 3. Multi-File Repo Changes    7. Tool Approval & Anti-Tamper   11. Strict 0% False Verify |
| 4. Context Retrieval (P/R)    8. North Star Goal Switching     12. Vision Modality Gating |
+-------------------------------------------------------------------------------------------+
```

---

## 2. The 12 Evaluation Benchmarks

Every benchmark runs against active, live system code (or authentic offline fixtures in CI) and produces quantifiable metrics:

| # | Benchmark Name | Target Subsystem | Key Evaluation Criteria | Authentic Target Metric |
|---|---|---|---|---|
| **1** | **General Coding & Debugging** | Coding Loop / Sandbox | Off-by-one algorithmic bug repair; AST parse; unit test assertions passing. | `test_pass_rate = 100%` |
| **2** | **Roblox Luau & VFX Scripting** | `luau_analyzer` / `vfx_service` | Detect single-invocation debounce anti-pattern, invalid `Humanoid.CFrame` assignments, and enforce `FindFirstAncestorOfClass('Model')`. | `defects_detected > 0`, `domain_errors_in_valid = 0` |
| **3** | **Multi-File Repo Changes** | `file_service` / Isolated Workspace | Atomic multi-module modifications; import reload coherence; no partial corruptions. | `coherence_verified = true` |
| **4** | **Repository / Context Retrieval** | Context Pruner / Retrieval | Labelled corpus search; stemmed word-overlap retrieval without hallucination. | `precision = 1.0`, `recall = 1.0` |
| **5** | **Terminal & Filesystem Tools** | `terminal_service` | Workspace containment boundary enforcement; safe routine command execution (`git --version`); rejection of out-of-bounds traversal (`/etc/shadow`). | `path_boundary_enforced = true`, `exit_code = 0` |
| **6** | **MCP & Studio Offline Honesty** | `mcp_bridge` | Honest reporting when Roblox Studio or MCP servers are disconnected or closed. Zero fake passes. | `status = "error"`, `offline = true` |
| **7** | **Tool-Call Approval & Anti-Tampering** | Terminal / GitHub Approvals | Zero-trust approval gate; UID mismatch rejection (`approval_user_mismatch`); one-time consumption (anti-replay defense). | `tampering_rejected = true`, `replay_rejected = true` |
| **8** | **Long-Context & Task Switching** | `agent_orchestrator` | Active North Star Goal tracking; dynamically updating target when user submits follow-up requests; context budgeting. | `active_task_updated = true` |
| **9** | **Failure Recovery & Cancellation** | `agent_orchestrator` | User cancellation immutability; terminal state protection (no illegal transitions after cancellation). | `cancellation_enforced = true`, `terminal_state_protected = true` |
| **10** | **Prompt-Injection Resistance** | Terminal Policy / Redaction | Neutralization of embedded instructions in files (`rm -rf /`); redaction of exfiltrated secrets. | `destructive_command_blocked = true`, `secrets_neutralized = true` |
| **11** | **Verification Accuracy & False-Success** | `RobloxDomainTestRunner` | Broken code, syntax errors, and missing exports must NEVER receive green verification passes. | `false_verification_rate = 0.0%` |
| **12** | **Vision Task Gating** | `ai_provider_service` | Modal capability verification: text-only models reject multimodal image requests; vision models permit image ingestion. | `text_only_rejected = true`, `vision_permitted = true` |

---

## 3. Observability Architecture (`observability.py`)

### Canonical Categories
Events are classified into one of 8 distinct categories:
- `provider`: AI completions, streaming chunks, model load times, token usage, sampling parameters.
- `tool`: Model tool calls, arguments validation, approval requests, tool execution output.
- `filesystem`: File create, edit, patch, backup, restore, search operations.
- `terminal`: Process lifecycle, session reaping, command execution, exit codes, output buffering.
- `mcp`: Roblox Studio MCP, GitHub MCP, and custom dynamic MCP bridge operations.
- `download`: Model / asset downloading, checksum validation, progress tracking.
- `auth`: Firebase ID token verification, GitHub OAuth linking, session authentication.
- `persistence`: Firestore batch commits, local resilient disk fallback, state persistence.

### Event Data Model
```json
{
  "event_id": "evt_c11b348dec79",
  "timestamp": 1794714038.48,
  "iso_time": "2026-11-15T03:40:38Z",
  "task_id": "task_123",
  "category": "terminal",
  "action": "run",
  "status": "success",
  "latency_ms": 12.5,
  "details": {
    "cmd": "git --version",
    "token": "[REDACTED]"
  },
  "error": null
}
```

### Multi-Tier Redaction Engine
Stroke guarantees zero sensitive data leaks across telemetry and event logs:
1. **Key-Based Redaction**: Any dictionary key matching `password`, `secret`, `token`, `otp`, `auth`, `bearer`, `pat`, `credential`, or `key` is masked to `"[REDACTED]"`.
2. **Regex Pattern Redaction**: String values are scanned for:
   - GitHub Classic PATs (`ghp_...`) and Fine-Grained PATs (`github_pat_...`) -> `[REDACTED_GITHUB_PAT]`
   - GitHub OAuth Tokens (`gho_...`) -> `[REDACTED_GITHUB_OAUTH]`
   - JWTs / Bearer Tokens (`Bearer eyJ...`, `eyJ...`) -> `[REDACTED_JWT]`
   - API Keys (`sk-...`, `AIza...`, `re_...`) -> `[REDACTED_API_KEY]`, `[REDACTED_FIREBASE_KEY]`
   - Private Keys (`-----BEGIN RSA PRIVATE KEY-----...`) -> `[REDACTED_PRIVATE_KEY]`
   - Embedded Passwords in URLs (`http://user:password@host/`) -> `http://user:[REDACTED_PWD]@host/`
   - Explicit OTP codes (`otp: 123456`) -> `otp:[REDACTED_OTP]`
3. **Payload Sanitization**: Raw source code bodies are not stored in telemetry; file paths, byte sizes, line counts, and SHA-256 hashes are recorded instead.

### Channel Separation
- **User-Visible Progress**: Formatted via `UserProgressFormatter` into concise, polite, non-technical status indicators in the chat interface (e.g., *"Validating Luau code syntax..."*, *"Writing project file... Done."*).
- **Internal Diagnostics**: Retained in the thread-safe ring buffer for developer audits, metrics computation, and incident diagnostics.

---

## 4. Authentic Metrics Derivation

Stroke eliminates all fabricated metrics, random micro-training counts, and artificial multipliers:
- `task_success_rate`: Percentage of executed benchmark tasks that passed all validation checks.
- `false_verification_rate`: Percentage of broken or syntactically invalid code scripts that received a passing verification badge (strictly maintained at **0.0%**).
- `context_precision`: True Positives / (True Positives + False Positives) on labelled context queries.
- `context_recall`: True Positives / (True Positives + False Negatives) on labelled context queries.
- `average_latency_ms`: Real arithmetic mean of observed task and tool execution spans.
- `p95_latency_ms`: 95th percentile latency computed across historical spans.
- `authentic: true`: Cryptographic/runtime guarantee that numbers were computed from real executions.

---

## 5. API Endpoints Reference

All endpoints are mounted under FastAPI and enforce authenticated user identity via Firebase ID token:

### 1. `GET /observability/events`
Query parameters:
- `task_id` (optional): Filter events by correlated task identifier.
- `category` (optional): Filter events by category (`provider`, `tool`, `terminal`, etc.).
- `status` (optional): Filter events by status (`success`, `failure`, `requires_approval`, etc.).
- `limit` (default: 100): Maximum events to return (1 - 1000).

### 2. `GET /observability/metrics`
Query parameters:
- `task_id` (optional): Compute metrics for a specific task.
- `window_sec` (optional): Limit calculation to events within the last $N$ seconds.

### 3. `POST /evaluation/run`
Executes the full 12-benchmark evaluation suite in a clean, isolated background thread. Returns a complete `EvaluationSuiteReport`.

### 4. `GET /evaluation/latest`
Retrieves the most recent benchmark run report.

---

## 6. How to Reproduce & Run Tests

```bash
# 1. Run the Dedicated Evaluation and Observability Test Suite
STROKE_ALLOW_OFFLINE_DB=1 venv/bin/python -m unittest test_evaluation_and_observability.py

# 2. Run All 12 Benchmarks Directly
venv/bin/python -c "
import eval_harness
harness = eval_harness.StrokeEvaluationHarness()
report = harness.run_all()
print(f'Benchmarks Passed: {report.passed_benchmarks}/{report.total_benchmarks} ({report.pass_rate}%)')
print('Summary Metrics:', report.summary_metrics)
"

# 3. Run the Full Terminal Stress & Lifecycle Suite
venv/bin/python -m unittest test_terminal_stress.py
```
