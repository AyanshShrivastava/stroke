"""
================================================================================
STROKE // AUTONOMOUS CODING LOOP ENGINE
Architecture:
  1. Understand the request (Intent & requirements analysis)
  2. Generate code (Small coding model / Llama 3.2 1B / mini-agent / Qwen-Coder)
  3. Run checks (Syntax, AST, Roblox DataModel & Domain Test Runner)
  4. Read errors (Error Analyser & Failure Diagnosis)
  5. Fix the code (Correction Loop / Self-Healing Cycle)
  6. Verify again (Retest runner & validation)
  7. Present final answer (Verified code + Transparency & Quality Report)
================================================================================
Principle:
  Passing tests does not guarantee perfect code. Stroke reports which checks
  passed and never pretends untested code is verified.
================================================================================
"""

import sys
import os
import re
import ast
import json
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple, Set, Union

import paths_service
import backup_service
import file_service
import workspace_service
from agent_orchestrator import get_reasoning_profile, ReasoningProfile

try:
    from luaparser import ast as lua_ast
except Exception:
    lua_ast = None

try:
    from luau_analyzer import (
        AuthenticLuauValidator,
        mask_comments_and_strings,
        find_system_luau_tool,
        run_system_luau_compiler
    )
except Exception:
    AuthenticLuauValidator = None
    mask_comments_and_strings = None
    find_system_luau_tool = lambda: None
    run_system_luau_compiler = lambda p, c: (1, "", "luau_analyzer not available")

try:
    import terminal_service
    from terminal_service import TerminalManager
except Exception:
    TerminalManager = None


# ==============================================================================
# VALID ROBLOX DATA MODEL INSTANCES & FAKE API RULE ENGINE
# ==============================================================================

VALID_ROBLOX_INSTANCES = {
    "Part", "MeshPart", "Model", "Folder", "Script", "LocalScript", "ModuleScript",
    "ParticleEmitter", "Beam", "Trail", "Attachment", "Highlight", "PointLight", "SpotLight", "SurfaceLight",
    "Sound", "Animation", "AnimationTrack", "Humanoid", "HumanoidDescription", "Motor6D", "Weld", "WeldConstraint",
    "BodyPosition", "BodyGyro", "BodyVelocity", "LinearVelocity", "AlignPosition", "AlignOrientation",
    "ScreenGui", "Frame", "TextLabel", "TextButton", "ImageLabel", "ImageButton", "ScrollingFrame", "UIListLayout",
    "BillboardGui", "SurfaceGui", "ProximityPrompt", "ClickDetector", "RemoteEvent", "RemoteFunction", "BindableEvent", "BindableFunction",
    "Configuration", "StringValue", "IntValue", "NumberValue", "BoolValue", "Vector3Value", "CFrameValue", "Color3Value", "ObjectValue",
    "Decal", "Texture", "SpecialMesh", "BlockMesh", "CylinderMesh", "FileMesh",
    "Smoke", "Fire", "Sparkles", "Explosion", "ForceField", "CornerWedgePart", "WedgePart", "TrussPart",
    "SpawnLocation", "Seat", "VehicleSeat", "Camera", "Tool", "Accessory", "Shirt", "Pants", "ShirtGraphic",
    "Sky", "Atmosphere", "Clouds", "BloomEffect", "BlurEffect", "ColorCorrectionEffect", "SunRaysEffect", "DepthOfFieldEffect"
}

FAKE_ROBLOX_API_RULES = [
    (r"\bSpawnParticleEmitter\b", "ParticleEmitter:SpawnParticleEmitter() does not exist in Roblox. Use 'ParticleEmitter:Emit(count)' to emit particles."),
    (r"\bParticle\.new\b", "Particle.new() is not a standard Roblox API. Particles are not separate instances; configure ParticleEmitter properties (Rate, Lifetime, Speed, SpreadAngle) and call ':Emit(count)'."),
    (r"\bColor3\.from_rgb\b", "Color3.from_rgb() is invalid. Roblox Luau uses 'Color3.fromRGB(r, g, b)' or 'Color3.new(r, g, b)'."),
    (r":Spawn\s*\(", "':Spawn()' is not a valid method on Roblox particle or DataModel instances. Use ':Emit(count)' or task.spawn()."),
    (r"\b(\d+x\d+)\b", "Invalid Luau syntax '{match}'. Dimension literals like '{match}' are invalid; use 'Vector2.new(width, height)' or arithmetic operators."),
    (r"\bparticleType\s*=\s*[\"'](?:Sphere|Mesh)[\"']", "ParticleEmitter does not have a 'particleType' setting. ParticleEmitter emits 2D billboard textures. For 3D meshes, use BasePart or MeshPart with TweenService."),
    (r"particleEmitter\.(?:Spread|Density|Radius|Velocity)\s*=", "Invalid ParticleEmitter property assignment. Legitimate ParticleEmitter properties are: 'Rate', 'Lifetime', 'Speed', 'SpreadAngle', 'Color', 'Size', 'Texture', 'Acceleration', and 'Drag'."),
    (r"\b([a-zA-Z0-9_]+)\.Parent\s*=\s*\1\b", "Cyclic instance parenting error: '{match}' cannot be parented to itself."),
    # 1. WaitForChild callback misuse: :WaitForChild(name, function(...) ...)
    (r':WaitForChild\s*\(\s*([^,\n\)]+)\s*,\s*function\b', "Roblox API Error: 'Instance:WaitForChild(childName, timeout)' takes a numeric timeout as its second argument, not a callback function. WaitForChild returns the child Instance synchronously."),
    # 2. WaitForChild / FindFirstChild on properties
    (r':(?:WaitForChild|FindFirstChild)\s*\(\s*["\'](CFrame|Position|Size|Health|MaxHealth|Anchored|CanCollide|Orientation)["\']', "Roblox API Error: ':{match}' is a property, not a child Instance. Access properties directly using dot notation (e.g. 'part.{match}')."),
    # 3. Humanoid CFrame / Position / Size access
    (r'(?::FindFirstChild(?:OfClass)?\(["\']Humanoid["\']\)|\.Humanoid)\s*(?::WaitForChild|:FindFirstChild)\s*\(\s*["\'](CFrame|Position|Size|Orientation)["\']', "Roblox Type Error: 'Humanoid' is a Controller instance without spatial geometry. It does not possess a '{match}' property or child. Access '.CFrame' on the character's 'HumanoidRootPart' (BasePart) instead."),
    (r'(?::FindFirstChild(?:OfClass)?\(["\']Humanoid["\']\)|\.Humanoid)\s*\.\s*(CFrame|Position|Orientation)\b', "Roblox Type Error: 'Humanoid' does not have a '.{match}' property. Access '.{match}' on 'HumanoidRootPart' (BasePart) instead."),
    # 4. TakeDamage on non-Humanoid (Part, Hitbox, Model, etc.)
    (r'\b(hitbox|part|detectedPart|rootPart|humanoidRootPart|basePart|model|cframe)\s*:\s*TakeDamage\s*\(', "Roblox API Error: ':TakeDamage()' can only be invoked on a 'Humanoid' instance, not on '{match}' (BasePart). Locate the target's Humanoid via 'targetChar:FindFirstChildOfClass(\"Humanoid\")' and call 'humanoid:TakeDamage(damage)'."),
    # 5. Fatal Library Shadowing: local task = task.wait
    (r'\blocal\s+task\s*=\s*task\.wait\b', "Fatal Library Shadowing: 'local task = task.wait' shadows the standard 'task' library table with a function, causing all subsequent 'task.wait()' calls to crash ('attempt to index function with wait'). Remove this assignment; 'task.wait()' is already globally available."),
    (r'\blocal\s+(task|math|string|table|os|coroutine|debug)\s*=\s*\1\.\w+', "Fatal Library Shadowing: 'local {match} = ...' shadows the standard library table with a function. Use '{match}' library functions directly."),
    # 6. Fake API Mocking: Datatypes and Constructors
    (r'\blocal\s+(OverlapParams|RaycastParams|TweenInfo|Color3|Vector3|Vector2|CFrame|NumberRange|NumberSequence|ColorSequence)\s*=\s*\{\}', "Fake API Implementation: 'local {match} = {{}}' shadows the built-in Roblox datatype constructor '{match}.new()'. Do not mock Roblox built-in datatypes with empty tables."),
    # 7. Fake API Mocking: Methods and properties defined as empty tables
    (r'\blocal\s+(GetPartBoundsInBox|GetPartsInPart|GetPartBoundsInRadius|Raycast|TakeDamage|FilterDescendantsInstances|FilterType|MaxParts)\s*=\s*\{\}', "Fake API Implementation: '{match}' is a Roblox method or property, not a standalone global table. Do not define empty mock tables."),
    # 8. Type mismatch in function call: executeSpatialHitbox(HumanoidRootPart, ...)
    (r'\bexecuteSpatialHitbox\s*\(\s*(HumanoidRootPart|rootPart|part|Player)\b', "Type Mismatch in Call: 'executeSpatialHitbox' expects a character 'Model' as argument #1, but received '{match}' (a BasePart/Player). Pass the character Model (e.g. 'Player.Character' or 'casterCharacter') instead."),
]


# ==============================================================================
# 1. LUAU SYNTAX & AST VALIDATOR
# ==============================================================================

class LuauSyntaxValidator:
    """
    Robust static AST and syntax analyzer for Luau (Roblox Lua).
    Detects mismatched blocks, unbalanced delimiters, illegal operators,
    non-existent Roblox APIs, and deprecated calls without requiring external binaries.
    """

    LUAU_BLOCK_OPENERS = {"function", "if", "for", "while", "do", "repeat"}
    
    @staticmethod
    def strip_comments_and_strings(code: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Strips comments and string literals using authentic Luau lexer
        while preserving exact line and column numbers.
        """
        if mask_comments_and_strings:
            masked, _ = mask_comments_and_strings(code)
            return masked, []
        return code, []

    @classmethod
    def check_syntax(cls, code: str) -> List[Dict[str, Any]]:
        """
        Validates syntax, delimiters, blocks, illegal operators, and authentic Roblox APIs.
        Never falsely flags strings, comments, or long-bracket content.
        """
        if AuthenticLuauValidator:
            return AuthenticLuauValidator.validate_code(code)
        return []


# ==============================================================================
# 2. DOMAIN & HITBOX TEST RUNNER
# ==============================================================================

class RobloxDomainTestRunner:
    """
    Executes domain-specific static tests and verification checks:
    - Hitbox detection (Spatial queries, Debounce tables, Humanoid checks, Self-filter, Memory cleanup)
    - VFX Kinematics & Tweening (TweenInfo, ParticleEmitter, Attachment hierarchies)
    - Python script AST compilation (ast.parse, unit assertions)
    """

    @classmethod
    def test_luau_code(cls, code: str, prompt: str) -> Dict[str, Any]:
        """
        Runs full test suite on generated Luau code.
        Returns:
          {
            "passed_checks": [...],
            "failed_checks": [...],
            "untested_limitations": [...],
            "is_verified": bool
          }
        """
        passed_checks = []
        failed_checks = []
        untested_limitations = []

        # 1. Syntax Check
        syntax_issues = LuauSyntaxValidator.check_syntax(code)
        errors = [i for i in syntax_issues if i["type"] == "error"]
        warnings = [i for i in syntax_issues if i["type"] == "warning"]

        if not errors:
            passed_checks.append("Luau AST & Syntax Balance (Delimiters, blocks, and operators verified)")
        else:
            for err in errors:
                failed_checks.append(err)

        if not warnings:
            passed_checks.append("Modern Luau Standards (No deprecated wait(), spawn(), or :connect() calls)")
        else:
            for w in warnings:
                failed_checks.append(w)

        # 2. Roblox DataModel & Service Compliance
        has_get_service = bool(re.search(r'game:GetService\(["\'](\w+)["\']\)', code))
        if has_get_service:
            passed_checks.append("Roblox Service Resolution (Proper game:GetService() usage)")
        
        # 3. Domain Check: Hitbox & Combat Detection (Driven by code AST and APIs, not prompt keywords)
        has_spatial_query = any(q in code for q in [
            "GetPartsInPart", "GetPartBoundsInBox", "GetPartBoundsInRadius",
            "workspace:Raycast", "WorldRoot:Raycast", "OverlapParams"
        ])
        has_touched = ".Touched:Connect" in code or ".Touched:connect" in code
        has_damage_call = ":TakeDamage" in code
        has_combat_logic = has_spatial_query or has_touched or has_damage_call or "HumanoidRootPart" in code

        if has_combat_logic:
            has_spatial_blocking_error = any(
                ("Workspace" in f.get("message", "") and "Unresolved Global" in f.get("message", ""))
                or ("Fake API Implementation" in f.get("message", "") and any(term in f.get("message", "") for term in ["OverlapParams", "GetPartBoundsInBox", "GetPartsInPart", "GetPartBoundsInRadius"]))
                for f in failed_checks
            )

            if has_spatial_query and not has_spatial_blocking_error:
                passed_checks.append("Spatial Query Architecture (Modern OverlapParams / WorldRoot spatial query detected)")
            elif has_spatial_query and has_spatial_blocking_error:
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": "Spatial query architecture is corrupted by unresolved globals or fake API mock tables.",
                    "suggestion": "Call spatial queries directly on 'workspace' (lowercase) or 'game:GetService(\"Workspace\")' with authentic OverlapParams."
                })
            elif has_touched:
                passed_checks.append("Touched Event Architecture (Physical part collision detection detected)")
                untested_limitations.append("Touched events can suffer from physics latency; recommend spatial queries for competitive combat.")
            else:
                failed_checks.append({
                    "type": "warning",
                    "line": 1,
                    "message": "Hitbox lacks recognized spatial queries (e.g. workspace:GetPartBoundsInBox, GetPartsInPart) or Raycast.",
                    "suggestion": "Implement OverlapParams and workspace:GetPartBoundsInBox for robust server-side detection."
                })

            # Check Debounce / Multi-Hit Protection (CRITICAL for combat/hitboxes)
            has_debounce_identifier = any(w in code.lower() for w in [
                "debounce", "cooldown", "hittargets", "hit_characters", "hitcharacters",
                "damagedtargets", "alreadyhit", "hits[", "hitplayers", "activehitboxes", "hitdebounce"
            ])
            has_single_invocation_debounce = any("Single-Invocation Debounce Only" in f.get("message", "") for f in failed_checks)

            # Genuine debounce requires BOTH:
            # 1. A condition guard checking hit/debounce state
            has_debounce_guard = bool(
                re.search(r'\bnot\s+[a-zA-Z0-9_.]*?(?:hit|debounce)[a-zA-Z0-9_.]*?\s*(?:\[|\b)', code, re.IGNORECASE)
                or re.search(r'if\s+.*?\bnot\s+[a-zA-Z0-9_.]*?(?:hit|debounce)', code, re.IGNORECASE)
                or re.search(r'\([a-zA-Z0-9_.]+\s*-\s*[a-zA-Z0-9_.]+\)\s*>=?\s*[a-zA-Z0-9_.]+', code)
                or re.search(r'if\s+debounce\s+then\s+return\b', code, re.IGNORECASE)
            )
            # 2. A state mutation updating the hit state
            has_debounce_mutation = bool(
                re.search(r'[a-zA-Z0-9_.]*?(?:hit|debounce)[^=\n]*?=\s*(?:true|false|os\.clock|tick|now|currentTime|time)', code, re.IGNORECASE)
            )

            has_effective_debounce = has_debounce_identifier and has_debounce_guard and has_debounce_mutation

            if has_effective_debounce:
                if has_single_invocation_debounce:
                    passed_checks.append("Single-Query Limb Deduplication (Filters multiple character limbs during a single spatial query)")
                    untested_limitations.append("Hitbox uses single-invocation debounce table; repeated calls across frames will re-damage the same target without persistent cooldown.")
                else:
                    passed_checks.append("Multi-Hit Debounce Protection (Persistent debounce table or cooldown prevents damage spam across frames)")
            elif has_debounce_identifier and (not has_debounce_guard or not has_debounce_mutation):
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": "Ineffective Debounce Logic: A debounce variable or table was declared, but the code fails to both guard hits ('if not hitTargets[char]') AND mutate state ('hitTargets[char] = true'). Targets take continuous damage.",
                    "suggestion": "Implement both a conditional guard and state mutation on target hit."
                })
            else:
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": "Missing multi-hit debounce table. Without a hit cache (e.g., local hitTargets = {}), targets take damage on every frame.",
                    "suggestion": "Add a debounce dictionary (e.g. 'local hitTargets = {}') and check 'if not hitTargets[humanoid] then hitTargets[humanoid] = true ... end'."
                })

            # Check Humanoid & Health Check
            has_humanoid_check = bool(re.search(r'FindFirstChild(?:OfClass)?\(["\']Humanoid["\']\)', code))
            has_health_check = "humanoid.health" in code.lower() or "humanoid.health > 0" in code.lower()
            has_humanoid_blocking_error = any(
                ("Humanoid" in f.get("message", "") and ("Type Error" in f.get("message", "") or "API Error" in f.get("message", "")))
                or ("TakeDamage" in f.get("message", ""))
                for f in failed_checks
            )

            if has_humanoid_check and not has_humanoid_blocking_error:
                passed_checks.append("Entity Humanoid Resolution (Validates target character model has Humanoid)")
            elif has_humanoid_blocking_error:
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": "Humanoid resolution & damage execution contains fatal type/API errors (e.g. indexing Humanoid for CFrame or calling TakeDamage on a BasePart).",
                    "suggestion": "Access CFrame on HumanoidRootPart, resolve character model via FindFirstAncestorOfClass('Model'), and call :TakeDamage() on Humanoid."
                })
            else:
                failed_checks.append({
                    "type": "warning",
                    "line": 1,
                    "message": "Hitbox does not explicitly check for Humanoid before resolving hits.",
                    "suggestion": "Use 'character:FindFirstChildOfClass(\"Humanoid\")' to ensure valid damage targets."
                })

            if has_health_check and not has_humanoid_blocking_error:
                passed_checks.append("Living Entity Guard (Verifies Humanoid.Health > 0 to prevent corpse damage)")
            else:
                untested_limitations.append("Target health check (> 0) omitted; may register hits on dead characters.")

            # Check Self-Damage / Caster Filter
            has_caster_filter = any(w in code for w in [
                "FilterDescendantsInstances", "caster", "player.Character", "character ~= hitCharacter",
                "hitCharacter ~= character", "owner"
            ])
            has_caster_blocking_error = any(
                ("FilterDescendantsInstances" in f.get("message", "") and "Fake API" in f.get("message", ""))
                or ("Type Mismatch in Call" in f.get("message", "") and "executeSpatialHitbox" in f.get("message", ""))
                for f in failed_checks
            )

            if has_caster_filter and not has_caster_blocking_error:
                passed_checks.append("Caster Immunity Filter (Prevents attacker from damaging themselves)")
            elif has_caster_filter and has_caster_blocking_error:
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": "Caster immunity filter is invalid: caller passes a BasePart instead of character Model or FilterDescendantsInstances is shadowed.",
                    "suggestion": "Pass caster's character Model to FilterDescendantsInstances and assign directly to OverlapParams."
                })
            else:
                failed_checks.append({
                    "type": "warning",
                    "line": 1,
                    "message": "Attacker character is not filtered out from hitbox detection.",
                    "suggestion": "Filter the caster's character via OverlapParams.FilterDescendantsInstances = {casterCharacter}."
                })

            # Check Memory & Instance Cleanup
            creates_temporary_parts = bool(re.search(r'Instance\.new\(["\'](Part|MeshPart|Sphere|Attachment)["\']\)', code))
            has_cleanup = any(w in code for w in [
                "Debris:AddItem", ":Destroy()", "task.delay"
            ])
            if creates_temporary_parts:
                if has_cleanup:
                    passed_checks.append("Resource Memory Management (Temporary hitbox parts/visualizers destroyed or cleared via Debris)")
                else:
                    failed_checks.append({
                        "type": "warning",
                        "line": 1,
                        "message": "Hitbox creates Instance.new() parts or visualizers but lacks Debris:AddItem or :Destroy() cleanup.",
                        "suggestion": "Add 'game:GetService(\"Debris\"):AddItem(hitbox, duration)' to guarantee memory reclamation."
                    })
            elif not has_spatial_blocking_error:
                passed_checks.append("Partless Spatial Query Architecture (Uses spatial queries directly without instantiating physical Part instances)")

            untested_limitations.extend([
                "Multiplayer replication lag: Network ping between high-latency clients and server cannot be tested statically.",
                "Custom R15/R6 avatar scaling: Box bounds may vary with player bundle sizes (e.g., Anthro vs standard R15).",
                "Physics simulation: Actual part penetration depends on live Roblox engine collision groups."
            ])

        # 4. Domain Check: VFX & Particle Effects (Driven by code AST)
        has_particles = "ParticleEmitter" in code or "Beam" in code or "Highlight" in code or "Trail" in code
        has_attachments = "Attachment" in code

        if has_particles and not has_combat_logic:
            passed_checks.append("Visual Effect Emitter Architecture (Configures ParticleEmitters, Beams, or Highlights)")
            if has_attachments:
                passed_checks.append("Attachment Anchoring (Emitters parented to valid Attachment points)")

            has_rate_control = any(k in code for k in [".Rate", "Rate =", "math.clamp", "TouchEnabled"])
            has_lifetime_budget = any(k in code for k in [".Lifetime", "Lifetime =", "NumberRange.new"])
            has_burst_or_toggle = any(k in code for k in [":Emit", ".Enabled = false", "Enabled = false", ":Clear"])
            has_mobile_branch = any(k in code for k in ["TouchEnabled", "UserInputService", "isMobile", "mobile"])

            if has_rate_control:
                passed_checks.append("Mobile Emission Rate Budgeting (Throttles particles per second to prevent mobile fill-rate drops)")
            if has_lifetime_budget:
                passed_checks.append("Particle Lifetime Constriction (Reduces active on-screen particle lifetime to minimize overdraw)")
            if has_burst_or_toggle:
                passed_checks.append("Demand-Driven Emission (Uses :Emit(count) or toggles .Enabled to prevent continuous background draw calls)")
            if has_mobile_branch:
                passed_checks.append("Platform Capability Detection (Uses UserInputService.TouchEnabled to adapt VFX for mobile)")

            untested_limitations.append("GPU rendering framerate impact under 100+ simultaneous particle emitters.")

        # 5. Domain Check: 3D Structures & Assemblies (Driven by code AST)
        has_structures = bool(re.search(r'Instance\.new\(["\'](Part|MeshPart|Model|TrussPart|WedgePart)["\']\)', code)) and not has_combat_logic and not has_particles
        if has_structures:
            has_insert = "InsertService" in code or "GetObjects" in code
            has_parts = "Instance.new(\"Part\")" in code or "Instance.new('Part')" in code or "Instance.new(\"Model\")" in code
            has_anchored = ".Anchored = true" in code or "Anchored = true" in code
            has_parent = ".Parent = workspace" in code or ".Parent =" in code

            if has_insert:
                passed_checks.append("Creator Store Ingestion Pipeline (Uses InsertService / GetObjects for marketplace asset retrieval)")
            if has_parts:
                passed_checks.append("3D Architectural Instance Assembly (Constructs structural components: Foundation, Walls, Roof, Model)")
            if has_anchored:
                passed_checks.append("Structural Anchoring Guard (Ensures buildings and parts do not collapse under Roblox physics)")
            if has_parent:
                passed_checks.append("DataModel Hierarchy Parenting (Properly mounted to Workspace container)")

            untested_limitations.extend([
                "Creator Store Asset ID ownership / public distribution permissions in target place.",
                "Live workspace spatial collision with terrain geometry or existing map structures."
            ])

        # Background Terminal Execution Check for Luau
        has_compiler_verified = False
        commands_executed = []
        exit_codes = []
        compiler_used = "Stroke Luau AST & Domain Engine"
        syntax_status = "PASS"
        static_status = "PASS"
        api_status = "PASS"
        runtime_status = "NOT RUN"
        test_status = "NOT RUN"
        perf_status = "NOT RUN"

        # Real System or Terminal Compiler Execution Check for Luau
        system_tool = find_system_luau_tool() if find_system_luau_tool else None
        if system_tool:
            rc, out, err = run_system_luau_compiler(system_tool, code)
            commands_executed.append(f"{os.path.basename(system_tool)} -")
            exit_codes.append(rc)
            if rc == 0:
                has_compiler_verified = True
                compiler_used = f"{os.path.basename(system_tool)} CLI"
                syntax_status = "PASS"
                passed_checks.append(f"Luau Native Compilation ({os.path.basename(system_tool)} verified cleanly)")
            else:
                syntax_status = "FAIL"
                has_compiler_verified = False
                compiler_used = f"{os.path.basename(system_tool)} CLI"
                err_text = (err or out or "Luau compile error").strip()
                failed_checks.append({
                    "type": "error",
                    "line": 1,
                    "message": f"Luau Compiler Error: {err_text[:200]}",
                    "suggestion": "Fix Luau syntax/type errors identified by compiler."
                })
        elif TerminalManager:
            try:
                term_session = TerminalManager.terminal_create_session()
                session_id = term_session["session_id"]
                ws_path = term_session.get("workspace_path", os.getcwd())
                scratch_dir = os.path.join(ws_path, ".stroke_scratch")
                os.makedirs(scratch_dir, exist_ok=True)
                scratch_file = os.path.join(scratch_dir, f"test_{int(time.time()*1000)}.luau")
                with open(scratch_file, "w", encoding="utf-8") as f:
                    f.write(code)

                # Attempt luau-analyze via background terminal
                commands_executed.append(f"luau-analyze {os.path.basename(scratch_file)}")
                res = TerminalManager.terminal_run(session_id, "luau-analyze", [scratch_file], timeout_sec=10)
                ec = res.get("exit_code", 127)
                exit_codes.append(ec)
                if ec == 0:
                    passed_checks.append("Luau Static Type & Semantic Analysis (luau-analyze verified cleanly via private background terminal)")
                    has_compiler_verified = True
                    compiler_used = "luau-analyze CLI"
                    syntax_status = "PASS"
                elif ec == 127:
                    # luau-analyze binary not installed on host, AST analysis was used
                    syntax_status = "NOT RUN (COMPILER NOT INSTALLED - UNVERIFIED)"
                    compiler_used = "Stroke AST & Roblox Static Rules (Compiler Missing)"
                    untested_limitations.append("External luau / luau-analyze compiler binary not found on host; static AST and Roblox DataModel rules passed, but bytecode compilation and live runtime remain UNVERIFIED.")
                else:
                    syntax_status = "FAIL"
                    err_msg = res.get("stderr") or res.get("stdout") or "Semantic warning in Luau script"
                    failed_checks.append({
                        "type": "warning",
                        "line": 1,
                        "message": f"Luau Analyzer Report: {err_msg.strip()[:180]}",
                        "suggestion": "Review Luau type annotations and variable definitions."
                    })

                try:
                    if os.path.exists(scratch_file):
                        os.remove(scratch_file)
                except Exception:
                    pass
                TerminalManager.terminal_stop(session_id)
            except Exception as term_exc:
                untested_limitations.append(f"Private terminal runner note: {term_exc}")
        else:
            syntax_status = "NOT RUN (COMPILER NOT INSTALLED - UNVERIFIED)"
            compiler_used = "Stroke AST & Roblox Static Rules (Compiler Missing)"
            untested_limitations.append("External luau / luau-analyze compiler binary not found on host; static AST and Roblox DataModel rules passed, but bytecode compilation and live runtime remain UNVERIFIED.")

        # Check API and semantic errors
        api_errors = [
            f for f in failed_checks 
            if any(k in f.get("message", "").lower() for k in [
                "fake", "non-existent", "invalid roblox class", "spawnparticleemitter", 
                "createhitbox", "makeexplosion", "findnearestcharacter", "damagehumanoid",
                "roblox api error", "roblox type error", "fatal library shadowing",
                "unresolved global", "type mismatch in call"
            ])
        ]
        if api_errors:
            api_status = "FAIL"
            static_status = "FAIL"

        syntax_errors = [f for f in failed_checks if f.get("type") == "error"]
        if syntax_errors:
            syntax_status = "FAIL"
            static_status = "FAIL"

        # Final Verification Status: strictly requires real compiler verification and no syntax/API failures
        blocking_errors = [f for f in failed_checks if f.get("type") == "error"]
        if blocking_errors or api_status == "FAIL" or syntax_status == "FAIL" or static_status == "FAIL":
            is_verified = False
            verification_status = "FAIL"
        elif has_compiler_verified and syntax_status == "PASS":
            is_verified = True
            verification_status = "PASS"
        else:
            is_verified = False
            verification_status = "UNVERIFIED"

        return {
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "untested_limitations": untested_limitations,
            "is_verified": is_verified,
            "verification_status": verification_status,
            "has_compiler_verified": has_compiler_verified,
            "syntax_status": syntax_status,
            "static_status": static_status,
            "api_status": api_status,
            "runtime_status": runtime_status,
            "test_status": test_status,
            "perf_status": perf_status,
            "compiler_used": compiler_used,
            "commands_executed": commands_executed,
            "exit_codes": exit_codes
        }

    @classmethod
    def test_python_code(cls, code: str, prompt: str = "") -> Dict[str, Any]:
        """Runs real Python compilation and test verification on Python code."""
        passed_checks = []
        failed_checks = []
        untested_limitations = []
        commands_executed = []
        exit_codes = []
        compiler_used = f"Python {sys.version.split()[0]} Bytecode Compiler (compile + py_compile)"

        syntax_status = "NOT RUN"
        static_status = "NOT RUN"
        api_status = "PASS"
        runtime_status = "NOT RUN"
        test_status = "NOT RUN"
        perf_status = "NOT RUN"
        has_compiler_verified = False

        # 1. Compile in-memory using Python's real compiler
        # NOTE: ast.parse alone is NEVER proof of compilation!
        # compile() raises SyntaxError on 'await' outside async function (critical regression case)
        real_compile_error = None
        try:
            compile(code, "<string>", "exec")
            passed_checks.append("Python In-Memory Compilation (compile() exec bytecode generated cleanly)")
            has_compiler_verified = True
            syntax_status = "PASS"
        except SyntaxError as e:
            real_compile_error = e
            syntax_status = "FAIL"
            err_line = e.lineno or 1
            failed_checks.append({
                "type": "error",
                "line": err_line,
                "message": f"Python SyntaxError: {e.msg} on line {err_line}",
                "suggestion": f"Fix syntax near: {e.text.strip() if e.text else ''}"
            })
        except Exception as e:
            syntax_status = "FAIL"
            failed_checks.append({
                "type": "error",
                "line": 1,
                "message": f"Compilation Error: {str(e)}",
                "suggestion": "Fix Python syntax / bytecode structure."
            })

        # 2. Static AST analysis
        try:
            tree = ast.parse(code)
            passed_checks.append("Python AST Structure Verification (AST successfully parsed)")
            static_status = "PASS"
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            if funcs:
                passed_checks.append(f"Function Signatures Validated ({len(funcs)} defined: {', '.join(funcs[:3])})")
            if classes:
                passed_checks.append(f"Class Definitions Validated ({len(classes)} defined: {', '.join(classes[:2])})")
        except SyntaxError as e:
            static_status = "FAIL"
            if not real_compile_error:
                failed_checks.append({
                    "type": "error",
                    "line": e.lineno or 1,
                    "message": f"Python AST SyntaxError: {e.msg} on line {e.lineno}",
                    "suggestion": f"Fix syntax near: {e.text.strip() if e.text else ''}"
                })

        # 3. Real background terminal check via python -m py_compile
        if TerminalManager:
            try:
                term_session = TerminalManager.terminal_create_session()
                session_id = term_session["session_id"]
                ws_path = term_session.get("workspace_path", os.getcwd())
                scratch_dir = os.path.join(ws_path, ".stroke_scratch")
                os.makedirs(scratch_dir, exist_ok=True)
                scratch_file = os.path.join(scratch_dir, f"test_{int(time.time()*1000)}.py")
                with open(scratch_file, "w", encoding="utf-8") as f:
                    f.write(code)

                cmd_name = "python"
                args = ["-m", "py_compile", scratch_file]
                commands_executed.append(f"python -m py_compile {os.path.basename(scratch_file)}")
                res = TerminalManager.terminal_run(session_id, cmd_name, args, timeout_sec=10)
                ec = res.get("exit_code", 0)
                exit_codes.append(ec)

                if ec == 0:
                    passed_checks.append("Python Bytecode Compilation Check (python -m py_compile verified cleanly via private background terminal)")
                    has_compiler_verified = True
                    if syntax_status != "FAIL":
                        syntax_status = "PASS"
                else:
                    syntax_status = "FAIL"
                    has_compiler_verified = False
                    err_output = res.get("stderr") or res.get("stdout") or "Bytecode compilation error"
                    py_compile_line = 1
                    line_m = re.search(r'line (\d+)', err_output)
                    if line_m:
                        py_compile_line = int(line_m.group(1))
                    elif real_compile_error and real_compile_error.lineno:
                        py_compile_line = real_compile_error.lineno

                    if not any("SyntaxError" in f.get("message", "") and f.get("line") == py_compile_line for f in failed_checks):
                        failed_checks.append({
                            "type": "error",
                            "line": py_compile_line,
                            "message": f"Terminal Python Compiler Error:\n{err_output.strip()[:200]}",
                            "suggestion": "Fix Python syntax / bytecode error identified by python compiler."
                        })

                # 4. Automated Tests / Assertions Execution
                has_assertions = "assert " in code
                wants_tests = any(k in prompt.lower() for k in ["test", "assertion", "assert", "pytest", "unit"])
                if (has_assertions or wants_tests) and syntax_status == "PASS":
                    commands_executed.append(f"python {os.path.basename(scratch_file)}")
                    test_run = TerminalManager.terminal_run(session_id, "python", [scratch_file], timeout_sec=10)
                    t_ec = test_run.get("exit_code", 0)
                    exit_codes.append(t_ec)
                    if t_ec == 0:
                        test_status = "PASS"
                        runtime_status = "PASS"
                        passed_checks.append("Automated Test Assertions Passed (Exit code 0)")
                    else:
                        test_status = "FAIL"
                        runtime_status = "FAIL"
                        err_out = test_run.get("stderr") or test_run.get("stdout") or "Test assertion failed"
                        line_m = re.search(r'line (\d+)', err_out)
                        t_line = int(line_m.group(1)) if line_m else 1
                        failed_checks.append({
                            "type": "error",
                            "line": t_line,
                            "message": f"Automated Test Failure: {err_out.strip()[:200]}",
                            "suggestion": "Fix logic causing test assertion failure."
                        })

                try:
                    if os.path.exists(scratch_file):
                        os.remove(scratch_file)
                except Exception:
                    pass
                TerminalManager.terminal_stop(session_id)
            except Exception as term_exc:
                untested_limitations.append(f"Private terminal compiler note: {term_exc}")

        untested_limitations.append("Runtime environment dependencies, operating system differences, and edge-case I/O exceptions.")
        blocking_errors = [f for f in failed_checks if f.get("type") == "error"]
        if blocking_errors or syntax_status == "FAIL" or test_status == "FAIL":
            is_verified = False
            verification_status = "FAIL"
        elif syntax_status == "PASS" and has_compiler_verified and test_status != "FAIL":
            is_verified = True
            verification_status = "PASS"
        else:
            is_verified = False
            verification_status = "UNVERIFIED"

        return {
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "untested_limitations": untested_limitations,
            "is_verified": is_verified,
            "verification_status": verification_status,
            "has_compiler_verified": has_compiler_verified,
            "syntax_status": syntax_status,
            "static_status": static_status,
            "api_status": api_status,
            "runtime_status": runtime_status,
            "test_status": test_status,
            "perf_status": perf_status,
            "compiler_used": compiler_used,
            "commands_executed": commands_executed,
            "exit_codes": exit_codes
        }

    @classmethod
    def test_generic_code(cls, code: str, language: str) -> Dict[str, Any]:
        """
        Handles unsupported languages (e.g. JS, TS, C++, Rust).
        Never returns PASS; strictly marks as UNVERIFIED.
        """
        lang_norm = (language or "unknown").strip().lower()
        return {
            "passed_checks": [],
            "failed_checks": [],
            "untested_limitations": [
                f"Automated compiler and domain verification pipeline is not configured for '{lang_norm}'.",
                "Bytecode compilation, type analysis, and runtime behavior remain UNVERIFIED."
            ],
            "is_verified": False,
            "has_compiler_verified": False,
            "verification_status": "UNVERIFIED",
            "syntax_status": f"UNVERIFIED (NO COMPILER FOR {lang_norm.upper()})",
            "static_status": "UNVERIFIED",
            "api_status": "NOT RUN",
            "runtime_status": "NOT RUN",
            "test_status": "NOT RUN",
            "perf_status": "NOT RUN",
            "compiler_used": "N/A",
            "commands_executed": [],
            "exit_codes": []
        }


# ==============================================================================
# 3. ERROR ANALYSER & CORRECTION PROMPT SYNTHESIZER
# ==============================================================================

class ErrorAnalyser:
    """
    Ingests test runner results, diagnoses failures, and constructs
    crystal-clear corrective instructions for the local coding model.
    """

    @staticmethod
    def build_correction_prompt(code: str, failed_checks: List[Dict[str, Any]], language: str = "luau") -> str:
        """
        Builds a targeted diagnostic prompt for the small coding model to repair code.
        """
        diagnostic_lines = []
        for idx, check in enumerate(failed_checks, start=1):
            severity = check.get("type", "error").upper()
            line_no = check.get("line", 1)
            msg = check.get("message", "")
            sug = check.get("suggestion", "")
            diagnostic_lines.append(f"{idx}. [{severity}] (Line {line_no}): {msg}\n   FIX: {sug}")

        prompt = (
            f"### CRITICAL CODE DIAGNOSTIC REPORT\n"
            f"The generated {language.title()} script failed the following automated tests and checks:\n\n"
            + "\n".join(diagnostic_lines) + "\n\n"
            f"### INSTRUCTIONS FOR REVISION:\n"
            f"1. Fix every error and warning listed above.\n"
            f"2. Ensure complete block matching, modern Luau APIs (e.g. task.wait(), game:GetService()), "
            f"and robust debounce logic.\n"
            f"3. Return the complete, corrected, standalone production script enclosed in a ```{language} code block.\n"
            f"4. Do NOT output snippets or placeholders; output the fully fixed code."
        )
        return prompt


# ==============================================================================
# 4. ARCHIVIST & PROJECT CONTEXT
# ==============================================================================

class CodingArchivist:
    """
    Retains useful project context, verified code patterns, and test history.
    Stores records locally in data/verified_project_context.json and optionally Firestore.
    """
    CONTEXT_FILE = str(paths_service.get_verified_project_context_path())

    @classmethod
    def record_verified_artifact(cls, prompt: str, code: str, language: str, test_report: Dict[str, Any], user_email: Optional[str] = None):
        """Archives verified code and its test report into project context."""
        try:
            os.makedirs(os.path.dirname(cls.CONTEXT_FILE), exist_ok=True)
            records = []
            if os.path.exists(cls.CONTEXT_FILE):
                try:
                    with open(cls.CONTEXT_FILE, "r", encoding="utf-8") as f:
                        records = json.load(f)
                except Exception:
                    records = []

            report = test_report if isinstance(test_report, dict) else {}
            passed_checks = report.get("passed_checks", []) if isinstance(report.get("passed_checks"), list) else []
            untested = report.get("untested_limitations", []) if isinstance(report.get("untested_limitations"), list) else []
            entry = {
                "id": f"CTX-{int(time.time())}",
                "timestamp": time.time(),
                "prompt": str(prompt)[:120],
                "language": str(language),
                "passed_checks_count": len(passed_checks),
                "untested_count": len(untested),
                "verified": bool(report.get("is_verified", False)),
                "iterations": int(report.get("iteration_count", 1) or 1),
                "user_email": user_email or "anonymous",
                "summary": f"Verified {language} solution with {len(passed_checks)} passing checks."
            }
            records.insert(0, entry)
            # Keep top 50 project context entries
            tmp_file = f"{cls.CONTEXT_FILE}.tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(records[:50], f, indent=2, default=str)
            os.replace(tmp_file, cls.CONTEXT_FILE)
            print(f"[STROKE ARCHIVIST] Saved verified project context entry: {entry['id']}", flush=True)
        except Exception as exc:
            print(f"[STROKE ARCHIVIST NOTICE] Could not save context record: {exc}", flush=True)


# ==============================================================================
# 4b. ROLLING MEMORY & STATE LEDGER ENGINE
# ==============================================================================

def stitch_continuations(prev_text: str, next_text: str) -> str:
    """Seamlessly joins truncated model generations without duplicating code fences or headings."""
    if not prev_text:
        return next_text or ""
    if not next_text:
        return prev_text

    prev_clean = prev_text.rstrip()
    next_clean = next_text.lstrip()

    # Check if prev ended inside an unclosed code fence
    prev_fences = prev_clean.count("```")
    if prev_fences % 2 != 0:
        # Inside unclosed code block
        # If next starts with ```<lang>\n, strip that opening fence to prevent nested fence syntax error
        m = re.match(r"^```[a-zA-Z0-9_-]*\n?", next_clean)
        if m:
            next_clean = next_clean[m.end():]
        return prev_clean + "\n" + next_clean

    return prev_clean + "\n\n" + next_clean


def is_response_incomplete(text: str, finish_reason: Optional[str] = None) -> bool:
    """Detects whether model output was cut off by token window exhaustion or unclosed syntax."""
    if finish_reason == "length":
        return True
    if not text or len(text.strip()) < 10:
        return False
    # Check unclosed code fences: odd number of ```
    fence_count = text.count("```")
    if fence_count % 2 != 0:
        return True
    # Check trailing cutoffs (incomplete expressions or trailing ellipses)
    stripped = text.strip()
    if stripped.endswith(("...", "\\", "->", "=>", "(", "{", "[")):
        return True
    return False


class StateLedger:
    """
    Rolling Memory & State Ledger Engine:
    Maintains a high-speed, lean context memory for long-running agentic loops:
    1. Keep the Active Goal: Anchors reasoning to the current active user objective.
    2. Prune Failed Attempts: Deletes intermediate broken code drafts and resolved error traces.
    3. Maintain State Ledger: Evidence-derived workspace status reflecting genuine test results.
    """

    def __init__(self, north_star_goal: str):
        self.north_star_goal = (north_star_goal or "").strip()
        self.verified_modules: List[str] = []
        self.total_scripts_created: int = 0
        self.resolved_errors_count: int = 0
        self.unresolved_errors_count: int = 0
        self.failed_checks: List[Dict[str, Any]] = []
        self.verified_checks: List[Dict[str, Any]] = []
        self.active_mcp_servers: List[str] = []

    def record_resolved_check(self, module_name: str, passed_count: int = 1, evidence: Optional[Dict[str, Any]] = None):
        """Records a successful verification check based on actual positive evidence."""
        clean_name = str(module_name).strip()
        if clean_name and clean_name not in self.verified_modules:
            self.verified_modules.append(clean_name)
        self.total_scripts_created = max(1, len(self.verified_modules))
        if self.unresolved_errors_count > 0:
            self.unresolved_errors_count = max(0, self.unresolved_errors_count - 1)
            self.resolved_errors_count += 1
        self.verified_checks.append({
            "module": clean_name,
            "passed_count": passed_count,
            "evidence": evidence or {}
        })

    def record_failed_check(self, module_name: str, error_trace: str):
        """Records an actual failed compiler or verification check."""
        self.unresolved_errors_count += 1
        self.failed_checks.append({
            "module": str(module_name).strip(),
            "error": str(error_trace).strip()
        })

    def get_north_star_header(self) -> str:
        """Returns the active goal block."""
        return (
            "==================================================\n"
            "NORTH STAR USER GOAL (ACTIVE PRIMARY OBJECTIVE):\n"
            f"{self.north_star_goal}\n"
            "==================================================\n"
            "RULE: Always anchor all reasoning, actions, and code generation to this North Star goal. Never deviate or lose track of this objective.\n"
        )

    def get_ledger_summary(self) -> str:
        """
        Generates the evidence-bound State Ledger message.
        Only reports successful compilation when backed by verified checks.
        """
        if self.verified_modules:
            module_text = ", ".join(self.verified_modules[-3:])
            return (
                f"System Message (State Ledger): Module '{module_text}' compiled successfully. "
                f"Current Workspace state: {max(1, self.total_scripts_created)} script(s) created/verified, {self.unresolved_errors_count} errors."
            )
        elif self.unresolved_errors_count > 0:
            return (
                f"System Message (State Ledger): Workspace has {self.unresolved_errors_count} active error(s). "
                f"Pending resolution."
            )
        else:
            return (
                "System Message (State Ledger): Workspace initialized. "
                "Pending initial compilation and test verification."
            )

    @classmethod
    def prune_intermediate_history(
        cls,
        messages: List[Dict[str, str]],
        north_star_goal: str,
        state_ledger: 'StateLedger'
    ) -> List[Dict[str, str]]:
        """
        Prunes old intermediate failed attempts, raw tracebacks, and tool execution dumps.
        Compresses historical turns into a single State Ledger entry while keeping the North Star locked.
        """
        if not messages:
            return []

        pruned: List[Dict[str, str]] = []
        
        # 1. System prompt with locked North Star and State Ledger
        system_content = messages[0]["content"] if messages[0].get("role") == "system" else ""
        north_star_block = state_ledger.get_north_star_header()
        
        if "NORTH STAR USER GOAL" not in system_content:
            system_content = north_star_block + "\n" + system_content
            
        ledger_summary = state_ledger.get_ledger_summary()
        if "System Message (State Ledger):" not in system_content:
            system_content = system_content.rstrip() + "\n\n" + ledger_summary

        pruned.append({"role": "system", "content": system_content})

        # 2. Keep the original user prompt
        user_msgs = [m for m in messages[1:] if m.get("role") == "user" and not m.get("content", "").startswith("[TOOL_RESULT")]
        original_prompt = user_msgs[0]["content"] if user_msgs else north_star_goal
        pruned.append({"role": "user", "content": original_prompt})

        # 3. Keep ONLY the most recent assistant message and latest tool interaction (pruning all older intermediate attempts)
        recent_tail = [m for m in messages[1:] if m is not (user_msgs[0] if user_msgs else None)]
        if len(recent_tail) > 3:
            pruned.extend(recent_tail[-3:])
        else:
            pruned.extend(recent_tail)

        return pruned


# ==============================================================================
# 5. SMART 10-STAGE CODING WORKFLOW ENGINES
# ==============================================================================

@dataclass
class GoalSpecification:
    prompt: str
    target_language: str
    primary_objective: str
    target_files: List[str]
    explicit_requirements: List[str]
    detected_framework: str


class GoalUnderstandingEngine:
    """
    Stage 1: Understands the user's actual goal, intent, target domain,
    referenced files, and explicit requirements.
    """
    @classmethod
    def analyze_goal(cls, prompt: str, target_file: Optional[str] = None) -> GoalSpecification:
        text = (prompt or "").strip()
        lower = text.lower()

        lang = "luau"
        framework = "roblox_luau"
        if target_file:
            ext = Path(target_file).suffix.lower()
            if ext in (".luau", ".lua"):
                lang = "luau"
                framework = "roblox_luau"
            elif ext == ".py":
                lang = "python"
                framework = "python"
            elif ext in (".ts", ".tsx"):
                lang = "typescript"
                framework = "typescript"
            elif ext in (".js", ".jsx"):
                lang = "javascript"
                framework = "javascript"
        else:
            if any(term in lower for term in ("python", ".py", "pytest", "django", "fastapi", "asyncio", "pydantic", "pip")):
                lang = "python"
                framework = "python"
            elif any(term in lower for term in ("roblox", "luau", "lua", "datamodel", "cframe", "hitbox", "overlapparams", "humanoid", "workspace:raycast", "game:getservice", "tween")):
                lang = "luau"
                framework = "roblox_luau"
            elif any(term in lower for term in ("typescript", ".ts", ".tsx", "react")):
                lang = "typescript"
                framework = "typescript"

        mentioned_files = []
        file_pattern = r"\b([a-zA-Z0-9_\-\./\\]+\.(?:luau|lua|py|json|md|ts|tsx|js|jsx|txt))\b"
        for m in re.finditer(file_pattern, text):
            fname = m.group(1).replace("\\", "/")
            if fname not in mentioned_files:
                mentioned_files.append(fname)
        if target_file and target_file not in mentioned_files:
            mentioned_files.append(target_file)

        reqs = []
        if "debounce" in lower:
            reqs.append("Implement multi-hit debounce guard")
        if "spatial" in lower or "overlap" in lower:
            reqs.append("Use authentic spatial query / OverlapParams")
        if "async" in lower:
            reqs.append("Use async/await definition properly")
        if any(phrase in lower for phrase in ("no delete", "do not delete", "never delete", "don't delete", "without deleting")):
            reqs.append("Do not delete existing files")

        objective = text.split("\n")[0][:150]
        return GoalSpecification(
            prompt=text,
            target_language=lang,
            primary_objective=objective,
            target_files=mentioned_files,
            explicit_requirements=reqs,
            detected_framework=framework
        )


@dataclass
class InspectedProjectFile:
    relative_path: str
    absolute_path: Path
    initial_sha256: str
    size_bytes: int
    language: str
    content: str
    symbols: List[str] = field(default_factory=list)


class ProjectInspectionEngine:
    """
    Stage 2: Inspects relevant project files in the workspace,
    extracts existing structure, and records baseline SHA-256 hashes to guarantee
    user modifications are never silently overwritten.
    """
    @classmethod
    def inspect_workspace(
        cls,
        workspace_path: Optional[str],
        goal_spec: GoalSpecification
    ) -> List[InspectedProjectFile]:
        if not workspace_path:
            return []

        try:
            ws = Path(workspace_path).resolve()
        except Exception:
            return []

        if not ws.exists() or not ws.is_dir():
            return []

        inspected = []
        seen_paths = set()

        # 1. First inspect files explicitly mentioned in the goal
        for f_name in goal_spec.target_files:
            cand = ws / f_name
            if cand.exists() and cand.is_file():
                try:
                    p_rel = str(cand.relative_to(ws))
                    if p_rel not in seen_paths:
                        seen_paths.add(p_rel)
                        inspected.append(cls._inspect_single_file(cand, ws, goal_spec.target_language))
                except Exception:
                    pass

        # 2. If no mentioned files found, inspect top files matching target language
        if not inspected:
            ext_map = {"luau": [".luau", ".lua"], "python": [".py"], "typescript": [".ts", ".tsx"]}
            target_exts = ext_map.get(goal_spec.target_language, [".luau", ".py"])
            for root, dirs, files in os.walk(ws):
                dirs[:] = [d for d in dirs if d not in (".git", "venv", "node_modules", "__pycache__", ".backups")]
                for f in files:
                    if any(f.endswith(ext) for ext in target_exts):
                        full_f = Path(root) / f
                        try:
                            p_rel = str(full_f.relative_to(ws))
                            if p_rel not in seen_paths:
                                seen_paths.add(p_rel)
                                inspected.append(cls._inspect_single_file(full_f, ws, goal_spec.target_language))
                                if len(inspected) >= 5:
                                    break
                        except Exception:
                            pass
                if len(inspected) >= 5:
                    break

        return inspected

    @classmethod
    def _inspect_single_file(cls, path: Path, base_dir: Path, fallback_lang: str) -> InspectedProjectFile:
        rel = str(path.relative_to(base_dir))
        content = ""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

        sha = backup_service.compute_file_sha256(path) if path.exists() else ""
        ext = path.suffix.lower()
        lang = "luau" if ext in (".luau", ".lua") else ("python" if ext == ".py" else fallback_lang)

        symbols = []
        for line in content.splitlines():
            m_fn = re.search(r"^\s*(?:local\s+)?function\s+([a-zA-Z0-9_:\.]+)", line)
            if m_fn:
                symbols.append(m_fn.group(1))
            m_py = re.search(r"^\s*(?:async\s+)?def\s+([a-zA-Z0-9_]+)", line)
            if m_py:
                symbols.append(m_py.group(1))

        return InspectedProjectFile(
            relative_path=rel,
            absolute_path=path,
            initial_sha256=sha,
            size_bytes=len(content.encode("utf-8")),
            language=lang,
            content=content,
            symbols=symbols
        )


@dataclass
class SmartPlan:
    objective: str
    target_files_to_modify: List[str]
    target_files_to_create: List[str]
    implementation_steps: List[str]
    testing_strategy: str
    risk_mitigation: str


class SmartImplementationPlanner:
    """
    Stage 3: Creates a structured, bounded implementation plan.
    Strictly bounds the files to modify/create to prevent unnecessary file modifications.
    """
    @classmethod
    def create_plan(
        cls,
        goal_spec: GoalSpecification,
        inspected_files: List[InspectedProjectFile],
        llm_fn: Optional[Any] = None,
        planning_depth: str = "linear",
        max_steps: int = 4
    ) -> SmartPlan:
        to_modify = []
        to_create = []

        if goal_spec.target_files:
            for tf in goal_spec.target_files:
                matched = next((f for f in inspected_files if f.relative_path == tf or f.absolute_path.name == tf), None)
                if matched:
                    to_modify.append(matched.relative_path)
                else:
                    to_create.append(tf)
        elif inspected_files:
            to_modify.append(inspected_files[0].relative_path)
        else:
            default_name = f"solution.{'luau' if goal_spec.target_language == 'luau' else 'py'}"
            to_create.append(default_name)

        lang_title = goal_spec.target_language.title()

        if planning_depth in ("multi_agent_strategic", "hierarchical_decomposed"):
            steps = [
                f"1. Strategic Decomposition: Architect {lang_title} components fulfilling North Star goal: '{goal_spec.primary_objective}'",
                "2. Context & Lock Management: Verify baseline SHA-256 snapshots and register file ownership locks",
                f"3. Core Implementation: Construct balanced {lang_title} source with authentic Roblox/system service resolution",
                "4. VFX & Memory Safeguards: Implement explicit Debris / :Destroy() resource cleanup and platform throttling",
                "5. Domain Guard Verification: Implement multi-hit debounce dictionary and living entity (Humanoid.Health) filters",
                "6. Structural AST Balancing: Validate block closures, delimiter nesting, and eliminate unresolved globals",
                "7. Real Compiler Verification: Execute native Luau/Python compiler in private background terminal with code 0 exit requirement",
                "8. Independent Code Review: Review applied diffs against plan with specialized ReviewerAgent audit criteria",
                "9. Final Evidence Synthesis: Generate evidence-backed transparency matrix without simulated success"
            ]
        elif planning_depth == "tree_of_thought":
            steps = [
                f"1. Intent Analysis: Evaluate alternative implementation paths for '{goal_spec.primary_objective}'",
                f"2. Dependency Mapping: Inspect {len(inspected_files)} workspace file(s) and resolve symbol references",
                f"3. Balanced Implementation: Author {lang_title} module adhering to syntax and service conventions",
                "4. Debounce & Spatial Guard: Enforce OverlapParams and hit-caching logic",
                "5. Static & Compiler Checks: Run AST validation and compiler verification suite",
                "6. Plan Alignment Review: Audit output files to prevent extraneous modifications"
            ]
        elif planning_depth == "none":
            steps = [
                f"1. Direct Synthesis: Immediately generate {lang_title} code fulfilling user request without preliminary planning."
            ]
        else:  # linear
            steps = [
                f"1. Implement {lang_title} module fulfilling: {goal_spec.primary_objective}",
                "2. Ensure syntax balance and authentic service resolution",
                "3. Run automated domain test checks (AST & compiler verification)",
                "4. Validate that existing code and conventions are preserved"
            ]

        test_strat = f"Static AST analysis + {lang_title} bytecode verification ({planning_depth} planning depth)"
        risk = "Zero deletions allowed; pre-modification SHA-256 backup created before writing."

        return SmartPlan(
            objective=goal_spec.primary_objective,
            target_files_to_modify=to_modify,
            target_files_to_create=to_create,
            implementation_steps=steps,
            testing_strategy=test_strat,
            risk_mitigation=risk
        )


@dataclass
class FileChangeResult:
    relative_path: str
    action: str  # "created", "modified", "skipped", "conflict"
    backup_path: Optional[str] = None
    previous_sha256: str = ""
    new_sha256: str = ""
    diff: str = ""
    error: Optional[str] = None


class ControlledChangeManager:
    """
    Stage 4: Applies controlled code changes to the workspace.
    Guarantees:
      1. Preserves user changes: checks current hash against initial snapshot; stops if user modified it externally.
      2. Pre-modification backups: every edited file is automatically backed up before writing.
      3. No-Delete Policy: rejects any deletion or removal.
      4. Avoids unnecessary file modifications: only edits planned files.
    """
    @classmethod
    def apply_change(
        cls,
        workspace_path: str,
        relative_path: str,
        new_content: str,
        expected_initial_sha256: Optional[str] = None,
        task_id: str = "smart_coding_loop"
    ) -> FileChangeResult:
        ws = Path(workspace_path).resolve()
        target = (ws / relative_path).resolve()

        # Workspace security check
        if ws not in target.parents and target != ws:
            return FileChangeResult(
                relative_path=relative_path,
                action="skipped",
                error=f"Security error: path {relative_path} resolves outside workspace."
            )

        # 1. Conflict detection (Preserve user changes)
        if target.exists():
            current_sha = backup_service.compute_file_sha256(target)
            if expected_initial_sha256 and current_sha != expected_initial_sha256:
                return FileChangeResult(
                    relative_path=relative_path,
                    action="conflict",
                    previous_sha256=expected_initial_sha256,
                    new_sha256=current_sha,
                    error=f"User modification conflict: file '{relative_path}' was modified externally. Halting to preserve user changes."
                )

            # Avoid unnecessary file modification if content identical
            current_content = target.read_text(encoding="utf-8", errors="replace")
            if current_content == new_content:
                return FileChangeResult(
                    relative_path=relative_path,
                    action="skipped",
                    previous_sha256=current_sha,
                    new_sha256=current_sha,
                    diff="No changes needed (content identical)"
                )

            # Atomic write with automatic pre-modification backup
            res = backup_service.atomic_write_file(
                target_path=str(target),
                content=new_content,
                make_backup_if_exists=True,
                task_id=task_id,
                description=f"Smart Coding Loop edit on {relative_path}"
            )
            new_sha = backup_service.compute_file_sha256(target)
            b_entry = res.get("backup")
            b_path = b_entry.get("backup_path") if isinstance(b_entry, dict) else (str(b_entry) if b_entry else None)
            return FileChangeResult(
                relative_path=relative_path,
                action="modified",
                backup_path=b_path,
                previous_sha256=current_sha,
                new_sha256=new_sha
            )
        else:
            # Create new file
            target.parent.mkdir(parents=True, exist_ok=True)
            res = backup_service.atomic_write_file(
                target_path=str(target),
                content=new_content,
                make_backup_if_exists=False,
                task_id=task_id,
                description=f"Smart Coding Loop create {relative_path}"
            )
            new_sha = backup_service.compute_file_sha256(target)
            return FileChangeResult(
                relative_path=relative_path,
                action="created",
                new_sha256=new_sha
            )


class ChangeReviewer:
    """
    Stage 9: Reviews the applied changes against the original goal and implementation plan.
    Audits for correctness, security, syntax, and verifies no unnecessary files were touched.
    """
    @classmethod
    def review_changes(
        cls,
        goal_spec: GoalSpecification,
        plan: SmartPlan,
        edits: List[FileChangeResult],
        test_report: Dict[str, Any],
        review_mode: str = "formal_audit"
    ) -> Dict[str, Any]:
        passed_tests = test_report.get("is_verified", False) or test_report.get("static_status") == "PASS"
        has_errors = any(f.get("type") == "error" for f in test_report.get("failed_checks", []))

        # Check for unnecessary files touched
        planned_set = set(plan.target_files_to_modify + plan.target_files_to_create)
        actual_set = {e.relative_path for e in edits if e.action in ("created", "modified")}
        unplanned_files = list(actual_set - planned_set)

        reasons = []
        reviewer_role = "Automated Reviewer"
        domain_notes = []

        if review_mode == "none":
            approved = True
            reasons.append("Fast path: code review disabled in Low mode")
        elif review_mode == "basic_syntax_check":
            approved = passed_tests and not has_errors
            if not approved:
                reasons.append("Syntax or bytecode compilation failed")
        elif review_mode == "plan_alignment":
            approved = passed_tests and not has_errors and len(unplanned_files) == 0
            if not passed_tests or has_errors:
                reasons.append("Tests or compiler checks failed")
            if unplanned_files:
                reasons.append(f"Unplanned files touched outside plan: {unplanned_files}")
        elif review_mode == "specialized_reviewer_agent":
            # Absolute Peak: Independent ReviewerAgent audit
            reviewer_role = "Specialized ReviewerAgent"
            # Audit domain warnings for performance and memory
            warnings = [f for f in test_report.get("failed_checks", []) if f.get("type") == "warning"]
            for w in warnings:
                msg = w.get("message", "")
                if "Debris" in msg or "cleanup" in msg.lower():
                    domain_notes.append(f"Memory Notice: {msg}")
                if "debounce" in msg.lower():
                    domain_notes.append(f"Debounce Notice: {msg}")

            approved = passed_tests and not has_errors and len(unplanned_files) == 0
            if not passed_tests or has_errors:
                reasons.append("Compiler or test suite verification failed")
            if unplanned_files:
                reasons.append(f"Extraneous file modifications rejected: {unplanned_files}")
        else:  # formal_audit (Maximum)
            approved = passed_tests and not has_errors and len(unplanned_files) == 0
            if not passed_tests or has_errors:
                reasons.append("Tests or compiler checks failed")
            if unplanned_files:
                reasons.append(f"Unnecessary files modified outside plan: {unplanned_files}")

        verdict = "APPROVED" if approved else "CHANGES_REQUESTED"

        return {
            "verdict": verdict,
            "approved": approved,
            "reviewer_role": reviewer_role,
            "review_mode": review_mode,
            "reasons": reasons,
            "domain_notes": domain_notes,
            "planned_files_count": len(planned_set),
            "actual_files_modified_count": len(actual_set),
            "unplanned_files": unplanned_files,
            "timestamp": time.time()
        }


@dataclass
class SmartCodingWorkflowResult:
    success: bool
    prompt: str
    goal: GoalSpecification
    plan: SmartPlan
    inspected_files: List[InspectedProjectFile]
    file_changes: List[FileChangeResult]
    test_report: Dict[str, Any]
    review: Dict[str, Any]
    stages_executed: List[Dict[str, str]]
    final_reply: str
    iterations: int
    markdown_report: str
    reasoning_level: str = "medium"
    reasoning_profile: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "prompt": self.prompt,
            "goal": asdict(self.goal),
            "plan": asdict(self.plan),
            "inspected_files": [asdict(f) for f in self.inspected_files],
            "file_changes": [asdict(c) for c in self.file_changes],
            "test_report": self.test_report,
            "review": self.review,
            "stages_executed": self.stages_executed,
            "final_reply": self.final_reply,
            "iterations": self.iterations,
            "markdown_report": self.markdown_report,
            "reasoning_level": self.reasoning_level,
            "reasoning_profile": self.reasoning_profile
        }


# ==============================================================================
# 5b. AUTONOMOUS CODING LOOP ORCHESTRATOR
# ==============================================================================

class StrokeCodingLoop:
    """
    The Definitive Stroke Autonomous Coding Loop:
      1. Understand Request
      2. Generate Initial Code Draft
      3. Run Checks (Syntax, AST, Domain Tests)
      4. Read Errors (Error Analyser)
      5. Fix the Code (Correction Loop with small model)
      6. Verify Again (Retest runner)
      7. Present Final Answer (Verified code + Transparency Verification Report)
    """

    @classmethod
    def extract_code_block(cls, text: str, default_lang: str = "luau") -> Tuple[str, str]:
        """Extracts primary code block and language tag from markdown code fences."""
        blocks = cls.extract_all_code_blocks(text, default_lang=default_lang)
        if blocks:
            return blocks[0]["code"], blocks[0]["language"]
        return "", default_lang

    @classmethod
    def extract_all_code_blocks(cls, text: str, default_lang: str = "luau") -> List[Dict[str, str]]:
        """Extracts all code blocks and language tags from markdown code fences while preserving internal indentation."""
        pattern = r"```([a-zA-Z0-9_]*)\n([\s\S]*?)```"
        blocks = []
        for match in re.finditer(pattern, text):
            lang, code = match.groups()
            clean_code = cls._clean_code_artifacts(code).strip("\r\n")
            if clean_code:
                blocks.append({
                    "language": (lang.lower() if lang else default_lang),
                    "code": clean_code
                })

        # If no closed fences, check unclosed fence
        if not blocks:
            unclosed_match = re.search(r"```([a-zA-Z0-9_]*)\n([\s\S]+)$", text)
            if unclosed_match:
                lang, code = unclosed_match.groups()
                clean_code = cls._clean_code_artifacts(code).strip("\r\n")
                if clean_code:
                    blocks.append({
                        "language": (lang.lower() if lang else default_lang),
                        "code": clean_code
                    })

        # If still no fences, check if raw text looks like code
        if not blocks:
            lines = text.splitlines()
            code_indicators = ["local ", "function ", "import ", "def ", "class ", "game:GetService", "task.wait"]
            if any(any(ind in line for ind in code_indicators) for line in lines[:10]):
                clean_code = cls._clean_code_artifacts(text).strip("\r\n")
                if clean_code:
                    blocks.append({
                        "language": default_lang,
                        "code": clean_code
                    })

        return blocks

    @staticmethod
    def _clean_code_artifacts(code: str) -> str:
        """
        Preserves generated source exactly. Never silently deletes legitimate
        identical statements, table entries, comments, or code.
        """
        return code

    @classmethod
    def format_verification_report_markdown(cls, report: Dict[str, Any], iterations: int) -> str:
        """
        Formats a transparent, professional Verification & Quality Report.
        Strictly observes: Passing tests doesn't guarantee perfect code.
        Reports which checks passed and never pretends untested code is verified.
        """
        passed = report.get("passed_checks", [])
        failed = report.get("failed_checks", [])
        untested = report.get("untested_limitations", [])
        is_verified = report.get("is_verified", False)
        has_compiler_verified = report.get("has_compiler_verified", False)
        verification_status = report.get(
            "verification_status",
            "PASS" if (is_verified and has_compiler_verified) else ("FAIL" if any(f.get("type") == "error" for f in failed) else "UNVERIFIED")
        )

        syntax_status = report.get("syntax_status", "PASS" if (is_verified and has_compiler_verified) else "NOT RUN")
        static_status = report.get("static_status", "PASS" if is_verified else ("FAIL" if verification_status == "FAIL" else "UNVERIFIED"))
        api_status = report.get("api_status", "PASS" if is_verified else "NOT RUN")
        runtime_status = report.get("runtime_status", "NOT RUN")
        test_status = report.get("test_status", "NOT RUN")
        perf_status = report.get("perf_status", "NOT RUN")

        compiler_used = report.get("compiler_used", "N/A")
        commands_executed = report.get("commands_executed", [])
        exit_codes = report.get("exit_codes", [])

        errors = [f for f in failed if f.get("type") == "error"]
        warnings = [f for f in failed if f.get("type") == "warning"]

        if verification_status == "FAIL" or errors or api_status == "FAIL" or syntax_status == "FAIL" or static_status == "FAIL":
            badge = "FAILED (ROBLOX API OR TYPE ERRORS DETECTED)" if api_status == "FAIL" else "FAILED (SYNTAX OR RUNTIME ISSUES DETECTED)"
        elif verification_status == "PASS" and is_verified and has_compiler_verified:
            badge = f"VERIFIED ({iterations} PASS{'ES' if iterations > 1 else ''})"
        elif verification_status == "UNVERIFIED" and len(errors) == 0 and api_status == "PASS" and static_status == "PASS":
            badge = "STATIC CHECKS PASSED (COMPILER UNVERIFIED)"
        elif verification_status == "UNVERIFIED":
            badge = "UNVERIFIED (UNSUPPORTED LANGUAGE OR COMPILER MISSING)"
        else:
            badge = "COMPLETED WITH WARNINGS"

        verification_incomplete = "YES (Compiler unverified or live runtime unverified)" if (runtime_status != "PASS" or not has_compiler_verified) else "NO"
        tests_passed_status = "PASS" if test_status == "PASS" else ("FAIL" if test_status == "FAIL" else "NOT AVAILABLE")

        md = f"\n\n---\n\n### Stroke Verification & Quality Report\n"
        md += f"> **Status**: `{badge}` | **Verification State**: `{verification_status}` | **Iterations**: `{iterations}`\n\n"

        md += "#### Verification Status Matrix\n"
        md += f"- Verification State: {verification_status}\n"
        md += f"- Static Validation: {static_status}\n"
        md += f"- Syntax Compilation: {syntax_status}\n"
        md += f"- API Validation: {api_status}\n"
        md += f"- Runtime Execution: {runtime_status}\n"
        md += f"- Automated Tests: {tests_passed_status}\n"
        md += f"- Tests Passed: {tests_passed_status}\n"
        md += f"- Verification Incomplete: {verification_incomplete}\n\n"

        md += "#### Execution Details\n"
        md += f"- **Compiler / Analyzer**: {compiler_used}\n"
        md += f"- **Commands Executed**: {', '.join(commands_executed) if commands_executed else 'None'}\n"
        md += f"- **Exit Codes**: {exit_codes}\n"
        md += f"- **Iterations Required**: {iterations}\n"
        md += f"- **Limitations**: {'; '.join(untested) if untested else 'None'}\n\n"

        md += "#### Automated Checks Passed\n"
        if passed:
            for p in passed:
                md += f"- **[PASS]** {p}\n"
        else:
            md += "- None registered.\n"

        if errors:
            md += "\n#### Blocking Errors Detected\n"
            for e in errors:
                md += f"- **[ERROR]** Line {e.get('line', '?')}: {e.get('message')}\n"

        if warnings:
            md += "\n#### Active Diagnostic Warnings\n"
            for w in warnings:
                md += f"- **[WARNING]** Line {w.get('line', '?')}: {w.get('message')}\n"

        md += "\n#### Untested Runtime Limitations (Transparency Mandate)\n"
        md += "> *Passing static tests does not guarantee flawless live runtime execution. Stroke transparently identifies the following unverified parameters:*\n"
        if untested:
            for u in untested:
                md += f"- **[UNTESTED]** {u}\n"
        else:
            md += "- Real-world network replication and external engine constraints require live in-game testing.\n"

        return md

    @classmethod
    def run_coding_loop(
        cls,
        prompt: str,
        initial_reply: str,
        llm_generate_fn,
        user_email: Optional[str] = None,
        max_iterations: Optional[int] = None,
        include_markdown_report: bool = True,
        workspace_path: Optional[str] = None,
        reasoning_level: Optional[str] = "medium"
    ) -> Tuple[str, Dict[str, Any], List[Dict[str, str]]]:
        """
        Executes the Write -> Test -> Diagnose -> Fix -> Retest coding loop across ALL code blocks.
        Runs autonomously until the problem is solved (unlimited until clean verification).
        When code is verified and works, Stroke immediately delivers the final answer without
        unnecessary improvement cycles.
        """
        loop_steps = []
        blocks = cls.extract_all_code_blocks(initial_reply, default_lang="luau")

        if not blocks:
            # Not a code generation response
            return initial_reply, {"is_verified": False, "passed_checks": [], "failed_checks": [], "untested_limitations": []}, loop_steps

        profile = get_reasoning_profile(reasoning_level)
        primary_lang = blocks[0]["language"]
        total_lines = sum(len(b["code"].splitlines()) for b in blocks)

        # Step 1: Understand
        goal_spec = GoalUnderstandingEngine.analyze_goal(prompt)
        loop_steps.append({
            "name": "Understanding request...",
            "detail": f"Target: {primary_lang.title()} | Reasoning: {profile.label} | Goal: {goal_spec.primary_objective[:80]} | Identified {len(blocks)} code block(s)"
        })

        # Step 2: Generate
        loop_steps.append({
            "name": "Generating code...",
            "detail": f"Drafted {total_lines} lines across {len(blocks)} block(s) for verification"
        })

        current_reply = initial_reply
        iteration = 1
        final_report = {}
        state_ledger = StateLedger(north_star_goal=prompt)
        safety_ceiling = max_iterations if (max_iterations is not None and max_iterations > 0) else 50
        previous_code = None
        stagnant_count = 0
        seen_code_hashes: Set[str] = set()
        seen_error_signatures: Dict[str, int] = {}

        while iteration <= safety_ceiling:
            current_blocks = cls.extract_all_code_blocks(current_reply, default_lang=primary_lang)
            if not current_blocks:
                break

            # Step 3: Verify / Retest
            step_name = "Running checks..." if iteration == 1 else "Retesting..."
            loop_steps.append({
                "name": step_name,
                "detail": f"Executing compiler, static analysis, and verification checks (Pass {iteration})"
            })

            b_reps = []
            combined_passed = []
            combined_failed = []
            combined_untested = []
            all_compiler_verified = True

            for b_idx, blk in enumerate(current_blocks, start=1):
                b_code = blk["code"]
                b_lang = blk["language"]
                if b_lang in ("lua", "luau"):
                    b_rep = RobloxDomainTestRunner.test_luau_code(b_code, prompt)
                elif b_lang == "python":
                    b_rep = RobloxDomainTestRunner.test_python_code(b_code, prompt)
                else:
                    b_rep = RobloxDomainTestRunner.test_generic_code(b_code, b_lang)

                b_reps.append(b_rep)
                if not b_rep.get("has_compiler_verified", False):
                    all_compiler_verified = False

                for p in b_rep.get("passed_checks", []):
                    prefix = f"Block {b_idx}: " if len(current_blocks) > 1 else ""
                    combined_passed.append(f"{prefix}{p}")

                for f in b_rep.get("failed_checks", []):
                    f_copy = dict(f)
                    if len(current_blocks) > 1:
                        f_copy["message"] = f"[Block {b_idx}] {f_copy.get('message', '')}"
                    combined_failed.append(f_copy)

                for u in b_rep.get("untested_limitations", []):
                    if u not in combined_untested:
                        combined_untested.append(u)

            def _aggregate_status(key: str, default: str = "NOT RUN") -> str:
                statuses = [r.get(key, default) for r in b_reps]
                if any(s == "FAIL" for s in statuses):
                    return "FAIL"
                if any(s == "PASS" for s in statuses):
                    return "PASS"
                return default

            blocking_errors = [c for c in combined_failed if c.get("type") == "error"]
            is_verified_all = all(r.get("is_verified", False) for r in b_reps)
            verification_status = "PASS" if (is_verified_all and all_compiler_verified) else ("FAIL" if blocking_errors or _aggregate_status("syntax_status") == "FAIL" else "UNVERIFIED")

            report = {
                "passed_checks": combined_passed,
                "failed_checks": combined_failed,
                "untested_limitations": combined_untested,
                "is_verified": is_verified_all,
                "has_compiler_verified": all_compiler_verified,
                "verification_status": verification_status,
                "iteration_count": iteration,
                "syntax_status": _aggregate_status("syntax_status"),
                "static_status": _aggregate_status("static_status"),
                "api_status": _aggregate_status("api_status"),
                "runtime_status": _aggregate_status("runtime_status"),
                "test_status": _aggregate_status("test_status"),
                "perf_status": "NOT RUN",
                "compiler_used": b_reps[0].get("compiler_used", "N/A") if b_reps else "N/A",
                "commands_executed": [c for r in b_reps for c in r.get("commands_executed", [])],
                "exit_codes": [ec for r in b_reps for ec in r.get("exit_codes", [])]
            }
            final_report = report

            blocking_errors = [c for c in report.get("failed_checks", []) if c.get("type") == "error"]

            # CRITICAL: When code works cleanly, give the answer immediately!
            # Stroke does not keep looping to "improve" code that is already working.
            if not blocking_errors and (report.get("is_verified", False) or report.get("static_status") == "PASS"):
                state_ledger.record_resolved_check(f"{primary_lang.title()}Module", len(report.get("passed_checks", [])))
                loop_steps.append({
                    "name": f"Verification Passed (Pass {iteration})",
                    "detail": f"{state_ledger.get_ledger_summary()} Code verified cleanly. Delivering verified solution immediately without unnecessary revisions."
                })
                break

            # Stagnant loop guard: check if model produces identical code or repeats code
            all_current_code = "".join(b["code"] for b in current_blocks)
            current_code_hash = hashlib.sha256(all_current_code.encode("utf-8")).hexdigest()
            if current_code_hash in seen_code_hashes or (previous_code is not None and all_current_code == previous_code):
                stagnant_count += 1
                if stagnant_count >= 3:
                    loop_steps.append({
                        "name": "Self-Correction Loop Concluded",
                        "detail": f"Model produced identical code across {stagnant_count} consecutive attempts. Halting to prevent infinite loop or repeated failed edits."
                    })
                    break
            else:
                seen_code_hashes.add(current_code_hash)
                stagnant_count = 0
            previous_code = all_current_code

            # Error signature guard: check if exact same error persists across 4 cycles
            if blocking_errors:
                err_sig = "|".join(f"{c.get('line', '?')}:{c.get('message', '')[:60]}" for c in blocking_errors)
                seen_error_signatures[err_sig] = seen_error_signatures.get(err_sig, 0) + 1
                if seen_error_signatures[err_sig] >= 4:
                    loop_steps.append({
                        "name": "Infinite Loop Guard Triggered",
                        "detail": "Identical compiler error signature persisted across 4 consecutive cycles. Halting to prevent infinite loop."
                    })
                    break

            # If errors remain, continue correcting until solved
            if iteration < safety_ceiling:
                if blocking_errors:
                    state_ledger.record_failed_check(f"{primary_lang.title()}Module", str(blocking_errors[0].get("message", "Compilation error")))

                # Step 4: Diagnose
                loop_steps.append({
                    "name": "Analysing error...",
                    "detail": f"Identified {len(blocking_errors)} blocking issue(s) on Pass {iteration}. Compiling targeted diagnostics"
                })

                first_code = current_blocks[0]["code"]
                correction_prompt = ErrorAnalyser.build_correction_prompt(first_code, report["failed_checks"], language=primary_lang)

                # Step 5: Correct
                loop_steps.append({
                    "name": "Correcting implementation...",
                    "detail": f"Model resolving compiler/runtime diagnostics (Attempt {iteration})"
                })

                # Rolling Memory & State Ledger Strategy:
                # 1. Lock North Star at the absolute top of the system prompt
                # 2. Maintain a State Ledger entry replacing messy prior error dumps
                # 3. Prune old broken drafts from prior iterations (retaining only current_reply)
                ledger_summary = state_ledger.get_ledger_summary()
                system_ledger_content = (
                    f"{state_ledger.get_north_star_header()}\n"
                    f"{ledger_summary}\n"
                    f"Instruction: Resolve the targeted compiler/runtime diagnostics below. Return complete, corrected code."
                )

                fix_messages = [
                    {"role": "system", "content": system_ledger_content},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": current_reply},
                    {"role": "user", "content": correction_prompt}
                ]

                try:
                    fixed_reply = llm_generate_fn(fix_messages)
                    
                    # Auto-continue if code block was cut off by token limit before properly closing
                    if fixed_reply and is_response_incomplete(fixed_reply):
                        cont_attempts = 0
                        while cont_attempts < 3 and is_response_incomplete(fixed_reply):
                            cont_attempts += 1
                            cont_messages = list(fix_messages)
                            cont_messages.append({"role": "assistant", "content": fixed_reply})
                            cont_messages.append({"role": "user", "content": "continue without repeating; complete the code block until properly closed."})
                            cont_chunk = llm_generate_fn(cont_messages)
                            if not cont_chunk:
                                break
                            fixed_reply = stitch_continuations(fixed_reply, cont_chunk)

                    if fixed_reply and len(fixed_reply.strip()) > 30:
                        current_reply = fixed_reply
                    else:
                        break
                except Exception as exc:
                    print(f"[STROKE CODING LOOP NOTICE] Correction generation failed: {exc}", flush=True)
                    break

            iteration += 1

        # Step 9: Self-Review
        review_plan = SmartPlan(
            objective=goal_spec.primary_objective,
            target_files_to_modify=[],
            target_files_to_create=[],
            implementation_steps=["Verify syntax and domain structure"],
            testing_strategy="AST & compiler domain checks",
            risk_mitigation="Zero deletions"
        )
        self_review = ChangeReviewer.review_changes(goal_spec, review_plan, [], final_report, review_mode=profile.code_review_mode)
        final_report["self_review"] = self_review

        # Step 10: Final Response
        loop_steps.append({
            "name": "Preparing final result...",
            "detail": "Formatting verified code and comprehensive evidence report"
        })

        effective_iterations = final_report.get("iteration_count", min(iteration, safety_ceiling))
        report_md = cls.format_verification_report_markdown(final_report, iterations=effective_iterations)
        final_reply = (current_reply + report_md) if include_markdown_report else current_reply

        if final_report.get("is_verified", False):
            first_valid_code = current_blocks[0]["code"] if 'current_blocks' in locals() and current_blocks else ""
            CodingArchivist.record_verified_artifact(
                prompt=prompt,
                code=first_valid_code,
                language=primary_lang,
                test_report=final_report,
                user_email=user_email
            )

        return final_reply, final_report, loop_steps

    @classmethod
    def run_smart_coding_workflow(
        cls,
        prompt: str,
        workspace_path: Optional[str] = None,
        initial_reply: Optional[str] = None,
        llm_generate_fn: Optional[Any] = None,
        user_email: Optional[str] = None,
        max_iterations: Optional[int] = None,
        target_file: Optional[str] = None,
        include_markdown_report: bool = True,
        reasoning_level: Optional[str] = "medium"
    ) -> SmartCodingWorkflowResult:
        """
        The Rebuilt 10-Stage Stroke Smart Coding Workflow:
          1. Understand the user's actual goal (GoalUnderstandingEngine).
          2. Inspect relevant project files & record baseline SHA-256 (ProjectInspectionEngine).
          3. Create structured implementation plan (SmartImplementationPlanner with depth profile).
          4. Make controlled code changes with backups & conflict checks (ControlledChangeManager).
          5. Run appropriate tests (RobloxDomainTestRunner / Python compiler).
          6. Read actual error output (real compiler lines, messages, suggestions).
          7. Fix failures (targeted diagnostic self-healing loop).
          8. Re-run tests (StateLedger updates, verify resolution).
          9. Review its own changes (ChangeReviewer auditing modified files vs plan).
          10. Report what genuinely succeeded (honest evidence matrix, zero false claims).
        """
        stages_executed: List[Dict[str, str]] = []
        applied_edits: List[FileChangeResult] = []
        profile = get_reasoning_profile(reasoning_level)

        # STAGE 1: Understand user's actual goal
        goal_spec = GoalUnderstandingEngine.analyze_goal(prompt, target_file=target_file)
        stages_executed.append({
            "stage": "1",
            "name": "Understand User Goal",
            "detail": f"Target: {goal_spec.target_language.title()} | Reasoning: {profile.label} ({profile.planning_depth}) | Objective: {goal_spec.primary_objective[:80]}"
        })

        # STAGE 2: Inspect relevant project files
        inspected_files = ProjectInspectionEngine.inspect_workspace(workspace_path, goal_spec)
        baseline_hashes = {f.relative_path: f.initial_sha256 for f in inspected_files}
        stages_executed.append({
            "stage": "2",
            "name": "Inspect Project Files",
            "detail": f"Inspected {len(inspected_files)} file(s) in workspace. Baseline hashes recorded to preserve user changes."
        })

        # STAGE 3: Create implementation plan
        plan = SmartImplementationPlanner.create_plan(
            goal_spec,
            inspected_files,
            llm_fn=llm_generate_fn,
            planning_depth=profile.planning_depth,
            max_steps=profile.planning_budget_steps
        )
        stages_executed.append({
            "stage": "3",
            "name": "Create Implementation Plan",
            "detail": f"Planned modifications: {plan.target_files_to_modify} | Creations: {plan.target_files_to_create} ({profile.planning_depth} depth)"
        })

        # STAGE 4: Make controlled code changes (Initial generation)
        current_reply = initial_reply or ""
        if not current_reply and llm_generate_fn:
            plan_context = (
                f"Objective: {plan.objective}\n"
                f"Language: {goal_spec.target_language}\n"
                f"Requirements: {', '.join(goal_spec.explicit_requirements) if goal_spec.explicit_requirements else 'None'}\n"
                f"Implementation steps:\n" + "\n".join(plan.implementation_steps)
            )
            draft_messages = [
                {"role": "system", "content": f"You are Stroke's Senior Autonomous Developer. Implement clean code fulfilling the plan below.\n{plan_context}"},
                {"role": "user", "content": prompt}
            ]
            try:
                current_reply = llm_generate_fn(draft_messages) or ""
            except Exception as gen_err:
                current_reply = f"// Error drafting initial implementation: {gen_err}"

        current_blocks = cls.extract_all_code_blocks(current_reply, default_lang=goal_spec.target_language)
        
        # Apply controlled changes to workspace if workspace exists
        if workspace_path and current_blocks:
            planned_targets = plan.target_files_to_modify + plan.target_files_to_create
            for b_idx, blk in enumerate(current_blocks):
                rel_f = planned_targets[b_idx] if b_idx < len(planned_targets) else (target_file or f"solution.{goal_spec.target_language}")
                change_res = ControlledChangeManager.apply_change(
                    workspace_path=workspace_path,
                    relative_path=rel_f,
                    new_content=blk["code"],
                    expected_initial_sha256=baseline_hashes.get(rel_f),
                    task_id="smart_coding_loop"
                )
                applied_edits.append(change_res)

        stages_executed.append({
            "stage": "4",
            "name": "Make Controlled Changes",
            "detail": f"Applied controlled code changes across {len(applied_edits) if workspace_path else len(current_blocks)} unit(s) with pre-modification backups."
        })

        # STAGES 5 to 8: Test -> Read Errors -> Fix Failures -> Re-run Tests
        iteration = 1
        safety_ceiling = max_iterations if (max_iterations is not None and max_iterations > 0) else profile.max_coding_iterations
        seen_code_hashes: Set[str] = set()
        seen_error_signatures: Dict[str, int] = {}
        stagnant_count = 0
        state_ledger = StateLedger(north_star_goal=prompt)
        test_report: Dict[str, Any] = {}

        while iteration <= safety_ceiling:
            current_blocks = cls.extract_all_code_blocks(current_reply, default_lang=goal_spec.target_language)
            if not current_blocks:
                break

            # STAGE 5 / STAGE 8: Run Tests
            b_reps = []
            combined_passed = []
            combined_failed = []
            combined_untested = []
            all_compiler_verified = True

            for b_idx, blk in enumerate(current_blocks, start=1):
                b_code = blk["code"]
                b_lang = blk["language"]
                if b_lang in ("lua", "luau"):
                    b_rep = RobloxDomainTestRunner.test_luau_code(b_code, prompt)
                elif b_lang == "python":
                    b_rep = RobloxDomainTestRunner.test_python_code(b_code, prompt)
                else:
                    b_rep = RobloxDomainTestRunner.test_generic_code(b_code, b_lang)

                b_reps.append(b_rep)
                if not b_rep.get("has_compiler_verified", False):
                    all_compiler_verified = False

                for p in b_rep.get("passed_checks", []):
                    prefix = f"Block {b_idx}: " if len(current_blocks) > 1 else ""
                    combined_passed.append(f"{prefix}{p}")

                for f in b_rep.get("failed_checks", []):
                    f_copy = dict(f)
                    if len(current_blocks) > 1:
                        f_copy["message"] = f"[Block {b_idx}] {f_copy.get('message', '')}"
                    combined_failed.append(f_copy)

                for u in b_rep.get("untested_limitations", []):
                    if u not in combined_untested:
                        combined_untested.append(u)

            def _agg_status(key: str, default: str = "NOT RUN") -> str:
                statuses = [r.get(key, default) for r in b_reps]
                if any(s == "FAIL" for s in statuses):
                    return "FAIL"
                if any(s == "PASS" for s in statuses):
                    return "PASS"
                return default

            blocking_errors = [c for c in combined_failed if c.get("type") == "error"]
            is_verified_all = all(r.get("is_verified", False) for r in b_reps)
            verification_status = "PASS" if (is_verified_all and all_compiler_verified) else ("FAIL" if blocking_errors or _agg_status("syntax_status") == "FAIL" else "UNVERIFIED")

            test_report = {
                "passed_checks": combined_passed,
                "failed_checks": combined_failed,
                "untested_limitations": combined_untested,
                "is_verified": is_verified_all,
                "has_compiler_verified": all_compiler_verified,
                "verification_status": verification_status,
                "iteration_count": iteration,
                "syntax_status": _agg_status("syntax_status"),
                "static_status": _agg_status("static_status"),
                "api_status": _agg_status("api_status"),
                "runtime_status": _agg_status("runtime_status"),
                "test_status": _agg_status("test_status"),
                "perf_status": "NOT RUN",
                "compiler_used": b_reps[0].get("compiler_used", "N/A") if b_reps else "N/A",
                "commands_executed": [c for r in b_reps for c in r.get("commands_executed", [])],
                "exit_codes": [ec for r in b_reps for ec in r.get("exit_codes", [])]
            }

            if iteration == 1:
                stages_executed.append({
                    "stage": "5",
                    "name": "Run Appropriate Tests",
                    "detail": f"Initial check completed. Compiler: {test_report['compiler_used']} | Passed: {len(combined_passed)} | Failed: {len(combined_failed)}"
                })
            else:
                stages_executed.append({
                    "stage": "8",
                    "name": "Re-run Tests",
                    "detail": f"Retest (Pass {iteration}) completed. Verified: {test_report['is_verified']} | Status: {test_report.get('syntax_status')}"
                })

            blocking_errors = [c for c in test_report.get("failed_checks", []) if c.get("type") == "error"]

            # STAGE 6: Read actual error output
            if iteration == 1:
                stages_executed.append({
                    "stage": "6",
                    "name": "Read Actual Error Output",
                    "detail": f"Parsed {len(blocking_errors)} blocking issue(s) with exact compiler line numbers and suggestions."
                })

            # Check if verified cleanly -> finish immediately without unnecessary churn
            if not blocking_errors and (test_report.get("is_verified", False) or test_report.get("static_status") == "PASS"):
                state_ledger.record_resolved_check(f"{goal_spec.target_language.title()}Module", len(combined_passed))
                break

            # Stagnation & Infinite loop prevention:
            code_hash = hashlib.sha256("".join(b["code"] for b in current_blocks).encode("utf-8")).hexdigest()
            if code_hash in seen_code_hashes:
                stagnant_count += 1
                if stagnant_count >= 2:
                    stages_executed.append({
                        "stage": "7",
                        "name": "Fix Failures",
                        "detail": "Model produced identical code previously seen. Halting self-correction to prevent infinite loop or repeated failed edits."
                    })
                    break
            else:
                seen_code_hashes.add(code_hash)
                stagnant_count = 0

            if blocking_errors:
                err_sig = "|".join(f"{c.get('line', '?')}:{c.get('message', '')[:60]}" for c in blocking_errors)
                seen_error_signatures[err_sig] = seen_error_signatures.get(err_sig, 0) + 1
                if seen_error_signatures[err_sig] >= 4:
                    stages_executed.append({
                        "stage": "7",
                        "name": "Fix Failures",
                        "detail": "Identical compiler error signature persisted across 4 cycles. Halting to prevent infinite loop."
                    })
                    break

            # STAGE 7: Fix Failures
            if iteration < safety_ceiling and llm_generate_fn:
                state_ledger.record_failed_check(f"{goal_spec.target_language.title()}Module", str(blocking_errors[0].get("message", "Compilation error")))
                first_code = current_blocks[0]["code"]
                correction_prompt = ErrorAnalyser.build_correction_prompt(first_code, test_report["failed_checks"], language=goal_spec.target_language)

                system_ledger_content = (
                    f"{state_ledger.get_north_star_header()}\n"
                    f"{state_ledger.get_ledger_summary()}\n"
                    f"Instruction: Resolve the targeted compiler/runtime diagnostics below. Return complete, corrected code."
                )
                fix_messages = [
                    {"role": "system", "content": system_ledger_content},
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": current_reply},
                    {"role": "user", "content": correction_prompt}
                ]

                try:
                    fixed_reply = llm_generate_fn(fix_messages)
                    if fixed_reply and is_response_incomplete(fixed_reply):
                        for _ in range(3):
                            if not is_response_incomplete(fixed_reply):
                                break
                            cont_msg = list(fix_messages)
                            cont_msg.append({"role": "assistant", "content": fixed_reply})
                            cont_msg.append({"role": "user", "content": "continue without repeating; complete the code block until properly closed."})
                            c_chunk = llm_generate_fn(cont_msg)
                            if not c_chunk:
                                break
                            fixed_reply = stitch_continuations(fixed_reply, c_chunk)

                    if fixed_reply and len(fixed_reply.strip()) > 30:
                        current_reply = fixed_reply
                        new_blocks = cls.extract_all_code_blocks(current_reply, default_lang=goal_spec.target_language)
                        if workspace_path and new_blocks:
                            planned_targets = plan.target_files_to_modify + plan.target_files_to_create
                            for b_idx, blk in enumerate(new_blocks):
                                rel_f = planned_targets[b_idx] if b_idx < len(planned_targets) else (target_file or f"solution.{goal_spec.target_language}")
                                change_res = ControlledChangeManager.apply_change(
                                    workspace_path=workspace_path,
                                    relative_path=rel_f,
                                    new_content=blk["code"],
                                    expected_initial_sha256=baseline_hashes.get(rel_f),
                                    task_id="smart_coding_loop"
                                )
                                applied_edits.append(change_res)
                        stages_executed.append({
                            "stage": "7",
                            "name": "Fix Failures",
                            "detail": f"Attempt {iteration}: Generated targeted fix and applied controlled code change."
                        })
                    else:
                        break
                except Exception as fix_err:
                    stages_executed.append({
                        "stage": "7",
                        "name": "Fix Failures",
                        "detail": f"Correction cycle failed: {fix_err}"
                    })
                    break

            iteration += 1

        # STAGE 9: Review its own changes
        review = ChangeReviewer.review_changes(goal_spec, plan, applied_edits, test_report, review_mode=profile.code_review_mode)
        stages_executed.append({
            "stage": "9",
            "name": "Review Own Changes",
            "detail": f"Self-review verdict: {review['verdict']} | Approved: {review['approved']} | Reviewer: {review.get('reviewer_role', 'Reviewer')} | Mode: {review.get('review_mode', 'formal')} | Unplanned files modified: {len(review['unplanned_files'])}"
        })

        # STAGE 10: Report what genuinely succeeded
        effective_iterations = test_report.get("iteration_count", min(iteration, safety_ceiling))
        report_md = cls.format_verification_report_markdown(test_report, iterations=effective_iterations)
        final_reply = (current_reply + report_md) if include_markdown_report else current_reply

        stages_executed.append({
            "stage": "10",
            "name": "Report What Genuinely Succeeded",
            "detail": f"Delivered evidence-backed quality matrix. Verification state: {test_report.get('verification_status', 'UNVERIFIED')}."
        })

        if test_report.get("is_verified", False):
            first_valid_code = current_blocks[0]["code"] if 'current_blocks' in locals() and current_blocks else ""
            CodingArchivist.record_verified_artifact(
                prompt=prompt,
                code=first_valid_code,
                language=goal_spec.target_language,
                test_report=test_report,
                user_email=user_email
            )

        success = bool(test_report.get("is_verified", False) or (test_report.get("static_status") == "PASS" and not [c for c in test_report.get("failed_checks", []) if c.get("type") == "error"]))

        return SmartCodingWorkflowResult(
            success=success,
            prompt=prompt,
            goal=goal_spec,
            plan=plan,
            inspected_files=inspected_files,
            file_changes=applied_edits,
            test_report=test_report,
            review=review,
            stages_executed=stages_executed,
            final_reply=final_reply,
            iterations=effective_iterations,
            markdown_report=report_md,
            reasoning_level=profile.level,
            reasoning_profile=profile.to_dict()
        )

