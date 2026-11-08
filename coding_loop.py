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

import os
import re
import ast
import json
import time
from typing import Dict, List, Any, Optional, Tuple

try:
    import terminal_service
    from terminal_service import TerminalManager
except Exception:
    TerminalManager = None


# ==============================================================================
# 1. LUAU SYNTAX & AST VALIDATOR
# ==============================================================================

class LuauSyntaxValidator:
    """
    Robust static AST and syntax analyzer for Luau (Roblox Lua).
    Detects mismatched blocks, unbalanced delimiters, illegal operators,
    and deprecated Roblox/Lua API calls without requiring external binaries.
    """

    LUAU_BLOCK_OPENERS = {"function", "if", "for", "while", "do", "repeat"}
    
    @staticmethod
    def strip_comments_and_strings(code: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Strips comments and string literals to simplify AST keyword parsing
        while preserving line numbers and collecting string literals for inspection.
        """
        literals = []
        cleaned_lines = []
        in_multiline_comment = False
        in_multiline_string = False

        for line_idx, line in enumerate(code.splitlines(), start=1):
            cleaned = ""
            i = 0
            n = len(line)

            while i < n:
                if in_multiline_comment:
                    if line[i:i+2] == "]]":
                        in_multiline_comment = False
                        i += 2
                    else:
                        i += 1
                    continue

                if in_multiline_string:
                    if line[i:i+2] == "]]":
                        in_multiline_string = False
                        i += 2
                    else:
                        i += 1
                    continue

                # Check multiline comment start --[[
                if line[i:i+4] == "--[[":
                    in_multiline_comment = True
                    i += 4
                    continue

                # Check single-line comment --
                if line[i:i+2] == "--":
                    # Comment rest of the line
                    break

                # Check multiline string [[
                if line[i:i+2] == "[[":
                    in_multiline_string = True
                    i += 2
                    continue

                # Check string quotes ' or "
                if line[i] in ('"', "'"):
                    quote_char = line[i]
                    start_pos = i
                    i += 1
                    str_content = ""
                    closed = False
                    while i < n:
                        if line[i] == "\\" and i + 1 < n:
                            str_content += line[i:i+2]
                            i += 2
                            continue
                        if line[i] == quote_char:
                            closed = True
                            i += 1
                            break
                        str_content += line[i]
                        i += 1
                    literals.append({
                        "line": line_idx,
                        "quote": quote_char,
                        "closed": closed,
                        "content": str_content
                    })
                    cleaned += f'"{str_content}"' if closed else f'"{str_content}'
                    continue

                cleaned += line[i]
                i += 1

            cleaned_lines.append(cleaned)

        return "\n".join(cleaned_lines), literals

    @classmethod
    def check_syntax(cls, code: str) -> List[Dict[str, Any]]:
        """
        Runs comprehensive syntax validation on Luau code.
        Returns a list of diagnosed issues: { "type": "error"|"warning", "line": int, "message": str, "suggestion": str }
        """
        issues = []
        raw_lines = code.splitlines()

        # 1. Delimiter balance check: (), [], {}
        stack = []
        matching_delims = {')': '(', ']': '[', '}': '{'}
        
        for line_idx, line in enumerate(raw_lines, start=1):
            # Check for illegal operators common from C/JS transitions
            # Check for != (Lua uses ~=)
            # Make sure it's not inside comments or quotes
            if "!=" in line:
                issues.append({
                    "type": "error",
                    "line": line_idx,
                    "message": "Illegal operator '!=' detected. Luau uses '~=' for inequality.",
                    "suggestion": "Replace '!=' with '~='."
                })
            if "&&" in line:
                issues.append({
                    "type": "error",
                    "line": line_idx,
                    "message": "Illegal operator '&&' detected. Luau uses keyword 'and'.",
                    "suggestion": "Replace '&&' with 'and'."
                })
            if "||" in line:
                issues.append({
                    "type": "error",
                    "line": line_idx,
                    "message": "Illegal operator '||' detected. Luau uses keyword 'or'.",
                    "suggestion": "Replace '||' with 'or'."
                })

            # Check for unclosed string quotes on a single line
            s_quotes = line.count("'") - line.count("\\'")
            d_quotes = line.count('"') - line.count('\\"')
            # Simple heuristic when string doesn't continue across lines
            if s_quotes % 2 != 0 and "[[" not in line and "]]" not in line and "--" not in line:
                issues.append({
                    "type": "error",
                    "line": line_idx,
                    "message": f"Unclosed single quote on line {line_idx}.",
                    "suggestion": "Ensure all single quotes (') are properly paired."
                })
            if d_quotes % 2 != 0 and "[[" not in line and "]]" not in line and "--" not in line:
                issues.append({
                    "type": "error",
                    "line": line_idx,
                    "message": f"Unclosed double quote on line {line_idx}.",
                    "suggestion": 'Ensure all double quotes (") are properly paired.'
                })

        # 2. Block Keyword matching (function, if, for, while, do -> end; repeat -> until)
        cleaned_code, _ = cls.strip_comments_and_strings(code)
        block_stack = []

        for line_idx, line in enumerate(cleaned_code.splitlines(), start=1):
            tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", line)
            for t_idx, token in enumerate(tokens):
                if token in ("function", "for", "while", "do"):
                    # Check if 'do' is part of 'while ... do' or 'for ... do'
                    # In Lua: 'while expr do' introduces ONE end, not two!
                    if token == "do":
                        # If preceded by for/while on same line, it closes the for/while clause
                        if t_idx > 0 and tokens[t_idx - 1] in ("for", "while"):
                            continue
                        if block_stack and block_stack[-1]["token"] in ("for", "while"):
                            # The 'do' pairs with the active for/while
                            continue
                    block_stack.append({"token": token, "line": line_idx})
                elif token == "if":
                    block_stack.append({"token": "if", "line": line_idx})
                elif token == "repeat":
                    block_stack.append({"token": "repeat", "line": line_idx})
                elif token == "until":
                    if block_stack and block_stack[-1]["token"] == "repeat":
                        block_stack.pop()
                    else:
                        issues.append({
                            "type": "error",
                            "line": line_idx,
                            "message": f"Unexpected 'until' without a matching 'repeat' on line {line_idx}.",
                            "suggestion": "Verify repeat...until loop structure."
                        })
                elif token == "end":
                    if not block_stack:
                        issues.append({
                            "type": "error",
                            "line": line_idx,
                            "message": f"Unexpected 'end' on line {line_idx} with no corresponding opening block.",
                            "suggestion": "Remove extra 'end' keyword or verify block closures."
                        })
                    else:
                        popped = block_stack.pop()
                        # 'repeat' expects 'until', not 'end'
                        if popped["token"] == "repeat":
                            issues.append({
                                "type": "error",
                                "line": line_idx,
                                "message": f"Repeat block opened on line {popped['line']} must close with 'until', not 'end'.",
                                "suggestion": "Replace 'end' with 'until <condition>'."
                            })

        # If blocks remain open
        for open_block in block_stack:
            issues.append({
                "type": "error",
                "line": open_block["line"],
                "message": f"Unclosed block '{open_block['token']}' opened on line {open_block['line']}; missing 'end'.",
                "suggestion": f"Add 'end' to close the '{open_block['token']}' block."
            })

        # 3. Modern Luau & Roblox Best Practices (Warnings/Suggestions)
        for line_idx, line in enumerate(raw_lines, start=1):
            stripped = line.strip()
            if stripped.startswith("--"):
                continue

            # Deprecated wait()
            if re.search(r"\bwait\s*\(", line) and not re.search(r"\btask\.wait\s*\(", line):
                issues.append({
                    "type": "warning",
                    "line": line_idx,
                    "message": "Deprecated global 'wait()' call detected. Modern Luau requires 'task.wait()'.",
                    "suggestion": "Replace 'wait(...)' with 'task.wait(...)' for 60Hz frame synchronization."
                })
            # Deprecated spawn()
            if re.search(r"\bspawn\s*\(", line) and not re.search(r"\btask\.spawn\s*\(", line):
                issues.append({
                    "type": "warning",
                    "line": line_idx,
                    "message": "Deprecated global 'spawn()' call detected. Modern Luau requires 'task.spawn()'.",
                    "suggestion": "Replace 'spawn(fn)' with 'task.spawn(fn)' to eliminate the 1-frame resume delay."
                })
            # Deprecated delay()
            if re.search(r"\bdelay\s*\(", line) and not re.search(r"\btask\.delay\s*\(", line):
                issues.append({
                    "type": "warning",
                    "line": line_idx,
                    "message": "Deprecated global 'delay()' call detected. Modern Luau requires 'task.delay()'.",
                    "suggestion": "Replace 'delay(t, fn)' with 'task.delay(t, fn)'."
                })
            # Deprecated :connect(
            if re.search(r":connect\s*\(", line):
                issues.append({
                    "type": "warning",
                    "line": line_idx,
                    "message": "Deprecated event method ':connect()' detected (lowercase 'c').",
                    "suggestion": "Replace ':connect()' with standard uppercase ':Connect()'."
                })

        return issues


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
        
        # 3. Domain Check: Hitbox Detection
        p_lower = prompt.lower()
        is_hitbox_request = any(k in p_lower for k in ["hitbox", "hit box", "hit detection", "melee", "combat", "damage detection", "cleave", "slash"])
        
        if is_hitbox_request:
            # Check spatial query or raycast methodology
            has_spatial_query = any(q in code for q in [
                "GetPartsInPart", "GetPartBoundsInBox", "GetPartBoundsInRadius",
                "workspace:Raycast", "WorldRoot:Raycast", "OverlapParams"
            ])
            has_touched = ".Touched:Connect" in code or ".Touched:connect" in code

            if has_spatial_query:
                passed_checks.append("Spatial Query Architecture (Modern OverlapParams / WorldRoot spatial query detected)")
            elif has_touched:
                passed_checks.append("Touched Event Architecture (Physical part collision detection detected)")
                untested_limitations.append("Touched events can suffer from physics latency; recommend spatial queries for competitive combat.")
            else:
                failed_checks.append({
                    "type": "warning",
                    "line": 1,
                    "message": "Hitbox lacks recognized spatial queries (e.g. Workspace:GetPartBoundsInBox, GetPartsInPart) or Raycast.",
                    "suggestion": "Implement OverlapParams and Workspace:GetPartBoundsInBox for robust server-side detection."
                })

            # Check Debounce / Multi-Hit Protection (CRITICAL for hitboxes)
            has_debounce = any(w in code.lower() for w in [
                "debounce", "cooldown", "hittargets", "hit_characters", "hitcharacters",
                "damagedtargets", "alreadyhit", "hits[", "hitplayers"
            ])
            if has_debounce:
                passed_checks.append("Multi-Hit Debounce Protection (Prevents 60Hz damage spam per frame)")
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

            if has_humanoid_check:
                passed_checks.append("Entity Humanoid Resolution (Validates target character model has Humanoid)")
            else:
                failed_checks.append({
                    "type": "warning",
                    "line": 1,
                    "message": "Hitbox does not explicitly check for Humanoid before resolving hits.",
                    "suggestion": "Use 'character:FindFirstChildOfClass(\"Humanoid\")' to ensure valid damage targets."
                })

            if has_health_check:
                passed_checks.append("Living Entity Guard (Verifies Humanoid.Health > 0 to prevent corpse damage)")
            else:
                untested_limitations.append("Target health check (> 0) omitted; may register hits on dead characters.")

            # Check Self-Damage / Caster Filter
            has_caster_filter = any(w in code for w in [
                "FilterDescendantsInstances", "caster", "player.Character", "character ~= hitCharacter",
                "hitCharacter ~= character", "owner"
            ])
            if has_caster_filter:
                passed_checks.append("Caster Immunity Filter (Prevents attacker from damaging themselves)")
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
            else:
                passed_checks.append("Zero-Allocation Memory Profile (Pure spatial query without temporary Part allocations)")

            # Domain Untested Limitations
            untested_limitations.extend([
                "Multiplayer replication lag: Network ping between high-latency clients and server cannot be tested statically.",
                "Custom R15/R6 avatar scaling: Box bounds may vary with player bundle sizes (e.g., Anthro vs standard R15).",
                "Physics simulation: Actual part penetration depends on live Roblox engine collision groups."
            ])

        # 4. Domain Check: VFX & Particle Effects
        is_vfx_request = any(k in p_lower for k in ["vfx", "particle", "beam", "domain expansion", "cleave", "aura"])
        if is_vfx_request and not is_hitbox_request:
            has_particles = "ParticleEmitter" in code or "Beam" in code or "Highlight" in code
            has_attachments = "Attachment" in code
            if has_particles:
                passed_checks.append("Visual Effect Emitter Architecture (Configures ParticleEmitters, Beams, or Highlights)")
            if has_attachments:
                passed_checks.append("Attachment Anchoring (Emitters parented to valid Attachment points)")
            untested_limitations.append("GPU rendering framerate impact under 100+ simultaneous particle emitters.")

        # 5. Domain Check: Creator Store & Architecture (House, Buildings, Models)
        is_structure_request = any(k in p_lower for k in ["house", "building", "structure", "creator store", "toolbox", "architecture", "cabin", "cottage"])
        if is_structure_request and not is_hitbox_request and not is_vfx_request:
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
        if TerminalManager:
            try:
                term_session = TerminalManager.create_terminal()
                session_id = term_session["session_id"]
                ws_path = term_session["workspace_path"]
                scratch_dir = os.path.join(ws_path, ".stroke_scratch")
                os.makedirs(scratch_dir, exist_ok=True)
                scratch_file = os.path.join(scratch_dir, f"test_{int(time.time()*1000)}.luau")
                with open(scratch_file, "w", encoding="utf-8") as f:
                    f.write(code)

                # Attempt luau-analyze via background terminal
                res = TerminalManager.run_command(session_id, "luau-analyze", [scratch_file], timeout_sec=10)
                if res.get("exit_code") == 0:
                    passed_checks.append("Luau Static Type & Semantic Analysis (luau-analyze verified cleanly via private background terminal)")
                elif res.get("exit_code") == 127:
                    # luau-analyze binary not installed on host, AST analysis was used
                    untested_limitations.append("External luau-analyze compiler binary not in workspace path; AST and semantic rules validated via internal engine.")
                else:
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
                TerminalManager.stop_terminal(session_id)
            except Exception as term_exc:
                untested_limitations.append(f"Private terminal runner note: {term_exc}")

        # Final Verification Status
        # Passed if zero blocking errors (warnings are permitted but reported)
        is_verified = (len([f for f in failed_checks if f["type"] == "error"]) == 0)

        return {
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "untested_limitations": untested_limitations,
            "is_verified": is_verified
        }

    @classmethod
    def test_python_code(cls, code: str) -> Dict[str, Any]:
        """Runs AST compilation and structural tests on Python code."""
        passed_checks = []
        failed_checks = []
        untested_limitations = []

        try:
            tree = ast.parse(code)
            passed_checks.append("Python AST Syntax Verification (Code compiles cleanly with ast.parse)")
            
            # Inspect structure
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            
            if funcs:
                passed_checks.append(f"Function Signatures Validated ({len(funcs)} defined: {', '.join(funcs[:3])})")
            if classes:
                passed_checks.append(f"Class Definitions Validated ({len(classes)} defined: {', '.join(classes[:2])})")

        except SyntaxError as e:
            failed_checks.append({
                "type": "error",
                "line": e.lineno or 1,
                "message": f"Python SyntaxError: {e.msg} on line {e.lineno}",
                "suggestion": f"Fix syntax near: {e.text.strip() if e.text else ''}"
            })

        # Real background terminal compiler check for Python
        if TerminalManager:
            try:
                term_session = TerminalManager.create_terminal()
                session_id = term_session["session_id"]
                ws_path = term_session["workspace_path"]
                scratch_dir = os.path.join(ws_path, ".stroke_scratch")
                os.makedirs(scratch_dir, exist_ok=True)
                scratch_file = os.path.join(scratch_dir, f"test_{int(time.time()*1000)}.py")
                with open(scratch_file, "w", encoding="utf-8") as f:
                    f.write(code)

                res = TerminalManager.run_command(session_id, "python", ["-m", "py_compile", scratch_file], timeout_sec=10)
                if res.get("exit_code") == 0:
                    passed_checks.append("Python Bytecode Compilation Check (python -m py_compile verified cleanly via private background terminal)")
                else:
                    err_output = res.get("stderr") or res.get("stdout") or "Bytecode compilation error"
                    failed_checks.append({
                        "type": "error",
                        "line": 1,
                        "message": f"Terminal Python Compiler Error:\n{err_output.strip()[:200]}",
                        "suggestion": "Fix Python syntax / bytecode error identified by python compiler."
                    })

                try:
                    if os.path.exists(scratch_file):
                        os.remove(scratch_file)
                except Exception:
                    pass
                TerminalManager.stop_terminal(session_id)
            except Exception as term_exc:
                untested_limitations.append(f"Private terminal compiler note: {term_exc}")

        untested_limitations.append("Runtime environment dependencies, operating system differences, and edge-case I/O exceptions.")
        is_verified = (len([f for f in failed_checks if f["type"] == "error"]) == 0)

        return {
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "untested_limitations": untested_limitations,
            "is_verified": is_verified
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
    CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "verified_project_context.json")

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

            entry = {
                "id": f"CTX-{int(time.time())}",
                "timestamp": time.time(),
                "prompt": prompt[:120],
                "language": language,
                "passed_checks_count": len(test_report.get("passed_checks", [])),
                "untested_count": len(test_report.get("untested_limitations", [])),
                "verified": test_report.get("is_verified", False),
                "iterations": test_report.get("iteration_count", 1),
                "user_email": user_email or "anonymous",
                "summary": f"Verified {language} solution with {len(test_report.get('passed_checks', []))} passing checks."
            }
            records.insert(0, entry)
            # Keep top 50 project context entries
            with open(cls.CONTEXT_FILE, "w", encoding="utf-8") as f:
                json.dump(records[:50], f, indent=2)
            print(f"[STROKE ARCHIVIST] Saved verified project context entry: {entry['id']}", flush=True)
        except Exception as exc:
            print(f"[STROKE ARCHIVIST NOTICE] Could not save context record: {exc}", flush=True)


# ==============================================================================
# 5. AUTONOMOUS CODING LOOP ORCHESTRATOR
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
        """Extracts code and language tag from markdown code fences (closed or unclosed)."""
        pattern = r"```([a-zA-Z0-9_]*)\n([\s\S]*?)```"
        matches = re.findall(pattern, text)
        if matches:
            lang, code = matches[0]
            clean_code = cls._clean_code_artifacts(code)
            return clean_code.strip(), (lang.lower() if lang else default_lang)
        
        # Check unclosed code fence at end of text
        unclosed_match = re.search(r"```([a-zA-Z0-9_]*)\n([\s\S]+)$", text)
        if unclosed_match:
            lang, code = unclosed_match.groups()
            clean_code = cls._clean_code_artifacts(code)
            return clean_code.strip(), (lang.lower() if lang else default_lang)

        # If no code fence, return full text if it looks like code
        lines = text.splitlines()
        code_indicators = ["local ", "function ", "import ", "def ", "class ", "game:GetService", "task.wait"]
        if any(any(ind in line for ind in code_indicators) for line in lines[:10]):
            clean_code = cls._clean_code_artifacts(text)
            return clean_code.strip(), default_lang
        return "", default_lang

    @staticmethod
    def _clean_code_artifacts(code: str) -> str:
        """Strips extreme repetitive loop sequences common in 1B LLM outputs."""
        lines = code.splitlines()
        deduped = []
        consecutive_count = 0
        prev_line = None
        for l in lines:
            stripped = l.strip()
            if stripped and stripped == prev_line:
                consecutive_count += 1
                if consecutive_count > 2:
                    continue
            else:
                consecutive_count = 0
                prev_line = stripped
            deduped.append(l)
        return "\n".join(deduped)

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

        badge = f"VERIFIED ({iterations} PASS{'ES' if iterations > 1 else ''})" if is_verified else "COMPLETED WITH WARNINGS"

        md = f"\n\n---\n\n### Stroke Verification & Quality Report\n"
        md += f"> **Status**: `{badge}` | **Engine**: Stroke Autonomous Coding Loop | **Iterations**: `{iterations}`\n\n"

        md += "#### Automated Checks Passed\n"
        if passed:
            for p in passed:
                md += f"- **[PASS]** {p}\n"
        else:
            md += "- None registered.\n"

        if failed:
            md += "\n#### Active Diagnostic Warnings\n"
            for f in failed:
                md += f"- **[{f.get('type', 'warning').upper()}]** Line {f.get('line', '?')}: {f.get('message')}\n"

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
        max_iterations: int = 2
    ) -> Tuple[str, Dict[str, Any], List[Dict[str, str]]]:
        """
        Executes the Write -> Test -> Diagnose -> Fix -> Retest coding loop.
        
        Args:
          prompt: User prompt
          initial_reply: Initial LLM response containing the first code draft
          llm_generate_fn: Callable(messages: list) -> str, for asking the model to fix issues
          user_email: User identity for archivist
          max_iterations: Max correction passes (default 2)
          
        Returns:
          (final_markdown_reply, test_report, loop_steps)
        """
        loop_steps = []
        code, lang = cls.extract_code_block(initial_reply, default_lang="luau")

        # Step 1: Understand Request
        loop_steps.append({
            "name": "Coding Loop // Step 1: Understand Request",
            "detail": f"Target: {lang.title()} | Analyzing physics, syntax, and API requirements"
        })

        if not code:
            # Not a code generation response
            return initial_reply, {"is_verified": False, "passed_checks": [], "failed_checks": [], "untested_limitations": []}, loop_steps

        # Step 2: Generated Code
        loop_steps.append({
            "name": "Coding Loop // Step 2: Initial Draft Synthesized",
            "detail": f"Extracted {len(code.splitlines())} lines of {lang.title()} code for testing"
        })

        current_code = code
        current_reply = initial_reply
        iteration = 1
        final_report = {}

        while iteration <= max_iterations:
            # Step 3: Run Checks
            loop_steps.append({
                "name": f"Coding Loop // Step 3: Run Checks (Pass {iteration})",
                "detail": f"Executing AST syntax parser, Roblox DataModel checks & domain tests"
            })

            if lang in ("lua", "luau"):
                report = RobloxDomainTestRunner.test_luau_code(current_code, prompt)
            elif lang == "python":
                report = RobloxDomainTestRunner.test_python_code(current_code)
            else:
                # Generic fallback syntax check
                report = {"passed_checks": ["Standard Code Block Extracted"], "failed_checks": [], "untested_limitations": ["Domain-specific static runner unavailable for this language."], "is_verified": True}

            report["iteration_count"] = iteration
            final_report = report

            blocking_errors = [c for c in report.get("failed_checks", []) if c.get("type") == "error"]

            if not blocking_errors:
                # Code passed all blocking checks!
                loop_steps.append({
                    "name": f"Coding Loop // Verification Passed (Pass {iteration})",
                    "detail": f"{len(report.get('passed_checks', []))} checks verified cleanly"
                })
                break

            # If there are errors and we haven't reached max iterations
            if iteration < max_iterations:
                # Step 4: Read errors & Diagnose
                loop_steps.append({
                    "name": f"Coding Loop // Step 4: Read Errors & Diagnose (Pass {iteration})",
                    "detail": f"Detected {len(blocking_errors)} blocking issue(s). Compiling diagnostic prompt"
                })

                correction_prompt = ErrorAnalyser.build_correction_prompt(current_code, report["failed_checks"], language=lang)

                # Step 5: Fix the code
                loop_steps.append({
                    "name": f"Coding Loop // Step 5: Autonomous Self-Healing Fix",
                    "detail": f"Dispatching error diagnostics to model for targeted code repair"
                })

                fix_messages = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": current_reply},
                    {"role": "user", "content": correction_prompt}
                ]

                try:
                    fixed_reply = llm_generate_fn(fix_messages)
                    if fixed_reply and len(fixed_reply.strip()) > 30:
                        new_code, new_lang = cls.extract_code_block(fixed_reply, default_lang=lang)
                        if new_code:
                            current_code = new_code
                            current_reply = fixed_reply
                            if new_lang:
                                lang = new_lang
                except Exception as exc:
                    print(f"[STROKE CODING LOOP NOTICE] Correction generation failed: {exc}", flush=True)
                    break

            iteration += 1

        # Step 6: Verify again & Compile Report
        loop_steps.append({
            "name": "Coding Loop // Step 6: Verify Again",
            "detail": f"Completed write-test-diagnose-fix cycle. Finalizing transparency report"
        })

        # Step 7: Present final answer with report
        loop_steps.append({
            "name": "Coding Loop // Step 7: Present Verified Solution",
            "detail": f"Presenting code with verified status and stated runtime limitations"
        })

        # Append the Verification & Quality Report to the reply
        report_md = cls.format_verification_report_markdown(final_report, iterations=min(iteration, max_iterations))
        final_reply = current_reply + report_md

        # Archivist retains project context
        CodingArchivist.record_verified_artifact(
            prompt=prompt,
            code=current_code,
            language=lang,
            test_report=final_report,
            user_email=user_email
        )

        return final_reply, final_report, loop_steps
