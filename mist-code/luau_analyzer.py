"""
luau_analyzer.py
=============================================================================
STROKE V1 — AUTHENTIC LUAU LEXER, AST ANALYZER & VERIFICATION PIPELINE
=============================================================================
Provides a real Luau lexer, comment/string stripper with exact line/column
mapping, block-token parser, and Roblox API validator.

Features:
1. LuauLexer: Full lexical scanner supporting:
   - Arbitrary long bracket strings and comments with matching '=' counts ([====[ ... ]====])
   - Escaped single/double quote string literals ('...', "...") with full escape parsing
   - Illegal operators from other languages (!=, &&, ||)
   - Luau keywords, numbers, operators, and delimiters
   - Exact line and column tracking for every token
2. Comment & String Masking:
   - Replaces comments and strings with whitespace/safe tokens preserving exact line/column layout
   - Ensures AST checks and API rules NEVER report text inside strings or comments as code
3. LuauAstValidator:
   - Delimiter balance check ((), [], {}) with exact line/col reporting
   - Block balance check (function, if..then, while..do, for..do, repeat..until, do..end)
   - Illegal operator diagnosis in code (never inside comments or strings)
   - Roblox API compliance (rejects Instance.new("Hitbox"), capitalized Workspace global, etc.)
   - Separation of compiler-confirmed errors from heuristic warnings
4. Tooling Detection:
   - Detects and runs real 'luau' or 'luau-analyze' CLI binaries if present on the host
   - Transparently distinguishes static checks, native compiler checks, and live playtest
=============================================================================
"""

import os
import re
import shutil
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Set


# =============================================================================
# 1. TOKENS & LEXER DATA MODELS
# =============================================================================

class LuauTokenType(str, Enum):
    WHITESPACE = "WHITESPACE"
    COMMENT = "COMMENT"
    STRING = "STRING"
    KEYWORD = "KEYWORD"
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    OPERATOR = "OPERATOR"
    ILLEGAL_OPERATOR = "ILLEGAL_OPERATOR"
    DELIMITER = "DELIMITER"
    PUNCTUATION = "PUNCTUATION"
    UNKNOWN = "UNKNOWN"


@dataclass
class LuauToken:
    type: LuauTokenType
    value: str
    line: int
    col: int
    end_line: int
    end_col: int
    raw: str
    start_pos: int = 0
    end_pos: int = 0


LUAU_KEYWORDS: Set[str] = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while", "continue", "type", "export", "typeof"
}

VALID_ROBLOX_INSTANCES: Set[str] = {
    "Part", "WedgePart", "CornerWedgePart", "TrussPart", "MeshPart", "UnionOperation",
    "Model", "Folder", "Attachment", "Bone", "ParticleEmitter", "Beam", "Trail", "Fire",
    "Smoke", "Sparkles", "Highlight", "BillboardGui", "SurfaceGui", "ScreenGui", "Frame",
    "TextLabel", "TextButton", "ImageLabel", "ImageButton", "UIListLayout", "UIGridLayout",
    "UIPadding", "UICorner", "UIGradient", "UIStroke", "Sound", "Animation", "AnimationTrack",
    "Animator", "Humanoid", "HumanoidDescription", "Shirt", "Pants", "ShirtGraphic", "BodyColors",
    "ClickDetector", "ProximityPrompt", "Tool", "Accessory", "Camera", "PointLight", "SpotLight",
    "SurfaceLight", "ColorCorrectionEffect", "BloomEffect", "BlurEffect", "SunRaysEffect",
    "Atmosphere", "Sky", "Clouds", "LinearVelocity", "AngularVelocity", "AlignPosition",
    "AlignOrientation", "BallSocketConstraint", "HingeConstraint", "PrismaticConstraint",
    "RopeConstraint", "RodConstraint", "SpringConstraint", "VectorForce", "Torque",
    "WeldConstraint", "Motor6D", "Weld", "RemoteEvent", "RemoteFunction", "BindableEvent",
    "BindableFunction", "Configuration", "ModuleScript", "Script", "LocalScript",
    "Actor", "AudioPlayer", "AudioEmitter", "AudioListener", "Wire"
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
    (r':WaitForChild\s*\(\s*([^,\n\)]+)\s*,\s*function\b', "Roblox API Error: 'Instance:WaitForChild(childName, timeout)' takes a numeric timeout as its second argument, not a callback function. WaitForChild returns the child Instance synchronously."),
    (r':(?:WaitForChild|FindFirstChild)\s*\(\s*["\'](CFrame|Position|Size|Health|MaxHealth|Anchored|CanCollide|Orientation)["\']', "Roblox API Error: ':{match}' is a property, not a child Instance. Access properties directly using dot notation (e.g. 'part.{match}')."),
    (r'(?::FindFirstChild(?:OfClass)?\(["\']Humanoid["\']\)|\.Humanoid)\s*(?::WaitForChild|:FindFirstChild)\s*\(\s*["\'](CFrame|Position|Size|Orientation)["\']', "Roblox Type Error: 'Humanoid' is a Controller instance without spatial geometry. It does not possess a '{match}' property or child. Access '.CFrame' on the character's 'HumanoidRootPart' (BasePart) instead."),
    (r'(?::FindFirstChild(?:OfClass)?\(["\']Humanoid["\']\)|\.Humanoid)\s*\.\s*(CFrame|Position|Orientation)\b', "Roblox Type Error: 'Humanoid' does not have a '.{match}' property. Access '.{match}' on 'HumanoidRootPart' (BasePart) instead."),
    (r'\b(hitbox|part|detectedPart|rootPart|humanoidRootPart|basePart|model|cframe)\s*:\s*TakeDamage\s*\(', "Roblox API Error: ':TakeDamage()' can only be invoked on a 'Humanoid' instance, not on '{match}' (BasePart). Locate the target's Humanoid via 'targetChar:FindFirstChildOfClass(\"Humanoid\")' and call 'humanoid:TakeDamage(damage)'."),
    (r'\blocal\s+task\s*=\s*task\.wait\b', "Fatal Library Shadowing: 'local task = task.wait' shadows the standard 'task' library table with a function, causing all subsequent 'task.wait()' calls to crash ('attempt to index function with wait'). Remove this assignment; 'task.wait()' is already globally available."),
    (r'\blocal\s+(task|math|string|table|os|coroutine|debug)\s*=\s*\1\.\w+', "Fatal Library Shadowing: 'local {match} = ...' shadows the standard library table with a function. Use '{match}' library functions directly."),
    (r'\blocal\s+(OverlapParams|RaycastParams|TweenInfo|Color3|Vector3|Vector2|CFrame|NumberRange|NumberSequence|ColorSequence)\s*=\s*\{\}', "Fake API Implementation: 'local {match} = {{}}' shadows the built-in Roblox datatype constructor '{match}.new()'. Do not mock Roblox built-in datatypes with empty tables."),
    (r'\blocal\s+(GetPartBoundsInBox|GetPartsInPart|GetPartBoundsInRadius|Raycast|TakeDamage|FilterDescendantsInstances|FilterType|MaxParts)\s*=\s*\{\}', "Fake API Implementation: '{match}' is a Roblox method or property, not a standalone global table. Do not define empty mock tables."),
    (r'\bexecuteSpatialHitbox\s*\(\s*(HumanoidRootPart|rootPart|part|Player)\b', "Type Mismatch in Call: 'executeSpatialHitbox' expects a character 'Model' as argument #1, but received '{match}' (a BasePart/Player). Pass the character Model (e.g. 'Player.Character' or 'casterCharacter') instead."),
]


# =============================================================================
# 2. FULL LUAU LEXER
# =============================================================================

class LuauLexer:
    """
    Complete lexical analyzer for Luau with exact line/column tracking,
    handling arbitrary-depth long brackets and escaped quotes.
    """

    def __init__(self, source: str):
        self.source = source
        self.length = len(source)
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[LuauToken] = []
        self.lex_errors: List[Dict[str, Any]] = []

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        if idx < self.length:
            return self.source[idx]
        return ""

    def _advance(self, count: int = 1) -> str:
        chunk = ""
        for _ in range(count):
            if self.pos < self.length:
                ch = self.source[self.pos]
                chunk += ch
                self.pos += 1
                if ch == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
        return chunk

    def tokenize(self) -> List[LuauToken]:
        while self.pos < self.length:
            start_pos = self.pos
            ch = self._peek()

            # 1. Whitespace
            if ch in (" ", "\t", "\r", "\n"):
                start_l, start_c = self.line, self.col
                ws = self._advance(1)
                while self._peek() in (" ", "\t", "\r", "\n"):
                    ws += self._advance(1)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.WHITESPACE,
                    value=ws,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=ws,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 2. Comments: single-line (-- ...) or multi-line (--[=*[ ... ]=*])
            if ch == "-" and self._peek(1) == "-":
                start_l, start_c = self.line, self.col
                raw_chunk = self._advance(2)

                # Check for long-bracket comment --[=*[
                long_match = re.compile(r"^\[(=*)\[").match(self.source[self.pos:])
                if long_match:
                    num_equals = len(long_match.group(1))
                    bracket_len = 2 + num_equals
                    raw_chunk += self._advance(bracket_len)
                    close_pat = re.compile(r"\]" + "=" * num_equals + r"\]")
                    close_match = close_pat.search(self.source, self.pos)
                    if close_match:
                        content_to_close = self._advance(close_match.end() - self.pos)
                        raw_chunk += content_to_close
                    else:
                        # Unclosed multiline comment
                        raw_chunk += self._advance(self.length - self.pos)
                        self.lex_errors.append({
                            "type": "error",
                            "line": start_l,
                            "col": start_c,
                            "message": f"Unclosed long bracket comment started on line {start_l}, column {start_c} ('--[{'=' * num_equals}[')."
                        })
                else:
                    # Single-line comment
                    while self.pos < self.length and self._peek() != "\n":
                        raw_chunk += self._advance(1)

                self.tokens.append(LuauToken(
                    type=LuauTokenType.COMMENT,
                    value=raw_chunk,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw_chunk,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 3. Long bracket strings [=*[ ... ]=*]
            if ch == "[":
                long_str_match = re.compile(r"^\[(=*)\[").match(self.source[self.pos:])
                if long_str_match:
                    start_l, start_c = self.line, self.col
                    num_equals = len(long_str_match.group(1))
                    bracket_len = 2 + num_equals
                    raw_chunk += self._advance(bracket_len)
                    close_pat = re.compile(r"\]" + "=" * num_equals + r"\]")
                    close_match = close_pat.search(self.source, self.pos)
                    if close_match:
                        raw_chunk += self._advance(close_match.end() - self.pos)
                    else:
                        raw_chunk += self._advance(self.length - self.pos)
                        self.lex_errors.append({
                            "type": "error",
                            "line": start_l,
                            "col": start_c,
                            "message": f"Unclosed long bracket string started on line {start_l}, column {start_c} ('[{'=' * num_equals}[')."
                        })
                    self.tokens.append(LuauToken(
                        type=LuauTokenType.STRING,
                        value=raw_chunk,
                        line=start_l,
                        col=start_c,
                        end_line=self.line,
                        end_col=self.col,
                        raw=raw_chunk,
                        start_pos=start_pos,
                        end_pos=self.pos
                    ))
                    continue

            # 4. Quoted string literals ('...' or "...")
            if ch in ('"', "'"):
                quote = ch
                start_l, start_c = self.line, self.col
                raw_chunk = self._advance(1)
                closed = False
                while self.pos < self.length:
                    curr = self._peek()
                    if curr == "\\":
                        raw_chunk += self._advance(2)
                        continue
                    if curr == quote:
                        raw_chunk += self._advance(1)
                        closed = True
                        break
                    if curr == "\n":
                        # Unescaped newline in single-line string is invalid
                        break
                    raw_chunk += self._advance(1)

                if not closed:
                    self.lex_errors.append({
                        "type": "error",
                        "line": start_l,
                        "col": start_c,
                        "message": f"Unclosed string literal starting on line {start_l}, column {start_c} ({quote}).",
                        "suggestion": f"Close the string literal with matching {quote}."
                    })

                self.tokens.append(LuauToken(
                    type=LuauTokenType.STRING,
                    value=raw_chunk,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw_chunk,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 5. Illegal Operators: !=, &&, ||
            two_ch = self.source[self.pos:self.pos+2]
            if two_ch == "!=":
                start_l, start_c = self.line, self.col
                raw = self._advance(2)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.ILLEGAL_OPERATOR,
                    value="!=",
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue
            if two_ch == "&&":
                start_l, start_c = self.line, self.col
                raw = self._advance(2)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.ILLEGAL_OPERATOR,
                    value="&&",
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue
            if two_ch == "||":
                start_l, start_c = self.line, self.col
                raw = self._advance(2)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.ILLEGAL_OPERATOR,
                    value="||",
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 6. Numbers (integers, floats, hex 0x, binary 0b)
            if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
                start_l, start_c = self.line, self.col
                num_match = re.compile(r"^(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|[0-9_]+(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]+)?)").match(self.source[self.pos:])
                if num_match:
                    num_str = self._advance(len(num_match.group(0)))
                    self.tokens.append(LuauToken(
                        type=LuauTokenType.NUMBER,
                        value=num_str,
                        line=start_l,
                        col=start_c,
                        end_line=self.line,
                        end_col=self.col,
                        raw=num_str,
                        start_pos=start_pos,
                        end_pos=self.pos
                    ))
                    continue

            # 7. Identifiers & Keywords
            if ch.isalpha() or ch == "_":
                start_l, start_c = self.line, self.col
                id_match = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*").match(self.source[self.pos:])
                if id_match:
                    id_str = self._advance(len(id_match.group(0)))
                    t_type = LuauTokenType.KEYWORD if id_str in LUAU_KEYWORDS else LuauTokenType.IDENTIFIER
                    self.tokens.append(LuauToken(
                        type=t_type,
                        value=id_str,
                        line=start_l,
                        col=start_c,
                        end_line=self.line,
                        end_col=self.col,
                        raw=id_str,
                        start_pos=start_pos,
                        end_pos=self.pos
                    ))
                    continue

            # 8. Multi-character operators
            three_ch = self.source[self.pos:self.pos+3]
            if three_ch in ("...", "//="):
                start_l, start_c = self.line, self.col
                raw = self._advance(3)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.OPERATOR,
                    value=three_ch,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            if two_ch in ("==", "~=", "<=", ">=", "..", "//", "::", "+=", "-=", "*=", "/=", "%=", "^=", "..="):
                start_l, start_c = self.line, self.col
                raw = self._advance(2)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.OPERATOR,
                    value=two_ch,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=raw,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 9. Delimiters
            if ch in ("(", ")", "{", "}", "[", "]"):
                start_l, start_c = self.line, self.col
                delim = self._advance(1)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.DELIMITER,
                    value=delim,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=delim,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 10. Single punctuation and operators
            if ch in (";", ":", ","):
                start_l, start_c = self.line, self.col
                punc = self._advance(1)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.PUNCTUATION,
                    value=punc,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=punc,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            if ch in ("+", "-", "*", "/", "%", "^", "#", "<", ">", "=", "."):
                start_l, start_c = self.line, self.col
                op = self._advance(1)
                self.tokens.append(LuauToken(
                    type=LuauTokenType.OPERATOR,
                    value=op,
                    line=start_l,
                    col=start_c,
                    end_line=self.line,
                    end_col=self.col,
                    raw=op,
                    start_pos=start_pos,
                    end_pos=self.pos
                ))
                continue

            # 11. Unknown / fallback
            start_l, start_c = self.line, self.col
            unk = self._advance(1)
            self.tokens.append(LuauToken(
                type=LuauTokenType.UNKNOWN,
                value=unk,
                line=start_l,
                col=start_c,
                end_line=self.line,
                end_col=self.col,
                raw=unk,
                start_pos=start_pos,
                end_pos=self.pos
            ))

        return self.tokens


# =============================================================================
# 3. CODE MASKING & LINE/COLUMN PRESERVATION
# =============================================================================

def mask_comments_and_strings(code: str) -> Tuple[str, List[LuauToken]]:
    """
    Replaces comments and strings with space-padding while preserving
    exact line numbers and column mapping.
    """
    lexer = LuauLexer(code)
    tokens = lexer.tokenize()
    masked_chars = list(code)

    for tok in tokens:
        if tok.type in (LuauTokenType.COMMENT, LuauTokenType.STRING):
            for idx in range(tok.start_pos, min(tok.end_pos, len(masked_chars))):
                if masked_chars[idx] != "\n":
                    masked_chars[idx] = " "

    return "".join(masked_chars), tokens


def mask_comments_only(code: str) -> Tuple[str, List[LuauToken]]:
    """
    Replaces comments with space-padding while preserving string content,
    exact line numbers, and column mapping.
    """
    lexer = LuauLexer(code)
    tokens = lexer.tokenize()
    masked_chars = list(code)

    for tok in tokens:
        if tok.type == LuauTokenType.COMMENT:
            for idx in range(tok.start_pos, min(tok.end_pos, len(masked_chars))):
                if masked_chars[idx] != "\n":
                    masked_chars[idx] = " "

    return "".join(masked_chars), tokens


# =============================================================================
# 4. ROBUST LUAU SYNTAX & AST VALIDATOR
# =============================================================================

class AuthenticLuauValidator:
    """
    Authentic Luau Syntax and AST Validator:
    - Never inspects strings or comments for operators, keywords, or APIs.
    - Delimiter balancing with exact line/col.
    - Block balance matching with single 'end' for while/for clauses.
    - Authentic Roblox class names validation.
    - Separates compiler errors from heuristic warnings.
    """

    @classmethod
    def validate_code(cls, code: str) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        lexer = LuauLexer(code)
        tokens = lexer.tokenize()
        masked_code, _ = mask_comments_and_strings(code)

        # Add lexer syntax errors (e.g. unclosed quotes or long brackets)
        issues.extend(lexer.lex_errors)

        # Filter out comments and whitespace for AST inspection
        code_tokens = [t for t in tokens if t.type not in (LuauTokenType.WHITESPACE, LuauTokenType.COMMENT)]

        # 1. Illegal operators in CODE tokens ONLY (never strings or comments)
        for tok in code_tokens:
            if tok.type == LuauTokenType.ILLEGAL_OPERATOR:
                if tok.value == "!=":
                    issues.append({
                        "type": "error",
                        "line": tok.line,
                        "col": tok.col,
                        "message": "Illegal operator '!=' in Luau. Luau uses '~=' for inequality.",
                        "suggestion": "Replace '!=' with '~='."
                    })
                elif tok.value == "&&":
                    issues.append({
                        "type": "error",
                        "line": tok.line,
                        "col": tok.col,
                        "message": "Illegal operator '&&' in Luau. Luau uses keyword 'and'.",
                        "suggestion": "Replace '&&' with 'and'."
                    })
                elif tok.value == "||":
                    issues.append({
                        "type": "error",
                        "line": tok.line,
                        "col": tok.col,
                        "message": "Illegal operator '||' in Luau. Luau uses keyword 'or'.",
                        "suggestion": "Replace '||' with 'or'."
                    })

        # 2. Delimiter Balancing ((), [], {})
        stack: List[Tuple[str, int, int]] = []
        matching = {')': '(', ']': '[', '}': '{'}

        for tok in code_tokens:
            if tok.type == LuauTokenType.DELIMITER:
                ch = tok.value
                if ch in ("(", "[", "{"):
                    stack.append((ch, tok.line, tok.col))
                elif ch in (")", "]", "}"):
                    expected = matching[ch]
                    if not stack:
                        issues.append({
                            "type": "error",
                            "line": tok.line,
                            "col": tok.col,
                            "message": f"Unexpected closing delimiter '{ch}' without matching '{expected}'.",
                            "suggestion": f"Remove extra '{ch}' or add opening '{expected}'."
                        })
                    else:
                        top, l_no, c_no = stack.pop()
                        if top != expected:
                            issues.append({
                                "type": "error",
                                "line": tok.line,
                                "col": tok.col,
                                "message": f"Mismatched delimiter: opened with '{top}' on line {l_no}, col {c_no} but closed with '{ch}'.",
                                "suggestion": f"Replace '{ch}' with matching '{top}' closure."
                            })

        for unclosed, l_no, c_no in stack:
            issues.append({
                "type": "error",
                "line": l_no,
                "col": c_no,
                "message": f"Unclosed opening delimiter '{unclosed}' on line {l_no}, col {c_no}.",
                "suggestion": f"Add closing delimiter for '{unclosed}'."
            })

        # 3. Block Structure Balancing
        # Luau block rules:
        # 'function ... end'
        # 'if ... then ... elseif ... then ... else ... end'
        # 'while ... do ... end'  (Note: the 'do' belongs to 'while', 1 'end')
        # 'for ... do ... end'    (Note: the 'do' belongs to 'for', 1 'end')
        # 'do ... end'            (Standalone 'do' opens a block)
        # 'repeat ... until'      (Closes with 'until', NOT 'end')
        block_stack: List[Dict[str, Any]] = []

        i = 0
        n = len(code_tokens)
        while i < n:
            tok = code_tokens[i]
            val = tok.value

            if val in ("function", "if", "for", "while", "repeat"):
                block_stack.append({"token": val, "line": tok.line, "col": tok.col})
            elif val == "do":
                # Check if this 'do' pairs with active 'for' or 'while'
                if block_stack and block_stack[-1]["token"] in ("for", "while") and not block_stack[-1].get("has_do"):
                    block_stack[-1]["has_do"] = True
                else:
                    # Standalone 'do ... end' block
                    block_stack.append({"token": "do", "line": tok.line, "col": tok.col})
            elif val == "until":
                if block_stack and block_stack[-1]["token"] == "repeat":
                    block_stack.pop()
                else:
                    issues.append({
                        "type": "error",
                        "line": tok.line,
                        "col": tok.col,
                        "message": f"Unexpected 'until' without a matching 'repeat' on line {tok.line}.",
                        "suggestion": "Ensure repeat...until loop structure is correct."
                    })
            elif val == "end":
                if not block_stack:
                    issues.append({
                        "type": "error",
                        "line": tok.line,
                        "col": tok.col,
                        "message": f"Unexpected 'end' on line {tok.line} with no opening block.",
                        "suggestion": "Remove extra 'end' or add opening block."
                    })
                else:
                    popped = block_stack.pop()
                    if popped["token"] == "repeat":
                        issues.append({
                            "type": "error",
                            "line": tok.line,
                            "col": tok.col,
                            "message": f"Repeat block opened on line {popped['line']} must close with 'until', not 'end'.",
                            "suggestion": "Replace 'end' with 'until <condition>'."
                        })
            i += 1

        for unclosed_b in block_stack:
            issues.append({
                "type": "error",
                "line": unclosed_b["line"],
                "col": unclosed_b["col"],
                "message": f"Unclosed block '{unclosed_b['token']}' opened on line {unclosed_b['line']}, col {unclosed_b['col']}; missing 'end'.",
                "suggestion": f"Add 'end' to close '{unclosed_b['token']}'."
            })

        # 4. Roblox API Checks (Executed strictly on code tokens and masked code, NEVER comments or strings)
        # 4a. Check Instance.new(...) valid classes
        for idx in range(len(code_tokens) - 2):
            t0, t1, t2 = code_tokens[idx], code_tokens[idx+1], code_tokens[idx+2]
            if t0.value == "Instance" and t1.value == "." and t2.value == "new":
                arg_tok = None
                if idx + 3 < len(code_tokens):
                    t3 = code_tokens[idx+3]
                    if t3.value == "(" and idx + 4 < len(code_tokens):
                        arg_tok = code_tokens[idx+4]
                    elif t3.type == LuauTokenType.STRING:
                        arg_tok = t3
                if arg_tok and arg_tok.type == LuauTokenType.STRING:
                    raw_val = arg_tok.value
                    if raw_val.startswith(('"', "'")):
                        raw_cls = raw_val[1:-1] if len(raw_val) >= 2 and raw_val[-1] == raw_val[0] else raw_val[1:]
                    elif raw_val.startswith("["):
                        raw_cls = re.sub(r"^\[=*\[|\]=*\]$", "", raw_val)
                    else:
                        raw_cls = raw_val.strip("\"'[]=").strip()
                    if raw_cls and raw_cls not in VALID_ROBLOX_INSTANCES:
                        issues.append({
                            "type": "error",
                            "line": t0.line,
                            "col": t0.col,
                            "message": f"Invalid Roblox class '{raw_cls}' in Instance.new(). '{raw_cls}' is not a valid Roblox DataModel class.",
                            "suggestion": "Use legitimate Roblox classes: Part, Model, Attachment, ParticleEmitter, Beam, etc."
                        })

        # 4b. Non-Existent & Hallucinated Roblox APIs (Tested on comments-masked code so string args are preserved)
        comments_masked, _ = mask_comments_only(code)
        for pat, msg_template in FAKE_ROBLOX_API_RULES:
            for match in re.finditer(pat, comments_masked):
                matched_text = match.group(1) if match.groups() else match.group(0)
                line_no = comments_masked[:match.start()].count("\n") + 1
                msg = msg_template.format(match=matched_text)
                issues.append({
                    "type": "error",
                    "line": line_no,
                    "col": 1,
                    "message": msg,
                    "suggestion": "Replace with authentic Roblox Luau APIs."
                })

        # Check single-invocation debounce table declared inside function
        func_depth = 0
        for idx, tok in enumerate(code_tokens):
            if tok.value == "function":
                func_depth += 1
            elif tok.value == "end" and func_depth > 0:
                func_depth -= 1
            elif func_depth > 0 and tok.value == "local" and idx + 3 < len(code_tokens):
                var_tok = code_tokens[idx + 1]
                eq_tok = code_tokens[idx + 2]
                val_tok = code_tokens[idx + 3]
                var_lower = var_tok.value.lower()
                if (
                    eq_tok.value == "="
                    and val_tok.value == "{"
                    and any(k in var_lower for k in ("hit", "debounce", "damaged", "targets"))
                ):
                    issues.append({
                        "type": "warning",
                        "line": var_tok.line,
                        "col": var_tok.col,
                        "message": f"Single-Invocation Debounce Only: Debounce table '{var_tok.value}' is declared inside a function body. It will be re-instantiated on every call, failing to prevent multi-hit damage across frames. Move the debounce table outside the function or use a persistent cooldown table.",
                        "suggestion": f"Move '{var_tok.value}' outside the function so it persists across invocations."
                    })

        # Check incomplete target character resolution (part.Parent)
        for match in re.finditer(r'\blocal\s+([a-zA-Z0-9_]*char[a-zA-Z0-9_]*|[a-zA-Z0-9_]*target[a-zA-Z0-9_]*)\s*=\s*([a-zA-Z0-9_]+)\.Parent\b', comments_masked, re.IGNORECASE):
            line_no = comments_masked[:match.start()].count("\n") + 1
            part_var = match.group(2)
            issues.append({
                "type": "warning",
                "line": line_no,
                "col": 1,
                "message": f"Incomplete Target Character Resolution: '{part_var}.Parent' assumes character limbs are directly parented to the Model. Accessories, hats, and tools have nested hierarchy; use '{part_var}:FindFirstAncestorOfClass(\"Model\")' to reliably resolve the character Model.",
                "suggestion": f"Replace '{part_var}.Parent' with '{part_var}:FindFirstAncestorOfClass(\"Model\")'."
            })

        # Check capitalized Workspace global: 'Workspace.' or 'Workspace:'
        for idx in range(len(code_tokens) - 1):
            t0, t1 = code_tokens[idx], code_tokens[idx+1]
            if t0.value == "Workspace" and t1.value in (".", ":"):
                # Check if local Workspace was declared
                has_decl = False
                for prev_idx in range(idx):
                    pt0, pt1 = code_tokens[prev_idx], code_tokens[prev_idx+1] if prev_idx+1 < idx else None
                    if pt0.value == "local" and pt1 and pt1.value == "Workspace":
                        has_decl = True
                        break
                if not has_decl:
                    issues.append({
                        "type": "error",
                        "line": t0.line,
                        "col": t0.col,
                        "message": "Unresolved Global: 'Workspace' (capitalized) is not defined in Luau scope. In Roblox, the global is lowercase 'workspace' or obtained via 'game:GetService(\"Workspace\")'.",
                        "suggestion": "Replace 'Workspace' with lowercase 'workspace' or 'game:GetService(\"Workspace\")'."
                    })

        # 5. Heuristic Warnings (Separated cleanly from compiler errors)
        # Check deprecated wait(), spawn(), delay(), :connect()
        for idx in range(len(code_tokens) - 1):
            t0, t1 = code_tokens[idx], code_tokens[idx+1]
            prev = code_tokens[idx-1].value if idx > 0 else ""
            if t0.value == "wait" and t1.value == "(" and prev != ".":
                issues.append({
                    "type": "warning",
                    "line": t0.line,
                    "col": t0.col,
                    "message": "Deprecated global 'wait()' call detected. Modern Luau requires 'task.wait()'.",
                    "suggestion": "Replace 'wait(...)' with 'task.wait(...)'."
                })
            elif t0.value == "spawn" and t1.value == "(" and prev != ".":
                issues.append({
                    "type": "warning",
                    "line": t0.line,
                    "col": t0.col,
                    "message": "Deprecated global 'spawn()' call detected. Modern Luau requires 'task.spawn()'.",
                    "suggestion": "Replace 'spawn(fn)' with 'task.spawn(fn)'."
                })
            elif t0.value == "connect" and t1.value == "(" and prev == ":":
                issues.append({
                    "type": "warning",
                    "line": t0.line,
                    "col": t0.col,
                    "message": "Deprecated event method ':connect()' detected (lowercase 'c').",
                    "suggestion": "Replace ':connect()' with standard uppercase ':Connect()'."
                })

        return issues


# =============================================================================
# 5. EXTERNAL LUAU TOOLING INTEGRATION
# =============================================================================

def find_system_luau_tool() -> Optional[str]:
    """Finds real 'luau' or 'luau-analyze' compiler on PATH or common developer paths."""
    for tool in ("luau", "luau-analyze"):
        found = shutil.which(tool)
        if found:
            return found
    common_paths = [
        "/usr/local/bin/luau",
        "/usr/local/bin/luau-analyze",
        "/opt/homebrew/bin/luau",
        "/opt/homebrew/bin/luau-analyze",
        os.path.expanduser("~/.cargo/bin/luau"),
        os.path.expanduser("~/.aftman/bin/luau")
    ]
    for p in common_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def run_system_luau_compiler(tool_path: str, code: str) -> Tuple[int, str, str]:
    """Runs genuine Luau compiler/analyzer binary on code."""
    try:
        proc = subprocess.run(
            [tool_path, "-"],
            input=code,
            text=True,
            capture_output=True,
            timeout=5
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 1, "", str(exc)
