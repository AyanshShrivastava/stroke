# STROKE // Autonomous Roblox AI Engineering Matrix

> **AAA-Grade Roblox Studio AI Companion & Autonomous Luau Systems Architect**  
> Runs 100% locally on your machine with offline neural inference, live Studio MCP orchestration, verified compiler execution, and enterprise-grade terminal sandboxing.

---

## Architecture Overview

```
                                      +------------------------------------+
                                      |     Stroke Cyberpunk UI / WebApp    |
                                      |     (http://127.0.0.1:8501)         |
                                      +-----------------+------------------+
                                                        |
                                           REST API & Event Streams
                                                        |
                                      +-----------------v------------------+
                                      |      FastAPI Backend Engine        |
                                      |      (Loopback: 127.0.0.1)         |
                                      +--------+--------+--------+---------+
                                               |        |        |
        +--------------------------------------+        |        +-------------------------------------+
        |                                               |                                              |
+-------v----------------------+        +---------------v--------------+        +----------------------v-------+
|  Local GGUF Neural Engine    |        | Roblox Domain Test Runner    |        | Universal MCP Bridge         |
|  - Llama 3.2 1B Instruct     |        | - Luau AST Parser            |        | - Roblox Studio Live Socket  |
|  - Metal/CUDA GPU Offload    |        | - luau-analyze Static Check  |        | - GitHub PAT (Fernet Enc.)   |
|  - Rolling Memory & Ledger   |        | - Honest Compiler Reporting  |        | - Custom MCP Servers         |
+------------------------------+        +---------------+--------------+        +------------------------------+
                                                        |
                                        +---------------v--------------+
                                        | Sandboxed Background Terminal|
                                        | - Approved Project Roots     |
                                        | - Interpreter Eval Gating    |
                                        | - 256 KB Ring Buffer Cap     |
                                        +------------------------------+
```

---

## Key Capabilities & Systems

### 1. Local-First Autonomous AI Engine
* **Offline GGUF Execution**: Powered by `llama-cpp-python` with automatic Apple Silicon Metal and NVIDIA CUDA acceleration checks (`llama_supports_gpu_offload()`).
* **Thinking Levels**:
  * **Low & Medium**: Fast targeted edits and syntactic corrections.
  * **High & Maximum**: In-depth architecture reasoning with unlimited tool turns, compiler passes, and MCP calls.
  * **Absolute Peak**: Multi-system VFX pipeline orchestration, procedural world generation, and full agentic synchronization.
* **Rolling Memory & Summary Strategy**:
  * **North Star Prompt Locking**: Locks user intent at the system prompt root throughout long auto-continue loops.
  * **Pruning Failed Code Drafts**: Discards intermediate broken snippets once repaired and compilation passes green.
  * **State Ledger Memory**: Retains compact, structured summaries of workspace state to preserve context length and execution speed.
  * **Automatic Continuation**: Seamlessly sends continuous continuation tokens without requiring manual user input.

### 2. Sandboxed Background Terminal Engine
* **Private Execution**: Internal-only daemon architecture; operates silently without unapproved terminal panels.
* **Interpreter Security Gating**: Gated approval for arbitrary inline execution flags (`python -c`, `node -e`, `sh`, `bash`, `zsh`).
* **Strict Project Boundaries**: Confined to approved workspace roots; directory traversal outside approved boundaries is denied.
* **Memory Bounding**: Enforces strict byte caps (256 KB) on output streams with concurrent non-blocking pipe readers to prevent OS buffer deadlocks and memory saturation.
* **Local Loopback Enforcement**: Restricted to loopback addresses (`127.0.0.1`, `::1`) with internal authentication dependencies.

### 3. Truthful Compiler Verification
* **Real Static Analysis**: Integrates with `luau-analyze` and `py_compile`.
* **Honest Verification Reporting**: If a compiler binary is missing from the host environment, reports `UNVERIFIED (NO COMPILER)` rather than a false green pass.
* **Roblox DataModel AST Guard**: Rejects non-existent Roblox API methods, deprecated globals, and improper particle constructions.

### 4. Hardened Security & Authentication
* **OTP Rate Limiting & Account Lockout**: Enforces a strict 5-attempt limit with a 15-minute lockout on failed OTP handshakes.
* **PBKDF2-HMAC Password Hashing**: Upgraded from plain hashes to 100,000-iteration salted PBKDF2-HMAC.
* **Session-Bound OAuth Nonce Validation**: GitHub OAuth state strings are validated against a server-side cache with TTL to eliminate CSRF risks.
* **Application-Level Token Encryption**: Stores GitHub Personal Access Tokens in Firestore encrypted with AES/Fernet encryption keys.
* **Zero Secret Leakage**: OTP codes and sensitive PAT tokens are redacted from responses, terminal logs, and child outputs.

### 5. Universal MCP Bridge & Honest Status
* **Roblox Studio MCP**: Connects directly to active Studio sessions for real-time script inspection and Luau execution.
* **Honest Offline Reporting**: If Roblox Studio or custom MCP servers are disconnected, tools report truthful `offline` or `error` statuses without simulated success.

### 6. Reviewed VFX Knowledge Registry
* **Deterministic Scoring**: Replaces synthetic random numbers with technical code analysis (particle density, lifetime control, Debris cleanup, and valid Roblox asset IDs).
* **Transparent Telemetry**: Reports real domain distributions, active insights, and verified knowledge models.

---

## Getting Started

### Prerequisites
* Python 3.9+ (Python 3.11 recommended)
* Optional: `luau` / `aftman` for Luau compilation
* Optional: Active Roblox Studio session with MCP plugin companion

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AyanshShrivastava/stroke.git
   cd stroke
   ```

2. **Set up virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Install desktop dependencies (optional for desktop window):**
   ```bash
   pip install pywebview pyinstaller
   ```

### Running Stroke

* **Web Mode (Default):**
  ```bash
  venv/bin/python main.py
  ```
  Open your browser to `http://127.0.0.1:8501`.

* **Native Desktop Client:**
  ```bash
  venv/bin/python desktop.py
  ```

---

## Running Test Battery

Run the comprehensive unit test suite:
```bash
venv/bin/python -m unittest discover -s . -p "test_*.py"
```

---

## License & Policy
Proprietary & Private Source. Built for autonomous engineering and game development.
