# Stroke V1 — Remediation & Engineering Overhaul Plan

**Target Branch:** `product-v1-overhaul`  
**Audit Reference:** [STROKE_V1_AUDIT.md](file:///Users/ayansh/Desktop/stroke/docs/STROKE_V1_AUDIT.md)  
**Scope:** Dependency-ordered remediation of all 18 core audit categories (`AUD-01` to `AUD-60`) and 22 independent findings (`NEW-01` to `NEW-22`) across 8 structured phases (Phases 0–7).

---

## Phase Dependency Graph

```text
Phase 0 (Hygiene, Git & Packaging Containment)
   ├──▶ Phase 1 (Auth, Session Security, CORS & Firestore)
   │       ├──▶ Phase 3 (MCP Security & AI Coding Loop Integrity)
   │       └──▶ Phase 5 (Frontend Security, Integration & Honesty)
   ├──▶ Phase 2 (Filesystem, Workspace, Terminal Sandboxing & Patch Safety)
   │       └──▶ Phase 3 (MCP Security & AI Coding Loop Integrity)
   ├──▶ Phase 4 (Model Download Integrity & Backend Reliability)
   └──▶ Phase 6 (Installers, Packaging & CI/CD)
           └──▶ Phase 7 (Test Suite Overhaul & Final Verification Gate)
```

---

## Phase 0: Immediate Hygiene, Git & Secret Containment

- **Objective:** Prevent secret leakage in desktop packaging, stop runtime data pollution in git, and establish clean working tree boundaries.
- **Audit Findings Addressed:** `AUD-57`, `AUD-58`, `NEW-01`
- **Primary Locations:**
  - `build_desktop.py:43-45`
  - `src-tauri/tauri.conf.json:10, 25-27`
  - `.gitignore`
  - `github_service.py:23-26`
  - `data/local_chat_sessions.json`, `data/learned_chat_insights.json`, `data/verified_project_context.json`, `data/vfx_learned_models.json`
- **Key Deliverables:**
  1. Relocate `.vault_key` and token vault storage from `data/` to the per-user application support directory (`paths_service.get_app_data_dir()`).
  2. Untrack runtime chat and telemetry JSON files from git (`git rm --cached`) and add them to `.gitignore`.
  3. Update `build_desktop.py` to package only static VFX datasets (`data/vfx_data.json`, `data/vfx_dump.txt`, `data/VFX_ASSET_MANIFEST.md`), excluding runtime JSONs and keys.
  4. Retire duplicate Tauri runtime or point `frontendDist` to a dedicated `dist/` folder with strict CSP.
- **Dependencies:** None (must execute first to protect secrets and clean repository state).

---

## Phase 1: Authentication, Session Security, CORS & Firestore

- **Objective:** Eliminate unauthenticated API access, caller-supplied user identity vulnerabilities, OAuth CSRF/XSS, plaintext password/OTP storage, in-memory identity sets, and silent Firestore write failures.
- **Audit Findings Addressed:** `AUD-01`, `AUD-02`, `AUD-03`, `AUD-04`, `AUD-05`, `AUD-06`, `AUD-07`, `AUD-08`, `AUD-09`, `AUD-10`, `AUD-11`, `AUD-12`, `AUD-13`, `AUD-14`, `AUD-15`, `AUD-16`, `AUD-53`, `NEW-08`, `NEW-09`, `NEW-10`, `NEW-15`, `NEW-17`, `NEW-18`
- **Primary Locations:**
  - `main.py` (CORS middleware, auth endpoints, OAuth callback, memory/chat routes)
  - `github_service.py`
  - `src/integrations/supabase/*`
- **Key Deliverables:**
  1. Replace caller-supplied `email` query parameters with server-side session authentication (Bearer token or signed HTTP-only cookies).
  2. Restrict CORS `allow_origins` strictly to authorized desktop/localhost origins; eliminate wildcard reflection with credentials.
  3. Require authenticated session context before initiating GitHub OAuth; sanitize callback error rendering with `html.escape()`; eliminate wildcard `*` `postMessage`.
  4. Replace `_LOCAL_OTP_STORE` plaintext password caching with cryptographic salted PBKDF2/Argon2 hashes; compare OTP digests with `hmac.compare_digest`.
  5. Replace in-memory `_AUTHENTICATED_IDENTITIES` with an expiring, revocable session token store.
  6. Require explicit `FIRESTORE_EMULATOR_HOST` for `AnonymousCredentials`; fall back to transactional local SQLite/JSON persistence when cloud Firestore is unconfigured.
  7. Implement authentic multi-document deletion for `clear_user_memory` and add `POST /auth/github/disconnect`.
- **Dependencies:** Phase 0.

---

## Phase 2: Filesystem, Workspace, Terminal Sandboxing & Patch Safety

- **Objective:** Resolve client-controlled approval bypasses, loopback trust vulnerabilities, subprocess environment leakage, path traversal in isolated tasks, symlink escapes, `restore_backup` target checks, and `file_service.apply_patch()` data destruction.
- **Audit Findings Addressed:** `AUD-17`, `AUD-18`, `AUD-19`, `AUD-20`, `AUD-21`, `AUD-22`, `AUD-23`, `AUD-24`, `AUD-25`, `AUD-26`, `AUD-27`, `AUD-28`, `AUD-29`, `AUD-30`, `AUD-31`, `AUD-32`, `NEW-05`, `NEW-06`, `NEW-07`, `NEW-14`, `NEW-16`
- **Primary Locations:**
  - `terminal_service.py`
  - `file_service.py`
  - `workspace_service.py`
  - `isolated_workspace.py`
  - `backup_service.py`
- **Key Deliverables:**
  1. Remove `approved: bool` from client payloads; require an authoritative, server-issued single-use approval challenge token.
  2. Replace loopback IP checks in `verify_terminal_access` with mandatory `X-Stroke-Token` validation.
  3. Sanitize `subprocess.Popen` environment to pass only safe system variables (`PATH`, `SYSTEMROOT`), stripping all application API keys and secrets.
  4. Re-wire `is_ai_initiated=True` to activate the Absolute No-Delete Policy for AI commands.
  5. Sanitize `task_id` in `isolated_workspace.py` with strict alphanumeric regex and assert workspace relative bounds.
  6. Rewrite `file_service.apply_patch()` to preserve untouched lines before and after diff hunks using verified unified diff algorithms.
  7. Add cross-process file locking (`fcntl.flock` / `filelock`) to `BackupIndexManager` and implement corrupted index recovery.
  8. Enforce approved workspace validation in `restore_backup`.
- **Dependencies:** Phase 0.

---

## Phase 3: MCP Security & AI Coding Loop Integrity

- **Objective:** Eliminate arbitrary command execution in dynamic MCP configurations, prevent SSRF in MCP HTTP transports, correct Luau lexer limitations, fix block deduplication bugs, and prevent unverified language passes.
- **Audit Findings Addressed:** `AUD-33`, `AUD-34`, `AUD-35`, `AUD-36`, `AUD-44`, `AUD-45`, `AUD-46`, `AUD-52`, `NEW-04`
- **Primary Locations:**
  - `mcp_client.py`
  - `mcp_bridge.py`
  - `coding_loop.py`
  - `github_service.py`
- **Key Deliverables:**
  1. Restrict MCP server commands to an authorized binary allowlist; block arbitrary system executables.
  2. Implement SSRF filtering in `check_server_health` and `StreamableHttpTransport` (blocking cloud metadata and private IP subnets).
  3. Implement genuine JSON-RPC `initialize` handshake verification before reporting MCP server status as `ready`.
  4. Fix `coding_loop._clean_code_artifacts` to avoid stripping structural keywords (e.g. consecutive `end` tokens).
  5. Add backtick string interpolation support to Luau syntax validation.
  6. Return `status: "UNTESTED"` rather than false `PASS` for languages lacking local compilers.
  7. Implement standard `Link` header pagination for GitHub branch and issue listing.
- **Dependencies:** Phase 1 & Phase 2.

---

## Phase 4: Model Download Integrity & Backend Reliability

- **Objective:** Resolve missing `import os` runtime crashes, fix HTTP Range append corruption, enforce SHA-256 validation against catalog digests, correct `GET /ai/status` return path bugs, and consolidate duplicate downloaders.
- **Audit Findings Addressed:** `AUD-37`, `AUD-38`, `AUD-39`, `AUD-40`, `AUD-41`, `AUD-43`
- **Primary Locations:**
  - `download_model.py`
  - `model_download_service.py`
  - `main.py` (`get_ai_status`)
- **Key Deliverables:**
  1. Add missing `import os` to `download_model.py`.
  2. Check `response.status_code == 206` and validate `Content-Range` headers before appending partial bytes on resume.
  3. Add canonical expected SHA-256 checksums to model catalogs and enforce byte verification prior to atomic file promotion.
  4. Fix indentation of `get_ai_status` in `main.py` so the endpoint returns valid telemetry when Ollama succeeds.
  5. Dynamically configure system instructions based on actual provider (Local GGUF vs Cloud API).
- **Dependencies:** Phase 0.

---

## Phase 5: Frontend Security, Integration & Honesty

- **Objective:** Fix chat archival race conditions and message deletion, eliminate plaintext secret storage in `localStorage`, remove fake 1 GB quota claims, replace simulated vision reports with honest metadata, and fix XSS vectors in `index.html`.
- **Audit Findings Addressed:** `AUD-42`, `AUD-47`, `AUD-48`, `AUD-49`, `AUD-50`, `AUD-51`, `NEW-02`, `NEW-03`, `NEW-12`, `NEW-19`, `NEW-20`, `NEW-22`
- **Primary Locations:**
  - `src/routes/_authenticated/chat.$chatId.tsx`
  - `src/routes/_authenticated/integrations.tsx`
  - `src/lib/keyboard-store.ts`
  - `index.html`
  - `vfx_service.py`
- **Key Deliverables:**
  1. Fix the chat archival race condition in `chat.$chatId.tsx` using functional state updates to prevent clobbering new messages.
  2. Eliminate plaintext GitHub PAT storage in browser `localStorage`; retrieve credentials from the backend vault.
  3. Replace simulated 1 GB `localStorage` quota claims with realistic browser storage boundaries.
  4. Replace hardcoded "Modular House" fake AI vision analysis with honest image metadata inspection.
  5. Replace random `metric_load` values with authentic telemetry (indexed models, instance counts).
  6. Sanitize markdown link parsers in `index.html` to block `javascript:` URI execution and escape dynamic tool names.
- **Dependencies:** Phase 1 & Phase 2.

---

## Phase 6: Installers, Packaging, Desktop Host & CI/CD

- **Objective:** Fix broken installer scripts that create empty launchers without copying application source, resolve wrong `STROKE_HOME` paths, eliminate unquoted variables, and ensure safe desktop packaging.
- **Audit Findings Addressed:** `AUD-54`, `AUD-55`, `AUD-56`, `NEW-13`, `NEW-21`
- **Primary Locations:**
  - `scripts/install_macos.sh`
  - `scripts/install_linux.sh`
  - `scripts/install_windows.ps1`
  - `build_desktop.py`
  - `desktop.py`
- **Key Deliverables:**
  1. Update installer scripts to copy all application source files, icons, and virtual environments to the destination directory.
  2. Correct `STROKE_HOME` resolution in macOS and Linux wrapper scripts so launchers find `desktop.py`.
  3. Quote all variable expansions to support paths containing spaces.
  4. Ensure Windows PATH modifications deduplicate semicolons and preserve existing user configurations.
  5. Verify PyInstaller desktop bundle packages only verified static VFX assets.
- **Dependencies:** Phase 0, Phase 4 & Phase 5.

---

## Phase 7: Test Suite Overhaul & Final Verification Gate

- **Objective:** Isolate test suites from global environment contamination, redirect test outputs away from tracked git files, and establish regression tests for all resolved vulnerabilities.
- **Audit Findings Addressed:** `AUD-59`, `AUD-60`
- **Primary Locations:**
  - `test_agent_loop.py`
  - `test_autonomous_coding_system.py`
  - `test_engineering_audit.py`
  - `test_bug_fixes.py`
  - `test_security_audit.py`
- **Key Deliverables:**
  1. Scope `STROKE_TEST_AUTO_APPROVE` to individual test cases using `mock.patch.dict`; remove global module-level assignments.
  2. Redirect test file writes to `tempfile.TemporaryDirectory()`, leaving tracked repository data files untouched.
  3. Add regression tests verifying:
     - Rejection of unauthenticated email/identity manipulation.
     - Rejection of `approved: true` without server challenge tokens.
     - Unified diff patch preservation of untouched file lines.
     - Blocking of `task_id` directory traversal attempts.
     - SHA-256 verification enforcement on model downloads.
     - Proper HTTP Range resume status handling.
  4. Run full test suite and confirm all verification gates pass.
- **Dependencies:** All preceding phases (Phases 0–6).
