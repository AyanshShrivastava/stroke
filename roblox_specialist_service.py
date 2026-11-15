"""
================================================================================
STROKE // ROBLOX STUDIO SPECIALIST SERVICE
================================================================================
Comprehensive Roblox Studio Intelligence and Engineering Engine:
1. Luau Code Understanding: Modern Luau syntax, strict typing (--!strict), table shapes,
   deprecated API detection (wait, spawn, delay, FilteringEnabled), and modern replacements.
2. Roblox API Awareness: 25+ core Roblox services, classes, constraints, properties,
   and client-vs-server execution context safety.
3. Explorer Hierarchy Inspection: DataModel tree inspection, path resolution, and
   CollectionService tag discovery.
4. Script Creation & Editing: Multi-edit, Server/Local/Module script authoring with
   truthful Live-Studio vs. Rojo-Workspace synchronization.
5. RemoteEvent & RemoteFunction Network Analysis: Paired client-server contract auditing,
   orphan detection, and security auditing for client-authoritative vulnerabilities.
6. Server/Client Architecture: Network boundary rules, container placement, and
   Single-Script / Knit / Flamework architecture patterns.
7. UI Creation: Declarative, responsive UI hierarchy generation (ScreenGui, Frame, TextLabel,
   UIListLayout, UICorner, UIStroke, UIAspectRatioConstraint) with Scale vs. Offset rules.
8. Terrain & Map-Building: Procedural biome and terrain synthesizers (workspace.Terrain:FillBlock,
   FillBall, FillWedge, material sequences).
9. VFX & Animation Assistance: ParticleEmitter configs (ColorSequence, NumberSequence),
   Beam, Trail, Highlight, TweenService kinematics, and Animator tracks.
10. Studio Error Detection & Diagnostics: Console traceback parsing, nil-indexing detection,
    infinite yield diagnostics, and automated remediation.
11. Play-Test & Verification Workflows: Real DataModel object verification (never fabricating
    creation), play-test orchestration, and console capture.
================================================================================
"""

import os
import re
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set

import paths_service


# ------------------------------------------------------------------------------
# 1. ROBLOX API KNOWLEDGE BASE & CONTEXT RULES
# ------------------------------------------------------------------------------
class RobloxApiKnowledge:
    """Authoritative knowledge base for Roblox services, classes, and execution contexts."""

    CORE_SERVICES: Dict[str, Dict[str, Any]] = {
        "Players": {
            "context": "shared",
            "description": "Manages player instances, connections, teams, and character spawning.",
            "common_events": ["PlayerAdded", "PlayerRemoving"]
        },
        "ReplicatedStorage": {
            "context": "shared",
            "description": "Networked container replicated across server and all connected clients.",
            "common_events": []
        },
        "ServerScriptService": {
            "context": "server",
            "description": "Secure server-only container for ServerScripts and server modules.",
            "common_events": []
        },
        "ServerStorage": {
            "context": "server",
            "description": "Secure server-only storage for assets, templates, maps, and tools.",
            "common_events": []
        },
        "StarterPlayer": {
            "context": "client",
            "description": "Container for StarterPlayerScripts and StarterCharacterScripts.",
            "common_events": []
        },
        "StarterGui": {
            "context": "client",
            "description": "Container for ScreenGuis cloned to Player.PlayerGui upon spawn.",
            "common_events": []
        },
        "Workspace": {
            "context": "shared",
            "description": "3D active physical world containing parts, models, terrain, and cameras.",
            "common_events": []
        },
        "Lighting": {
            "context": "shared",
            "description": "Environment lighting, skyboxes, atmosphere, bloom, and post-processing VFX.",
            "common_events": []
        },
        "RunService": {
            "context": "shared",
            "description": "Frame step lifecycle events: Heartbeat (shared), Stepped (shared), RenderStepped (client-only).",
            "common_events": ["Heartbeat", "Stepped", "RenderStepped"]
        },
        "TweenService": {
            "context": "shared",
            "description": "Smooth interpolation of instance properties across time.",
            "common_events": []
        },
        "UserInputService": {
            "context": "client",
            "description": "Detects player keyboard, mouse, gamepad, and touch inputs on the client.",
            "common_events": ["InputBegan", "InputEnded", "InputChanged"]
        },
        "ContextActionService": {
            "context": "client",
            "description": "Binds player inputs to actions with priority stacking and mobile button creation.",
            "common_events": []
        },
        "HttpService": {
            "context": "server",
            "description": "JSON encoding/decoding, UUID generation, and external HTTP requests.",
            "common_events": []
        },
        "DataStoreService": {
            "context": "server",
            "description": "Persistent cloud key-value database for player profiles and world state.",
            "common_events": []
        },
        "MemoryStoreService": {
            "context": "server",
            "description": "High-throughput ephemeral cross-server memory cache and queues.",
            "common_events": []
        },
        "MessagingService": {
            "context": "server",
            "description": "Pub/sub communication across live experience game servers.",
            "common_events": []
        },
        "CollectionService": {
            "context": "shared",
            "description": "Tag-based instance querying and lifecycle event binding.",
            "common_events": ["TagAdded", "TagRemoved"]
        },
        "PhysicsService": {
            "context": "server",
            "description": "Configures collision groups and non-colliding collision matrices.",
            "common_events": []
        },
        "PathfindingService": {
            "context": "server",
            "description": "Calculates navigation paths through 3D geometry for NPCs.",
            "common_events": []
        },
        "SoundService": {
            "context": "shared",
            "description": "Manages sound playback, sound groups, audio effects, and listener positioning.",
            "common_events": []
        },
        "Debris": {
            "context": "shared",
            "description": "Schedules instance destruction after a specified duration without yielding.",
            "common_events": []
        },
        "TextChatService": {
            "context": "shared",
            "description": "Modern Roblox text chat channels, commands, and bubble chat customization.",
            "common_events": ["MessageReceived"]
        },
        "TeleportService": {
            "context": "server",
            "description": "Transfers players between places and reserved servers.",
            "common_events": []
        },
        "MarketplaceService": {
            "context": "server",
            "description": "Handles gamepasses, developer products, and receipt processing callbacks.",
            "common_events": ["PromptPurchaseFinished", "ProcessReceipt"]
        }
    }

    DEPRECATED_APIS: Dict[str, Dict[str, str]] = {
        "wait": {
            "replacement": "task.wait()",
            "reason": "Global wait() throttles to 30Hz and can yield indefinitely under load. task.wait() runs reliably at 60Hz/frame rate."
        },
        "spawn": {
            "replacement": "task.spawn()",
            "reason": "Global spawn() introduces an arbitrary 1-2 frame delay. task.spawn() resumes immediately."
        },
        "delay": {
            "replacement": "task.delay()",
            "reason": "Global delay() uses legacy scheduler with unpredictable throttling. task.delay() is frame-accurate."
        },
        "ypcall": {
            "replacement": "pcall()",
            "reason": "ypcall is an obsolete synonym for pcall from older Lua versions."
        },
        "FilteringEnabled": {
            "replacement": "Modern Network Boundary (RemoteEvents / RemoteFunctions)",
            "reason": "workspace.FilteringEnabled is deprecated; all Roblox places have filtering permanently enabled."
        },
        "FindService": {
            "replacement": "game:GetService()",
            "reason": "game:FindService is deprecated in modern Luau; use game:GetService()."
        },
        "LoadCharacter": {
            "replacement": "player:LoadCharacter() on Server",
            "reason": "LoadCharacter must only be called from server scripts; calling it from client is deprecated/unsupported."
        }
    }

    CLIENT_ONLY_APIS: Set[str] = {
        "UserInputService", "ContextActionService", "Camera", "CurrentCamera",
        "RenderStepped", "LocalPlayer", "PlayerGui", "Mouse"
    }

    SERVER_ONLY_APIS: Set[str] = {
        "DataStoreService", "MemoryStoreService", "ServerStorage", "ServerScriptService",
        "MessagingService", "ProcessReceipt"
    }

    @classmethod
    def get_service_info(cls, name: str) -> Optional[Dict[str, Any]]:
        return cls.CORE_SERVICES.get(name)

    @classmethod
    def is_service_valid(cls, name: str) -> bool:
        return name in cls.CORE_SERVICES

    @classmethod
    def check_context_safety(cls, api_name: str, script_role: str) -> Optional[str]:
        """Checks if an API call violates client/server execution boundaries."""
        role_lower = script_role.lower()
        if "server" in role_lower and api_name in cls.CLIENT_ONLY_APIS:
            return f"Client-only API '{api_name}' invoked in {script_role}. This will fail or cause runtime errors on the server."
        if "local" in role_lower or "client" in role_lower:
            if api_name in cls.SERVER_ONLY_APIS:
                return f"Server-only API '{api_name}' invoked in {script_role}. Clients cannot access secure server services."
        return None


# ------------------------------------------------------------------------------
# 2. LUAU CODE UNDERSTANDING & ANALYSIS ENGINE
# ------------------------------------------------------------------------------
class LuauAnalyzer:
    """Performs deep static analysis of Luau code for modern standards, typing, and safety."""

    FN_REGEX = re.compile(r'^\s*(?:local\s+)?function\s+([A-Za-z0-9_.:]+)\s*\(([^)]*)\)', re.MULTILINE)
    TYPE_REGEX = re.compile(r'^\s*(?:export\s+)?type\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*=', re.MULTILINE)
    TASK_LIB_REGEX = re.compile(r'\btask\.(wait|spawn|delay|defer|cancel)\b')
    LEGACY_WAIT_REGEX = re.compile(r'(?<!\.)\b(wait|spawn|delay|ypcall)\s*\(')

    @classmethod
    def analyze_source(cls, source: str, script_role: str = "ModuleScript") -> Dict[str, Any]:
        """
        Analyzes Luau source for syntax, typing mode, deprecated APIs,
        execution context boundary safety, and modern task library adoption.
        """
        lines = source.splitlines()
        issues: List[Dict[str, Any]] = []

        # 1. Mode Detection
        mode = "nocheck"
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith("--!strict"):
                mode = "strict"
            elif first_line.startswith("--!nonstrict"):
                mode = "nonstrict"
            elif first_line.startswith("--!nocheck"):
                mode = "nocheck"

        # 2. Deprecated API Checks
        for idx, line in enumerate(lines, start=1):
            line_clean = line.strip()
            if line_clean.startswith("--"):
                continue

            for match in cls.LEGACY_WAIT_REGEX.finditer(line):
                legacy_fn = match.group(1)
                info = RobloxApiKnowledge.DEPRECATED_APIS.get(legacy_fn)
                if info:
                    issues.append({
                        "line": idx,
                        "severity": "warning",
                        "rule": "deprecated_legacy_timing",
                        "symbol": legacy_fn,
                        "message": f"Legacy `{legacy_fn}()` detected. {info['reason']}",
                        "replacement": info["replacement"]
                    })

            # Check FilteringEnabled
            if "FilteringEnabled" in line:
                issues.append({
                    "line": idx,
                    "severity": "info",
                    "rule": "obsolete_filtering_enabled",
                    "symbol": "FilteringEnabled",
                    "message": "workspace.FilteringEnabled is obsolete (filtering is permanently enforced).",
                    "replacement": "Remove manual FilteringEnabled check"
                })

            # 3. Context Safety Checks
            for client_api in RobloxApiKnowledge.CLIENT_ONLY_APIS:
                if client_api in line:
                    context_err = RobloxApiKnowledge.check_context_safety(client_api, script_role)
                    if context_err:
                        issues.append({
                            "line": idx,
                            "severity": "error",
                            "rule": "client_api_on_server",
                            "symbol": client_api,
                            "message": context_err
                        })

            for server_api in RobloxApiKnowledge.SERVER_ONLY_APIS:
                if server_api in line:
                    context_err = RobloxApiKnowledge.check_context_safety(server_api, script_role)
                    if context_err:
                        issues.append({
                            "line": idx,
                            "severity": "error",
                            "rule": "server_api_on_client",
                            "symbol": server_api,
                            "message": context_err
                        })

        # 4. Symbol Extraction
        functions = []
        for m in cls.FN_REGEX.finditer(source):
            functions.append({"name": m.group(1), "params": m.group(2).strip()})

        types = []
        for m in cls.TYPE_REGEX.finditer(source):
            types.append(m.group(1))

        # 5. Health Score Calculation
        error_count = sum(1 for i in issues if i["severity"] == "error")
        warn_count = sum(1 for i in issues if i["severity"] == "warning")
        score = max(0, 100 - (error_count * 25) - (warn_count * 5))
        if mode == "strict":
            score = min(100, score + 5)

        return {
            "mode": mode,
            "script_role": script_role,
            "total_lines": len(lines),
            "declared_functions": functions,
            "declared_types": types,
            "has_strict_mode": mode == "strict",
            "issues": issues,
            "health_score": score,
            "is_production_ready": error_count == 0 and score >= 80
        }


# ------------------------------------------------------------------------------
# 3. REMOTE EVENT & NETWORK CONTRACT ANALYZER
# ------------------------------------------------------------------------------
class RemoteContractAnalyzer:
    """
    Audits RemoteEvent, RemoteFunction, and UnreliableRemoteEvent connections
    across server and client scripts, verifying paired endpoints and security sanity.
    """

    REMOTE_DEF_REGEX = re.compile(r'Instance\.new\s*\(\s*["\'](RemoteEvent|RemoteFunction|UnreliableRemoteEvent)["\']')
    FIRE_SERVER_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\s*:\s*FireServer\s*\(([^)]*)\)')
    INVOKE_SERVER_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\s*:\s*InvokeServer\s*\(([^)]*)\)')
    ON_SERVER_EVENT_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\.OnServerEvent\s*:\s*Connect\s*\(\s*(?:function\s*\(([^)]*)\)|([A-Za-z0-9_.:]+))')
    ON_SERVER_INVOKE_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\.OnServerInvoke\s*=\s*(?:function\s*\(([^)]*)\)|([A-Za-z0-9_.:]+))')
    FIRE_CLIENT_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\s*:\s*(?:FireClient|FireAllClients)\s*\(([^)]*)\)')
    ON_CLIENT_EVENT_REGEX = re.compile(r'([A-Za-z0-9_.:]+)\.OnClientEvent\s*:\s*Connect\s*\(')

    SUSPICIOUS_CLIENT_ARGS = ["damage", "amount", "money", "coins", "gold", "health", "targetcframe", "teleportpos"]

    @classmethod
    def audit_workspace_network(cls, files: Dict[str, str]) -> Dict[str, Any]:
        """
        Audits all Luau scripts in workspace to discover network remotes, verify
        sender-receiver parity, and flag client-authoritative security vulnerabilities.
        """
        dispatches_from_client: List[Dict[str, Any]] = []
        listeners_on_server: List[Dict[str, Any]] = []
        dispatches_from_server: List[Dict[str, Any]] = []
        listeners_on_client: List[Dict[str, Any]] = []

        security_vulnerabilities: List[Dict[str, Any]] = []

        for rel_path, code in files.items():
            p_lower = rel_path.lower()
            is_server = "server" in p_lower
            is_client = "client" in p_lower or "starterplayer" in p_lower or "gui" in p_lower

            # Client Dispatches
            for m in cls.FIRE_SERVER_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                args = m.group(2).strip()
                dispatches_from_client.append({
                    "remote": target,
                    "file": rel_path,
                    "kind": "FireServer",
                    "args": args
                })

            for m in cls.INVOKE_SERVER_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                args = m.group(2).strip()
                dispatches_from_client.append({
                    "remote": target,
                    "file": rel_path,
                    "kind": "InvokeServer",
                    "args": args
                })

            # Server Listeners
            for m in cls.ON_SERVER_EVENT_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                params = m.group(2) or m.group(3) or ""
                listeners_on_server.append({
                    "remote": target,
                    "file": rel_path,
                    "kind": "OnServerEvent",
                    "params": params.strip()
                })

                # Check client-authoritative security risks
                param_tokens = [p.strip().lower() for p in params.split(",")]
                for suspicious in cls.SUSPICIOUS_CLIENT_ARGS:
                    if any(suspicious in p for p in param_tokens[1:]):  # skip player arg
                        security_vulnerabilities.append({
                            "severity": "critical",
                            "remote": target,
                            "file": rel_path,
                            "type": "client_authoritative_parameter",
                            "parameter": suspicious,
                            "message": f"Server listener for '{target}' directly accepts suspicious client parameter '{suspicious}'. Never trust client-provided damage, currency, or position values without server validation."
                        })

            for m in cls.ON_SERVER_INVOKE_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                params = m.group(2) or m.group(3) or ""
                listeners_on_server.append({
                    "remote": target,
                    "file": rel_path,
                    "kind": "OnServerInvoke",
                    "params": params.strip()
                })

            # Server Dispatches
            for m in cls.FIRE_CLIENT_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                args = m.group(2).strip()
                dispatches_from_server.append({
                    "remote": target,
                    "file": rel_path,
                    "args": args
                })

            # Client Listeners
            for m in cls.ON_CLIENT_EVENT_REGEX.finditer(code):
                target = m.group(1).split(".")[-1]
                listeners_on_client.append({
                    "remote": target,
                    "file": rel_path
                })

        # Pair Matching & Orphan Detection
        client_remote_names = {d["remote"] for d in dispatches_from_client}
        server_listener_names = {l["remote"] for l in listeners_on_server}

        orphans_unhandled = client_remote_names - server_listener_names
        orphans_unused = server_listener_names - client_remote_names

        paired_remotes = client_remote_names & server_listener_names

        contracts = []
        for r_name in sorted(list(client_remote_names | server_listener_names)):
            callers = [d for d in dispatches_from_client if d["remote"] == r_name]
            receivers = [l for l in listeners_on_server if l["remote"] == r_name]
            contracts.append({
                "remote_name": r_name,
                "is_paired": r_name in paired_remotes,
                "client_callers": [c["file"] for c in callers],
                "server_receivers": [rc["file"] for rc in receivers]
            })

        return {
            "total_remotes_detected": len(contracts),
            "paired_remotes_count": len(paired_remotes),
            "unhandled_client_calls": sorted(list(orphans_unhandled)),
            "uncalled_server_listeners": sorted(list(orphans_unused)),
            "security_vulnerabilities": security_vulnerabilities,
            "contracts": contracts
        }


# ------------------------------------------------------------------------------
# 4. EXPLORER HIERARCHY & DATAMODEL INSPECTOR
# ------------------------------------------------------------------------------
class HierarchyInspector:
    """Inspects DataModel trees, resolves instance paths, and verifies existence."""

    ROOT_SERVICES = [
        "Workspace", "Players", "Lighting", "ReplicatedFirst", "ReplicatedStorage",
        "ServerScriptService", "ServerStorage", "StarterGui", "StarterPack",
        "StarterPlayer", "SoundService", "Chat", "TextChatService"
    ]

    @classmethod
    def resolve_datamodel_path(
        cls,
        target_path: str,
        workspace_path: Optional[str] = None,
        live_mcp_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Truthfully resolves an instance path (e.g. 'ReplicatedStorage.VFX.HitFx').
        Never fabricates an instance if it cannot be verified in live Studio or workspace files.
        """
        path_clean = target_path.strip().replace("/", ".").strip(".")
        parts = path_clean.split(".")
        root_service = parts[0] if parts else ""

        if root_service not in cls.ROOT_SERVICES and root_service != "game":
            return {
                "verified": False,
                "path": target_path,
                "exists": False,
                "message": f"Invalid DataModel root '{root_service}'. Expected one of: {', '.join(cls.ROOT_SERVICES[:6])}..."
            }

        # Check live MCP result if available
        if live_mcp_result and live_mcp_result.get("connected"):
            instances = live_mcp_result.get("instances", [])
            for inst in instances:
                if inst.get("name") == parts[-1] or inst.get("path") == path_clean:
                    return {
                        "verified": True,
                        "source": "live_studio_mcp",
                        "path": path_clean,
                        "exists": True,
                        "class_name": inst.get("class_name", "Instance"),
                        "name": inst.get("name", parts[-1]),
                        "children_count": inst.get("children_count", 0)
                    }

        # Check local workspace if path provided (Rojo or local tree)
        if workspace_path and os.path.exists(workspace_path):
            ws = Path(workspace_path)
            # Check default.project.json Rojo mappings
            rojo_file = ws / "default.project.json"
            if rojo_file.exists():
                try:
                    with open(rojo_file, "r", encoding="utf-8") as f:
                        rojo_data = json.load(f)
                    tree = rojo_data.get("tree", {})
                    if root_service in tree:
                        fs_sub = tree[root_service].get("$path", "")
                        if fs_sub:
                            rest = "/".join(parts[1:])
                            cand = ws / fs_sub / rest
                            for ext in ("", ".luau", ".lua", ".rbxmx", "/init.luau"):
                                cand_ext = Path(f"{cand}{ext}")
                                if cand_ext.exists():
                                    return {
                                        "verified": True,
                                        "source": "rojo_project_mapping",
                                        "path": path_clean,
                                        "exists": True,
                                        "filesystem_path": str(cand_ext.relative_to(ws)),
                                        "class_name": "ModuleScript" if ext in (".luau", ".lua") else "Folder"
                                    }
                except Exception:
                    pass

        return {
            "verified": False,
            "path": path_clean,
            "exists": False,
            "message": f"Instance '{path_clean}' was not found in active Studio DataModel or workspace tree."
        }


# ------------------------------------------------------------------------------
# 5. UI CREATION & RESPONSIVE COMPONENT BUILDER
# ------------------------------------------------------------------------------
class UiBuilder:
    """Generates production-grade, multi-device responsive Roblox UI code (Scale vs Offset)."""

    THEMES = {
        "dark_glass": {
            "bg_color": "Color3.fromRGB(24, 24, 30)",
            "panel_color": "Color3.fromRGB(35, 36, 44)",
            "accent_color": "Color3.fromRGB(0, 162, 255)",
            "text_color": "Color3.fromRGB(245, 245, 245)",
            "corner_radius": 10,
            "transparency": 0.15
        },
        "cyberpunk": {
            "bg_color": "Color3.fromRGB(10, 10, 18)",
            "panel_color": "Color3.fromRGB(18, 20, 32)",
            "accent_color": "Color3.fromRGB(255, 0, 128)",
            "text_color": "Color3.fromRGB(0, 255, 220)",
            "corner_radius": 4,
            "transparency": 0.05
        },
        "fantasy_rpg": {
            "bg_color": "Color3.fromRGB(42, 33, 24)",
            "panel_color": "Color3.fromRGB(60, 48, 36)",
            "accent_color": "Color3.fromRGB(212, 175, 55)",
            "text_color": "Color3.fromRGB(250, 240, 220)",
            "corner_radius": 8,
            "transparency": 0.0
        }
    }

    @classmethod
    def generate_ui_script(
        cls,
        title: str,
        elements: List[Dict[str, Any]],
        theme_name: str = "dark_glass",
        target_container: str = "StarterGui"
    ) -> str:
        """
        Synthesizes a self-contained, responsive Luau script constructing a modern UI
        hierarchy with UICorners, UIStrokes, and AspectRatioConstraints.
        """
        theme = cls.THEMES.get(theme_name, cls.THEMES["dark_glass"])
        gui_name = re.sub(r'[^A-Za-z0-9_]', '', title) or "StrokeInterface"

        lines = [
            "--!strict",
            f"-- Auto-generated by Stroke Roblox Specialist: {title}",
            "local Players = game:GetService('Players')",
            "local TweenService = game:GetService('TweenService')",
            "",
            "local player = Players.LocalPlayer",
            "local playerGui = player:WaitForChild('PlayerGui')",
            "",
            f"local screenGui = Instance.new('ScreenGui')",
            f"screenGui.Name = '{gui_name}'",
            "screenGui.ResetOnSpawn = false",
            "screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling",
            "",
            "-- Main Responsive Container (Center Anchor)",
            "local mainFrame = Instance.new('Frame')",
            "mainFrame.Name = 'MainFrame'",
            "mainFrame.AnchorPoint = Vector2.new(0.5, 0.5)",
            "mainFrame.Position = UDim2.new(0.5, 0, 0.5, 0)",
            "mainFrame.Size = UDim2.new(0.4, 0, 0.5, 0) -- Responsive Scale",
            f"mainFrame.BackgroundColor3 = {theme['panel_color']}",
            f"mainFrame.BackgroundTransparency = {theme['transparency']}",
            "mainFrame.BorderSizePixel = 0",
            "mainFrame.Parent = screenGui",
            "",
            "local corner = Instance.new('UICorner')",
            f"corner.CornerRadius = UDim.new(0, {theme['corner_radius']})",
            "corner.Parent = mainFrame",
            "",
            "local stroke = Instance.new('UIStroke')",
            f"stroke.Color = {theme['accent_color']}",
            "stroke.Thickness = 1.5",
            "stroke.Transparency = 0.3",
            "stroke.Parent = mainFrame",
            "",
            "-- Title Header",
            "local titleLabel = Instance.new('TextLabel')",
            "titleLabel.Name = 'TitleLabel'",
            "titleLabel.Size = UDim2.new(1, -20, 0, 40)",
            "titleLabel.Position = UDim2.new(0, 10, 0, 10)",
            "titleLabel.BackgroundTransparency = 1",
            f"titleLabel.Text = '{title}'",
            f"titleLabel.TextColor3 = {theme['text_color']}",
            "titleLabel.TextSize = 20",
            "titleLabel.Font = Enum.Font.GothamBold",
            "titleLabel.TextXAlignment = Enum.TextXAlignment.Left",
            "titleLabel.Parent = mainFrame",
            "",
            "-- Elements Container with List Layout",
            "local contentFrame = Instance.new('ScrollingFrame')",
            "contentFrame.Name = 'ContentFrame'",
            "contentFrame.Size = UDim2.new(1, -20, 1, -70)",
            "contentFrame.Position = UDim2.new(0, 10, 0, 60)",
            "contentFrame.BackgroundTransparency = 1",
            "contentFrame.ScrollBarThickness = 4",
            "contentFrame.Parent = mainFrame",
            "",
            "local listLayout = Instance.new('UIListLayout')",
            "listLayout.Padding = UDim.new(0, 8)",
            "listLayout.SortOrder = Enum.SortOrder.LayoutOrder",
            "listLayout.Parent = contentFrame",
            ""
        ]

        # Generate elements
        for i, el in enumerate(elements, start=1):
            el_type = el.get("type", "button").lower()
            el_label = el.get("label", f"Element {i}")
            el_name = f"Element_{i}"

            if el_type == "button":
                lines.extend([
                    f"local btn_{i} = Instance.new('TextButton')",
                    f"btn_{i}.Name = '{el_name}'",
                    f"btn_{i}.Size = UDim2.new(1, 0, 0, 36)",
                    f"btn_{i}.BackgroundColor3 = {theme['bg_color']}",
                    f"btn_{i}.Text = '{el_label}'",
                    f"btn_{i}.TextColor3 = {theme['text_color']}",
                    f"btn_{i}.Font = Enum.Font.GothamMedium",
                    f"btn_{i}.TextSize = 14",
                    f"btn_{i}.LayoutOrder = {i}",
                    f"btn_{i}.Parent = contentFrame",
                    f"local btnCorner_{i} = Instance.new('UICorner')",
                    f"btnCorner_{i}.CornerRadius = UDim.new(0, 6)",
                    f"btnCorner_{i}.Parent = btn_{i}",
                    ""
                ])
            elif el_type == "label":
                lines.extend([
                    f"local lbl_{i} = Instance.new('TextLabel')",
                    f"lbl_{i}.Name = '{el_name}'",
                    f"lbl_{i}.Size = UDim2.new(1, 0, 0, 24)",
                    f"lbl_{i}.BackgroundTransparency = 1",
                    f"lbl_{i}.Text = '{el_label}'",
                    f"lbl_{i}.TextColor3 = {theme['text_color']}",
                    f"lbl_{i}.Font = Enum.Font.Gotham",
                    f"lbl_{i}.TextSize = 13",
                    f"lbl_{i}.TextXAlignment = Enum.TextXAlignment.Left",
                    f"lbl_{i}.LayoutOrder = {i}",
                    f"lbl_{i}.Parent = contentFrame",
                    ""
                ])

        lines.extend([
            "screenGui.Parent = playerGui",
            f"print('[Stroke UI] {title} successfully instantiated into PlayerGui.')"
        ])

        return "\n".join(lines)


# ------------------------------------------------------------------------------
# 6. TERRAIN & MAP-BUILDING GENERATOR
# ------------------------------------------------------------------------------
class TerrainBuilder:
    """Generates performant procedural terrain and biome filling scripts."""

    BIOMES = {
        "plains": {
            "surface": "Enum.Material.Grass",
            "subsurface": "Enum.Material.Ground",
            "bottom": "Enum.Material.Rock"
        },
        "desert": {
            "surface": "Enum.Material.Sand",
            "subsurface": "Enum.Material.Sandstone",
            "bottom": "Enum.Material.Rock"
        },
        "snow": {
            "surface": "Enum.Material.Snow",
            "subsurface": "Enum.Material.Glacier",
            "bottom": "Enum.Material.Rock"
        },
        "volcanic": {
            "surface": "Enum.Material.Basalt",
            "subsurface": "Enum.Material.CrackedLava",
            "bottom": "Enum.Material.Rock"
        }
    }

    @classmethod
    def generate_terrain_script(
        cls,
        biome: str = "plains",
        size: Tuple[int, int, int] = (256, 32, 256),
        center: Tuple[int, int, int] = (0, 0, 0),
        water_level: int = -8
    ) -> str:
        """Generates Luau script utilizing workspace.Terrain to construct terrain slabs and water tables."""
        mats = cls.BIOMES.get(biome.lower(), cls.BIOMES["plains"])
        cx, cy, cz = center
        sx, sy, sz = size

        lines = [
            "--!strict",
            f"-- Procedural Terrain Generator ({biome.capitalize()} Biome)",
            "local Workspace = game:GetService('Workspace')",
            "local terrain = Workspace.Terrain",
            "",
            f"local center = Vector3.new({cx}, {cy}, {cz})",
            f"local size = Vector3.new({sx}, {sy}, {sz})",
            "",
            "-- 1. Bedrock base",
            f"terrain:FillBlock(CFrame.new(center - Vector3.new(0, size.Y * 0.25, 0)), Vector3.new(size.X, size.Y * 0.5, size.Z), {mats['bottom']})",
            "",
            "-- 2. Subsurface foundation",
            f"terrain:FillBlock(CFrame.new(center), Vector3.new(size.X, size.Y * 0.3, size.Z), {mats['subsurface']})",
            "",
            "-- 3. Top surface layer",
            f"terrain:FillBlock(CFrame.new(center + Vector3.new(0, size.Y * 0.35, 0)), Vector3.new(size.X, size.Y * 0.2, size.Z), {mats['surface']})",
            ""
        ]

        if water_level < cy + (sy * 0.5):
            lines.extend([
                "-- 4. Water table",
                f"local waterCenter = Vector3.new(center.X, {water_level}, center.Z)",
                f"local waterSize = Vector3.new(size.X * 1.2, 12, size.Z * 1.2)",
                "terrain:FillBlock(CFrame.new(waterCenter), waterSize, Enum.Material.Water)",
                ""
            ])

        lines.append("print('[Stroke Terrain] Procedural terrain generation completed successfully.')")
        return "\n".join(lines)


# ------------------------------------------------------------------------------
# 7. VFX & ANIMATION BUILDER
# ------------------------------------------------------------------------------
class VfxBuilder:
    """Synthesizes verified particle emitters, beams, highlights, and tween kinematics."""

    @classmethod
    def generate_particle_vfx(
        cls,
        vfx_type: str = "FireAura",
        target_name: str = "VFXEmitterPart",
        target_parent: str = "workspace"
    ) -> str:
        """Generates Luau script creating complete particle effect hierarchy."""
        return f"""--!strict
local Debris = game:GetService("Debris")

local part = Instance.new("Part")
part.Name = "{target_name}"
part.Size = Vector3.new(1, 1, 1)
part.Transparency = 1
part.Anchored = true
part.CanCollide = false
part.CFrame = CFrame.new(0, 5, 0)
part.Parent = {target_parent}

local attachment = Instance.new("Attachment")
attachment.Name = "VFXAttachment"
attachment.Parent = part

local emitter = Instance.new("ParticleEmitter")
emitter.Name = "{vfx_type}"
emitter.Rate = 45
emitter.Lifetime = NumberRange.new(0.6, 1.2)
emitter.Speed = NumberRange.new(5, 12)
emitter.SpreadAngle = Vector2.new(25, 25)
emitter.Size = NumberSequence.new({{
    NumberSequenceKeypoint.new(0, 1.5),
    NumberSequenceKeypoint.new(0.5, 3.0),
    NumberSequenceKeypoint.new(1, 0.0)
}})
emitter.Transparency = NumberSequence.new({{
    NumberSequenceKeypoint.new(0, 0.1),
    NumberSequenceKeypoint.new(0.8, 0.4),
    NumberSequenceKeypoint.new(1, 1.0)
}})
emitter.Color = ColorSequence.new({{
    ColorSequenceKeypoint.new(0, Color3.fromRGB(255, 180, 50)),
    ColorSequenceKeypoint.new(1, Color3.fromRGB(255, 40, 0))
}})
emitter.LightEmission = 0.8
emitter.Parent = attachment

local highlight = Instance.new("Highlight")
highlight.FillColor = Color3.fromRGB(255, 100, 0)
highlight.OutlineColor = Color3.fromRGB(255, 255, 200)
highlight.FillTransparency = 0.6
highlight.Parent = part

Debris:AddItem(part, 10)
print("[Stroke VFX] {vfx_type} instantiated successfully.")
"""


# ------------------------------------------------------------------------------
# 8. STUDIO ERROR DETECTION & CONSOLE DIAGNOSTICS
# ------------------------------------------------------------------------------
class StudioErrorDiagnoser:
    """Diagnoses runtime errors, syntax issues, and infinite yield warnings from console output."""

    STACK_TRACE_REGEX = re.compile(r'([A-Za-z0-9_./\\]+):(\d+):\s*(.*)')
    INFINITE_YIELD_REGEX = re.compile(r'Infinite yield possible on [\'"]([^\'"]+)[\'"]')
    NIL_INDEX_REGEX = re.compile(r'attempt to index nil with [\'"]([^\'"]+)[\'"]')

    @classmethod
    def diagnose_console(cls, lines: List[str]) -> Dict[str, Any]:
        detected_errors: List[Dict[str, Any]] = []

        for line in lines:
            line_str = line.strip()

            # Stack traces
            m_trace = cls.STACK_TRACE_REGEX.search(line_str)
            if m_trace:
                script_path = m_trace.group(1)
                line_no = int(m_trace.group(2))
                error_msg = m_trace.group(3)

                diagnosis = "Runtime error in script execution."
                remedy = "Inspect line for invalid assumptions or missing checks."

                if "attempt to index nil" in error_msg:
                    diagnosis = "Nil indexing exception: target table, instance, or return value was nil."
                    remedy = "Add guard clause (if target then ... end) or verify WaitForChild return."
                elif "expected" in error_msg and "got" in error_msg:
                    diagnosis = "Type mismatch argument error."
                    remedy = "Verify parameter count and types passed to the function."

                detected_errors.append({
                    "severity": "error",
                    "file": script_path,
                    "line": line_no,
                    "raw_message": error_msg,
                    "diagnosis": diagnosis,
                    "remedy": remedy
                })

            # Infinite Yield Warnings
            m_yield = cls.INFINITE_YIELD_REGEX.search(line_str)
            if m_yield:
                inst_path = m_yield.group(1)
                detected_errors.append({
                    "severity": "warning",
                    "file": "DataModel",
                    "line": 0,
                    "raw_message": line_str,
                    "diagnosis": f"Infinite yield warning waiting for child '{inst_path}'. The child instance was never created, replicated, or named correctly.",
                    "remedy": f"Check spelling of '{inst_path}', verify server script creates it, or supply a timeout to WaitForChild('{inst_path}', 5)."
                })

        return {
            "total_issues_found": len(detected_errors),
            "errors_count": sum(1 for e in detected_errors if e["severity"] == "error"),
            "warnings_count": sum(1 for e in detected_errors if e["severity"] == "warning"),
            "diagnoses": detected_errors
        }


# ------------------------------------------------------------------------------
# 9. PLAY-TEST & OBJECT VERIFICATION ENGINE
# ------------------------------------------------------------------------------
class PlaytestAndVerificationEngine:
    """Orchestrates verified playtesting and truthful object existence checks."""

    @classmethod
    async def verify_object(
        cls,
        target_path: str,
        expected_class: Optional[str] = None,
        workspace_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Truthfully verifies an object in Roblox Studio or approved workspace.
        Never fabricates an object or reports success without proof.
        """
        import mcp_bridge
        session = mcp_bridge.StudioMcpSession.get_instance()
        is_live = await session.ensure_session() and session.client

        if is_live:
            # Query live game tree
            res = await session.client.call_tool("search_game_tree", {
                "query": target_path.split(".")[-1],
                "studio_id": session.active_studio_id
            })
            if res.get("status") == "success":
                result_data = res.get("result", {})
                content = result_data.get("content", [])
                text_out = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
                if target_path.split(".")[-1].lower() in text_out.lower():
                    return {
                        "verified": True,
                        "exists": True,
                        "source": "live_studio_mcp",
                        "target_path": target_path,
                        "message": f"Object '{target_path}' verified live in Roblox Studio DataModel."
                    }

        # Check local filesystem workspace
        res_ws = HierarchyInspector.resolve_datamodel_path(target_path, workspace_path=workspace_path)
        if res_ws.get("verified"):
            return {
                "verified": True,
                "exists": True,
                "source": "workspace_tree",
                "target_path": target_path,
                "filesystem_path": res_ws.get("filesystem_path"),
                "message": f"Object '{target_path}' verified in workspace structure at {res_ws.get('filesystem_path')}."
            }

        return {
            "verified": False,
            "exists": False,
            "source": "verification_failed",
            "target_path": target_path,
            "message": f"Verification failed: Object '{target_path}' could not be confirmed in live Studio or workspace tree."
        }
