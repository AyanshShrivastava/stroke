# Stroke Project Intelligence System

## 1. Executive Summary

The **Stroke Project Intelligence System** transforms Stroke from a naive file search tool into an authoritative codebase intelligence engine. Rather than relying on random directory scans or assuming a project is indexed when only filenames and sizes have been counted, Stroke ingests genuine file contents, parses syntax and symbols across multiple languages, tracks internal and external dependencies, maps Roblox DataModel hierarchies, and generates rich architectural blueprints.

### Key Capabilities

| Capability | Description |
|---|---|
| **Multi-Language Parsing** | Native AST-based parsing for Python, regex/token extraction for TypeScript/JavaScript, Luau/Lua, and Roblox XML models (`.rbxmx`/`.rbxlx`). |
| **Roblox & Luau Awareness** | Full awareness of Rojo DataModel layouts (`default.project.json`), Wally packages (`wally.toml`), Luau exported types, Roblox services (`game:GetService`), and network contracts (`RemoteEvent`, `RemoteFunction`). |
| **File Relationship & Dependency Graph** | Tracks outgoing dependencies, incoming callers (reverse dependents), external libraries, and calculates transitive **impact radius** (BFS traversal). |
| **Global Symbol Catalog** | Cross-file symbol table indexing functions, methods, classes, types, interfaces, and event listeners with exact and fuzzy lookup. |
| **Architectural Blueprints** | Auto-detects project archetypes (`roblox_experience`, `python_backend`, `web_frontend`, `fullstack_application`, `rust_crate`), entry points, and structural layers. |
| **Graph-Aware Context Retrieval** | Combines lexical BM25 relevance and symbol boosting with **dependency contract expansion** (injecting signatures of imported modules into context). |
| **Incremental Re-Indexing** | SHA-256 content hashing skips AST and regex parsing for unchanged files, detects modifications, and prunes deleted files. |
| **Enterprise Security & Limits** | Enforces 1MB per-file limit, 25MB total capacity limit, 1,000 files limit, 30s timeout, `.gitignore` compliance, and strict exclusion of secrets/credentials. |

---

## 2. Ingestion & Incremental Indexing Engine

Stroke guarantees that a project is never considered indexed without genuine content ingestion.

### 2.1 Content Verification & SHA-256 Hashing
Every file is verified through a multi-stage validation pipeline:
1. **Security & Path Exclusion**: Checks against `.gitignore` rules, `.env`, certificates, tokens, and SSH keys.
2. **Resource Limits**: Checks individual file size ($\le 1\text{ MB}$), index byte capacity ($\le 25\text{ MB}$), and file count limits ($\le 1,000$).
3. **Binary & Secret Inspection**: Detects null bytes and searches content for API keys, private keys, and bearer tokens.
4. **SHA-256 Incremental Matching**:
   $$\text{Hash} = \text{SHA-256}(\text{file\_bytes})$$
   - **Unchanged**: If `existing.content_hash == current_hash`, file content is not re-parsed, retaining cached symbols and relationships.
   - **Modified**: Re-parsed through language-specific extractors, updating symbol tables and dependency relationships.
   - **Deleted**: Surgically removed from file records, symbol table, and reverse dependency graphs.

---

## 3. Multi-Language Symbol Extraction

### 3.1 Python AST Parser (`PythonSymbolExtractor`)
Stroke uses Python's standard `ast` module for deterministic AST extraction:
- **Classes**: Names, inheritance bases (`BaseManager`), decorators (`@singleton`), docstrings, and start/end line offsets.
- **Methods**: Sync and async methods, parameters, and decorators (`@async_retry`).
- **Standalone Functions**: Function signatures, parameters, return annotations, and docstrings.
- **Imports**: Resolves `import x` (external libraries) vs `from .y import z` (internal project modules).
- **Fallback**: Gracefully falls back to regex extraction if a Python file contains syntax errors.

### 3.2 TypeScript & JavaScript Extractor (`TypeScriptSymbolExtractor`)
- **Interfaces & Types**: `interface AgentState { ... }`, `type AgentStatus = 'idle' | 'running'`.
- **Classes**: Class declarations, `extends`, and `implements`.
- **Functions**: Function declarations, default exports, and exported arrow functions `const handler = (...) =>`.
- **Imports**: Classifies internal relative imports (`./auth`, `../utils`) vs external npm packages (`react`, `axios`).

### 3.3 Luau & Roblox Extractor (`LuauSymbolExtractor`)
- **Functions & Methods**: Global and local functions, table methods `function Controller:method(...)`, `function Controller.method(...)`.
- **Luau Type System**: Local and exported types `export type CombatPacket = { ... }`.
- **Roblox Services**: Catalogs all `game:GetService("ServiceName")` calls.
- **Network Contracts**: Detects `Instance.new("RemoteEvent")`, `Instance.new("RemoteFunction")`, and `BindableEvent`.
- **Event Listeners**: Extracts connections `Players.PlayerAdded:Connect(...)`, `RunService.Heartbeat:Connect(...)`.

### 3.4 Roblox XML Model Extractor (`RobloxXmlExtractor`)
- Parses `.rbxmx` and `.rbxlx` XML place and model files.
- Traverses instance hierarchies (`Part`, `Model`, `Folder`, `Script`, `LocalScript`, `ModuleScript`).
- Decodes embedded Luau script sources (`ProtectedString`) and runs `LuauSymbolExtractor` on the embedded code.

---

## 4. Roblox & Rojo Awareness

### 4.1 Rojo DataModel Mapping (`RobloxProjectResolver`)
Stroke parses `default.project.json` or `rojo.json` to map filesystem directories to Roblox DataModel containers:
- `src/server` $\rightarrow$ `ServerScriptService`
- `src/shared` $\rightarrow$ `ReplicatedStorage`
- `src/client` $\rightarrow$ `StarterPlayer.StarterPlayerScripts`

### 4.2 Cross-Module Require Resolution
When a script contains:
```luau
local CombatService = require(ReplicatedStorage.Shared.CombatService)
```
Stroke's `RobloxProjectResolver` translates the Roblox container expression into the relative filesystem path:
$$\text{ReplicatedStorage.Shared.CombatService} \longrightarrow \text{src/shared/CombatService.luau}$$

### 4.3 Wally Package Manifests
Stroke parses `wally.toml` to catalog:
- Package identity: `[package] name = "team/combat-core"`
- Shared dependencies: `[dependencies]` (e.g. Signal, Component, Roact)
- Server-only dependencies: `[server-dependencies]` (e.g. ProfileService)

---

## 5. Dependency Graph & Impact Radius Analysis

### 5.1 Graph Architecture (`ProjectDependencyGraph`)
The graph maintains four relational maps:
- `dependencies[file]` $\rightarrow$ Set of files directly imported/required.
- `dependents[file]` $\rightarrow$ Set of incoming callers that require this file.
- `external_imports[file]` $\rightarrow$ External packages (npm, pip, Wally, crates).
- `service_usage[service]` $\rightarrow$ Files utilizing a specific Roblox service.

### 5.2 Transitive Impact Radius (BFS)
When an agent or developer plans to edit or refactor a file, Stroke computes its **impact radius** using breadth-first search across incoming dependents:
```
File A (Core Module)
  ├── Level 1 (Direct Callers): ServiceB, WorkerC
  └── Level 2 (Secondary Callers): ApiControllerD, TestSuiteE
```
This enables agents (e.g. `Planner`, `Reviewer`, `Debugger`) to anticipate side-effects and run targeted regression tests.

---

## 6. Graph-Aware Context Retrieval

Stroke avoids "prompt flooding" by combining BM25 lexical similarity, symbol boosting, and **dependency contract expansion**:

1. **Query Tokenization**: Cleans and extracts search terms from the agent prompt or user goal.
2. **Relevance Scoring**:
   $$\text{Score} = \text{PathBoost} + \text{SymbolBoost} + \text{BM25Frequency}$$
3. **Dependency Contract Expansion**:
   For each top result file, Stroke inspects its dependencies in `ProjectDependencyGraph`. If the file requires another module (e.g. `CombatController` requires `DamageModule`), Stroke automatically injects the **exported signatures and types** of `DamageModule` into the prompt block:
   ```markdown
   #### File: `src/client/CombatController.luau`
   **Matched Symbols:** executeSlashAttack
   **Imported Module Contracts:**
   - `src/shared/DamageModule.luau`: type DamageRecord, Damage.applyTrueDamage(target: number, amount: number)
   ```
   This gives the model immediate visibility into external function signatures and contracts without requiring manual file reads.

---

## 7. Project Architecture Blueprint Generator

`ProjectArchitectureSummarizer` classifies projects and generates structured summaries:

### Archetype Detection Rules
- **`roblox_experience`**: Presence of `default.project.json`, `wally.toml`, `.rbxmx`, or majority Luau code.
- **`python_backend`**: Presence of `pyproject.toml`, `requirements.txt`, or majority Python code.
- **`web_frontend`**: Presence of `package.json` with React/Vue/Svelte or majority TS/JS code.
- **`fullstack_application`**: Combined frontend manifests and backend frameworks.
- **`rust_crate`**: Presence of `Cargo.toml`.

### Structural Layers
Identifies files belonging to architectural layers:
- **Server Layer**: `src/server/`, `*.server.luau`, backend services.
- **Client Layer**: `src/client/`, `*.client.luau`, `StarterPlayer`, `StarterGui`.
- **Shared Layer**: `src/shared/`, `ReplicatedStorage`, common libraries.
- **API Routes**: `routes/`, `endpoints/`, `controllers/`.
- **Tests**: `test_*.py`, `*.spec.luau`, `*.test.tsx`.
- **Configs**: `*.json`, `*.toml`, `*.yaml`.

---

## 8. AI Agent & Tool Integration

All project intelligence capabilities are exposed to autonomous agents via `ToolDispatcher` in `terminal_service.py` and authorized in `parallel_agent_system.py`:

| Tool Name | Arguments | Description |
|---|---|---|
| `project_index` | `workspace_path` | Scans and incrementally indexes the workspace. |
| `project_search` | `query`, `max_results`, `workspace_path` | Retrieves context snippets with contract expansion. |
| `project_get_architecture` | `markdown`, `workspace_path` | Returns structured blueprint or markdown summary. |
| `project_get_dependencies` | `file_path`, `workspace_path` | Returns outgoing dependencies, callers, and impact radius. |
| `project_find_symbol` | `name`, `kind`, `file_path` | Discovers symbols across the entire codebase. |

---

## 9. REST API Endpoints

All endpoints require standard session authentication:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/project/index` | Trigger scan and incremental ingestion. |
| `GET` | `/project/index/status` | Ingestion metrics (total files, bytes, last indexed timestamp). |
| `POST` | `/project/search` | Targeted BM25 and symbol search. |
| `GET` | `/project/architecture` | Architectural blueprint and archetype detection. |
| `GET` | `/project/dependencies` | Outgoing dependencies, incoming callers, and impact radius. |
| `GET` | `/project/symbols` | Symbol catalog query by name, file, or kind. |
| `DELETE` | `/project/index` | Clears stored project index. |

---

## 10. Verification & Test Coverage Summary

- **`test_project_intelligence_system.py`**: 13 comprehensive tests covering multi-language extraction, AST parsing, Rojo mapping, dependency analysis, impact radius, incremental hashing, and REST endpoints.
- **`test_project_context_and_multimodal.py`**: 10 tests confirming full backward compatibility with existing project context and multimodal features.
- **Full Backend Suite**: **444 tests passing** with 0 regressions in 44.51s.
- **Frontend Test Suite**: **17 Vitest tests passing** across 3 test suites.
- **Frontend Build**: `npm run build` compiles cleanly with zero errors.
