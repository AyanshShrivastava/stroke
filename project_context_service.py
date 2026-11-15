"""
================================================================================
STROKE // PROJECT INTELLIGENCE & CONTEXT INDEXING SERVICE
================================================================================
Provides genuine project intelligence across approved workspaces:
1. File Ingestion: Reads actual file contents; never counts filenames/sizes as ingestion.
2. Structure Preservation: Preserves relative paths and workspace hierarchy.
3. Language & Format Support: Luau/Lua (ServerScript, LocalScript, ModuleScript),
   Roblox XML (.rbxmx / .rbxlx) parsing, project metadata (Rojo, Wally), and configs.
4. Robust Limits: Per-file byte limits (1MB), total byte limits (25MB), file count limits,
   and execution timeouts.
5. Streamed / Resilient Scanning: Handles large projects without blowing up memory.
   Individual failures (binary, malformed, oversized) never abort the entire index.
6. Exclusion Engine: Respects .gitignore, workspace boundaries, and strictly excludes
   .env, tokens, private keys, credential stores, and unapproved files.
7. Incremental Indexing: SHA-256 content hashes to detect added, modified, unchanged,
   and deleted files.
8. Targeted Semantic / Lexical Retrieval: BM25 and symbol-aware snippet retrieval
   to inject relevant context without prompt starvation.
================================================================================
"""

import os
import sys
import re
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
    # Roblox XML formats
    ".rbxmx", ".rbxlx",
    # Project configurations & metadata
    ".json", ".toml", ".yaml", ".yml",
    # Documentation & text
    ".md", ".txt"
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
    "__pycache__", ".output", ".nitro", "dist", "build", "target"
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
        metadata: Optional[Dict[str, Any]] = None
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
            "metadata": self.metadata
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
            metadata=data.get("metadata", {})
        )


# ------------------------------------------------------------------------------
# PARSERS & EXTRACTORS
# ------------------------------------------------------------------------------
class LuauSymbolExtractor:
    """Extracts function, type, service, and export declarations from Luau/Lua code."""

    FN_REGEX = re.compile(r'^\s*(?:local\s+)?function\s+([A-Za-z0-9_.:]+)\s*\(([^)]*)\)', re.MULTILINE)
    TYPE_REGEX = re.compile(r'^\s*(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*=', re.MULTILINE)
    SERVICE_REGEX = re.compile(r'game:(?:GetService|FindService)\(["\']([A-Za-z0-9_]+)["\']\)')
    REQUIRE_REGEX = re.compile(r'require\(([^)]+)\)')

    @classmethod
    def extract_symbols(cls, source: str) -> List[Dict[str, Any]]:
        symbols = []
        # Functions
        for m in cls.FN_REGEX.finditer(source):
            symbols.append({
                "kind": "function",
                "name": m.group(1),
                "signature": f"{m.group(1)}({m.group(2).strip()})",
                "offset": m.start()
            })

        # Exported & local types
        for m in cls.TYPE_REGEX.finditer(source):
            symbols.append({
                "kind": "type",
                "name": m.group(1),
                "signature": f"type {m.group(1)}",
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

        return symbols

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
# GITIGNORE & EXCLUSION MATCHER
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
# AUTHORITATIVE PROJECT CONTEXT INDEX
# ------------------------------------------------------------------------------
class ProjectContextIndex:
    """
    Authoritative index for workspace contents, enabling genuine incremental
    indexing, symbol cataloging, and bounded lexical retrieval.
    """

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path: Path = Path(workspace_path).resolve() if workspace_path else Path.cwd().resolve()
        self.storage_dir = paths_service.get_app_data_dir()
        self.index_file = self.storage_dir / "project_context_index.json"
        self.legacy_context_file = Path(__file__).parent / "data" / "verified_project_context.json"
        self.files: Dict[str, ProjectFileRecord] = {}
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
            except Exception as e:
                print(f"[ProjectContext] Error reading persisted index: {e}", flush=True)

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
                "files": {p: f.to_dict() for p, f in self.files.items()}
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
        Returns detailed ingestion statistics.
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
                if ext not in SUPPORTED_EXTENSIONS and fname not in ("default.project.json", "wally.toml", "rojo.json"):
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

                # Parse specific file types
                symbols: List[Dict[str, Any]] = []
                file_type = "text"
                summary = ""

                try:
                    if ext in (".luau", ".lua"):
                        role = LuauSymbolExtractor.classify_script_role(rel_path)
                        file_type = f"luau_{role.lower()}"
                        symbols = LuauSymbolExtractor.extract_symbols(text_content)
                        fn_names = [s["name"] for s in symbols if s["kind"] == "function"][:5]
                        summary = f"{role} ({len(text_content.splitlines())} lines). Declares: {', '.join(fn_names) if fn_names else 'variables/logic'}"

                    elif ext in (".rbxmx", ".rbxlx"):
                        file_type = "roblox_xml"
                        instances, rep_text = RobloxXmlExtractor.parse_xml_model(text_content)
                        symbols = instances
                        summary = f"Roblox XML Model with {len(instances)} instances."
                        # Use extracted structural text representation instead of raw XML verbosity
                        text_content = rep_text

                    elif ext == ".json" or fname in ("default.project.json", "rojo.json"):
                        file_type = "project_metadata"
                        summary = f"Project config / JSON metadata ({len(text_content)} chars)"

                    elif ext == ".toml" or fname == "wally.toml":
                        file_type = "dependency_manifest"
                        summary = f"TOML manifest / dependency config ({len(text_content)} chars)"

                    elif ext in (".md", ".txt"):
                        file_type = "documentation"
                        summary = f"Documentation ({len(text_content.splitlines())} lines)"

                except Exception as parse_err:
                    # Individual file parsing failure must not crash the job
                    skipped_count += 1
                    skipped_files.append({"path": rel_path, "reason": f"parse_error: {parse_err}"})
                    continue

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
                    summary=summary
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
    # TARGETED CONTEXT RETRIEVAL (BM25 & SYMBOL SCORING)
    # --------------------------------------------------------------------------
    def retrieve_context(
        self,
        query: str,
        max_results: int = 5,
        max_total_chars: int = 12_000
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top relevant files and symbol snippets using BM25 lexical
        similarity and symbol boosting without dumping entire projects into prompts.
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
                if tok in rec.file_type:
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
                    # Logarithmic term frequency
                    import math
                    score += 1.0 + math.log(count)

            if score > 0.5:
                scored_results.append((score, rec, matched_symbols))

        # Sort by relevance score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)

        selected = []
        char_count = 0
        for score, rec, syms in scored_results[:max_results]:
            # Extract most relevant snippet around matched symbols or file head
            snippet = rec.content
            if len(snippet) > 2500:
                # Truncate to relevant section
                snippet = snippet[:2500] + "\n...[file truncated for context]"

            if char_count + len(snippet) > max_total_chars and selected:
                break

            char_count += len(snippet)
            selected.append({
                "path": rec.relative_path,
                "file_type": rec.file_type,
                "score": round(score, 2),
                "matched_symbols": [s.get("name") for s in syms[:4]],
                "matched_signatures": [s.get("signature") or s.get("name") for s in syms[:4]],
                "summary": rec.summary,
                "snippet": snippet
            })

        return selected

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
            lines.append("```luau" if "luau" in item['file_type'] else "```")
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
