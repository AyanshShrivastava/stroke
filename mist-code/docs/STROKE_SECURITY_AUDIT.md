# STROKE AI // COMPLETE SECURITY AUDIT & VULNERABILITY REMEDIATION REPORT

**Audit Date:** November 15, 2026  
**Auditor:** Stroke Advanced Agentic Security Engine  
**Target Repository:** Stroke (`product-v1-overhaul`)  
**Scope:** Repository-wide security evaluation across 11 vectors, vulnerability confirmation, concrete code remediation, and comprehensive automated regression testing.

---

## 1. Executive Summary

A comprehensive repository-wide security audit of Stroke was conducted across backend services, API routing, agent orchestration, multi-provider AI adapters, local credential vaults, terminal execution pipelines, filesystem boundary enforcement, and MCP integrations.

### Key Audit Metrics
- **Evaluated Security Vectors:** 11 / 11
- **Vulnerabilities Identified & Confirmed:** 4 distinct vulnerability categories
- **Vulnerabilities Remediated & Hardened:** 4 / 4 (100%)
- **New Automated Security Regression Tests Added:** 17 tests in `test_security_audit_comprehensive.py`
- **Total Backend Test Pass Rate:** 420 / 420 passed (100%)
- **Total Frontend Test Pass Rate:** 17 / 17 passed (100%)
- **Production Build Status:** Passed (`npm run build` succeeds cleanly)

---

## 2. Comprehensive Evaluation of 11 Security Vectors

| # | Security Vector | Assessment | Key Controls & Status |
|---|---|---|---|
| **1** | **API-Key Exposure** | **Remediated** | Removed Gemini API keys from URL query strings; migrated to `x-goog-api-key` header. Added Groq and OpenRouter keys to terminal output redaction. |
| **2** | **Firebase Auth & Authorization** | **Remediated** | Repaired Broken Object-Level Authorization (BOLA/IDOR) in chat sessions, single-chat retrievals, session deletions, and agent tasks/jobs. Firebase ID token verification, lockout on failed attempts, and constant-time token comparison remain strictly enforced. |
| **3** | **Filesystem Access & Path Traversal** | **Secure** | `validate_path_access` and `validate_task_id` resolve canonical paths, inspect symlink targets before dereference, disallow system roots (`/`, `/bin`, `/System`, `C:\Windows`), and enforce user-approved workspace boundaries. Absolute no-delete policy enforced via `NoDeletePolicyViolation`. |
| **4** | **Terminal Command Execution** | **Hardened** | Enforces single-use atomic approval tokens (`ApprovalRecord`) tied to user UID, session ID, and command hash. Minimizes child process environment with `ALLOWED_ENV_VARS` whitelist, stripping parent backend secrets. Output buffer cap (256KB) and stream eviction prevent process exhaustion. |
| **5** | **MCP Permissions** | **Hardened** | Dynamic tool registry with strict JSON schema validation, timeout limits, and STDIO/HTTP transport isolation. Dynamic registration protected against untrusted capabilities. |
| **6** | **Roblox Studio Integration** | **Secure** | Luau static verification prevents fake compile passes when `luau-analyze` is absent. Studio MCP calls run through hardened client channels with schema validation and input sanitation. |
| **7** | **GitHub Auth & OAuth** | **Secure** | State parameters are cryptographically generated, bound to authenticated user UIDs, and consumed atomically. OAuth redirect URLs are strictly validated. PATs are stored in machine-bound Fernet encrypted vaults, never exposed in client responses, and redacted from logs. |
| **8** | **Secret Storage** | **Secure** | BYOK keys are managed via OS keyring (Keychain/Credential Manager) with AES-256 Fernet fallback using machine hardware node + PBKDF2-HMAC-SHA256 salt with `0600` file permissions. API responses return masked digests only (`gsk_••••••••••••...4a89`). |
| **9** | **Agent Permissions** | **Hardened** | Multi-agent orchestrator enforces per-agent workspaces, file-locking concurrency controls (`_file_locks`), tool budgets, iteration caps, and user UID tenant isolation. Tasks and jobs verify ownership before read, cancel, or approve actions. |
| **10** | **Network Requests & SSRF** | **Remediated** | Hardened custom AI provider connections with `SsrfProtector`. Blocked requests targeting link-local metadata (`169.254.169.254`), cloud metadata (`metadata.google.internal`), and IP obfuscations while preserving access to legitimate local model proxies (`localhost`, `127.0.0.1`). |
| **11** | **Desktop App Security** | **Secure** | `paths_service.is_elevated_privilege` strictly rejects execution as administrator or root. CORS and CSRF middleware reject cross-origin requests from untrusted hosts. Tauri configuration prohibits dangerous plugins and restricts window webview access. |

---

## 3. Confirmed Vulnerabilities & Remediation Details

### Vulnerability 1: SSRF in Custom AI Provider Endpoint
- **Severity:** High
- **Affected Components:** `ai_provider_service.py` (`CustomProvider.chat_complete`, `CustomProvider.stream_chat`, `test_provider_connection`, `fetch_live_provider_models`).
- **Mechanics:** User-supplied `base_url` values were accepted without IP or domain validation. An attacker or malicious prompt could supply cloud metadata endpoints (`http://169.254.169.254`, `http://metadata.google.internal`) or internal subnets, causing the backend server to make unauthorized intranet requests and potentially leak cloud instance credentials.
- **Remediation:** Integrated `SsrfProtector.validate_url(base_url, allow_local=True)` from `mcp_client.py` into all Custom AI Provider network entrypoints. Cloud metadata hostnames, link-local IPs, reserved ranges, and obfuscated/hex/octal representations are unconditionally rejected with a `400 / ProviderServiceError`. Legitimate local servers (e.g. `http://localhost:11434`, `http://127.0.0.1:8000`) remain supported.

### Vulnerability 2: API Key Exposure in URL Query Parameters
- **Severity:** Medium
- **Affected Components:** `ai_provider_service.py` (`GeminiProvider.chat_complete`, `GeminiProvider.stream_chat`, `fetch_live_provider_models`).
- **Mechanics:** Google Gemini API requests constructed URLs appending `?key={api_key}` in the query string. In HTTP client libraries (`httpx`), request URLs are captured in exception strings, HTTP access logs, proxy logs, and error telemetry, exposing user API keys in plaintext.
- **Remediation:** Migrated Gemini API authentication from query parameters to the official `x-goog-api-key: {api_key}` HTTP header across REST content generation, SSE streaming generation, and models catalog discovery.

### Vulnerability 3: Broken Object-Level Authorization (BOLA / IDOR) in Chats & Agent Tasks
- **Severity:** High
- **Affected Components:** `main.py` (`list_user_chats`, `get_single_user_chat`, `save_user_chat`, `delete_user_chat`, `/agent/tasks/{task_id}`, `/agent/tasks/{task_id}/cancel`, `/agent/tasks/{task_id}/approve`, `/api/orchestrator/jobs/{job_id}`, `/api/orchestrator/jobs/{job_id}/cancel`, `/api/orchestrator/jobs/{job_id}/stream`).
- **Mechanics:**
  - In chat endpoints, an optional `?email=` query or payload parameter was used to index into the local session fallback store (`_LOCAL_CHAT_SESSIONS`). An authenticated user could pass another user's email address and read, overwrite, or delete that user's chat history.
  - In agent tasks and multi-agent jobs, endpoints took `{task_id}` or `{job_id}` but failed to verify whether the requesting user owned the corresponding task or job, allowing cross-tenant inspection, streaming, and cancellation.
- **Remediation:**
  - Implemented strict email identity validation on all chat endpoints: if an `email` parameter is supplied that differs from the authenticated `user.email`, the endpoint immediately aborts with `HTTP 403 Forbidden`. The canonical lookup key is strictly derived from verified credentials (`(user.email or user.uid).strip().lower()`).
  - Implemented object-level ownership checks on all Task and Parallel Agent Job endpoints: if `task.user_uid != user.uid` or `job.user_uid != user.uid` (and the task is not public/anonymous), access is rejected with `HTTP 403 Forbidden`.

### Vulnerability 4: Incomplete Secret Redaction in Terminal Output
- **Severity:** Low
- **Affected Components:** `terminal_service.py` (`REDACTION_PATTERNS`).
- **Mechanics:** `REDACTION_PATTERNS` lacked explicit regular expressions for Groq API keys (`gsk_...`) and OpenRouter API keys (`sk-or-v1-...`), and had an overly restrictive character count on Google API keys (`{35}`). If a terminal command printed environment variables or command-line arguments containing these keys, they were displayed in plaintext in the terminal buffer.
- **Remediation:** Added `gsk_[a-zA-Z0-9_\-]{20,}` (redacting to `[REDACTED_GROQ_API_KEY]`) and `sk-or-v1-[a-zA-Z0-9_\-]{20,}` (redacting to `[REDACTED_OPENROUTER_API_KEY]`), and broadened Google API key matching to `AIza[0-9A-Za-z-_]{30,40}`.

---

## 4. Verification Evidence & Automated Regression Testing

All remediated vulnerabilities have been verified with automated tests in `test_security_audit_comprehensive.py`.

```
============================= test session starts ==============================
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_01_gemini_uses_headers_not_url_query_param PASSED [  5%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_02_gemini_models_fetch_uses_header PASSED [ 11%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_03_custom_provider_blocks_cloud_metadata_ssrf PASSED [ 17%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_04_custom_provider_permits_safe_local_models PASSED [ 23%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_05_chat_list_rejects_cross_account_email PASSED [ 29%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_06_chat_get_rejects_cross_account_email PASSED [ 35%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_07_chat_save_rejects_cross_account_email PASSED [ 41%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_08_chat_delete_rejects_cross_account_email PASSED [ 47%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_09_agent_task_access_control PASSED [ 52%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_10_parallel_agent_job_access_control PASSED [ 58%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_11_terminal_redacts_groq_and_openrouter_keys PASSED [ 64%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_12_terminal_redacts_github_google_and_bearer_tokens PASSED [ 70%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_13_workspace_path_traversal_rejection PASSED [ 76%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_14_child_process_environment_strips_secrets PASSED [ 82%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_15_elevation_status_reporting PASSED [ 88%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_16_credentials_vault_masks_keys PASSED [ 94%]
test_security_audit_comprehensive.py::TestSecurityAuditComprehensive::test_17_github_service_input_validation PASSED [100%]
======================== 17 passed in 9.48s ========================
```

### Overall Regression Test Results
- **Full Backend Pytest:** `420 passed, 5 warnings in 41.10s` (100% pass)
- **Frontend Vitest:** `17 passed in 549ms` (100% pass)
- **Production Bundle Build:** `npm run build` completed successfully with zero compile warnings or chunking errors.

---

## 5. Security Architecture Summary

```
                       [Incoming Request]
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
    [Host & Origin Check]              [Authentication Gate]
  DNS Rebinding & CORS Header        Firebase Bearer JWT / Cookie
            │                                     │
            └──────────────────┬──────────────────┘
                               │
                               ▼
                   [Tenant Authorization Gate]
         Cross-Account IDOR & BOLA Checks on Chats & Tasks
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
 [Filesystem Guard]     [Terminal Guard]       [AI Provider Guard]
  validate_path_access   ALLOWED_ENV_VARS       SsrfProtector Validation
  Symlink Resolution     ApprovalRecord         x-goog-api-key Headers
  No-Delete Enforcement  REDACTION_PATTERNS     Localhost-Only Whitelist
```

With these defenses in place, Stroke maintains a zero-trust execution sandbox, tenant-isolated data structures, secure encrypted credential storage, and protected network boundaries across all supported operating systems.
