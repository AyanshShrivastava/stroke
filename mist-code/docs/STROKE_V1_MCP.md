# STROKE V1 — MODEL CONTEXT PROTOCOL (MCP) & ROBLOX STUDIO INTEGRATION

## 1. Architectural Overview

Stroke V1 unifies all external tool providers, language servers, and runtime execution bridges under a single, authoritative Model Context Protocol (MCP) subsystem. Previously fragmented dispatchers and competing registries have been consolidated into two cooperating core components:

1. **`mcp_client.py`**: The authoritative protocol client, transport engine, cryptographic vault, security guardrails, and server registry.
2. **`mcp_bridge.py`**: The application dispatch bridge connecting Stroke's agentic loop, REST endpoints, and two-tier tool discovery catalog to the MCP ecosystem, featuring persistent managed sessions for Roblox Studio (`StudioMCP`).

```
                                  +---------------------------------------+
                                  |   Stroke Agent Orchestrator / API     |
                                  +-------------------+-------------------+
                                                      |
                                          execute_mcp_tool()
                                                      v
                                  +---------------------------------------+
                                  |             mcp_bridge.py             |
                                  |    (Dynamic Catalog & Studio Session) |
                                  +---------+-------------------+---------+
                                            |                   |
                        Studio Tools (37)   |                   | Custom / Remote Tools
                                            v                   v
+---------------------------------------+---+-------------------+---------------------------------------+
|                                       mcp_client.py                                                   |
|                                                                                                       |
|  +---------------------------+  +--------------------------+  +------------------------------------+  |
|  |     McpServerRegistry     |  |    McpApprovalManager    |  |         McpSecretVault             |  |
|  | (Authoritative Singleton) |  |   (Cryptographic Tokens) |  |    (Fernet AES-256 Secret Enc)     |  |
|  +-------------+-------------+  +--------------------------+  +------------------+-----------------+  |
|                |                                                                 |                    |
|  +-------------v-------------+  +--------------------------+  +------------------v-----------------+  |
|  |   McpJsonSchemaValidator  |  |      SsrfProtector       |  |       build_minimal_mcp_env        |  |
|  |  (Types, Enums, Limits)   |  | (DNS / Private / Rebind) |  |   (Scrubbed Backend Credentials)   |  |
|  +-------------+-------------+  +-------------+------------+  +------------------+-----------------+  |
|                |                              |                                  |                    |
+----------------+------------------------------+----------------------------------+--------------------+
                 |                                                                 |
                 v                                                                 v
+------------------------------------+                           +--------------------------------------+
|          StdioTransport            |                           |       StreamableHttpTransport        |
|  - Process Group Isolation         |                           |  - Manual Redirect & Rebind Checks   |
|  - 16MB Chunk Buffer Limit         |                           |  - SSE (text/event-stream) Decoder   |
|  - SIGTERM -> SIGKILL Cleanup      |                           |  - JSON-RPC 2.0 Over HTTP            |
+-----------------+------------------+                           +-------------------+------------------+
                  |                                                                  |
                  v                                                                  v
      Local Executables / StudioMCP                                      Remote / Local HTTP Endpoints
```

---

## 2. Security Architecture

### 2.1 Authenticated User Approval Gate (`McpApprovalManager`)
No MCP server may be registered or launched without an authenticated user's explicit, single-use approval token:
- Tokens are cryptographically generated via `secrets.token_urlsafe(32)` with a 5-minute time-to-live.
- Each approval is strictly bound to the target `server_id`, `action` (`register` or `connect`), and the authenticated user's `uid`.
- Tokens are atomically consumed upon execution; replay attempts are rejected immediately.
- Exposed via `POST /mcp/approval/request` and validated before any connection handshake.

### 2.2 Strict SSRF & DNS Rebinding Protection (`SsrfProtector`)
All HTTP transports and registered server URLs are scrutinized before connection:
- **Private Subnet Rejection**: Blocks all RFC 1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback addresses (`127.0.0.0/8`, `::1`), link-local addresses (`169.254.0.0/16`, `fe80::/10`), carrier-grade NAT (`100.64.0.0/10`), and broadcast ranges (`224.0.0.0/4`, `255.255.255.255`).
- **Cloud Metadata Protection**: Explicitly blocks requests to AWS/GCP/Azure metadata services (`169.254.169.254`, `metadata.google.internal`, `169.254.169.253`).
- **Obfuscated IP Formats**: Blocks hexadecimal (`0x7f000001`), octal (`017700000001`), and decimal integer notations used to bypass string pattern filters.
- **Explicit Localhost Gating**: Local addresses are strictly rejected unless explicitly flagged with `allow_local=True` in an authorized user configuration.
- **Redirect Validation**: HTTP redirects (`Location` headers) are intercepted and re-validated through `SsrfProtector` before following, preventing DNS rebinding and open redirect vulnerabilities.

### 2.3 Secret Vault & Environment Scrubbing
- **`McpSecretVault`**: Sensitive environment variables and authentication headers are encrypted using machine-bound AES-256 Fernet tokens (`enc:fernet:...`) with secure filesystem permissions (`0600`) on `data/.vault_key`.
- **`build_minimal_mcp_env`**: Child MCP processes never inherit backend secrets. The environment scrubber strips all keys containing `FIREBASE_*`, `SESSION_*`, `GITHUB_*`, `FERNET_*`, `STROKE_*`, `JWT_*`, `SECRET`, `PASSWORD`, or `TOKEN`. Only a minimal PATH, system locale, and explicitly configured server variables are passed to the child process.

---

## 3. Protocol & Reliability Specifications

### 3.1 JSON Schema Validation (`McpJsonSchemaValidator`)
- Enforces strict JSON Schema compliance for both tool arguments and discovered tool definitions.
- Validates field types (`string`, `integer`, `number`, `boolean`, `array`, `object`), handling Python type subtleties (such as `bool` being a subclass of `int`).
- Verifies required arguments, string lengths (`minLength`, `maxLength`), numeric bounds (`minimum`, `maximum`), regex patterns, enum sets, and additional properties policies.

### 3.2 Protocol Honesty & `isError` Handling
- Stroke respects the MCP specification: tool results returning `isError: true` or JSON-RPC error objects (`-32000` to `-32700`) are **never** masked or wrapped as successes.
- Detailed, redacted diagnostic traces are recorded while user-facing messages remain clean and truthful.

### 3.3 Streamable HTTP & SSE Content Negotiation
- `StreamableHttpTransport` supports both `application/json` and `text/event-stream` response shapes.
- Server-Sent Event (SSE) buffers are decoded chunk-by-chunk, parsing `data: {...}` blocks into standardized JSON-RPC notifications and responses.

### 3.4 Cycle-Resistant Discovery Pagination
- `McpClient.list_tools()` implements cursor-based pagination with repetition detection:
  - Caps traversal at a hard limit of 25 pages to prevent unbounded loops.
  - Detects repeated cursor states and terminates safely.
  - Automatically deduplicates tool definitions by tool name.

### 3.5 Process Lifecycle & Zombie Prevention
- `StdioTransport` isolates child processes into dedicated process groups (`start_new_session=True` on POSIX).
- Child process pipes are configured with a 16MB stream buffer limit (`limit=16*1024*1024`) to handle massive tool catalogs and code payloads without truncation or deadlocks.
- Teardown sequence: Closes `stdin` -> Sends `SIGTERM` to the process group -> Awaits exit up to 1.5s -> Falls back to `SIGKILL` on timeout.

---

## 4. Roblox Studio MCP Integration

### 4.1 Persistent Session Multiplexing (`StudioMcpSession`)
Rather than spawning disposable child processes for each tool call, Stroke maintains a persistent singleton session with the native `StudioMCP` binary:
- Auto-discovers the binary on macOS (`~/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP`, `/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP`) and Windows (`~/AppData/Local/Roblox/StudioMCP.exe`).
- Dispatches and multiplexes all **37 Roblox Studio tools** through the persistent connection.

### 4.2 Complete 37-Tool Studio Catalog
Stroke provides complete first-class schemas and handlers for every Roblox Studio capability:
1. `studio_execute_luau` / `execute_luau`
2. `studio_search_scripts` / `script_search`
3. `studio_read_script` / `script_read`
4. `studio_grep_scripts` / `script_grep`
5. `studio_edit_script` / `multi_edit`
6. `studio_insert_vfx_asset` / `insert_asset`
7. `studio_get_console` / `get_console_output`
8. `list_roblox_studios`
9. `get_studio_state`
10. `inspect_instance`
11. `search_game_tree`
12. `generate_scene`
13. `generate_animation`
14. `generate_mesh`
15. `generate_texture`
16. `generate_material`
17. `generate_procedural_model`
18. `segment_mesh`
19. `search_asset`
20. `save_place`
21. `start_stop_play`
22. `character_navigation`
23. `user_mouse_input`
24. `user_keyboard_input`
25. `screen_capture`
26. `upload_image`
27. `store_image`
28. `auto_setup_avatar`
29. `wait_job_finished`
30. `open_cloud_invoke`
31. `http_get`
32. `list_skills`
33. `create_skill`
34. `edit_skill`
35. `skill`
36. `subagent`
37. `submit_feedback`

### 4.3 Open Place Verification & Honest Offline Reporting
When Roblox Studio is running at the start hub without an active place open, StudioMCP returns `{"mode": "Unavailable", "state": "Place is not open"}`.
- Stroke inspects Studio instances and filters out unavailable hubs.
- If no place is open or Studio is not running, tools return an honest offline state (`status: "offline"`, `connected: false`) detailing why execution could not proceed.
- Stroke **never** synthesizes fake execution output or claims code ran in Studio when disconnected.

---

## 5. 5-Tier Connection Lifecycle Diagnostics

All MCP connections report their real-time state using a 5-tier diagnostic hierarchy:

| Lifecycle State | Description |
| :--- | :--- |
| `configured` | Server entry exists in configuration (`mcp_config.json`) but executable/URL unverified. |
| `executable_found` | Binary path exists on disk and is executable, or HTTP endpoint URL is well-formed. |
| `process_running` | Subprocess is actively running in background or HTTP endpoint responds to health probes. |
| `protocol_connected`| JSON-RPC handshake initialized; server capabilities and protocol version negotiated. |
| `tools_ready` | Tool discovery succeeded; schemas validated and registered in Stroke's AI catalog. |
| `offline` / `failed` | Connection failed, process exited, or target place is not open. Detailed error logged. |

---

## 6. Verification & Test Coverage

The MCP subsystem is validated across unit, protocol, integration, and benchmark suites:

1. **`test_mcp_security_and_protocol.py` (20 Tests — 100% PASS)**:
   - SSRF protection (private subnets, metadata IPs, integer/hex obfuscation, DNS rebinding, redirect bypasses).
   - Secret encryption, decryption, and environment scrubbing.
   - JSON Schema validator (types, enums, min/max, required fields).
   - Strict `isError` handling and non-masking of RPC errors.
   - Stdio process tree termination (SIGTERM -> SIGKILL).
   - Pagination loop/cycle resistance and tool deduplication.
   - SSE buffer parsing.
   - Cryptographic approval token generation, single-use consumption, and expiration.
   - 37 Roblox Studio tools verification and honest offline states.
   - 5-tier lifecycle state reporting.

2. **`test_mcp_and_github_overhaul.py` (15 Tests — 100% PASS)**:
   - Dynamic catalog search (`tools_search`).
   - Two-tier tool selection for small context windows (Llama 3.2 1B).
   - Studio subprocess management and fallback synthesis.

3. **`test_evaluation_and_observability.py` (12/12 Benchmarks — 100% PASS)**:
   - `BENCH_06_MCP_STUDIO`: Honest offline reporting verification (0% fake verification).
   - Zero event loop errors or unhandled subprocess pipes.
