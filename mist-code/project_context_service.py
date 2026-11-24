"""
================================================================================
STROKE // PROJECT INTELLIGENCE & CONTEXT INDEXING SERVICE
================================================================================
Provides genuine project intelligence across approved workspaces:
1. File Ingestion: Reads actual file contents; never counts filenames/sizes as ingestion.
2. Structure Preservation: Preserves relative paths and workspace hierarchy.
3. Multi-Language & Format Support: Luau/Lua (ServerScript, LocalScript, ModuleScript),
   Python (AST classes, functions, decorators, imports), TypeScript/JavaScript (AST/regex
   classes, interfaces, types, exports), Rust, Go, Roblox XML (.rbxmx / .rbxlx) parsing,
   manifests (Rojo default.project.json, Wally wally.toml, package.json, pyproject.toml,
   requirements.txt, Cargo.toml), configs, and documentation.
4. Dependency Analysis & File Relationships: Resolves internal imports and requires,
   reverse dependents (callers), external packages, Roblox service usage, and impact radius.
5. Symbol Discovery & Global Symbol Table: Indexes functions, methods, classes, types,
   interfaces, and services with cross-file symbol lookup and reference finding.
6. Project Architecture Summaries: Detects archetype (Roblox, Python backend, Web frontend,
   Fullstack, Rust), entry points, frameworks, component layers, and generates executive
   summaries for AI agents.
7. Incremental Indexing: SHA-256 content hashes to detect added, modified, unchanged,
   and deleted files without redundant AST/regex re-parsing.
8. Graph-Aware Context Retrieval: Combines BM25 lexical relevance, symbol matching,
   and dependency graph expansion (pulling in imported contract signatures).
9. Robust Limits & Security: Per-file byte limits (1MB), total index limits (25MB),
   file count limits, execution timeouts, .gitignore enforcement, and strict secret exclusion.
================================================================================
"""

import os
import sys
import re
import ast
import json
import time
import hashlib
import fnmatch
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Tuple, Set, Generator

import paths_service
import workspace_service


# ------------------------------------------------------------------------------
# CONSTANTS & LIMITS
# ------------------------------------------------------------------------------
MAX_PER_FILE_BYTES = 1_048_576       # 1 MB per file
MAX_TOTAL_INDEX_BYTES = 25_000_000    # 25 MB total index capacity
MAX_INDEXED_FILES = 1_000            # Maximum files in a single project index
INDEX_TIMEOUT_SECONDS = 30.0          # Max time for an indexing job

SUPPORTED_EXTENSIONS = {
    # Luau / Lua
    ".luau", ".lua",
    # Python
    ".py", ".pyi",
    # TypeScript / JavaScript
    ".ts", ".tsx", ".mts", ".cts",
    ".js", ".jsx", ".mjs", ".cjs",
    # Systems & Compiled
    ".rs", ".go",
    # Roblox XML formats
    ".rbxmx", ".rbxlx",
    # Project configurations & manifests
    ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
    # Web & Database
    ".html", ".htm", ".css", ".scss", ".sql",
    # Shell scripting
    ".sh", ".bash", ".zsh",
    # Documentation & text
    ".md", ".txt", ".rst"
}

SECRET_NAME_PATTERNS = [
    r"^\.env(\..+)?$",
    r".*token.*",
    r".*secret.*",
    r".*credential.*",
    r".*id_rsa.*",
    r".*id_ed25519.*",
    r".*\.pem$",
    r".*\.key$",
    r".*\.pfx$",
    r".*\.p12$",
    r"^\.vault_key$"
]

SECRET_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"eyJhbGciOi[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r'(?i)(?:password|passwd|api_key|secret_key)\s*[:=]\s*["\'][^"\']{6,}["\']')
]

DEFAULT_IGNORED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "venv", ".venv",
    "__pycache__", ".output", ".nitro", "dist", "build", "target", ".backups"
}

CORE_ROBLOX_SERVICES = {
    "Players": "Manages player instances, connections, teams, and character loading.",
    "ReplicatedStorage": "Shared network container replicated across server and all clients.",
    "ServerScriptService": "Secure server-only script container inaccessible to clients.",
    "ServerStorage": "Secure server-only storage for assets, maps, and templates.",
    "StarterPlayer": "Contains StarterPlayerScripts (client code) and StarterCharacterScripts.",
    "StarterGui": "Container for ScreenGuis replicated to player PlayerGui upon spawn.",
    "Workspace": "Active 3D physical world containing parts, models, terrain, and cameras.",
    "Lighting": "Configures ambient lighting, skyboxes, atmosphere, and post-processing VFX.",
    "RunService": "Frame lifecycle events: Heartbeat, Stepped, RenderStepped, and IsServer/IsClient.",
    "TweenService": "Interpolates instance properties smoothly over time.",
    "UserInputService": "Detects client keyboard, mouse, gamepad, and touch inputs.",
    "ContextActionService": "Binds player inputs to actions with priority stack.",
    "HttpService": "Handles JSON encoding/decoding, UUID generation, and external HTTP requests.",
    "DataStoreService": "Persistent cloud key-value database for player profiles and world state.",
    "CollectionService": "Tag-based instance querying and lifecycle event binding.",
    "SoundService": "Manages sound playback, sound groups, and audio effects.",
    "Debris": "Schedules instance destruction after a specified duration.",
    "Chat": "Legacy chat service and text filtering backend.",
    "TextChatService": "Modern Roblox text chat system and channel management."
}


# ------------------------------------------------------------------------------
# DATA STRUCTURES
# ------------------------------------------------------------------------------
class ProjectFileRecord:
    def __init__(
        self,
        relative_path: str,
        content_hash: str,
        size_bytes: int,
        modified_at: float,
        file_type: str,
        content: str,
        symbols: Optional[List[Dict[str, Any]]] = None,
        summary: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        language: str = "unknown",
        dependencies: Optional[List[str]] = None,
        external_imports: Optional[List[str]] = None,
        docstring: str = ""
    ):
        self.relative_path = relative_path
        self.content_hash = content_hash
        self.size_bytes = size_bytes
        self.modified_at = modified_at
        self.file_type = file_type
        self.content = content
        self.symbols = symbols or []
        self.summary = summary
        self.metadata = metadata or {}
        self.language = language
        self.dependencies = dependencies or []
        self.external_imports = external_imports or []
        self.docstring = docstring

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "file_type": self.file_type,
            "content": self.content,
            "symbols": self.symbols,
            "summary": self.summary,
            "metadata": self.metadata,
            "language": self.language,
            "dependencies": self.dependencies,
            "external_imports": self.external_imports,
            "docstring": self.docstring
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectFileRecord':
        return cls(
            relative_path=data.get("relative_path", ""),
            content_hash=data.get("content_hash", ""),
            size_bytes=data.get("size_bytes", 0),
            modified_at=data.get("modified_at", 0.0),
            file_type=data.get("file_type", "unknown"),
            content=data.get("content", ""),
            symbols=data.get("symbols", []),
            summary=data.get("summary", ""),
            metadata=data.get("metadata", {}),
            language=data.get("language", "unknown"),
            dependencies=data.get("dependencies", []),
            external_imports=data.get("external_imports", []),
            docstring=data.get("docstring", "")
        )


# ------------------------------------------------------------------------------
# 1. LANGUAGE DETECTOR
# ------------------------------------------------------------------------------
class LanguageDetector:
    """Detects programming language and file categories with precision."""

    EXT_MAP = {
        ".luau": "luau",
        ".lua": "lua",
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".mts": "typescript",
        ".cts": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".rbxmx": "roblox_xml",
        ".rbxlx": "roblox_xml",
        ".json": "json",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".ini": "ini",
        ".cfg": "ini",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".sql": "sql",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        ".md": "markdown",
        ".txt": "text",
        ".rst": "text"
    }

    SPECIAL_FILENAMES = {
        "default.project.json": ("roblox_project", "project_metadata"),
        "rojo.json": ("roblox_project", "project_metadata"),
        "wally.toml": ("roblox_wally", "dependency_manifest"),
        "wally.lock": ("roblox_wally_lock", "dependency_manifest"),
        "package.json": ("nodejs_package", "dependency_manifest"),
        "package-lock.json": ("nodejs_lock", "dependency_manifest"),
        "tsconfig.json": ("typescript_config", "project_metadata"),
        "pyproject.toml": ("python_project", "dependency_manifest"),
        "requirements.txt": ("python_requirements", "dependency_manifest"),
        "Cargo.toml": ("rust_cargo", "dependency_manifest"),
        "Cargo.lock": ("rust_lock", "dependency_manifest"),
        "Dockerfile": ("dockerfile", "configuration"),
        "docker-compose.yml": ("docker_compose", "configuration")
    }

    @classmethod
    def detect_language(cls, rel_path: str, sample_content: str = "") -> Tuple[str, str]:
        """
        Returns: (language_name, file_category)
        File categories: code, project_metadata, dependency_manifest, documentation, configuration, text.
        """
        fname = Path(rel_path).name
        if fname in cls.SPECIAL_FILENAMES:
            return cls.SPECIAL_FILENAMES[fname]

        ext = Path(rel_path).suffix.lower()
        lang = cls.EXT_MAP.get(ext, "unknown")

        # Shebang inspection for extensionless or generic files
        if lang in ("unknown", "text") and sample_content.startswith("#!"):
            first_line = sample_content.splitlines()[0].lower()
            if "python" in first_line:
                return "python", "code"
            if "node" in first_line:
                return "javascript", "code"
            if "bash" in first_line or "sh" in first_line or "zsh" in first_line:
                return "shell", "code"

        # Categorize
        if lang in ("luau", "lua", "python", "typescript", "javascript", "rust", "go", "sql", "shell", "html", "css", "scss"):
            return lang, "code"
        elif lang == "roblox_xml":
            return "roblox_xml", "code"
        elif lang in ("json", "yaml"):
            return lang, "project_metadata"
        elif lang == "toml":
            return lang, "dependency_manifest"
        elif lang in ("markdown", "text"):
            return lang, "documentation"
        elif lang == "ini":
            return lang, "configuration"

        return lang, "text"


# ------------------------------------------------------------------------------
# 2. MULTI-LANGUAGE SYMBOL EXTRACTORS
# ------------------------------------------------------------------------------
class LuauSymbolExtractor:
    """Extracts function, type, service, require, and export declarations from Luau/Lua code."""

    FN_REGEX = re.compile(
        r'^\s*(?:local\s+)?function\s+([A-Za-z0-9_.:]+)\s*\(([^)]*)\)',
        re.MULTILINE
    )
    TYPE_REGEX = re.compile(
        r'^\s*(?:export\s+)?type\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*=',
        re.MULTILINE
    )
    SERVICE_REGEX = re.compile(
        r'game:(?:GetService|FindService)\(["\']([A-Za-z0-9_]+)["\']\)'
    )
    REQUIRE_REGEX = re.compile(
        r'(?:local\s+([A-Za-z0-9_]+)\s*=\s*)?require\(([^)]+)\)'
    )
    EVENT_REGEX = re.compile(
        r'([A-Za-z0-9_.:]+)\s*:\s*Connect\s*\('
    )
    REMOTE_DEF_REGEX = re.compile(
        r'Instance\.new\s*\(\s*["\'](RemoteEvent|RemoteFunction|BindableEvent|BindableFunction)["\']'
    )

    @classmethod
    def extract_symbols(cls, source: str) -> List[Dict[str, Any]]:
        symbols = []

        # Functions (methods, standalone, local)
        for m in cls.FN_REGEX.finditer(source):
            fn_name = m.group(1)
            params = m.group(2).strip()
            kind = "method" if (":" in fn_name or "." in fn_name) else "function"
            symbols.append({
                "kind": kind,
                "name": fn_name,
                "signature": f"{fn_name}({params})",
                "offset": m.start()
            })

        # Exported & local types
        for m in cls.TYPE_REGEX.finditer(source):
            type_name = m.group(1)
            is_exported = "export type" in source[max(0, m.start() - 10):m.end()]
            symbols.append({
                "kind": "type",
                "name": type_name,
                "signature": f"type {type_name}",
                "is_exported": is_exported,
                "offset": m.start()
            })

        # Services accessed
        services_seen = set()
        for m in cls.SERVICE_REGEX.finditer(source):
            svc = m.group(1)
            if svc not in services_seen:
                services_seen.add(svc)
                symbols.append({
                    "kind": "service_dependency",
                    "name": svc,
                    "signature": f"game:GetService('{svc}')",
                    "offset": m.start()
                })

        # Remote / Network Instances
        for m in cls.REMOTE_DEF_REGEX.finditer(source):
            remote_kind = m.group(1)
            symbols.append({
                "kind": "network_contract",
                "name": remote_kind,
                "signature": f"Instance.new('{remote_kind}')",
                "offset": m.start()
            })

        # Event connections
        for m in cls.EVENT_REGEX.finditer(source):
            target = m.group(1)
            symbols.append({
                "kind": "event_listener",
                "name": target,
                "signature": f"{target}:Connect(...)",
                "offset": m.start()
            })

        return symbols

    @classmethod
    def extract_requires(cls, source: str) -> List[Dict[str, str]]:
        """Extracts all require(...) statements and variable bindings."""
        requires = []
        for m in cls.REQUIRE_REGEX.finditer(source):
            var_name = m.group(1) or ""
            target_expr = m.group(2).strip().strip("'\"")
            requires.append({
                "variable": var_name,
                "target": target_expr
            })
        return requires

    @classmethod
    def classify_script_role(cls, rel_path: str) -> str:
        p_lower = rel_path.lower()
        if p_lower.endswith(".server.luau") or p_lower.endswith(".server.lua"):
            return "ServerScript"
        if p_lower.endswith(".client.luau") or p_lower.endswith(".client.lua"):
            return "LocalScript"
        if "server" in p_lower:
            return "ServerScript"
        if "client" in p_lower:
            return "LocalScript"
        return "ModuleScript"


class PythonSymbolExtractor:
    """AST-based symbol extractor for Python files, extracting classes, functions, decorators, and imports."""

    @classmethod
    def extract_symbols(cls, source: str) -> Tuple[List[Dict[str, Any]], List[str], List[str], str]:
        """
        Returns: (symbols, internal_imports, external_imports, module_docstring)
        """
        symbols: List[Dict[str, Any]] = []
        internal_imports: List[str] = []
        external_imports: List[str] = []
        module_docstring = ""

        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Fallback to regex on malformed or partial Python files
            return cls._fallback_regex_extract(source)

        module_docstring = ast.get_docstring(tree) or ""

        for node in tree.body:
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    external_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level > 0:
                    internal_imports.append(f"{'.' * node.level}{mod}")
                elif mod:
                    # Distinguish local relative modules from stdlib/3rd-party
                    if mod.startswith(".") or not any(mod.startswith(p) for p in ("os", "sys", "json", "time", "re", "math", "typing")):
                        internal_imports.append(mod)
                    else:
                        external_imports.append(mod)

            # Classes
            elif isinstance(node, ast.ClassDef):
                bases = [cls._node_name(b) for b in node.bases]
                decorators = [cls._node_name(d) for d in node.decorator_list]
                class_doc = ast.get_docstring(node) or ""

                class_sym = {
                    "kind": "class",
                    "name": node.name,
                    "signature": f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                    "bases": bases,
                    "decorators": decorators,
                    "docstring": class_doc[:200],
                    "line": node.lineno
                }
                symbols.append(class_sym)

                # Class methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_decorators = [cls._node_name(d) for d in item.decorator_list]
                        m_args = [a.arg for a in item.args.args]
                        is_async = isinstance(item, ast.AsyncFunctionDef)
                        symbols.append({
                            "kind": "method",
                            "name": f"{node.name}.{item.name}",
                            "parent_class": node.name,
                            "signature": f"{'async ' if is_async else ''}def {item.name}({', '.join(m_args)})",
                            "is_async": is_async,
                            "decorators": m_decorators,
                            "line": item.lineno
                        })

            # Standalone Functions
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_decorators = [cls._node_name(d) for d in node.decorator_list]
                fn_args = [a.arg for a in node.args.args]
                is_async = isinstance(node, ast.AsyncFunctionDef)
                symbols.append({
                    "kind": "function",
                    "name": node.name,
                    "signature": f"{'async ' if is_async else ''}def {node.name}({', '.join(fn_args)})",
                    "is_async": is_async,
                    "decorators": fn_decorators,
                    "line": node.lineno
                })

        return symbols, internal_imports, external_imports, module_docstring

    @staticmethod
    def _node_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{PythonSymbolExtractor._node_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return PythonSymbolExtractor._node_name(node.func)
        return ""

    @classmethod
    def _fallback_regex_extract(cls, source: str) -> Tuple[List[Dict[str, Any]], List[str], List[str], str]:
        symbols = []
        imports = []
        for m in re.finditer(r'^\s*class\s+([A-Za-z0-9_]+)(?:\(([^)]*)\))?:', source, re.MULTILINE):
            symbols.append({
                "kind": "class",
                "name": m.group(1),
                "signature": f"class {m.group(1)}({m.group(2) or ''})"
            })
        for m in re.finditer(r'^\s*(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(([^)]*)\):', source, re.MULTILINE):
            symbols.append({
                "kind": "function",
                "name": m.group(1),
                "signature": f"def {m.group(1)}({m.group(2).strip()})"
            })
        for m in re.finditer(r'^\s*(?:from\s+([A-Za-z0-9_.]+)\s+import|import\s+([A-Za-z0-9_.]+))', source, re.MULTILINE):
            mod = m.group(1) or m.group(2)
            if mod:
                imports.append(mod)
        return symbols, imports, [], ""


class TypeScriptSymbolExtractor:
    """Extracts classes, interfaces, types, functions, exports, and imports from TypeScript/JavaScript."""

    CLASS_REGEX = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_]+)(?:\s+extends\s+([A-Za-z0-9_]+))?(?:\s+implements\s+([^{]+))?', re.MULTILINE)
    INTERFACE_REGEX = re.compile(r'^\s*(?:export\s+)?interface\s+([A-Za-z0-9_]+)(?:\s+extends\s+([^{]+))?', re.MULTILINE)
    TYPE_ALIAS_REGEX = re.compile(r'^\s*(?:export\s+)?type\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*=', re.MULTILINE)
    FN_REGEX = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', re.MULTILINE)
    CONST_FN_REGEX = re.compile(r'^\s*(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>', re.MULTILINE)
    IMPORT_REGEX = re.compile(r'import\s+(?:(?:\{[^}]*\}|\*\s+as\s+[A-Za-z0-9_]+|[A-Za-z0-9_]+)\s+from\s+)?["\']([^"\']+)["\']')
    REQUIRE_REGEX = re.compile(r'require\(["\']([^"\']+)["\']\)')

    @classmethod
    def extract_symbols(cls, source: str) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        symbols = []
        internal_imports = []
        external_imports = []

        # Classes
        for m in cls.CLASS_REGEX.finditer(source):
            c_name = m.group(1)
            ext_name = m.group(2) or ""
            sig = f"class {c_name} extends {ext_name}" if ext_name else f"class {c_name}"
            symbols.append({"kind": "class", "name": c_name, "signature": sig, "offset": m.start()})

        # Interfaces
        for m in cls.INTERFACE_REGEX.finditer(source):
            i_name = m.group(1)
            symbols.append({"kind": "interface", "name": i_name, "signature": f"interface {i_name}", "offset": m.start()})

        # Type aliases
        for m in cls.TYPE_ALIAS_REGEX.finditer(source):
            t_name = m.group(1)
            symbols.append({"kind": "type", "name": t_name, "signature": f"type {t_name}", "offset": m.start()})

        # Functions
        for m in cls.FN_REGEX.finditer(source):
            fn_name = m.group(1)
            params = m.group(2).strip()
            symbols.append({"kind": "function", "name": fn_name, "signature": f"function {fn_name}({params})", "offset": m.start()})

        # Arrow functions
        for m in cls.CONST_FN_REGEX.finditer(source):
            fn_name = m.group(1)
            params = m.group(2).strip()
            symbols.append({"kind": "function", "name": fn_name, "signature": f"const {fn_name} = ({params}) =>", "offset": m.start()})

        # Imports & requires
        for m in cls.IMPORT_REGEX.finditer(source):
            target = m.group(1)
            if target.startswith("."):
                internal_imports.append(target)
            else:
                external_imports.append(target)

        for m in cls.REQUIRE_REGEX.finditer(source):
            target = m.group(1)
            if target.startswith("."):
                internal_imports.append(target)
            else:
                external_imports.append(target)

        return symbols, internal_imports, external_imports


class RobloxXmlExtractor:
    """Parses Roblox XML (.rbxmx / .rbxlx) models and places, extracting instances and embedded scripts."""

    @classmethod
    def parse_xml_model(cls, content: str) -> Tuple[List[Dict[str, Any]], str]:
        """
        Parses XML content and extracts structural instances and embedded Luau scripts.
        Returns: (symbols_and_instances, extracted_text_representation)
        """
        instances = []
        text_lines = []

        try:
            root = ET.fromstring(content)
        except ET.ParseError as pe:
            raise ValueError(f"Malformed Roblox XML: {pe}")

        # Traverse Items
        for item in root.iter("Item"):
            class_name = item.attrib.get("class", "UnknownClass")
            props = item.find("Properties")
            name = "Unnamed"
            source = ""

            if props is not None:
                # Name property
                name_elem = props.find("./string[@name='Name']")
                if name_elem is not None and name_elem.text:
                    name = name_elem.text

                # Script source
                source_elem = props.find("./ProtectedString[@name='Source']")
                if source_elem is not None and source_elem.text:
                    source = source_elem.text.strip()

            inst_info = {
                "kind": "roblox_instance",
                "class_name": class_name,
                "name": name,
                "has_script": bool(source)
            }
            instances.append(inst_info)
            text_lines.append(f"Instance: {name} (Class: {class_name})")

            if source:
                # Extract symbols from embedded script
                extracted_syms = LuauSymbolExtractor.extract_symbols(source)
                for s in extracted_syms:
                    instances.append({
                        "kind": f"embedded_{s['kind']}",
                        "name": f"{name}::{s['name']}",
                        "signature": s.get("signature", ""),
                        "parent_instance": name
                    })
                text_lines.append(f"  Embedded Script ({len(source.splitlines())} lines): {name}")

        return instances, "\n".join(text_lines[:200])


# ------------------------------------------------------------------------------
# 3. MANIFEST & DEPENDENCY PARSERS
# ------------------------------------------------------------------------------
class DependencyManifestParser:
    """Parses project manifests: package.json, wally.toml, pyproject.toml, requirements.txt, Cargo.toml."""

    @classmethod
    def parse_package_json(cls, content: str) -> Dict[str, Any]:
        try:
            data = json.loads(content)
            return {
                "name": data.get("name", ""),
                "version": data.get("version", ""),
                "scripts": list(data.get("scripts", {}).keys()),
                "dependencies": list(data.get("dependencies", {}).keys()),
                "devDependencies": list(data.get("devDependencies", {}).keys()),
                "framework": "react" if "react" in data.get("dependencies", {}) else ("vue" if "vue" in data.get("dependencies", {}) else "")
            }
        except Exception:
            return {}

    @classmethod
    def parse_wally_toml(cls, content: str) -> Dict[str, Any]:
        """Extracts Wally package dependencies for Roblox experiences."""
        pkg_name = ""
        deps = []
        server_deps = []
        dev_deps = []

        current_section = ""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if "=" in line:
                key, val = [p.strip() for p in line.split("=", 1)]
                if current_section == "package" and key == "name":
                    pkg_name = val.strip('"\'')
                elif current_section == "dependencies":
                    deps.append(val.strip('"\''))
                elif current_section == "server-dependencies":
                    server_deps.append(val.strip('"\''))
                elif current_section == "dev-dependencies":
                    dev_deps.append(val.strip('"\''))

        return {
            "package_name": pkg_name,
            "dependencies": deps,
            "server_dependencies": server_deps,
            "dev_dependencies": dev_deps
        }

    @classmethod
    def parse_requirements_txt(cls, content: str) -> List[str]:
        reqs = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[><=~;\[]", line)[0].strip()
            if pkg:
                reqs.append(pkg)
        return reqs

    @classmethod
    def parse_cargo_toml(cls, content: str) -> Dict[str, Any]:
        pkg_name = ""
        deps = []
        current_section = ""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if "=" in line:
                key, val = [p.strip() for p in line.split("=", 1)]
                if current_section == "package" and key == "name":
                    pkg_name = val.strip('"\'')
                elif current_section == "dependencies":
                    deps.append(key)
        return {"package_name": pkg_name, "dependencies": deps}


# ------------------------------------------------------------------------------
# 4. ROBLOX PROJECT RESOLVER (ROJO & DATAMODEL)
# ------------------------------------------------------------------------------
class RobloxProjectResolver:
    """
    Parses Rojo project files (default.project.json), maps filesystem paths to
    Roblox DataModel containers, and resolves Roblox-style requires.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.datamodel_map: Dict[str, str] = {}  # "ServerScriptService" -> "src/server"
        self.inverse_map: Dict[str, str] = {}    # "src/server" -> "ServerScriptService"
        self.project_name: str = ""
        self._load_rojo()

    def _load_rojo(self):
        rojo_file = self.workspace_root / "default.project.json"
        if not rojo_file.exists():
            rojo_file = self.workspace_root / "rojo.json"
        if not rojo_file.exists():
            return

        try:
            with open(rojo_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.project_name = data.get("name", "")
            tree = data.get("tree", {})
            self._traverse_tree(tree, [])
        except Exception:
            pass

    def _traverse_tree(self, node: Any, path_acc: List[str]):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if key == "$path" and isinstance(val, str):
                dm_path = ".".join(path_acc)
                self.datamodel_map[dm_path] = val
                self.inverse_map[val] = dm_path
            elif not key.startswith("$"):
                self._traverse_tree(val, path_acc + [key])

    def resolve_require(self, require_expr: str, current_file: str) -> Optional[str]:
        """
        Translates a Roblox require expression (e.g. 'ReplicatedStorage.Shared.Combat')
        into a workspace relative file path ('src/shared/Combat.luau').
        """
        expr = require_expr.strip()

        # Handle script.Parent or script.Child
        if expr.startswith("script."):
            cur_dir = Path(current_file).parent
            parts = expr.split(".")
            target_path = cur_dir
            for p in parts[1:]:
                if p == "Parent":
                    target_path = target_path.parent
                else:
                    target_path = target_path / p
            for cand in (f"{target_path}.luau", f"{target_path}.lua", f"{target_path}/init.luau", f"{target_path}/init.lua"):
                cand_clean = str(cand).replace("\\", "/")
                if (self.workspace_root / cand_clean).exists():
                    return cand_clean

        # Handle DataModel containers: ReplicatedStorage.Shared.Module
        parts = expr.split(".")
        if parts:
            first = parts[0]
            # Match top-level or nested container
            for dm_key, fs_root in self.datamodel_map.items():
                if dm_key == first or dm_key.endswith(f".{first}") or first in dm_key:
                    sub_path = "/".join(parts[1:])
                    cand_base = f"{fs_root}/{sub_path}".strip("/")
                    for ext in (".luau", ".lua", "/init.luau", "/init.lua"):
                        full_cand = f"{cand_base}{ext}"
                        if (self.workspace_root / full_cand).exists():
                            return full_cand
        return None


# ------------------------------------------------------------------------------
# 5. DEPENDENCY GRAPH & IMPACT RADIUS
# ------------------------------------------------------------------------------
class ProjectDependencyGraph:
    """
    Maintains file-to-file dependency graph, reverse dependents, external libraries,
    and calculates impact radius for safe refactoring and deep agent context.
    """

    def __init__(self):
        # file_path -> Set of files it directly imports/requires
        self.dependencies: Dict[str, Set[str]] = {}
        # file_path -> Set of files that import/require this file
        self.dependents: Dict[str, Set[str]] = {}
        # file_path -> Set of external package names
        self.external_imports: Dict[str, Set[str]] = {}
        # service_name -> Set of files accessing this service
        self.service_usage: Dict[str, Set[str]] = {}

    def add_dependency(self, from_file: str, to_target: str, is_external: bool = False):
        if is_external:
            self.external_imports.setdefault(from_file, set()).add(to_target)
            return

        self.dependencies.setdefault(from_file, set()).add(to_target)
        self.dependents.setdefault(to_target, set()).add(from_file)

    def record_service_access(self, service_name: str, file_path: str):
        self.service_usage.setdefault(service_name, set()).add(file_path)

    def remove_file(self, file_path: str):
        """Cleans up all references to a deleted or re-indexed file."""
        if file_path in self.dependencies:
            for dep in self.dependencies[file_path]:
                if dep in self.dependents:
                    self.dependents[dep].discard(file_path)
            del self.dependencies[file_path]

        if file_path in self.dependents:
            for caller in self.dependents[file_path]:
                if caller in self.dependencies:
                    self.dependencies[caller].discard(file_path)
            del self.dependents[file_path]

        self.external_imports.pop(file_path, None)

        for svc_files in self.service_usage.values():
            svc_files.discard(file_path)

    def get_dependencies(self, file_path: str) -> Dict[str, List[str]]:
        return {
            "internal": sorted(list(self.dependencies.get(file_path, set()))),
            "external": sorted(list(self.external_imports.get(file_path, set())))
        }

    def get_dependents(self, file_path: str) -> List[str]:
        return sorted(list(self.dependents.get(file_path, set())))

    def get_impact_radius(self, file_path: str, max_depth: int = 3) -> Dict[str, Any]:
        """
        Calculates all files affected by changes to `file_path` using BFS traversal
        over incoming dependents (callers).
        """
        visited: Dict[str, int] = {}
        queue: List[Tuple[str, int]] = [(file_path, 0)]

        while queue:
            curr, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            callers = self.dependents.get(curr, set())
            for caller in callers:
                if caller not in visited:
                    visited[caller] = depth + 1
                    queue.append((caller, depth + 1))

        # Group by distance
        levels: Dict[int, List[str]] = {}
        for f, d in visited.items():
            levels.setdefault(d, []).append(f)

        return {
            "target_file": file_path,
            "total_impacted_files": len(visited),
            "direct_callers": sorted(levels.get(1, [])),
            "secondary_callers": sorted(levels.get(2, [])),
            "tertiary_callers": sorted(levels.get(3, [])),
            "max_traversal_depth": max_depth
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dependencies": {k: sorted(list(v)) for k, v in self.dependencies.items()},
            "dependents": {k: sorted(list(v)) for k, v in self.dependents.items()},
            "external_imports": {k: sorted(list(v)) for k, v in self.external_imports.items()},
            "service_usage": {k: sorted(list(v)) for k, v in self.service_usage.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectDependencyGraph':
        g = cls()
        g.dependencies = {k: set(v) for k, v in data.get("dependencies", {}).items()}
        g.dependents = {k: set(v) for k, v in data.get("dependents", {}).items()}
        g.external_imports = {k: set(v) for k, v in data.get("external_imports", {}).items()}
        g.service_usage = {k: set(v) for k, v in data.get("service_usage", {}).items()}
        return g


# ------------------------------------------------------------------------------
# 6. GLOBAL SYMBOL TABLE
# ------------------------------------------------------------------------------
class ProjectSymbolTable:
    """Cross-project symbol catalog for fast discovery, references, and type lookup."""

    def __init__(self):
        # symbol_name -> List of symbol definitions
        self.symbols_by_name: Dict[str, List[Dict[str, Any]]] = {}
        # file_path -> List of symbol definitions declared in that file
        self.symbols_by_file: Dict[str, List[Dict[str, Any]]] = {}

    def index_file_symbols(self, rel_path: str, symbols: List[Dict[str, Any]]):
        self.remove_file_symbols(rel_path)
        self.symbols_by_file[rel_path] = symbols

        for sym in symbols:
            name = sym.get("name", "")
            if name:
                sym_with_file = dict(sym)
                sym_with_file["file"] = rel_path
                self.symbols_by_name.setdefault(name.lower(), []).append(sym_with_file)

    def remove_file_symbols(self, rel_path: str):
        old_syms = self.symbols_by_file.pop(rel_path, [])
        for sym in old_syms:
            name = sym.get("name", "").lower()
            if name in self.symbols_by_name:
                self.symbols_by_name[name] = [
                    s for s in self.symbols_by_name[name] if s.get("file") != rel_path
                ]
                if not self.symbols_by_name[name]:
                    del self.symbols_by_name[name]

    def find_symbol(self, name: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        query = name.strip().lower()
        results = self.symbols_by_name.get(query, [])
        if not results:
            # Substring match if exact match not found
            for k, sym_list in self.symbols_by_name.items():
                if query in k or k in query:
                    results.extend(sym_list)

        if kind:
            results = [s for s in results if s.get("kind") == kind]
        return results

    def get_symbols_for_file(self, rel_path: str) -> List[Dict[str, Any]]:
        return self.symbols_by_file.get(rel_path, [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbols_by_file": self.symbols_by_file
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectSymbolTable':
        st = cls()
        for f, syms in data.get("symbols_by_file", {}).items():
            st.index_file_symbols(f, syms)
        return st


# ------------------------------------------------------------------------------
# 7. PROJECT ARCHITECTURE SUMMARIZER
# ------------------------------------------------------------------------------
class ProjectArchitectureSummarizer:
    """
    Analyzes indexed files, manifests, Rojo maps, and symbols to produce
    comprehensive architectural summaries grounding AI agents.
    """

    @classmethod
    def summarize(
        cls,
        files: Dict[str, ProjectFileRecord],
        dependency_graph: ProjectDependencyGraph,
        roblox_resolver: Optional[RobloxProjectResolver] = None
    ) -> Dict[str, Any]:
        """Produces a structured architectural blueprint of the project."""
        total_files = len(files)
        lang_counts: Dict[str, int] = {}
        for rec in files.values():
            lang_counts[rec.language] = lang_counts.get(rec.language, 0) + 1

        # Determine Archetype
        has_rojo = any(p in files for p in ("default.project.json", "rojo.json"))
        has_wally = "wally.toml" in files
        has_pyproject = any(p in files for p in ("pyproject.toml", "requirements.txt", "setup.py"))
        has_pkg_json = "package.json" in files
        has_cargo = "Cargo.toml" in files

        archetype = "general_codebase"
        if has_rojo or has_wally or lang_counts.get("luau", 0) + lang_counts.get("roblox_xml", 0) > 0:
            archetype = "roblox_experience"
        elif has_pyproject and has_pkg_json:
            archetype = "fullstack_application"
        elif has_pyproject or lang_counts.get("python", 0) > (total_files * 0.4):
            archetype = "python_backend"
        elif has_pkg_json or (lang_counts.get("typescript", 0) + lang_counts.get("javascript", 0)) > (total_files * 0.4):
            archetype = "web_frontend"
        elif has_cargo or lang_counts.get("rust", 0) > 0:
            archetype = "rust_crate"

        # Detect entry points
        entry_points = []
        for p in files.keys():
            p_lower = p.lower()
            if p_lower in ("main.py", "app.py", "index.ts", "index.js", "src/main.rs", "src/index.ts"):
                entry_points.append(p)
            elif p_lower.endswith(".server.luau") or p_lower.endswith(".server.lua"):
                entry_points.append(p)

        # Detect structural layers
        layers: Dict[str, List[str]] = {
            "server": [],
            "client": [],
            "shared": [],
            "api_routes": [],
            "tests": [],
            "configs": []
        }
        for p, rec in files.items():
            p_lower = p.lower()
            if "server" in p_lower:
                layers["server"].append(p)
            elif "client" in p_lower or "starterplayer" in p_lower or "gui" in p_lower:
                layers["client"].append(p)
            elif "shared" in p_lower or "replicated" in p_lower or "common" in p_lower:
                layers["shared"].append(p)
            elif "route" in p_lower or "api" in p_lower or "endpoint" in p_lower:
                layers["api_routes"].append(p)
            elif "test" in p_lower or "spec" in p_lower:
                layers["tests"].append(p)
            elif rec.file_type in ("project_metadata", "dependency_manifest", "configuration"):
                layers["configs"].append(p)

        # External dependencies
        all_ext_deps: Set[str] = set()
        for deps in dependency_graph.external_imports.values():
            all_ext_deps.update(deps)

        # Core Roblox services used
        active_roblox_services = sorted(list(dependency_graph.service_usage.keys()))

        return {
            "archetype": archetype,
            "total_files": total_files,
            "language_distribution": lang_counts,
            "entry_points": sorted(entry_points)[:10],
            "structural_layers": {k: len(v) for k, v in layers.items()},
            "external_dependencies": sorted(list(all_ext_deps))[:25],
            "roblox_services_used": active_roblox_services[:15],
            "has_rojo": has_rojo,
            "has_wally": has_wally
        }

    @classmethod
    def generate_markdown_summary(cls, summary_data: Dict[str, Any], project_name: str) -> str:
        lines = [
            f"# Project Architecture Blueprint: `{project_name}`",
            f"**Archetype:** `{summary_data.get('archetype', 'unknown')}` | **Indexed Files:** {summary_data.get('total_files', 0)}",
            "",
            "## Language Breakdown"
        ]
        for lang, count in sorted(summary_data.get("language_distribution", {}).items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{lang.capitalize()}**: {count} file(s)")

        if summary_data.get("entry_points"):
            lines.append("\n## Primary Entry Points")
            for ep in summary_data["entry_points"]:
                lines.append(f"- `{ep}`")

        layers = summary_data.get("structural_layers", {})
        if any(layers.values()):
            lines.append("\n## Architectural Components & Layers")
            for lay, count in layers.items():
                if count > 0:
                    lines.append(f"- **{lay.capitalize()} Layer**: {count} file(s)")

        if summary_data.get("roblox_services_used"):
            lines.append("\n## Roblox Services Utilized")
            lines.append(f"> {', '.join(summary_data['roblox_services_used'])}")

        if summary_data.get("external_dependencies"):
            lines.append("\n## External Dependencies & Packages")
            lines.append(f"> {', '.join(summary_data['external_dependencies'][:20])}")

        return "\n".join(lines)


# ------------------------------------------------------------------------------
# 8. GITIGNORE & EXCLUSION MATCHER
# ------------------------------------------------------------------------------
class ProjectExclusionFilter:
    """Enforces .gitignore rules, secret file heuristics, and sensitive content detection."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.ignore_patterns: List[str] = list(DEFAULT_IGNORED_DIRS)
        self._load_gitignore()

    def _load_gitignore(self):
        gi_path = self.workspace_root / ".gitignore"
        if gi_path.exists() and gi_path.is_file():
            try:
                with open(gi_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        self.ignore_patterns.append(line.rstrip("/"))
            except Exception:
                pass

    def is_ignored_path(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/").strip("/")
        parts = norm.split("/")

        # Check default ignored dirs anywhere in hierarchy
        for part in parts:
            if part in DEFAULT_IGNORED_DIRS:
                return True

        for pat in self.ignore_patterns:
            pat_clean = pat.strip("/")
            if fnmatch.fnmatch(norm, pat_clean) or fnmatch.fnmatch(norm, f"*/{pat_clean}*"):
                return True
            for part in parts:
                if fnmatch.fnmatch(part, pat_clean):
                    return True
        return False

    def is_secret_filename(self, filename: str) -> bool:
        fn_lower = filename.lower()
        for pat in SECRET_NAME_PATTERNS:
            if re.match(pat, fn_lower):
                return True
        return False

    @staticmethod
    def contains_secrets(sample_bytes: bytes) -> bool:
        try:
            sample_text = sample_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return False
        for rx in SECRET_CONTENT_PATTERNS:
            if rx.search(sample_text):
                return True
        return False


# ------------------------------------------------------------------------------
# 9. AUTHORITATIVE PROJECT CONTEXT INDEX
# ------------------------------------------------------------------------------
class ProjectContextIndex:
    """
    Authoritative index for workspace contents, enabling genuine incremental
    indexing, multi-language symbol cataloging, dependency analysis, and bounded
    graph-aware lexical retrieval.
    """

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path: Path = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
        self.storage_dir = paths_service.get_app_data_dir()
        self.index_file = self.storage_dir / "project_context_index.json"
        self.legacy_context_file = Path(__file__).parent / "data" / "verified_project_context.json"
        self.files: Dict[str, ProjectFileRecord] = {}
        self.dependency_graph = ProjectDependencyGraph()
        self.symbol_table = ProjectSymbolTable()
        self.roblox_resolver = RobloxProjectResolver(self.workspace_path)
        self.last_indexed_at: float = 0.0
        self.project_name: str = self.workspace_path.name
        self.total_bytes: int = 0
        self._load_persisted()

    def _load_persisted(self):
        """Loads existing index cache if present."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("workspace_path") == str(self.workspace_path):
                    self.last_indexed_at = data.get("last_indexed_at", 0.0)
                    self.project_name = data.get("project_name", self.workspace_path.name)
                    records = data.get("files", {})
                    self.files = {p: ProjectFileRecord.from_dict(r) for p, r in records.items()}
                    self.total_bytes = sum(f.size_bytes for f in self.files.values())
                    if "dependency_graph" in data:
                        self.dependency_graph = ProjectDependencyGraph.from_dict(data["dependency_graph"])
                    else:
                        self._rebuild_graphs()
                    if "symbols" in data:
                        self.symbol_table = ProjectSymbolTable.from_dict(data["symbols"])
                    else:
                        for p, rec in self.files.items():
                            self.symbol_table.index_file_symbols(p, rec.symbols)
            except Exception as e:
                print(f"[ProjectContext] Error reading persisted index: {e}", flush=True)

    def _rebuild_graphs(self):
        """Rebuilds symbol table and dependency graph from loaded records."""
        self.dependency_graph = ProjectDependencyGraph()
        self.symbol_table = ProjectSymbolTable()
        for p, rec in self.files.items():
            self.symbol_table.index_file_symbols(p, rec.symbols)
            for dep in rec.dependencies:
                self.dependency_graph.add_dependency(p, dep, is_external=False)
            for ext in rec.external_imports:
                self.dependency_graph.add_dependency(p, ext, is_external=True)

    def persist(self):
        """Persists index to per-user storage and mirrors summary to verified_project_context.json."""
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "workspace_path": str(self.workspace_path),
                "project_name": self.project_name,
                "last_indexed_at": self.last_indexed_at,
                "total_files": len(self.files),
                "total_bytes": sum(f.size_bytes for f in self.files.values()),
                "files": {p: f.to_dict() for p, f in self.files.items()},
                "dependency_graph": self.dependency_graph.to_dict(),
                "symbols": self.symbol_table.to_dict()
            }
            tmp = self.index_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.index_file)

            # Mirror to legacy verified_project_context.json for backward compatibility
            self.legacy_context_file.parent.mkdir(parents=True, exist_ok=True)
            summary_records = []
            for p, rec in sorted(self.files.items(), key=lambda x: x[0])[:50]:
                summary_records.append({
                    "id": f"CTX-{rec.content_hash[:8]}",
                    "path": rec.relative_path,
                    "type": rec.file_type,
                    "bytes": rec.size_bytes,
                    "symbols_count": len(rec.symbols),
                    "summary": rec.summary or f"{rec.file_type} file at {rec.relative_path}"
                })
            with open(self.legacy_context_file, "w", encoding="utf-8") as f:
                json.dump(summary_records, f, indent=2)
        except Exception as e:
            print(f"[ProjectContext] Could not persist index: {e}", flush=True)

    def is_binary(self, sample: bytes) -> bool:
        """Determines if content is binary via null byte detection and UTF-8 decodability."""
        if b"\x00" in sample:
            return True
        try:
            sample.decode("utf-8")
            return False
        except UnicodeDecodeError:
            return True

    def scan_and_index(self) -> Dict[str, Any]:
        """
        Executes a complete incremental scan of the approved workspace directory.
        Ingests actual file contents, extracts symbols, maps dependencies, and
        returns comprehensive indexing statistics.
        """
        t0 = time.time()
        filter_engine = ProjectExclusionFilter(workspace_root=self.workspace_path)

        total_scanned = 0
        indexed_count = 0
        skipped_count = 0
        added_count = 0
        modified_count = 0
        unchanged_count = 0
        deleted_count = 0

        skipped_files: List[Dict[str, str]] = []
        found_relative_paths: Set[str] = set()
        running_total_bytes = 0

        if not self.workspace_path.exists() or not self.workspace_path.is_dir():
            return {
                "status": "error",
                "message": f"Workspace directory not found: {self.workspace_path}",
                "indexed_count": 0
            }

        # Refresh Rojo resolver
        self.roblox_resolver = RobloxProjectResolver(self.workspace_path)

        # Traverse directory
        for root, dirs, files in os.walk(self.workspace_path):
            # Check timeout
            if time.time() - t0 > INDEX_TIMEOUT_SECONDS:
                skipped_files.append({"path": str(root), "reason": "index_job_timeout"})
                break

            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if not filter_engine.is_ignored_path(os.path.relpath(os.path.join(root, d), self.workspace_path))]

            for fname in sorted(files):
                full_path = Path(root) / fname
                try:
                    rel_path = str(full_path.relative_to(self.workspace_path)).replace("\\", "/")
                except ValueError:
                    rel_path = fname

                total_scanned += 1

                # 1. Check gitignore & path exclusion
                if filter_engine.is_ignored_path(rel_path):
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "gitignore_match"})
                    continue

                # 2. Check secret filename
                if filter_engine.is_secret_filename(fname):
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "secret_or_credential"})
                    continue

                # 3. Check extension support
                ext = full_path.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS and fname not in LanguageDetector.SPECIAL_FILENAMES:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "unsupported_extension"})
                    continue

                # 4. Check file limits
                try:
                    st = full_path.stat()
                except OSError as e:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": f"stat_error: {e}"})
                    continue

                if st.st_size > MAX_PER_FILE_BYTES:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": f"oversized_file ({st.st_size} bytes > {MAX_PER_FILE_BYTES})"})
                    continue

                if running_total_bytes + st.st_size > MAX_TOTAL_INDEX_BYTES:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "total_index_capacity_exceeded"})
                    continue

                if len(found_relative_paths) >= MAX_INDEXED_FILES:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "max_file_count_reached"})
                    continue

                # 5. Read file bytes
                try:
                    with open(full_path, "rb") as f:
                        file_bytes = f.read()
                except Exception as e:
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": f"read_error: {e}"})
                    continue

                # 6. Binary check
                sample_chunk = file_bytes[:4096]
                if self.is_binary(sample_chunk):
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "binary_file"})
                    continue

                # 7. Content secret check
                if ProjectExclusionFilter.contains_secrets(sample_chunk):
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": "secret_or_credential"})
                    continue

                # Compute content hash
                content_hash = hashlib.sha256(file_bytes).hexdigest()
                found_relative_paths.add(rel_path)

                # Incremental Hash Check: is file unchanged?
                existing = self.files.get(rel_path)
                if existing and existing.content_hash == content_hash:
                    unchanged_count += 1
                    indexed_count += 1
                    running_total_bytes += existing.size_bytes
                    continue

                # Decode text
                try:
                    text_content = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text_content = file_bytes.decode("latin-1")
                    except Exception as de:
                        skipped_count += 1
                        skipped_files.append({"path": rel_path, "reason": f"decode_error: {de}"})
                        continue

                # Language Detection
                lang, category = LanguageDetector.detect_language(rel_path, text_content[:200])

                # Parse specific file types
                symbols: List[Dict[str, Any]] = []
                file_type = category
                summary = ""
                internal_deps: List[str] = []
                ext_deps: List[str] = []
                docstring = ""

                try:
                    if ext in (".luau", ".lua") or lang in ("luau", "lua"):
                        role = LuauSymbolExtractor.classify_script_role(rel_path)
                        file_type = f"luau_{role.lower()}"
                        symbols = LuauSymbolExtractor.extract_symbols(text_content)
                        fn_names = [s["name"] for s in symbols if s["kind"] in ("function", "method")][:5]
                        summary = f"{role} ({len(text_content.splitlines())} lines). Declares: {', '.join(fn_names) if fn_names else 'variables/logic'}"

                        # Extract requires & Roblox services
                        requires = LuauSymbolExtractor.extract_requires(text_content)
                        for r in requires:
                            resolved = self.roblox_resolver.resolve_require(r["target"], rel_path)
                            if resolved:
                                internal_deps.append(resolved)
                            else:
                                ext_deps.append(r["target"])

                        for s in symbols:
                            if s["kind"] == "service_dependency":
                                self.dependency_graph.record_service_access(s["name"], rel_path)

                    elif ext in (".rbxmx", ".rbxlx") or lang == "roblox_xml":
                        file_type = "roblox_xml"
                        instances, rep_text = RobloxXmlExtractor.parse_xml_model(text_content)
                        symbols = instances
                        summary = f"Roblox XML Model with {len(instances)} instances."
                        text_content = rep_text

                    elif ext in (".py", ".pyi") or lang == "python":
                        file_type = "python_code"
                        symbols, py_internal, py_external, docstring = PythonSymbolExtractor.extract_symbols(text_content)
                        internal_deps.extend(py_internal)
                        ext_deps.extend(py_external)
                        fn_names = [s["name"] for s in symbols if s["kind"] in ("function", "method", "class")][:5]
                        summary = f"Python module ({len(text_content.splitlines())} lines). Declares: {', '.join(fn_names) if fn_names else 'module code'}"

                    elif ext in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs") or lang in ("typescript", "javascript"):
                        file_type = f"{lang}_code"
                        symbols, js_internal, js_external = TypeScriptSymbolExtractor.extract_symbols(text_content)
                        # Resolve relative JS/TS imports
                        for imp in js_internal:
                            cand_dir = Path(rel_path).parent
                            cand = (cand_dir / imp).as_posix()
                            internal_deps.append(cand)
                        ext_deps.extend(js_external)
                        names = [s["name"] for s in symbols if s["kind"] in ("class", "interface", "function")][:5]
                        summary = f"{lang.capitalize()} code ({len(text_content.splitlines())} lines). Declares: {', '.join(names) if names else 'logic'}"

                    elif ext == ".json" or fname in ("default.project.json", "rojo.json"):
                        file_type = "project_metadata"
                        if fname == "package.json":
                            pkg_info = DependencyManifestParser.parse_package_json(text_content)
                            ext_deps.extend(pkg_info.get("dependencies", []))
                            summary = f"Node package '{pkg_info.get('name')}' v{pkg_info.get('version')} ({len(ext_deps)} dependencies)"
                        else:
                            summary = f"Project config / JSON metadata ({len(text_content)} chars)"

                    elif ext == ".toml" or fname == "wally.toml":
                        file_type = "dependency_manifest"
                        if fname == "wally.toml":
                            wally_info = DependencyManifestParser.parse_wally_toml(text_content)
                            ext_deps.extend(wally_info.get("dependencies", []))
                            ext_deps.extend(wally_info.get("server_dependencies", []))
                            summary = f"Wally manifest '{wally_info.get('package_name')}' with {len(ext_deps)} dependencies"
                        elif fname == "Cargo.toml":
                            cargo_info = DependencyManifestParser.parse_cargo_toml(text_content)
                            ext_deps.extend(cargo_info.get("dependencies", []))
                            summary = f"Rust crate '{cargo_info.get('package_name')}' with {len(ext_deps)} dependencies"
                        else:
                            summary = f"TOML manifest / config ({len(text_content)} chars)"

                    elif fname == "requirements.txt":
                        file_type = "dependency_manifest"
                        ext_deps.extend(DependencyManifestParser.parse_requirements_txt(text_content))
                        summary = f"Python requirements ({len(ext_deps)} packages)"

                    elif ext in (".md", ".txt", ".rst") or category == "documentation":
                        file_type = "documentation"
                        summary = f"Documentation ({len(text_content.splitlines())} lines)"

                except Exception as parse_err:
                    # Individual file parsing failure must not crash the job
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": f"parse_error: {parse_err}"})
                    continue

                # Register in Symbol Table
                self.symbol_table.index_file_symbols(rel_path, symbols)

                # Register in Dependency Graph
                self.dependency_graph.remove_file(rel_path)
                for dep in internal_deps:
                    self.dependency_graph.add_dependency(rel_path, dep, is_external=False)
                for dep in ext_deps:
                    self.dependency_graph.add_dependency(rel_path, dep, is_external=True)

                # Create or update record
                is_mod = rel_path in self.files
                record = ProjectFileRecord(
                    relative_path=rel_path,
                    content_hash=content_hash,
                    size_bytes=len(file_bytes),
                    modified_at=st.st_mtime,
                    file_type=file_type,
                    content=text_content,
                    symbols=symbols,
                    summary=summary,
                    language=lang,
                    dependencies=internal_deps,
                    external_imports=ext_deps,
                    docstring=docstring
                )
                self.files[rel_path] = record
                indexed_count += 1
                running_total_bytes += len(file_bytes)

                if is_mod:
                    modified_count += 1
                else:
                    added_count += 1

        # Incremental pruning: remove deleted files
        current_tracked = set(self.files.keys())
        deleted_paths = current_tracked - found_relative_paths
        for del_p in deleted_paths:
            del self.files[del_p]
            self.symbol_table.remove_file_symbols(del_p)
            self.dependency_graph.remove_file(del_p)
            deleted_count += 1

        self.last_indexed_at = time.time()
        self.total_bytes = running_total_bytes
        self.persist()

        duration_ms = round((time.time() - t0) * 1000, 2)
        return {
            "status": "success",
            "workspace_path": str(self.workspace_path),
            "project_name": self.project_name,
            "total_scanned": total_scanned,
            "indexed_count": indexed_count,
            "skipped_count": skipped_count,
            "added_count": added_count,
            "modified_count": modified_count,
            "unchanged_count": unchanged_count,
            "deleted_count": deleted_count,
            "total_bytes": running_total_bytes,
            "skipped_files": skipped_files[:50],
            "duration_ms": duration_ms
        }

    # --------------------------------------------------------------------------
    # TARGETED & GRAPH-AWARE CONTEXT RETRIEVAL (BM25 + SYMBOL + DEPENDENCIES)
    # --------------------------------------------------------------------------
    def retrieve_context(
        self,
        query: str,
        max_results: int = 5,
        max_total_chars: int = 12_000,
        expand_dependencies: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top relevant files and symbol snippets using BM25 lexical
        similarity, symbol boosting, and dependency contract expansion without
        flooding prompts.
        """
        if not self.files or not query.strip():
            return []

        # Tokenize query
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}", query)]
        if not tokens:
            return []

        scored_results: List[Tuple[float, ProjectFileRecord, List[Dict[str, Any]]]] = []

        for rel_path, rec in self.files.items():
            score = 0.0
            matched_symbols = []
            rel_lower = rel_path.lower()

            # Path matches (high boost)
            for tok in tokens:
                if tok in rel_lower:
                    score += 5.0
                if tok in rec.file_type or tok in rec.language:
                    score += 2.0

            # Symbol matches (critical boost)
            for sym in rec.symbols:
                s_name = sym.get("name", "").lower()
                s_sig = sym.get("signature", "").lower()
                matched = False
                for tok in tokens:
                    if tok in s_name:
                        score += 8.0
                        matched = True
                    elif tok in s_sig:
                        score += 4.0
                        matched = True
                if matched and sym not in matched_symbols:
                    matched_symbols.append(sym)

            # Content frequency
            content_lower = rec.content.lower()
            for tok in tokens:
                count = content_lower.count(tok)
                if count > 0:
                    import math
                    score += 1.0 + math.log(count)

            if score > 0.5:
                scored_results.append((score, rec, matched_symbols))

        # Sort by relevance score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)

        selected = []
        char_count = 0
        visited_paths: Set[str] = set()

        for score, rec, syms in scored_results[:max_results]:
            visited_paths.add(rec.relative_path)
            snippet = rec.content
            if len(snippet) > 2500:
                snippet = snippet[:2500] + "\n...[file truncated for context]"

            if char_count + len(snippet) > max_total_chars and selected:
                break

            char_count += len(snippet)

            # Contract signatures from imported dependencies
            imported_contracts = []
            if expand_dependencies and rec.dependencies:
                for dep_path in rec.dependencies:
                    dep_rec = self.files.get(dep_path)
                    if dep_rec and dep_rec.symbols:
                        exported = [
                            s.get("signature") or s.get("name")
                            for s in dep_rec.symbols
                            if s.get("is_exported") or s.get("kind") in ("function", "method", "class", "type")
                        ][:4]
                        if exported:
                            imported_contracts.append({
                                "module": dep_path,
                                "signatures": exported
                            })

            selected.append({
                "path": rec.relative_path,
                "file_type": rec.file_type,
                "language": rec.language,
                "score": round(score, 2),
                "matched_symbols": [s.get("name") for s in syms[:4]],
                "matched_signatures": [s.get("signature") or s.get("name") for s in syms[:4]],
                "summary": rec.summary,
                "dependencies": rec.dependencies,
                "imported_contracts": imported_contracts,
                "snippet": snippet
            })

        return selected

    def get_architecture_summary(self, markdown: bool = False) -> Any:
        """Generates architectural blueprint of the current project."""
        raw_summary = ProjectArchitectureSummarizer.summarize(
            files=self.files,
            dependency_graph=self.dependency_graph,
            roblox_resolver=self.roblox_resolver
        )
        if markdown:
            return ProjectArchitectureSummarizer.generate_markdown_summary(raw_summary, self.project_name)
        return raw_summary

    def get_dependencies_for_file(self, file_path: str) -> Dict[str, Any]:
        """Returns outgoing dependencies, incoming callers, and impact radius for a given file."""
        return {
            "file": file_path,
            "dependencies": self.dependency_graph.get_dependencies(file_path),
            "dependents": self.dependency_graph.get_dependents(file_path),
            "impact_radius": self.dependency_graph.get_impact_radius(file_path)
        }

    def find_symbol(self, name: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        """Finds symbol declarations across all indexed files."""
        return self.symbol_table.find_symbol(name, kind=kind)

    def format_context_prompt_block(self, query: str) -> str:
        """Formats retrieved context records as an authentic markdown prompt block."""
        results = self.retrieve_context(query)
        if not results:
            return ""

        lines = [
            "### Relevant Project Context (Indexed from Workspace)",
            f"> Source Workspace: `{self.project_name}` ({len(self.files)} active files)",
            ""
        ]

        for item in results:
            lines.append(f"#### File: `{item['path']}` ({item['file_type']})")
            if item.get("matched_symbols"):
                lines.append(f"**Matched Symbols:** {', '.join(item['matched_symbols'])}")
            if item.get("imported_contracts"):
                lines.append("**Imported Module Contracts:**")
                for contract in item["imported_contracts"]:
                    lines.append(f"- `{contract['module']}`: {', '.join(contract['signatures'])}")

            fence_lang = item.get("language") or ("luau" if "luau" in item['file_type'] else "")
            lines.append(f"```{fence_lang}")
            lines.append(item["snippet"])
            lines.append("```\n")

        return "\n".join(lines)


# Singleton Project Index Registry
_ACTIVE_PROJECT_INDEX: Optional[ProjectContextIndex] = None


def get_project_index(workspace_path: Optional[str] = None) -> ProjectContextIndex:
    """Returns the singleton project context index for the active workspace."""
    global _ACTIVE_PROJECT_INDEX
    if workspace_path:
        target = str(Path(workspace_path).resolve())
        if _ACTIVE_PROJECT_INDEX is None or str(_ACTIVE_PROJECT_INDEX.workspace_path) != target:
            _ACTIVE_PROJECT_INDEX = ProjectContextIndex(workspace_path=target)
        return _ACTIVE_PROJECT_INDEX

    if _ACTIVE_PROJECT_INDEX is not None:
        return _ACTIVE_PROJECT_INDEX

    target = str(Path.cwd().resolve())
    _ACTIVE_PROJECT_INDEX = ProjectContextIndex(workspace_path=target)
    return _ACTIVE_PROJECT_INDEX
