"""
================================================================================
STROKE // ROBLOX STUDIO SPECIALIST OVERHAUL TEST SUITE
================================================================================
Verifies:
  1. Luau Code Understanding (strict typing, table shapes, deprecated APIs, context safety).
  2. Roblox API Awareness (Services catalog, execution contexts, client-vs-server rules).
  3. Explorer Hierarchy Inspection (DataModel tree, Rojo resolution, truthful non-fabrication).
  4. Script Creation & Editing Workflows (Server/Client/Module script roles).
  5. RemoteEvent & RemoteFunction Analysis (Pairing, orphan detection, security auditing).
  6. Server/Client Architecture (Boundary rules, container placement).
  7. UI Creation (Responsive multi-device Scale vs. Offset layout, constraints).
  8. Terrain & Map-Building (Procedural biomes, FillBlock, water tables).
  9. VFX & Animation Assistance (ParticleEmitter ColorSequence/NumberSequence, Highlights).
  10. Studio Error Detection (Traceback parsing, nil indexing, infinite yield diagnosis).
  11. Play-Test & Verification Workflows (Proof-backed object verification, no false claims).
  12. ToolDispatcher Integration (roblox_analyze_luau, roblox_verify_object, etc.).
  13. REST API Endpoints (/roblox/* routes).
================================================================================
"""

import os
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import roblox_specialist_service
from roblox_specialist_service import (
    RobloxApiKnowledge,
    LuauAnalyzer,
    RemoteContractAnalyzer,
    HierarchyInspector,
    UiBuilder,
    TerrainBuilder,
    VfxBuilder,
    StudioErrorDiagnoser,
    PlaytestAndVerificationEngine
)
import terminal_service
from terminal_service import ToolDispatcher
import project_context_service
import main
import auth_service
from fastapi.testclient import TestClient


class TestRobloxSpecialistOverhaul(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stroke_roblox_test_")
        self.ws_path = Path(self.test_dir).resolve()

        # Set up authenticated client
        self.client = TestClient(main.app)
        self.test_uid = "roblox_specialist_user_001"
        self.test_user = auth_service.AuthenticatedUser(
            uid=self.test_uid,
            email="roblox_dev@stroke.internal",
            claims={"uid": self.test_uid, "email": "roblox_dev@stroke.internal"}
        )
        main.app.dependency_overrides[auth_service.get_current_user] = lambda: self.test_user
        main.app.dependency_overrides[main.verify_terminal_access] = lambda: {"auth": "internal_token"}

    def tearDown(self):
        main.app.dependency_overrides.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. LUAU CODE UNDERSTANDING & DEPRECATED API DETECTION
    # --------------------------------------------------------------------------
    def test_01_luau_code_understanding_and_deprecated_apis(self):
        """Detects legacy wait/spawn, deprecated APIs, strict mode, and suggests modern task library."""
        legacy_code = (
            "--!strict\n"
            "local Players = game:GetService('Players')\n\n"
            "export type PlayerData = { coins: number, level: number }\n\n"
            "function onPlayerSpawn(player: Player)\n"
            "    wait(1)\n"
            "    spawn(function()\n"
            "        print('Legacy spawned')\n"
            "    end)\n"
            "    if workspace.FilteringEnabled then\n"
            "        print('Filtering enabled')\n"
            "    end\n"
            "end\n"
        )

        analysis = LuauAnalyzer.analyze_source(legacy_code, script_role="ServerScript")

        self.assertEqual(analysis["mode"], "strict")
        self.assertTrue(analysis["has_strict_mode"])
        self.assertIn("PlayerData", analysis["declared_types"])

        rules = [i["rule"] for i in analysis["issues"]]
        self.assertIn("deprecated_legacy_timing", rules)
        self.assertIn("obsolete_filtering_enabled", rules)

        # Verify modern task library replacement suggestion
        wait_issue = next(i for i in analysis["issues"] if i["symbol"] == "wait")
        self.assertEqual(wait_issue["replacement"], "task.wait()")

    # --------------------------------------------------------------------------
    # 2. CONTEXT SAFETY & ROBLOX API AWARENESS
    # --------------------------------------------------------------------------
    def test_02_context_safety_and_api_awareness(self):
        """Catches client APIs in server scripts and server APIs in client scripts."""
        # 1. Client API on Server
        bad_server_code = (
            "local UserInputService = game:GetService('UserInputService')\n"
            "local camera = workspace.CurrentCamera\n"
            "UserInputService.InputBegan:Connect(function() end)\n"
        )
        analysis_server = LuauAnalyzer.analyze_source(bad_server_code, script_role="ServerScript")
        server_errors = [i for i in analysis_server["issues"] if i["severity"] == "error"]
        self.assertGreaterEqual(len(server_errors), 1)
        self.assertIn("client_api_on_server", [e["rule"] for e in server_errors])

        # 2. Server API on Client
        bad_client_code = (
            "local DataStoreService = game:GetService('DataStoreService')\n"
            "local ServerStorage = game:GetService('ServerStorage')\n"
        )
        analysis_client = LuauAnalyzer.analyze_source(bad_client_code, script_role="LocalScript")
        client_errors = [i for i in analysis_client["issues"] if i["severity"] == "error"]
        self.assertGreaterEqual(len(client_errors), 1)
        self.assertIn("server_api_on_client", [e["rule"] for e in client_errors])

        # 3. Valid API service check
        self.assertTrue(RobloxApiKnowledge.is_service_valid("Players"))
        self.assertTrue(RobloxApiKnowledge.is_service_valid("ReplicatedStorage"))
        self.assertFalse(RobloxApiKnowledge.is_service_valid("InvalidFakeService"))

    # --------------------------------------------------------------------------
    # 3. REMOTE EVENT & NETWORK CONTRACT ANALYSIS
    # --------------------------------------------------------------------------
    def test_03_remote_event_and_security_analysis(self):
        """Audits RemoteEvent pairs, identifies orphaned remotes, and flags client-authoritative security risks."""
        files = {
            # Client script fires damage and coins
            "src/client/CombatController.client.luau": (
                "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                "local DamageRemote = ReplicatedStorage.DamageRemote\n"
                "local ShopRemote = ReplicatedStorage.ShopRemote\n"
                "local UnhandledRemote = ReplicatedStorage.UnhandledRemote\n"
                "DamageRemote:FireServer(100)\n"
                "ShopRemote:FireServer('buy_sword')\n"
                "UnhandledRemote:FireServer()\n"
            ),
            # Server script with a dangerous client-authoritative damage parameter
            "src/server/DamageService.server.luau": (
                "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                "local DamageRemote = ReplicatedStorage.DamageRemote\n"
                "DamageRemote.OnServerEvent:Connect(function(player, damage)\n"
                "    print('Inflicting client specified damage:', damage)\n"
                "end)\n"
            ),
            # Server script listening to an event never fired by client
            "src/server/AdminService.server.luau": (
                "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                "ReplicatedStorage.OrphanServerRemote.OnServerEvent:Connect(function(player)\n"
                "end)\n"
            )
        }

        report = RemoteContractAnalyzer.audit_workspace_network(files)

        self.assertIn("UnhandledRemote", report["unhandled_client_calls"])
        self.assertIn("OrphanServerRemote", report["uncalled_server_listeners"])

        # Check security vulnerability detection
        vulns = report["security_vulnerabilities"]
        self.assertGreater(len(vulns), 0)
        vuln_params = [v["parameter"] for v in vulns]
        self.assertIn("damage", vuln_params)
        self.assertEqual(vulns[0]["severity"], "critical")

    # --------------------------------------------------------------------------
    # 4. EXPLORER HIERARCHY INSPECTION & TRUTHFUL NON-FABRICATION
    # --------------------------------------------------------------------------
    def test_04_explorer_hierarchy_truthful_inspection(self):
        """Verifies DataModel paths against Rojo maps and truthfully reports non-existent objects."""
        rojo_cfg = {
            "name": "HierarchyProject",
            "tree": {
                "$className": "DataModel",
                "ReplicatedStorage": {
                    "$path": "src/shared"
                }
            }
        }
        (self.ws_path / "default.project.json").write_text(json.dumps(rojo_cfg), encoding="utf-8")

        shared_dir = self.ws_path / "src" / "shared"
        shared_dir.mkdir(parents=True)
        (shared_dir / "VFXManager.luau").write_text("return {}", encoding="utf-8")

        # 1. Existing instance: ReplicatedStorage.VFXManager
        res_found = HierarchyInspector.resolve_datamodel_path("ReplicatedStorage.VFXManager", workspace_path=str(self.ws_path))
        self.assertTrue(res_found["verified"])
        self.assertTrue(res_found["exists"])
        self.assertEqual(res_found["filesystem_path"], "src/shared/VFXManager.luau")

        # 2. Non-existent instance: ReplicatedStorage.MissingObject
        res_missing = HierarchyInspector.resolve_datamodel_path("ReplicatedStorage.MissingObject", workspace_path=str(self.ws_path))
        self.assertFalse(res_missing["verified"])
        self.assertFalse(res_missing["exists"])
        self.assertIn("was not found", res_missing["message"])

        # 3. Invalid root service
        res_invalid = HierarchyInspector.resolve_datamodel_path("FakeRootService.Item")
        self.assertFalse(res_invalid["verified"])
        self.assertIn("Invalid DataModel root", res_invalid["message"])

    # --------------------------------------------------------------------------
    # 5. UI CREATION & RESPONSIVE COMPONENT BUILDER
    # --------------------------------------------------------------------------
    def test_05_ui_creation_and_responsive_generation(self):
        """Generates multi-device responsive UI script utilizing Scale, UICorner, and UIStroke."""
        elements = [
            {"type": "button", "label": "Start Game"},
            {"type": "button", "label": "Settings"},
            {"type": "label", "label": "Version 1.0.0"}
        ]

        ui_code = UiBuilder.generate_ui_script(
            title="Main Menu",
            elements=elements,
            theme_name="cyberpunk"
        )

        self.assertIn("--!strict", ui_code)
        self.assertIn("MainMenu", ui_code)
        self.assertIn("ScreenGui", ui_code)
        self.assertIn("UICorner", ui_code)
        self.assertIn("UIStroke", ui_code)
        self.assertIn("UIListLayout", ui_code)
        self.assertIn("Start Game", ui_code)
        self.assertIn("Settings", ui_code)
        self.assertIn("Version 1.0.0", ui_code)

    # --------------------------------------------------------------------------
    # 6. TERRAIN & MAP-BUILDING GENERATION
    # --------------------------------------------------------------------------
    def test_06_terrain_and_biome_generation(self):
        """Generates procedural terrain filling script with biomes and water planes."""
        terrain_code = TerrainBuilder.generate_terrain_script(
            biome="volcanic",
            size=(256, 48, 256),
            center=(0, 10, 0),
            water_level=-5
        )

        self.assertIn("Workspace.Terrain", terrain_code)
        self.assertIn("FillBlock", terrain_code)
        self.assertIn("Enum.Material.Basalt", terrain_code)
        self.assertIn("Enum.Material.CrackedLava", terrain_code)
        self.assertIn("Enum.Material.Water", terrain_code)

    # --------------------------------------------------------------------------
    # 7. VFX & PARTICLE BUILDER
    # --------------------------------------------------------------------------
    def test_07_vfx_and_particle_generation(self):
        """Generates verified ParticleEmitter, Highlight, and Attachment configs."""
        vfx_code = VfxBuilder.generate_particle_vfx(
            vfx_type="CosmicNova",
            target_name="CosmicCore",
            target_parent="workspace"
        )

        self.assertIn("CosmicNova", vfx_code)
        self.assertIn("ParticleEmitter", vfx_code)
        self.assertIn("ColorSequence.new", vfx_code)
        self.assertIn("NumberSequence.new", vfx_code)
        self.assertIn("Highlight", vfx_code)
        self.assertIn("Debris:AddItem", vfx_code)

    # --------------------------------------------------------------------------
    # 8. STUDIO ERROR DETECTION & CONSOLE DIAGNOSTICS
    # --------------------------------------------------------------------------
    def test_08_studio_error_detection_and_diagnostics(self):
        """Parses console tracebacks, detects nil indexing and infinite yields, and suggests remedies."""
        console_logs = [
            "[System] Booting Roblox Studio...",
            "ServerScriptService.CombatServer:42: attempt to index nil with 'TakeDamage'",
            "Infinite yield possible on 'Workspace.Map.Boss:WaitForChild(\"HumanoidRootPart\")'",
            "ReplicatedStorage.Utils.Math:15: invalid argument #1 to 'sin' (number expected, got nil)"
        ]

        diagnoses = StudioErrorDiagnoser.diagnose_console(console_logs)

        self.assertEqual(diagnoses["total_issues_found"], 3)
        self.assertEqual(diagnoses["errors_count"], 2)
        self.assertEqual(diagnoses["warnings_count"], 1)

        err_files = [d["file"] for d in diagnoses["diagnoses"]]
        self.assertIn("ServerScriptService.CombatServer", err_files)
        self.assertIn("DataModel", err_files)

        nil_diag = next(d for d in diagnoses["diagnoses"] if d["file"] == "ServerScriptService.CombatServer")
        self.assertIn("Nil indexing", nil_diag["diagnosis"])
        self.assertIn("guard clause", nil_diag["remedy"])

    # --------------------------------------------------------------------------
    # 9. PLAY-TEST & OBJECT VERIFICATION WORKFLOWS
    # --------------------------------------------------------------------------
    def test_09_playtest_and_truthful_object_verification(self):
        """Proof-backed object verification truthfully reports whether an object exists."""
        import asyncio

        # 1. Existing local file
        (self.ws_path / "default.project.json").write_text(json.dumps({
            "name": "VerifyGame",
            "tree": {"$className": "DataModel", "ServerScriptService": {"$path": "src/server"}}
        }), encoding="utf-8")
        server_dir = self.ws_path / "src" / "server"
        server_dir.mkdir(parents=True)
        (server_dir / "TargetService.luau").write_text("return {}", encoding="utf-8")

        res_exist = asyncio.run(PlaytestAndVerificationEngine.verify_object(
            target_path="ServerScriptService.TargetService",
            workspace_path=str(self.ws_path)
        ))
        self.assertTrue(res_exist["verified"])
        self.assertTrue(res_exist["exists"])

        # 2. Non-existent object: MUST fail verification honestly (no hallucination!)
        res_fake = asyncio.run(PlaytestAndVerificationEngine.verify_object(
            target_path="ServerScriptService.NonExistentGhostService",
            workspace_path=str(self.ws_path)
        ))
        self.assertFalse(res_fake["verified"])
        self.assertFalse(res_fake["exists"])
        self.assertIn("Verification failed", res_fake["message"])

    # --------------------------------------------------------------------------
    # 10. TOOLDISPATCHER ROBLOX SPECIALIST INTEGRATION
    # --------------------------------------------------------------------------
    def test_10_tool_dispatcher_roblox_specialist_tools(self):
        """ToolDispatcher synchronously and asynchronously handles Roblox Specialist tools."""
        # 1. roblox_analyze_luau
        res_luau = ToolDispatcher.dispatch("roblox_analyze_luau", {
            "code": "function run() wait(0.5) end",
            "script_role": "ServerScript"
        })
        self.assertEqual(res_luau["mode"], "nocheck")
        self.assertTrue(any(i["symbol"] == "wait" for i in res_luau["issues"]))

        # 2. roblox_generate_ui
        res_ui = ToolDispatcher.dispatch("roblox_generate_ui", {
            "title": "InventoryPanel",
            "theme": "dark_glass",
            "elements": [{"type": "button", "label": "Equip"}]
        })
        self.assertEqual(res_ui["status"], "success")
        self.assertIn("InventoryPanel", res_ui["code"])

        # 3. roblox_generate_terrain
        res_terrain = ToolDispatcher.dispatch("roblox_generate_terrain", {
            "biome": "desert",
            "size": [128, 24, 128]
        })
        self.assertEqual(res_terrain["status"], "success")
        self.assertIn("Enum.Material.Sand", res_terrain["code"])

        # 4. roblox_diagnose_errors
        res_diag = ToolDispatcher.dispatch("roblox_diagnose_errors", {
            "lines": ["ServerScriptService.CombatServer:12: attempt to index nil with 'Health'"]
        })
        self.assertEqual(res_diag["total_issues_found"], 1)

    # --------------------------------------------------------------------------
    # 11. REST API ENDPOINTS
    # --------------------------------------------------------------------------
    def test_11_roblox_specialist_rest_endpoints(self):
        """HTTP endpoints for /roblox/analyze/luau, /roblox/generate/ui, etc."""
        # 1. POST /roblox/analyze/luau
        resp1 = self.client.post("/roblox/analyze/luau", json={
            "code": "--!strict\nfunction test() return 1 end",
            "script_role": "ModuleScript"
        })
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1["status"], "success")
        self.assertTrue(data1["analysis"]["has_strict_mode"])

        # 2. POST /roblox/generate/ui
        resp2 = self.client.post("/roblox/generate/ui", json={
            "title": "HUD",
            "elements": [{"type": "label", "label": "Health: 100"}]
        })
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["status"], "success")
        self.assertIn("HUD", data2["code"])

        # 3. POST /roblox/generate/vfx
        resp3 = self.client.post("/roblox/generate/vfx", json={"vfx_type": "LightningDischarge"})
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.json()
        self.assertEqual(data3["status"], "success")
        self.assertIn("LightningDischarge", data3["code"])

        # 4. POST /roblox/diagnostics/errors
        resp4 = self.client.post("/roblox/diagnostics/errors", json={
            "lines": ["Infinite yield possible on 'Workspace.Part:WaitForChild(\"VFX\")'"]
        })
        self.assertEqual(resp4.status_code, 200)
        data4 = resp4.json()
        self.assertEqual(data4["status"], "success")
        self.assertEqual(data4["diagnoses"]["warnings_count"], 1)


if __name__ == "__main__":
    unittest.main()
