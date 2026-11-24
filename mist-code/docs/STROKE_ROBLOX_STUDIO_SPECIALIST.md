# Stroke Roblox Studio Specialist Architecture

## 1. Executive Summary

Stroke treats **Roblox Studio** as a first-class engineering specialization rather than a generic scripting target. Roblox development requires deep awareness of:
1. **Network Boundaries**: Client-server replication, FilteringEnabled rules, and execution context constraints.
2. **Modern Luau**: Strict typing (`--!strict`), generic type contracts, and modern task scheduling (`task.wait`, `task.spawn`, `task.delay`).
3. **DataModel Architecture**: Rojo project mappings, container placement (`ServerScriptService`, `ReplicatedStorage`, `StarterPlayer`, `StarterGui`), and XML model hierarchies.
4. **Network Contracts**: RemoteEvent/RemoteFunction pairing and client-authoritative security auditing.
5. **Truthful Verification**: Never claiming an object or edit succeeded in Studio without proof.

---

## 2. Luau Code Understanding & Modern Standards

Stroke's [`LuauAnalyzer`](file:///Users/ayansh/Desktop/stroke/roblox_specialist_service.py) enforces modern Luau idioms and flags deprecated legacy patterns:

### Deprecated API Remediation
| Legacy / Deprecated Pattern | Modern Replacement | Risk & Technical Rationale |
|---|---|---|
| `wait(n)` | `task.wait(n)` | Global `wait()` throttles to 30Hz and yields unpredictably under thread-pool exhaustion. `task.wait()` is frame-accurate at 60Hz+. |
| `spawn(fn)` | `task.spawn(fn)` | Global `spawn()` introduces an arbitrary 1–2 frame delay. `task.spawn()` runs immediately in the next microtask cycle. |
| `delay(n, fn)` | `task.delay(n, fn)` | Global `delay()` uses legacy throttling scheduler. `task.delay()` provides frame-accurate timing. |
| `ypcall(fn)` | `pcall(fn)` | `ypcall` is an obsolete Lua 5.1 yield-safe synonym; modern Luau `pcall` natively handles yields. |
| `workspace.FilteringEnabled` | Network Boundaries | `FilteringEnabled` is obsolete; filtering is permanently enforced across all Roblox experiences. |
| `game:FindService("Svc")` | `game:GetService("Svc")` | `FindService` is deprecated; `GetService` guarantees singleton initialization. |

### Typing & Quality Analysis
- **Mode Detection**: Recognizes `--!strict`, `--!nonstrict`, and `--!nocheck`.
- **Declared Types**: Extracts `export type` declarations and generic shapes.
- **Health Score**: Computes code quality score ($0 - 100$) based on severity-weighted issues (errors: $-25$, warnings: $-5$).

---

## 3. Roblox API Awareness & Context Boundary Rules

Roblox scripts operate in distinct execution environments. Stroke flags context violations before code reaches runtime:

### Context Boundary Enforcement
- **Client APIs on Server**: Flags calls to `UserInputService`, `ContextActionService`, `RunService.RenderStepped`, `Players.LocalPlayer`, `Camera`, or `PlayerGui` inside `ServerScript` or server modules.
- **Server APIs on Client**: Flags calls to `DataStoreService`, `MemoryStoreService`, `ServerStorage`, `ServerScriptService`, `MessagingService`, or `ProcessReceipt` inside `LocalScript`.

### Core Services Knowledge Base
Tracks 25+ core Roblox services with descriptions, common event signatures, and execution tags (`Server`, `Client`, `Shared`).

---

## 4. RemoteEvent & Network Contract Analysis

The [`RemoteContractAnalyzer`](file:///Users/ayansh/Desktop/stroke/roblox_specialist_service.py) statically audits all client and server scripts in the project:

### 1. Parity & Pair Matching
- **Client Dispatches**: Scans for `:FireServer(...)` and `:InvokeServer(...)`.
- **Server Listeners**: Scans for `.OnServerEvent:Connect(...)` and `.OnServerInvoke = ...`.
- **Server Dispatches**: Scans for `:FireClient(...)` and `:FireAllClients(...)`.
- **Client Listeners**: Scans for `.OnClientEvent:Connect(...)`.
- **Orphan Detection**: Identifies remotes fired by the client with no server listener, and server listeners listening to events never fired by any client.

### 2. Client-Authoritative Vulnerability Auditing
Flags critical security flaws where server listeners blindly trust client arguments without server validation:
- **Direct Damage**: e.g., `DamageRemote.OnServerEvent:Connect(function(player, damage) ...)`
- **Economy & Currency**: e.g., `ShopRemote.OnServerEvent:Connect(function(player, amount, coins) ...)`
- **Teleportation & Positioning**: e.g., `TeleportRemote.OnServerEvent:Connect(function(player, targetCFrame) ...)`

Stroke advises sanitizing all client input, calculating damage/prices server-side, and using sanity checks (e.g. distance, cooldown, and inventory state).

---

## 5. Explorer Hierarchy & Truthful Inspection

[`HierarchyInspector`](file:///Users/ayansh/Desktop/stroke/roblox_specialist_service.py) inspects the DataModel hierarchy:

### Verification Rules
1. **Valid DataModel Roots**: Validates that target paths begin with authentic Roblox containers (`Workspace`, `ReplicatedStorage`, `ServerScriptService`, `StarterGui`, etc.).
2. **Live Studio MCP Query**: When a live Studio MCP session is active, invokes `search_game_tree` or `inspect_instance`.
3. **Workspace Rojo Mapping**: When offline, inspects `default.project.json` and local filesystem modules (`.luau`, `.rbxmx`).
4. **Truthfulness Guarantee**: If an instance cannot be confirmed, Stroke returns `exists: False` and **never claims or fabricates** that the object was created.

---

## 6. Procedural Builders: UI, Terrain, & VFX

### 6.1 UI Creation (`UiBuilder`)
Generates responsive multi-device Luau UI scripts:
- **Scale vs. Offset**: Uses Scale for primary dimensions and positions (`UDim2.new(0.5, 0, 0.5, 0)` with `AnchorPoint = Vector2.new(0.5, 0.5)`).
- **Constraints & Styling**: Automatically configures `UIAspectRatioConstraint`, `UICorner`, `UIStroke`, `UIPadding`, and `UIListLayout`.
- **Prebuilt Themes**: Supports `dark_glass`, `cyberpunk`, and `fantasy_rpg` design systems.

### 6.2 Terrain & Map-Building (`TerrainBuilder`)
- Synthesizes terrain filling code using `workspace.Terrain:FillBlock` and `FillBall`.
- Biome profiles: **Plains** (Grass, Ground, Rock), **Desert** (Sand, Sandstone, Rock), **Snow** (Snow, Glacier, Rock), and **Volcanic** (Basalt, CrackedLava, Rock).
- Generates water tables and elevation gradients.

### 6.3 VFX & Particle Systems (`VfxBuilder`)
- Synthesizes `Attachment`, `ParticleEmitter`, `Highlight`, `Beam`, and `PointLight` hierarchies.
- Configures multi-keypoint `ColorSequence` and `NumberSequence` for smooth particle growth and fadeouts.
- Integrates `Debris:AddItem` for self-cleaning effects.

---

## 7. Studio Error Detection & Diagnostics

[`StudioErrorDiagnoser`](file:///Users/ayansh/Desktop/stroke/roblox_specialist_service.py) parses raw console output from `get_console_output` or studio logs:

- **Stack Trace Parsing**: Extracts file path, line number, and raw error message.
- **Nil Indexing**: Diagnoses `attempt to index nil with '...'` and suggests exact guard clauses.
- **Infinite Yield Warnings**: Diagnoses `Infinite yield possible on '...:WaitForChild(...)'`, explaining whether the child is missing from replication, misspelled, or needs a timeout parameter.
- **Type Mismatches**: Explains parameter count and type requirements.

---

## 8. Play-Test & Verification Workflows

[`PlaytestAndVerificationEngine`](file:///Users/ayansh/Desktop/stroke/roblox_specialist_service.py) manages verification:

### Proof-Backed Object Verification
Before reporting that an object, model, or script was created:
1. Queries live Roblox Studio MCP via `search_game_tree` or `inspect_instance`.
2. If offline, checks the Rojo filesystem tree and XML models.
3. If not found, explicitly states:
   > "Verification failed: Object '...' could not be confirmed in live Studio or workspace tree."
   Never outputs fabricated success messages.

---

## 9. AI Agent Tools & REST Endpoints

### ToolDispatcher Tools (`terminal_service.py`)
- `roblox_analyze_luau(code, script_role)`
- `roblox_analyze_remotes(workspace_path)`
- `roblox_inspect_hierarchy(target_path, workspace_path)`
- `roblox_generate_ui(title, elements, theme)`
- `roblox_generate_terrain(biome, size, center)`
- `roblox_generate_vfx(vfx_type, target_name)`
- `roblox_diagnose_errors(lines)`
- `roblox_verify_object(target_path, workspace_path)`

### REST API Endpoints (`main.py`)
- `POST /roblox/analyze/luau`
- `POST /roblox/analyze/remotes`
- `POST /roblox/hierarchy/inspect`
- `POST /roblox/generate/ui`
- `POST /roblox/generate/terrain`
- `POST /roblox/generate/vfx`
- `POST /roblox/diagnostics/errors`
- `POST /roblox/verify/object`

---

## 10. Verification & Test Suite Summary

- **`test_roblox_specialist_overhaul.py`**: **11 / 11 tests passed** in 9.41s.
- **Combined Test Verification**: **39 tests passed** across Roblox specialist, project intelligence, and MCP overhaul suites.
- **Full Backend Pytest Suite**: **455 passed** with 0 regressions in 40.75s.
- **Frontend Vitest Suite**: **17 passed** across 3 test suites in 419ms.
- **Frontend Build (`npm run build`)**: Vite & Nitro compiled cleanly with 0 errors.
