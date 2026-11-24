"""
================================================================================
STROKE // PROJECT INTELLIGENCE SYSTEM TEST SUITE
================================================================================
Verifies:
  1. Multi-Language Project Indexing (Python, TypeScript/JS, Luau/Lua, Roblox XML, Configs).
  2. Python AST Symbol Extraction (Classes, Methods, Decorators, Async, Imports).
  3. TypeScript & JavaScript Symbol Extraction (Classes, Interfaces, Types, Exports, Imports).
  4. Luau & Roblox Awareness (Functions, Types, Services, Events, RemoteContracts).
  5. Rojo DataModel Mapping & Require Resolution (ReplicatedStorage -> filesystem path).
  6. Wally & Manifest Parsing (wally.toml, package.json, requirements.txt, Cargo.toml).
  7. Dependency Graph & Impact Radius (Outgoing dependencies, Reverse callers, BFS Impact).
  8. Global Symbol Table & Cross-File Discovery (find_symbol, find_references).
  9. Incremental Re-Indexing (Content hash matching, Modified re-parse, Deleted file pruning).
  10. Project Architecture Summarizer (Archetype detection, Entry points, Markdown blueprint).
  11. Graph-Aware Context Retrieval (BM25 + Symbol Boost + Imported Contracts Expansion).
  12. ToolDispatcher Integration (project_index, project_search, project_get_architecture, etc.).
  13. REST API Endpoints (/project/architecture, /project/dependencies, /project/symbols).
================================================================================
"""

import os
import json
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import project_context_service
from project_context_service import (
    ProjectContextIndex,
    ProjectDependencyGraph,
    ProjectSymbolTable,
    ProjectArchitectureSummarizer,
    LanguageDetector,
    PythonSymbolExtractor,
    TypeScriptSymbolExtractor,
    LuauSymbolExtractor,
    RobloxXmlExtractor,
    DependencyManifestParser,
    RobloxProjectResolver
)
import terminal_service
from terminal_service import ToolDispatcher
import main
import auth_service
from fastapi.testclient import TestClient


class TestProjectIntelligenceSystem(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stroke_intel_test_")
        self.ws_path = Path(self.test_dir).resolve()

        # Set up authenticated client
        self.client = TestClient(main.app)
        self.test_uid = "intel_user_001"
        self.test_user = auth_service.AuthenticatedUser(
            uid=self.test_uid,
            email="developer@stroke.internal",
            claims={"uid": self.test_uid, "email": "developer@stroke.internal"}
        )
        main.app.dependency_overrides[auth_service.get_current_user] = lambda: self.test_user
        main.app.dependency_overrides[main.verify_terminal_access] = lambda: {"auth": "internal_token"}

    def tearDown(self):
        main.app.dependency_overrides.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. LANGUAGE DETECTION & CATEGORIZATION
    # --------------------------------------------------------------------------
    def test_01_language_detection(self):
        """Detects language and category by file extension, shebang, and manifest names."""
        self.assertEqual(LanguageDetector.detect_language("script.luau"), ("luau", "code"))
        self.assertEqual(LanguageDetector.detect_language("server.py"), ("python", "code"))
        self.assertEqual(LanguageDetector.detect_language("App.tsx"), ("typescript", "code"))
        self.assertEqual(LanguageDetector.detect_language("model.rbxmx"), ("roblox_xml", "code"))
        self.assertEqual(LanguageDetector.detect_language("default.project.json"), ("roblox_project", "project_metadata"))
        self.assertEqual(LanguageDetector.detect_language("wally.toml"), ("roblox_wally", "dependency_manifest"))
        self.assertEqual(LanguageDetector.detect_language("package.json"), ("nodejs_package", "dependency_manifest"))
        self.assertEqual(LanguageDetector.detect_language("Cargo.toml"), ("rust_cargo", "dependency_manifest"))

        # Shebang detection
        self.assertEqual(
            LanguageDetector.detect_language("bin/tool", "#!/usr/bin/env python3\nprint(1)"),
            ("python", "code")
        )
        self.assertEqual(
            LanguageDetector.detect_language("deploy", "#!/bin/bash\necho ok"),
            ("shell", "code")
        )

    # --------------------------------------------------------------------------
    # 2. PYTHON AST SYMBOL EXTRACTION
    # --------------------------------------------------------------------------
    def test_02_python_ast_symbol_extraction(self):
        """Extracts classes, methods, functions, async functions, decorators, and imports."""
        py_source = (
            '"""Core engine service."""\n'
            'import os\n'
            'import sys\n'
            'from database import DatabaseSession\n\n'
            '@singleton\n'
            'class EngineManager(BaseManager):\n'
            '    """Manages physics and rendering ticks."""\n'
            '    def __init__(self, tick_rate: int):\n'
            '        self.tick_rate = tick_rate\n\n'
            '    @async_retry\n'
            '    async def start_loop(self, timeout: float):\n'
            '        pass\n\n'
            'def calculate_kinematics(mass: float, force: float) -> float:\n'
            '    """Returns acceleration."""\n'
            '    return force / mass\n'
        )

        symbols, internal_imports, ext_imports, docstring = PythonSymbolExtractor.extract_symbols(py_source)

        self.assertEqual(docstring, "Core engine service.")
        self.assertIn("os", ext_imports)
        self.assertIn("sys", ext_imports)
        self.assertIn("database", internal_imports)

        sym_names = [s["name"] for s in symbols]
        self.assertIn("EngineManager", sym_names)
        self.assertIn("EngineManager.__init__", sym_names)
        self.assertIn("EngineManager.start_loop", sym_names)
        self.assertIn("calculate_kinematics", sym_names)

        # Check metadata
        class_sym = next(s for s in symbols if s["name"] == "EngineManager")
        self.assertEqual(class_sym["bases"], ["BaseManager"])
        self.assertEqual(class_sym["decorators"], ["singleton"])

        method_sym = next(s for s in symbols if s["name"] == "EngineManager.start_loop")
        self.assertTrue(method_sym["is_async"])
        self.assertEqual(method_sym["decorators"], ["async_retry"])

    # --------------------------------------------------------------------------
    # 3. TYPESCRIPT & JAVASCRIPT SYMBOL EXTRACTION
    # --------------------------------------------------------------------------
    def test_03_typescript_symbol_extraction(self):
        """Extracts interfaces, classes, exported types, functions, and imports."""
        ts_source = (
            "import { User, Session } from './auth';\n"
            "import axios from 'axios';\n\n"
            "export interface AgentState {\n"
            "    agentId: string;\n"
            "    active: boolean;\n"
            "}\n\n"
            "export type AgentStatus = 'idle' | 'running' | 'completed';\n\n"
            "export class AgentDispatcher extends BaseDispatcher {\n"
            "    constructor() { super(); }\n"
            "}\n\n"
            "export async function dispatchTask(taskId: string): Promise<boolean> {\n"
            "    return true;\n"
            "}\n\n"
            "export const cancelTask = (taskId: string) => {\n"
            "    console.log(taskId);\n"
            "};\n"
        )

        symbols, internal_imports, ext_imports = TypeScriptSymbolExtractor.extract_symbols(ts_source)

        self.assertIn("./auth", internal_imports)
        self.assertIn("axios", ext_imports)

        sym_names = [s["name"] for s in symbols]
        self.assertIn("AgentState", sym_names)
        self.assertIn("AgentStatus", sym_names)
        self.assertIn("AgentDispatcher", sym_names)
        self.assertIn("dispatchTask", sym_names)
        self.assertIn("cancelTask", sym_names)

    # --------------------------------------------------------------------------
    # 4. LUAU & ROBLOX AWARENESS
    # --------------------------------------------------------------------------
    def test_04_luau_roblox_awareness(self):
        """Extracts functions, types, services, requires, and network event contracts."""
        luau_source = (
            "--!strict\n"
            "local Players = game:GetService('Players')\n"
            "local TweenService = game:GetService('TweenService')\n"
            "local Hitbox = require(script.Parent.Hitbox)\n\n"
            "export type CombatPacket = { target: Player, damage: number }\n\n"
            "local DamageEvent = Instance.new('RemoteEvent')\n"
            "DamageEvent.Name = 'DamageEvent'\n\n"
            "local CombatController = {}\n"
            "function CombatController:inflictDamage(packet: CombatPacket)\n"
            "    print('Inflicting damage')\n"
            "end\n\n"
            "Players.PlayerAdded:Connect(function(player)\n"
            "    print('Joined:', player.Name)\n"
            "end)\n\n"
            "return CombatController\n"
        )

        symbols = LuauSymbolExtractor.extract_symbols(luau_source)
        requires = LuauSymbolExtractor.extract_requires(luau_source)

        sym_names = [s["name"] for s in symbols]
        self.assertIn("CombatController:inflictDamage", sym_names)
        self.assertIn("CombatPacket", sym_names)
        self.assertIn("Players", sym_names)
        self.assertIn("TweenService", sym_names)
        self.assertIn("RemoteEvent", sym_names)
        self.assertIn("Players.PlayerAdded", sym_names)

        self.assertEqual(len(requires), 1)
        self.assertEqual(requires[0]["variable"], "Hitbox")
        self.assertEqual(requires[0]["target"], "script.Parent.Hitbox")

    # --------------------------------------------------------------------------
    # 5. ROJO DATAMODEL MAPPING & REQUIRE RESOLUTION
    # --------------------------------------------------------------------------
    def test_05_rojo_datamodel_mapping_and_require_resolution(self):
        """Maps Rojo default.project.json to filesystem paths and resolves requires."""
        rojo_cfg = {
            "name": "GameExperience",
            "tree": {
                "$className": "DataModel",
                "ReplicatedStorage": {
                    "$path": "src/shared"
                },
                "ServerScriptService": {
                    "$path": "src/server"
                }
            }
        }
        (self.ws_path / "default.project.json").write_text(json.dumps(rojo_cfg), encoding="utf-8")

        # Create target modules
        shared_dir = self.ws_path / "src" / "shared"
        shared_dir.mkdir(parents=True)
        (shared_dir / "VFXManager.luau").write_text("return {}", encoding="utf-8")

        server_dir = self.ws_path / "src" / "server"
        server_dir.mkdir(parents=True)
        (server_dir / "CombatServer.server.luau").write_text("return {}", encoding="utf-8")

        resolver = RobloxProjectResolver(self.ws_path)
        self.assertEqual(resolver.project_name, "GameExperience")

        # Resolve ReplicatedStorage.VFXManager
        res1 = resolver.resolve_require("ReplicatedStorage.VFXManager", "src/server/CombatServer.server.luau")
        self.assertEqual(res1, "src/shared/VFXManager.luau")

    # --------------------------------------------------------------------------
    # 6. MANIFEST & DEPENDENCY PARSING
    # --------------------------------------------------------------------------
    def test_06_manifest_parsing(self):
        """Parses wally.toml, package.json, requirements.txt, and Cargo.toml."""
        # 1. wally.toml
        wally_content = (
            "[package]\n"
            'name = "team/combat-core"\n'
            'version = "1.2.0"\n'
            "[dependencies]\n"
            'Signal = "sleitnick/signal@^2.0.0"\n'
            'Component = "sleitnick/component@^2.4.0"\n'
            "[server-dependencies]\n"
            'ProfileService = "madworkseth/profileservice@^1.4.2"\n'
        )
        wally = DependencyManifestParser.parse_wally_toml(wally_content)
        self.assertEqual(wally["package_name"], "team/combat-core")
        self.assertIn("sleitnick/signal@^2.0.0", wally["dependencies"])
        self.assertIn("madworkseth/profileservice@^1.4.2", wally["server_dependencies"])

        # 2. package.json
        pkg_content = json.dumps({
            "name": "stroke-desktop",
            "version": "2.4.0",
            "dependencies": {"react": "^18.2.0", "lucide-react": "^0.300.0"},
            "devDependencies": {"vitest": "^1.0.0"}
        })
        pkg = DependencyManifestParser.parse_package_json(pkg_content)
        self.assertEqual(pkg["name"], "stroke-desktop")
        self.assertIn("react", pkg["dependencies"])

        # 3. requirements.txt
        req_content = "fastapi>=0.100.0\nuvicorn[standard]==0.24.0\npydantic\n"
        reqs = DependencyManifestParser.parse_requirements_txt(req_content)
        self.assertEqual(reqs, ["fastapi", "uvicorn", "pydantic"])

        # 4. Cargo.toml
        cargo_content = (
            "[package]\n"
            'name = "stroke-core"\n'
            "[dependencies]\n"
            'serde = "1.0"\n'
            'tokio = "1.0"\n'
        )
        cargo = DependencyManifestParser.parse_cargo_toml(cargo_content)
        self.assertEqual(cargo["package_name"], "stroke-core")
        self.assertIn("serde", cargo["dependencies"])

    # --------------------------------------------------------------------------
    # 7. DEPENDENCY GRAPH & IMPACT RADIUS (BFS)
    # --------------------------------------------------------------------------
    def test_07_dependency_graph_and_impact_radius(self):
        """Builds dependency relationships and calculates transitive impact radius."""
        graph = ProjectDependencyGraph()

        # Architecture:
        # A (Leaf Module) <- B (Service) <- C (API Controller)
        #                 <- D (Background Worker)
        graph.add_dependency("src/service.py", "src/leaf.py")
        graph.add_dependency("src/worker.py", "src/leaf.py")
        graph.add_dependency("src/controller.py", "src/service.py")
        graph.add_dependency("src/service.py", "pydantic", is_external=True)

        deps_service = graph.get_dependencies("src/service.py")
        self.assertIn("src/leaf.py", deps_service["internal"])
        self.assertIn("pydantic", deps_service["external"])

        # Dependents of leaf (who calls leaf?)
        dependents_leaf = graph.get_dependents("src/leaf.py")
        self.assertEqual(sorted(dependents_leaf), ["src/service.py", "src/worker.py"])

        # Impact radius of leaf.py (changes to leaf affect service, worker, and controller)
        impact = graph.get_impact_radius("src/leaf.py", max_depth=3)
        self.assertEqual(impact["total_impacted_files"], 3)
        self.assertEqual(sorted(impact["direct_callers"]), ["src/service.py", "src/worker.py"])
        self.assertEqual(impact["secondary_callers"], ["src/controller.py"])

    # --------------------------------------------------------------------------
    # 8. GLOBAL SYMBOL TABLE & CROSS-FILE DISCOVERY
    # --------------------------------------------------------------------------
    def test_08_symbol_table_cross_file_discovery(self):
        """Indexes symbols across multiple files and supports fast exact and fuzzy lookups."""
        st = ProjectSymbolTable()

        st.index_file_symbols("server.py", [
            {"name": "start_server", "kind": "function", "signature": "def start_server()"},
            {"name": "ServerConfig", "kind": "class", "signature": "class ServerConfig"}
        ])
        st.index_file_symbols("client.py", [
            {"name": "start_client", "kind": "function", "signature": "def start_client()"}
        ])

        # Exact match
        res_fn = st.find_symbol("start_server")
        self.assertEqual(len(res_fn), 1)
        self.assertEqual(res_fn[0]["file"], "server.py")

        # Kind filter
        res_cls = st.find_symbol("ServerConfig", kind="class")
        self.assertEqual(len(res_cls), 1)
        self.assertEqual(res_cls[0]["kind"], "class")

        # Fuzzy match
        res_fuzzy = st.find_symbol("start")
        self.assertEqual(len(res_fuzzy), 2)

    # --------------------------------------------------------------------------
    # 9. INCREMENTAL RE-INDEXING & MULTI-LANGUAGE SCAN
    # --------------------------------------------------------------------------
    def test_09_multi_language_incremental_reindexing(self):
        """Indexes real multi-language workspace, reuses hashes on unchanged files, and prunes deleted."""
        # 1. Python file
        (self.ws_path / "main.py").write_text("def run(): print('Running')", encoding="utf-8")
        # 2. TypeScript file
        (self.ws_path / "types.ts").write_text("export interface UserProfile { id: string; }", encoding="utf-8")
        # 3. Luau file
        (self.ws_path / "combat.luau").write_text("function inflictHit() end", encoding="utf-8")

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        stats1 = index.scan_and_index()

        self.assertEqual(stats1["indexed_count"], 3)
        self.assertEqual(stats1["added_count"], 3)
        self.assertEqual(len(index.files), 3)

        # Re-index immediately: all 3 must be unchanged
        stats2 = index.scan_and_index()
        self.assertEqual(stats2["unchanged_count"], 3)
        self.assertEqual(stats2["added_count"], 0)
        self.assertEqual(stats2["modified_count"], 0)

        # Modify main.py, delete combat.luau, add worker.py
        (self.ws_path / "main.py").write_text("def run(): print('Running v2')", encoding="utf-8")
        os.remove(self.ws_path / "combat.luau")
        (self.ws_path / "worker.py").write_text("def do_work(): pass", encoding="utf-8")

        stats3 = index.scan_and_index()
        self.assertEqual(stats3["modified_count"], 1)
        self.assertEqual(stats3["deleted_count"], 1)
        self.assertEqual(stats3["added_count"], 1)
        self.assertIn("worker.py", index.files)
        self.assertNotIn("combat.luau", index.files)

    # --------------------------------------------------------------------------
    # 10. PROJECT ARCHITECTURE SUMMARIZER
    # --------------------------------------------------------------------------
    def test_10_project_architecture_summary(self):
        """Detects project archetype (Roblox experience), structural layers, and generates markdown."""
        # Setup Roblox project structure
        (self.ws_path / "default.project.json").write_text(json.dumps({
            "name": "ArenaCombat",
            "tree": {"$className": "DataModel", "ServerScriptService": {"$path": "src/server"}}
        }), encoding="utf-8")

        server_dir = self.ws_path / "src" / "server"
        server_dir.mkdir(parents=True)
        (server_dir / "ServerInit.server.luau").write_text(
            "local Players = game:GetService('Players')\nprint('Booted')",
            encoding="utf-8"
        )

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        index.scan_and_index()

        summary = index.get_architecture_summary(markdown=False)
        self.assertEqual(summary["archetype"], "roblox_experience")
        self.assertIn("ServerInit.server.luau", summary["entry_points"][0])
        self.assertIn("Players", summary["roblox_services_used"])

        # Markdown format
        md_summary = index.get_architecture_summary(markdown=True)
        self.assertIn("roblox_experience", md_summary.lower())
        self.assertIn("Players", md_summary)

    # --------------------------------------------------------------------------
    # 11. GRAPH-AWARE CONTEXT RETRIEVAL
    # --------------------------------------------------------------------------
    def test_11_graph_aware_context_retrieval(self):
        """Expands top search results with imported contract signatures from dependencies."""
        # Module A (exported contract)
        (self.ws_path / "DamageModule.luau").write_text(
            "--!strict\n"
            "export type DamageRecord = { targetId: number, amount: number }\n"
            "local Damage = {}\n"
            "function Damage.applyTrueDamage(target: number, amount: number): boolean\n"
            "    return true\n"
            "end\n"
            "return Damage\n",
            encoding="utf-8"
        )
        # Module B (imports Module A)
        (self.ws_path / "CombatController.luau").write_text(
            "local Damage = require(script.Parent.DamageModule)\n"
            "function executeSlashAttack(target: number)\n"
            "    Damage.applyTrueDamage(target, 50)\n"
            "end\n",
            encoding="utf-8"
        )

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        index.scan_and_index()

        results = index.retrieve_context("slash attack combat", expand_dependencies=True)
        self.assertGreater(len(results), 0)
        top = results[0]
        self.assertEqual(top["path"], "CombatController.luau")

        # Verify dependency contracts were expanded into context
        self.assertIn("DamageModule.luau", top["dependencies"])
        self.assertEqual(len(top["imported_contracts"]), 1)
        self.assertEqual(top["imported_contracts"][0]["module"], "DamageModule.luau")
        signatures = top["imported_contracts"][0]["signatures"]
        self.assertTrue(any("Damage.applyTrueDamage" in s for s in signatures))

    # --------------------------------------------------------------------------
    # 12. TOOLDISPATCHER PROJECT INTELLIGENCE TOOLS
    # --------------------------------------------------------------------------
    def test_12_tool_dispatcher_project_tools(self):
        """ToolDispatcher exposes project_index, project_search, project_get_architecture, etc."""
        (self.ws_path / "app.py").write_text("def init_app(): return True", encoding="utf-8")

        # 1. project_index
        idx_res = ToolDispatcher.dispatch("project_index", {"workspace_path": str(self.ws_path)})
        self.assertEqual(idx_res["status"], "success")
        self.assertEqual(idx_res["indexed_count"], 1)

        # 2. project_search
        search_res = ToolDispatcher.dispatch("project_search", {
            "workspace_path": str(self.ws_path),
            "query": "init_app"
        })
        self.assertEqual(search_res["status"], "success")
        self.assertEqual(len(search_res["results"]), 1)
        self.assertEqual(search_res["results"][0]["path"], "app.py")

        # 3. project_get_architecture
        arch_res = ToolDispatcher.dispatch("project_get_architecture", {
            "workspace_path": str(self.ws_path),
            "markdown": False
        })
        self.assertEqual(arch_res["status"], "success")
        self.assertIn("archetype", arch_res["architecture"])

        # 4. project_find_symbol
        sym_res = ToolDispatcher.dispatch("project_find_symbol", {
            "workspace_path": str(self.ws_path),
            "name": "init_app"
        })
        self.assertEqual(sym_res["status"], "success")
        self.assertEqual(len(sym_res["symbols"]), 1)
        self.assertEqual(sym_res["symbols"][0]["name"], "init_app")

    # --------------------------------------------------------------------------
    # 13. REST API ENDPOINTS
    # --------------------------------------------------------------------------
    def test_13_rest_api_endpoints(self):
        """Verifies /project/architecture, /project/dependencies, and /project/symbols HTTP endpoints."""
        (self.ws_path / "module_a.py").write_text("def function_alpha(): pass", encoding="utf-8")
        (self.ws_path / "module_b.py").write_text("from module_a import function_alpha\ndef function_beta(): pass", encoding="utf-8")

        # Index first
        self.client.post("/project/index", json={"workspace_path": str(self.ws_path)})

        # 1. GET /project/architecture
        resp_arch = self.client.get(f"/project/architecture?workspace_path={self.ws_path}")
        self.assertEqual(resp_arch.status_code, 200)
        data_arch = resp_arch.json()
        self.assertEqual(data_arch["status"], "success")
        self.assertEqual(data_arch["architecture"]["total_files"], 2)

        # 2. GET /project/dependencies
        resp_dep = self.client.get(f"/project/dependencies?file_path=module_b.py&workspace_path={self.ws_path}")
        self.assertEqual(resp_dep.status_code, 200)
        data_dep = resp_dep.json()
        self.assertEqual(data_dep["status"], "success")
        self.assertIn("module_a", data_dep["dependencies"]["internal"])

        # 3. GET /project/symbols
        resp_sym = self.client.get(f"/project/symbols?name=function_alpha&workspace_path={self.ws_path}")
        self.assertEqual(resp_sym.status_code, 200)
        data_sym = resp_sym.json()
        self.assertEqual(data_sym["status"], "success")
        self.assertEqual(data_sym["symbols_count"], 1)
        self.assertEqual(data_sym["symbols"][0]["name"], "function_alpha")


if __name__ == "__main__":
    unittest.main()
