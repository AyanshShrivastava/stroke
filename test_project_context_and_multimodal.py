"""
================================================================================
STROKE // PROJECT CONTEXT & MULTIMODAL VERIFICATION TEST SUITE
================================================================================
Verifies:
  1. Real Nested Roblox Project Indexing (Luau scripts, modules, Rojo configs, .rbxmx XML).
  2. Incremental Indexing: Content hashes detect modified/deleted/unchanged files.
  3. Secret & Gitignore Exclusion: .env, tokens, private keys, .git, node_modules.
  4. Resilient Error Handling: Binary, malformed XML, oversized files skipped individually.
  5. Exact Metric Reporting: Total scanned, indexed, skipped, and exact skip reasons.
  6. Targeted BM25 / Symbol Retrieval: Retrieves relevant snippets without prompt flooding.
  7. Retrieved Code Injected into AI Prompt: Verifies project code appears in AI answer context.
  8. Multimodal Attachment Gating: Text-only model returns honest unsupported status (no canned house!).
  9. Vision-Capable Model: Real vision inference execution when supported.
  10. Multi-Image Attachments: Iterates and analyzes EVERY image attachment.
  11. Decompression Bomb Protection: Rejects excessive pixel dimensions.
  12. Static Screenshot Disclaimer: Never claims live Studio inspection.
  13. REST Endpoints: /project/index, /project/index/status, /project/search with auth.
================================================================================
"""

import os
import io
import json
import time
import shutil
import base64
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from PIL import Image

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import project_context_service
from project_context_service import (
    ProjectContextIndex,
    LuauSymbolExtractor,
    RobloxXmlExtractor,
    ProjectExclusionFilter
)
import multimodal_service
from multimodal_service import (
    MultimodalAttachmentHandler,
    ImageAttachmentValidationError
)
import ai_provider_service
from ai_provider_service import (
    MODEL_REGISTRY,
    ModelMetadata,
    ProviderType,
    ProviderResponse
)
import main
import auth_service
from fastapi.testclient import TestClient


class TestProjectContextAndMultimodal(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stroke_project_test_")
        self.ws_path = Path(self.test_dir).resolve()

        # Create mock user for authenticated endpoints
        self.client = TestClient(main.app)
        self.test_uid = "project_multimodal_user_001"
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
    # 1. REAL NESTED ROBLOX PROJECT INDEXING
    # --------------------------------------------------------------------------
    def test_01_nested_roblox_project_indexing_and_symbols(self):
        """Indexes real nested Roblox files, extracts Luau symbols and Roblox XML instances."""
        # 1. Rojo configuration
        rojo_cfg = {
            "name": "ElementalCombat",
            "tree": {
                "$className": "DataModel",
                "ServerScriptService": {
                    "$path": "src/server"
                },
                "ReplicatedStorage": {
                    "$path": "src/shared"
                }
            }
        }
        (self.ws_path / "default.project.json").write_text(json.dumps(rojo_cfg, indent=2), encoding="utf-8")

        # 2. ServerScript
        server_dir = self.ws_path / "src" / "server"
        server_dir.mkdir(parents=True)
        combat_service_code = (
            "--!strict\n"
            "local Players = game:GetService('Players')\n"
            "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n\n"
            "export type DamagePacket = { targetId: number, amount: number, element: string }\n\n"
            "local CombatService = {}\n"
            "CombatService.__index = CombatService\n\n"
            "function CombatService.applyDamage(player: Player, packet: DamagePacket): boolean\n"
            "    print('Inflicting damage:', packet.amount, 'element:', packet.element)\n"
            "    return true\n"
            "end\n\n"
            "return CombatService\n"
        )
        (server_dir / "CombatService.server.luau").write_text(combat_service_code, encoding="utf-8")

        # 3. ModuleScript
        shared_dir = self.ws_path / "src" / "shared"
        shared_dir.mkdir(parents=True)
        vfx_module_code = (
            "local HitboxModule = {}\n"
            "function HitboxModule.createSpatialHitbox(originCFrame: CFrame, size: Vector3)\n"
            "    return { origin = originCFrame, size = size }\n"
            "end\n"
            "return HitboxModule\n"
        )
        (shared_dir / "HitboxModule.luau").write_text(vfx_module_code, encoding="utf-8")

        # 4. Roblox XML Model (.rbxmx)
        rbxmx_content = (
            '<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" version="4">\n'
            '  <Item class="Model" referent="RBX0">\n'
            '    <Properties>\n'
            '      <string name="Name">LightningStrikeModel</string>\n'
            '    </Properties>\n'
            '    <Item class="Script" referent="RBX1">\n'
            '      <Properties>\n'
            '        <string name="Name">ArcScript</string>\n'
            '        <ProtectedString name="Source"><![CDATA[\n'
            '          function dischargeLightning(intensity)\n'
            '            print("Arc discharged with intensity:", intensity)\n'
            '          end\n'
            '        ]]></ProtectedString>\n'
            '      </Properties>\n'
            '    </Item>\n'
            '  </Item>\n'
            '</roblox>'
        )
        (shared_dir / "LightningVFX.rbxmx").write_text(rbxmx_content, encoding="utf-8")

        # Execute indexing
        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        stats = index.scan_and_index()

        self.assertEqual(stats["status"], "success")
        self.assertEqual(stats["indexed_count"], 4)
        self.assertEqual(stats["skipped_count"], 0)
        self.assertGreater(stats["total_bytes"], 0)

        # Verify Luau symbol extraction
        rec_server = index.files["src/server/CombatService.server.luau"]
        self.assertEqual(rec_server.file_type, "luau_serverscript")
        sym_names = [s["name"] for s in rec_server.symbols]
        self.assertIn("CombatService.applyDamage", sym_names)
        self.assertIn("DamagePacket", sym_names)
        self.assertIn("Players", sym_names)

        # Verify XML model parsing and embedded script extraction
        rec_xml = index.files["src/shared/LightningVFX.rbxmx"]
        self.assertEqual(rec_xml.file_type, "roblox_xml")
        xml_sym_names = [s["name"] for s in rec_xml.symbols]
        self.assertIn("LightningStrikeModel", xml_sym_names)
        self.assertIn("ArcScript::dischargeLightning", xml_sym_names)

    # --------------------------------------------------------------------------
    # 2. INCREMENTAL INDEXING & CONTENT HASHES
    # --------------------------------------------------------------------------
    def test_02_incremental_indexing_modifications_and_deletions(self):
        """Index incrementally detects added, modified, unchanged, and deleted files using hashes."""
        file_a = self.ws_path / "moduleA.luau"
        file_b = self.ws_path / "moduleB.luau"
        file_a.write_text("function funcA() return 1 end", encoding="utf-8")
        file_b.write_text("function funcB() return 2 end", encoding="utf-8")

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        res1 = index.scan_and_index()
        self.assertEqual(res1["added_count"], 2)
        self.assertEqual(res1["modified_count"], 0)
        self.assertEqual(res1["unchanged_count"], 0)
        self.assertEqual(res1["deleted_count"], 0)

        # Re-index with no changes
        res2 = index.scan_and_index()
        self.assertEqual(res2["unchanged_count"], 2)
        self.assertEqual(res2["added_count"], 0)
        self.assertEqual(res2["modified_count"], 0)

        # Modify file_a and delete file_b, add file_c
        file_a.write_text("function funcA_v2() return 42 end", encoding="utf-8")
        os.remove(file_b)
        file_c = self.ws_path / "moduleC.luau"
        file_c.write_text("function funcC() return 99 end", encoding="utf-8")

        res3 = index.scan_and_index()
        self.assertEqual(res3["modified_count"], 1)
        self.assertEqual(res3["deleted_count"], 1)
        self.assertEqual(res3["added_count"], 1)
        self.assertIn("moduleA.luau", index.files)
        self.assertIn("moduleC.luau", index.files)
        self.assertNotIn("moduleB.luau", index.files)

        # Verify updated symbol in file_a
        syms_a = [s["name"] for s in index.files["moduleA.luau"].symbols]
        self.assertIn("funcA_v2", syms_a)

    # --------------------------------------------------------------------------
    # 3. EXCLUSION OF SECRETS, CREDENTIALS, AND GITIGNORE
    # --------------------------------------------------------------------------
    def test_03_secrets_and_gitignore_strict_exclusion(self):
        """Secret files (.env, keys) and gitignored directories are strictly excluded."""
        # Gitignore
        (self.ws_path / ".gitignore").write_text("ignored_folder/\n*.tmp\nsecret_notes.md\n", encoding="utf-8")

        # Files that must be excluded
        (self.ws_path / ".env").write_text("SECRET_KEY=12345", encoding="utf-8")
        (self.ws_path / ".env.local").write_text("STRIPE_KEY=xyz", encoding="utf-8")
        (self.ws_path / "github_token.txt").write_text("ghp_ABCDEF1234567890abcdefghijklmnopqrst", encoding="utf-8")
        (self.ws_path / "id_rsa").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQ...\n-----END RSA PRIVATE KEY-----", encoding="utf-8")
        (self.ws_path / "secret_notes.md").write_text("Do not read", encoding="utf-8")

        ign_dir = self.ws_path / "ignored_folder"
        ign_dir.mkdir()
        (ign_dir / "test.luau").write_text("function shouldNotBeIndexed() end", encoding="utf-8")

        # Valid file that must be included
        (self.ws_path / "valid.luau").write_text("function safeFunction() end", encoding="utf-8")

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        stats = index.scan_and_index()

        self.assertEqual(stats["indexed_count"], 1)
        self.assertIn("valid.luau", index.files)
        self.assertNotIn(".env", index.files)
        self.assertNotIn(".env.local", index.files)
        self.assertNotIn("github_token.txt", index.files)
        self.assertNotIn("id_rsa", index.files)
        self.assertNotIn("ignored_folder/test.luau", index.files)

        reasons = [item["reason"] for item in stats["skipped_files"]]
        self.assertTrue(any("secret" in r for r in reasons))
        self.assertTrue(any("gitignore" in r for r in reasons))

    # --------------------------------------------------------------------------
    # 4. ROBUST HANDLING: BINARY, MALFORMED, AND OVERSIZED FILES
    # --------------------------------------------------------------------------
    def test_04_binary_malformed_and_oversized_file_resilience(self):
        """Individual failures (binary, malformed XML, oversized) do not abort the entire index."""
        # 1. Binary file with .lua extension
        binary_path = self.ws_path / "corrupt.lua"
        binary_path.write_bytes(b"\x00\xff\xfe\x00\x12\x34\x56\x78\x00\x00binary_data")

        # 2. Malformed XML (.rbxmx)
        malformed_xml = self.ws_path / "broken.rbxmx"
        malformed_xml.write_text("<roblox><Item class='Part'><unclosed></roblox>", encoding="utf-8")

        # 3. Oversized file (> 1 MB)
        oversized_path = self.ws_path / "huge.luau"
        oversized_path.write_bytes(b"local x = 1\n" * 100_000)  # ~1.2 MB

        # 4. Valid file
        good_path = self.ws_path / "healthy.luau"
        good_path.write_text("function healthyLogic() return true end", encoding="utf-8")

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        stats = index.scan_and_index()

        # Healthy file must be indexed; the bad ones skipped individually
        self.assertEqual(stats["indexed_count"], 1)
        self.assertEqual(stats["skipped_count"], 3)
        self.assertIn("healthy.luau", index.files)
        self.assertNotIn("corrupt.lua", index.files)
        self.assertNotIn("broken.rbxmx", index.files)
        self.assertNotIn("huge.luau", index.files)

        skip_map = {item["path"]: item["reason"] for item in stats["skipped_files"]}
        self.assertEqual(skip_map["corrupt.lua"], "binary_file")
        self.assertIn("oversized", skip_map["huge.luau"])
        self.assertIn("parse_error", skip_map["broken.rbxmx"])

    # --------------------------------------------------------------------------
    # 5. TARGETED BM25 RETRIEVAL & CODE USAGE IN AI CHAT
    # --------------------------------------------------------------------------
    def test_05_targeted_retrieval_and_chat_prompt_injection(self):
        """Retrieves exact relevant snippets and verifies injected context in AI prompt."""
        (self.ws_path / "PhysicsEngine.luau").write_text(
            "local Physics = {}\n"
            "function Physics.calculateTrajectory(velocity: Vector3, gravity: number)\n"
            "    return velocity.Y / gravity\n"
            "end\n"
            "return Physics\n",
            encoding="utf-8"
        )
        (self.ws_path / "UIController.luau").write_text(
            "local UI = {}\n"
            "function UI.renderHealthBar(currentHealth: number, maxHealth: number)\n"
            "    return currentHealth / maxHealth\n"
            "end\n"
            "return UI\n",
            encoding="utf-8"
        )

        index = ProjectContextIndex(workspace_path=str(self.ws_path))
        index.scan_and_index()

        # Query targeting physics
        results = index.retrieve_context("calculate trajectory velocity physics")
        self.assertGreater(len(results), 0)
        top = results[0]
        self.assertEqual(top["path"], "PhysicsEngine.luau")
        self.assertIn("Physics.calculateTrajectory", top["matched_symbols"])

        # Format context block
        prompt_block = index.format_context_prompt_block("calculate trajectory velocity physics")
        self.assertIn("PhysicsEngine.luau", prompt_block)
        self.assertIn("calculateTrajectory", prompt_block)

    # --------------------------------------------------------------------------
    # 6. MULTIMODAL ATTACHMENT GATING (TEXT-ONLY MODEL HONESTY)
    # --------------------------------------------------------------------------
    def test_06_text_only_model_returns_honest_unsupported_not_canned_house(self):
        """Text-only model (llama3.2-1b) returns honest unsupported status without canned Roblox-house claims."""
        # Create a valid test PNG image (100x100 white square)
        img = Image.new("RGB", (100, 100), color="white")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        b64_img = base64.b64encode(bio.getvalue()).decode("utf-8")

        # Call analyze_attached_image for a text-only model
        att = main.FileAttachment(
            name="screenshot.png",
            content=f"data:image/png;base64,{b64_img}",
            type="image/png",
            is_image=True
        )

        analysis = main.analyze_attached_image(att, "Inspect this screenshot", model_id="llama3.2-1b")

        # Must NOT contain the old canned Roblox house text!
        self.assertNotIn("Modular House", analysis)
        self.assertNotIn("crimson slate roof", analysis)
        self.assertNotIn("SpawnedStructures", analysis)

        # Must report technical info and model limitations truthfully
        self.assertIn("100x100", analysis)
        self.assertIn("PNG", analysis)
        self.assertIn("text-only", analysis.lower())
        self.assertIn("does not support native visual processing", analysis)

    # --------------------------------------------------------------------------
    # 7. MULTIMODAL DECOMPRESSION BOMB MITIGATION
    # --------------------------------------------------------------------------
    def test_07_decompression_bomb_rejection(self):
        """Catches and rejects images with excessive pixel dimensions safely."""
        with mock.patch("PIL.Image.open") as mock_open:
            mock_img = mock.MagicMock()
            mock_img.verify.side_effect = Image.DecompressionBombError("Too many pixels")
            mock_open.return_value = mock_img

            with self.assertRaises(ImageAttachmentValidationError) as ctx:
                MultimodalAttachmentHandler.validate_and_decode_image(
                    content=base64.b64encode(b"fake_image_bytes").decode("utf-8"),
                    name="bomb.png"
                )
            self.assertIn("Decompression bomb", str(ctx.exception))

    # --------------------------------------------------------------------------
    # 8. MULTI-IMAGE ATTACHMENT ITERATION
    # --------------------------------------------------------------------------
    def test_08_multi_image_attachments_all_analyzed(self):
        """Every image attachment is analyzed, not only the first."""
        import asyncio

        def make_b64_image(w: int, h: int) -> str:
            im = Image.new("RGB", (w, h), color="blue")
            b = io.BytesIO()
            im.save(b, format="PNG")
            return base64.b64encode(b.getvalue()).decode("utf-8")

        att1 = main.FileAttachment(name="img1.png", content=make_b64_image(50, 50), type="image/png", is_image=True)
        att2 = main.FileAttachment(name="img2.png", content=make_b64_image(80, 60), type="image/png", is_image=True)

        results = asyncio.run(MultimodalAttachmentHandler.process_all_attachments(
            attachments=[att1, att2],
            model_id="llama3.2-1b",
            user_prompt="Examine both images"
        ))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["attachment_name"], "img1.png")
        self.assertEqual(results[0]["technical_metadata"]["width"], 50)
        self.assertEqual(results[1]["attachment_name"], "img2.png")
        self.assertEqual(results[1]["technical_metadata"]["width"], 80)

    # --------------------------------------------------------------------------
    # 9. REAL VISION MODEL DISPATCH
    # --------------------------------------------------------------------------
    def test_09_vision_capable_model_dispatches_genuine_inference(self):
        """When a vision-capable model (e.g. gpt-4o) is configured, genuine vision inference runs."""
        import asyncio

        # Mock the provider call for gpt-4o
        mock_provider = mock.AsyncMock()
        mock_provider.chat_complete.return_value = ProviderResponse(
            content="Detected a custom Roblox character rig with metallic mesh armor in the center.",
            model="gpt-4o",
            provider="openai",
            finish_reason="stop",
            selected_provider="openai"
        )

        with mock.patch.object(
            ai_provider_service.global_ai_provider_manager,
            "get_provider_for_model",
            return_value=mock_provider
        ):
            im = Image.new("RGB", (64, 64), color="red")
            bio = io.BytesIO()
            im.save(bio, format="PNG")
            b64_img = base64.b64encode(bio.getvalue()).decode("utf-8")

            res = asyncio.run(MultimodalAttachmentHandler.analyze_image_attachment(
                att_name="char.png",
                att_content=b64_img,
                model_id="gpt-4o",
                user_prompt="What character is this?"
            ))

            self.assertEqual(res["status"], "success")
            self.assertTrue(res["is_vision_capable"])
            self.assertIn("custom Roblox character rig", res["analysis"])
            self.assertIn("Disclaimed: Static screenshot observation only", res["message"])

    # --------------------------------------------------------------------------
    # 10. REST API ENDPOINTS
    # --------------------------------------------------------------------------
    def test_10_project_intelligence_api_endpoints(self):
        """FastAPI project index, status, search, and clear endpoints."""
        (self.ws_path / "Main.server.luau").write_text("function startServer() print('Booting') end", encoding="utf-8")

        # 1. POST /project/index
        idx_resp = self.client.post("/project/index", json={"workspace_path": str(self.ws_path)})
        self.assertEqual(idx_resp.status_code, 200)
        idx_data = idx_resp.json()
        self.assertEqual(idx_data["status"], "success")
        self.assertEqual(idx_data["indexed_count"], 1)

        # 2. GET /project/index/status
        status_resp = self.client.get(f"/project/index/status?workspace_path={self.ws_path}")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertEqual(status_data["total_files"], 1)

        # 3. POST /project/search
        search_resp = self.client.post("/project/search", json={"query": "startServer boot"})
        self.assertEqual(search_resp.status_code, 200)
        search_data = search_resp.json()
        self.assertEqual(search_data["results_count"], 1)
        self.assertEqual(search_data["results"][0]["path"], "Main.server.luau")

        # 4. DELETE /project/index
        del_resp = self.client.delete("/project/index")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "success")


if __name__ == "__main__":
    unittest.main()
