# Stroke V1 — API Authorization, OAuth & Secret Security Policy

This document defines the route-by-route authorization matrix, loopback security boundaries, OAuth handshake lifecycle, and secret management architecture for the Stroke V1 production API.

---

## 1. Threat Model & Security Principles

1. **Zero Trust Loopback:**
   Connecting from a loopback address (`127.0.0.1`, `::1`, or `localhost`) is **not** an authentication credential. Browsers running on the local host can be compelled by malicious external web pages to issue cross-origin requests (`fetch("http://localhost:8501/...")`). Every state-changing and sensitive local API endpoint must independently verify caller identity (Firebase ID token or internal daemon secret) and enforce strict Origin/Host validation.

2. **Sole Ownership Key:**
   All authorization decisions derive user identity exclusively from cryptographically verified Firebase ID tokens (`request.auth.uid`). Caller-supplied `email` or `uid` query parameters, headers, or JSON body fields are never trusted as proof of identity.

3. **Fail-Closed Secrets:**
   Cryptographic operations and OAuth integrations must fail closed:
   - If token encryption fails, the system refuses to store plaintext and raises a fatal exception.
   - If token decryption fails, the system returns `None` and never leaks ciphertext as a plaintext credential.
   - If OAuth client credentials (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) are missing or unconfigured, OAuth endpoints fail closed with HTTP 503.

4. **DNS Rebinding & CSRF Protection:**
   The API validates incoming `Host` and `Origin` headers before processing requests:
   - `Host` must match configured loopback identifiers (`localhost`, `127.0.0.1`, `[::1]`, or approved hostnames).
   - `Origin` on state-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`) must originate from approved local web or desktop origins (`http://localhost:*`, `http://127.0.0.1:*`, `tauri://localhost`, `https://tauri.localhost`).

---

## 2. Complete Route Authorization Matrix

| HTTP Method | Route Path | Access Policy | Identity / Authorization Rule | Scoping / Persistence Boundary |
| :--- | :--- | :--- | :--- | :--- |
| **GET** | `/` | Public | None | Serves static `index.html` |
| **GET** | `/docs`, `/redoc`, `/openapi.json` | Public / Local Dev | None | OpenAPI documentation |
| **GET** | `/auth/config` | Public | None | Returns non-secret Firebase project metadata (`projectId`, `authDomain`) |
| **POST** | `/auth/send-otp` | Deprecated (410) | None | Returns HTTP 410 Gone (migrated to Firebase Auth) |
| **POST** | `/auth/switch-account` | Deprecated (410) | None | Returns HTTP 410 Gone (migrated to Firebase Auth) |
| **POST** | `/auth/verify-otp` | Deprecated (410) | None | Returns HTTP 410 Gone (migrated to Firebase Auth) |
| **GET** | `/auth/me` | Authenticated | `get_current_user` | Returns claims for verified token UID |
| **POST** | `/auth/session` | Authenticated | `get_current_user` | Validates active session for verified UID |
| **POST** | `/auth/logout` | Authenticated / Optional | `get_optional_user` | Clears server session reference |
| **DELETE** | `/auth/account` | Authenticated | `get_current_user` | Purges backend data strictly for verified UID |
| **POST** | `/auth/migrate-legacy-data` | Authenticated | `get_current_user` | Migrates legacy records only matching verified token email to token UID |
| **GET** | `/auth/email-config` | Authenticated | `get_current_user` | Returns masked outbound email config |
| **POST** | `/auth/email-config` | Authenticated | `get_current_user` | Validates inputs (no newlines/control chars); persists to `.env` with `0600` permissions |
| **GET** | `/auth/github-connect` | Authenticated | `get_current_user` | Fails closed if GitHub unconfigured; issues state token bound to verified UID |
| **GET** | `/auth/github/callback` | OAuth Callback | Verified State Nonce | Consumes state atomically; writes token to `users/{uid}`; HTML-escapes all text; uses strict `postMessage` origin |
| **GET** | `/github/status` | Authenticated | `get_current_user` | Inspects PAT connection for verified UID; never logs token preview |
| **POST** | `/github/token` | Authenticated | `get_current_user` | Encrypts PAT (fails closed); stores under `users/{uid}` and local vault with `0600` |
| **DELETE** | `/github/token` | Authenticated | `get_current_user` | Clears stored PAT for verified UID |
| **POST** | `/database/feed-5x` | Authenticated | `get_current_user` | Persists structural records under `users/{uid}/records/` |
| **GET** | `/database/mandatory-cache` | Authenticated | `get_current_user` | Returns verified cache package for verified UID |
| **GET** | `/memory/stats` | Authenticated | `get_current_user` | Returns estimated memory metrics for `users/{uid}/memory/` |
| **POST** | `/memory/clear` | Authenticated | `get_current_user` | Paginated batched deletion across all records under `users/{uid}/memory/` |
| **POST** | `/database/feed-cycle` | Authenticated | `get_current_user` | Sequential 5-cycle ingestion under `users/{uid}/records/`; checks `feed_state/current` |
| **POST** | `/database/feed-5-cycles` | Authenticated | `get_current_user` | Atomic batch commit of all 5 cycles under `users/{uid}/records/` |
| **POST** | `/database/feed/reset-state` | Authenticated | `get_current_user` | Resets `users/{uid}/feed_state/current` for verified UID |
| **GET** | `/mcp/servers` | Authenticated | `get_current_user` | Probes and lists active MCP server bridges |
| **POST** | `/mcp/execute` | Authenticated | `get_current_user` | Dispatches MCP tool; uses encrypted GitHub PAT only from verified UID doc |
| **POST** | `/mcp/connect` | Authenticated | `get_current_user` | Registers custom MCP server bridge |
| **POST** | `/mcp/disconnect` | Authenticated | `get_current_user` | Disconnects custom MCP server bridge |
| **GET** | `/mcp/config` | Authenticated | `get_current_user` | Returns mcpServers configuration JSON |
| **POST** | `/mcp/config` | Authenticated | `get_current_user` | Validates and applies mcpServers configuration |
| **GET** | `/mcp/tools` | Authenticated | `get_current_user` | Returns catalog of available tools |
| **POST** | `/ai/notes/chat` | Authenticated | `get_current_user` | Executes LLM notes copilot for verified UID |
| **GET** | `/user/status` | Authenticated | `get_current_user` | Returns root user telemetry strictly from `users/{uid}` |
| **GET** | `/download/info` | Public | None | Returns desktop download release metadata |
| **GET** | `/download/{platform}` | Public | None | Downloads client installer binary |
| **POST** | `/ai/search` | Authenticated | `get_current_user` | Executes web search grounding for verified UID |
| **GET** | `/ai/status` | Authenticated | `get_current_user` | Returns local LLM engine status |
| **POST** | `/ai/model/download` | Authenticated | `get_current_user` | Triggers background GGUF weight download |
| **POST** | `/ai/model/pull` | Authenticated | `get_current_user` | Pulls local Ollama model |
| **GET** | `/ai/model/weights-status`| Authenticated | `get_current_user` | Returns status of local model weights |
| **POST** | `/ai/model/download-weights`| Authenticated | `get_current_user` | Starts GGUF streaming download |
| **GET** | `/chats` | Authenticated | `get_current_user` | Queries `users/{uid}/chats/` and local session store for verified UID |
| **GET** | `/chats/{session_id}` | Authenticated | `get_current_user` | Retrieves single chat belonging to verified UID |
| **POST** | `/chats/save` | Authenticated | `get_current_user` | Persists conversation under `users/{uid}/chats/` |
| **DELETE** | `/chats/{session_id}` | Authenticated | `get_current_user` | Deletes conversation belonging to verified UID |
| **GET** | `/ai/learned-insights` | Authenticated | `get_current_user` | Returns continuous learning telemetry |
| **POST** | `/ai/learn-from-chats` | Authenticated | `get_current_user` | Distills chat learnings for verified UID |
| **POST** | `/ai/refeed-with-learnings`| Authenticated | `get_current_user` | Refeeds model learnings for verified UID |
| **POST** | `/ai/chat` | Authenticated | `get_current_user` | Main neural agent chat loop; memory recorded under `users/{uid}/memory` |
| **POST** | `/ai/verify-code` | Authenticated | `get_current_user` | Runs AST and syntax verification suite on Luau/Python code |
| **POST** | `/terminal/create` | Loopback / Auth | `verify_terminal_access` | Creates background terminal session; requires internal token or verified UID |
| **POST** | `/terminal/run` | Loopback / Auth | `verify_terminal_access` | Executes command in approved workspace; checks approval policies |
| **GET** | `/terminal/{id}/output` | Loopback / Auth | `verify_terminal_access` | Reads ring buffer output |
| **GET** | `/terminal/{id}/status` | Loopback / Auth | `verify_terminal_access` | Checks terminal exit status |
| **GET** | `/terminal/list` | Loopback / Auth | `verify_terminal_access` | Lists active terminal sessions |
| **POST** | `/terminal/{id}/stop` | Loopback / Auth | `verify_terminal_access` | Terminates terminal process |
| **POST** | `/terminal/{id}/restart` | Loopback / Auth | `verify_terminal_access` | Restarts terminal session |
| **POST** | `/terminal/approval/respond` | Loopback / Auth | `verify_terminal_access` | Submits user approval decision for dangerous commands |
| **GET** | `/terminal/tools/schema` | Loopback / Auth | `verify_terminal_access` | Returns terminal AI tool definitions |
| **GET** | `/terminal/output/delta` | Loopback / Auth | `verify_terminal_access` | Returns delta buffer stream |
| **POST** | `/fs/list` | Loopback / Auth | `verify_terminal_access` | Lists directory within approved workspace |
| **POST** | `/fs/read` | Loopback / Auth | `verify_terminal_access` | Reads file within approved workspace |
| **POST** | `/fs/read-multiple` | Loopback / Auth | `verify_terminal_access` | Reads multiple files within approved workspace |
| **POST** | `/fs/create` | Loopback / Auth | `verify_terminal_access` | Creates file within approved workspace |
| **POST** | `/fs/edit` | Loopback / Auth | `verify_terminal_access` | Edits file within approved workspace |
| **POST** | `/fs/create-dir` | Loopback / Auth | `verify_terminal_access` | Creates directory within approved workspace |
| **POST** | `/fs/search` | Loopback / Auth | `verify_terminal_access` | Searches filename within approved workspace |
| **POST** | `/fs/search-content` | Loopback / Auth | `verify_terminal_access` | Greps content within approved workspace |
| **POST** | `/fs/inspect` | Loopback / Auth | `verify_terminal_access` | Inspects file metadata |
| **POST** | `/fs/apply-patch` | Loopback / Auth | `verify_terminal_access` | Applies unified diff within approved workspace |
| **POST** | `/fs/diff` | Loopback / Auth | `verify_terminal_access` | Computes diff within approved workspace |
| **POST** | `/fs/inspect-workspace` | Loopback / Auth | `verify_terminal_access` | Inspects workspace structure |
| **GET** | `/workspace/list-approved`| Loopback / Auth | `verify_terminal_access` | Lists user-approved workspace roots |
| **POST** | `/workspace/approve` | Loopback / Auth | `verify_terminal_access` | User explicitly approves a new workspace directory |
| **POST** | `/workspace/pick-native` | Loopback / Auth | `verify_terminal_access` | Native folder picker invocation |
| **GET** | `/backups/history` | Loopback / Auth | `verify_terminal_access` | Lists historical workspace file backups |
| **GET** | `/backups/{id}/compare` | Loopback / Auth | `verify_terminal_access` | Compares backup with current file |
| **POST** | `/backups/{id}/restore` | Loopback / Auth | `verify_terminal_access` | Restores workspace file from backup |
| **GET** | `/models/status` | Loopback / Auth | `verify_terminal_access` | Returns status of local model manager |
| **POST** | `/models/download` | Loopback / Auth | `verify_terminal_access` | Downloads model weights |
| **POST** | `/models/pause` | Loopback / Auth | `verify_terminal_access` | Pauses model download |
| **POST** | `/models/resume` | Loopback / Auth | `verify_terminal_access` | Resumes model download |
| **POST** | `/models/cancel` | Loopback / Auth | `verify_terminal_access` | Cancels model download |
| **GET** | `/system/elevation-status`| Loopback / Auth | `verify_terminal_access` | Checks execution privilege level |
| **GET** | `/system/paths` | Loopback / Auth | `verify_terminal_access` | Returns system directory layout |

---

## 3. GitHub OAuth Lifecycle Specification

### 3.1 Initiation (`GET /auth/github-connect`)
1. **Prerequisite:** Client MUST supply a valid Firebase ID token in `Authorization: Bearer <token>`.
2. **Fail Closed:** If `GITHUB_CLIENT_ID` or `GITHUB_CLIENT_SECRET` is unset, empty, or placeholder, returns HTTP 503 ("GitHub OAuth is not configured on this server").
3. **Cryptographic State Generation:**
   - State format: `f"STRK_{user.uid}_{secrets.token_urlsafe(32)}"`.
   - Stored in server-side `_OAUTH_STATE_REGISTRY` with:
     - `uid`: Authenticated user's Firebase UID.
     - `expires_at`: UTC timestamp set to `now + 600` (10-minute lifetime).
     - `initiating_origin`: Validated origin of the requesting client (used for `postMessage`).
4. **Redirect:** Returns HTTP 307 temporary redirect to `https://github.com/login/oauth/authorize`.

### 3.2 Callback & Exchange (`GET /auth/github/callback`)
1. **Atomic Consumption:**
   - State is extracted from query params and popped from `_OAUTH_STATE_REGISTRY` in a single operation: `_OAUTH_STATE_REGISTRY.pop(state, None)`.
   - If state is missing, unrecognized, expired, or previously used, the request is immediately rejected with HTTP 400.
2. **Token Exchange:**
   - Performs outbound POST to `https://github.com/login/oauth/access_token`.
   - If GitHub returns an error or code is invalid, delivers an error page with **all error text HTML-escaped**.
3. **Fail-Closed Encryption & Storage:**
   - Token is encrypted via `encrypt_token(access_token)`.
   - If encryption fails, no raw token is ever stored; the request raises HTTP 500.
   - Encrypted token is written to `users/{uid}.github_token` and the local machine token vault (`data/.github_token.enc`) with `0600` permissions.
4. **Zero Log Leaks:**
   - Server logs NEVER output token characters (not even prefixes like `ghp_xxxx...`).
5. **Safe HTML/JavaScript Bridge:**
   - Target origin for `window.opener.postMessage` is strictly set to `initiating_origin` or `FRONTEND_APP_URL` — **never `'*'`**.
   - `postMessage` payload contains:
     ```json
     {
       "type": "STROKE_GITHUB_CONNECTED",
       "status": "connected",
       "uid": "...",
       "connected": true
     }
     ```
     Token previews (`token_preview`) are completely removed.
   - All dynamic fields are JSON-encoded and HTML-escaped to prevent script injection.

---

## 4. Secret Management & Key Derivation

1. **Vault Encryption Key:**
   - Primary: `STROKE_ENCRYPTION_KEY` environment variable (if explicitly configured).
   - Local Vault: `data/.vault_key` generated with 256 bits of CSPRNG entropy (`Fernet.generate_key()`) and persisted with `0600` file permissions (owner read/write only).
   - Machine MAC addresses (`uuid.getnode()`) are never used as the sole cryptographic key source.
2. **Fail Closed Encryption:**
   - `encrypt_token(plain_token)`: Raises `RuntimeError` if encryption fails. Never falls back to plaintext.
   - `decrypt_token(cipher_token)`: Returns `None` if decryption fails. Never returns raw ciphertext.
3. **Environment Variable Injection Protection:**
   - `save_env_variable(key, value)` validates that neither `key` nor `value` contains newlines (`\r`, `\n`) or null bytes (`\0`).
   - Writes to `.env` using atomic temporary files with `0600` permissions.
