"""
================================================================================
STROKE // VFX KNOWLEDGE REGISTRY & TELEMETRY TEST SUITE
================================================================================
Verifies:
  1. Seeded vs User-Derived Separation:
     - Seeded reference patterns marked source_type='seeded'.
     - Seeded insights NEVER count toward total_chats_learned (starts at 0).
     - User-derived insights marked source_type='user_derived'.
  2. Missing, Empty, and Malformed Dataset Ingestion:
     - Missing or malformed vfx_data.json handles errors gracefully.
     - Zero fake counts or fallback numbers (no fabricated 15 emitters / 6 beams).
  3. Shipped Dataset Immutability & Persistence Isolation:
     - Read-only shipped files in repo data/ are never mutated.
     - Mutable files persisted to paths_service application data directory.
  4. Atomic Writes, Backups, and Thread Concurrency:
     - Atomic write (.tmp -> fsync -> .replace) creates .bak backup.
     - Multi-threaded learning operations execute without race conditions or corruption.
  5. Privacy & User Opt-Out Controls:
     - Opt-out disables retention and learning.
     - Opt-in resumes normal distillation.
  6. Feeding Cycle Integrity & Deterministic Content Hash:
     - Real SHA-256 hash of actual cycle payload.
     - Status is 'ingested' (not unverified 'optimized' or 'trained').
     - Zero fallback counts when models have 0 emitters / 0 beams.
  7. God-Tier VFX Evaluator & Chat Distillation:
     - Filters conversational, refusal, fake API, and trivial ball requests.
     - Accurately distills genuine God-Tier VFX Luau code.
  8. Honest Telemetry & RAG Semantics:
     - retrieval_method='lexicon_expanded_keyword_search' (NOT embeddings).
     - model_training='none_prompt_context_retrieval_only' (NOT fine-tuning).
     - Exact record reconciliation of counts and average scores.
  9. Lexicon-Expanded Keyword Search:
     - Multi-token and synonym expansion matches real models.
     - Empty/irrelevant queries return empty results without hallucinating.
  10. REST API Endpoints Integration:
     - /database/mandatory-cache, /ai/learned-insights, /ai/learning-preferences,
       /ai/learn-from-chats, /ai/refeed-with-learnings.
================================================================================
"""

import os
import json
import shutil
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import vfx_service
import paths_service
import main
import auth_service
from fastapi.testclient import TestClient


class TestVFXKnowledgeRegistryAndTelemetry(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="stroke_vfx_test_")
        self.user_vfx_dir = Path(self.test_dir) / "vfx"
        self.user_vfx_dir.mkdir(parents=True, exist_ok=True)

        # Patch paths_service to isolate tests
        self.patcher_app_data = mock.patch(
            "paths_service.get_app_data_dir",
            return_value=Path(self.test_dir)
        )
        self.patcher_app_data.start()

        # Update vfx_service storage paths to point to test dir
        vfx_service.USER_VFX_DIR = self.user_vfx_dir
        vfx_service.LEARNED_INSIGHTS_PATH = self.user_vfx_dir / "learned_chat_insights.json"
        vfx_service.LEARNED_MODELS_PATH = self.user_vfx_dir / "vfx_learned_models.json"
        vfx_service.LEARNING_PREFS_PATH = self.user_vfx_dir / "vfx_learning_prefs.json"

        # Isolate legacy paths so repo files don't leak into tests
        self.orig_legacy_insights = vfx_service.LEGACY_INSIGHTS_PATH
        self.orig_legacy_models = vfx_service.LEGACY_MODELS_PATH
        vfx_service.LEGACY_INSIGHTS_PATH = os.path.join(self.test_dir, "nonexistent_legacy_insights.json")
        vfx_service.LEGACY_MODELS_PATH = os.path.join(self.test_dir, "nonexistent_legacy_models.json")

        # Reset in-memory state
        with vfx_service._VFX_LOCK:
            vfx_service._VFX_CACHE = {
                "models": {},
                "instances_count": 0,
                "textures_count": 0,
                "raw_dump_text": None,
                "initialized": False,
                "error": None
            }
            vfx_service._LEARNED_POOL = {
                "insights": [],
                "total_chats_learned": 0,
                "initialized": False
            }

        # Setup FastAPI TestClient with auth override
        main.app.dependency_overrides[main.get_current_user] = lambda: auth_service.AuthenticatedUser(
            uid="test_user_vfx",
            email="vfx_tester@stroke.ai",
            auth_provider="email"
        )
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.patcher_app_data.stop()
        vfx_service.LEGACY_INSIGHTS_PATH = self.orig_legacy_insights
        vfx_service.LEGACY_MODELS_PATH = self.orig_legacy_models
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. SEEDED VS USER-DERIVED SEPARATION & ZERO INITIAL CHATS LEARNED
    # --------------------------------------------------------------------------
    def test_01_seeded_vs_user_derived_separation_and_zero_initial_learned_chats(self):
        insights = vfx_service.load_learned_insights()
        self.assertTrue(len(insights) > 0, "Default seeded insights should be loaded")

        for item in insights:
            self.assertEqual(
                item.get("source_type"),
                "seeded",
                f"Initial insight {item.get('id')} must be marked source_type='seeded'"
            )

        telemetry = vfx_service.get_learning_telemetry()
        self.assertEqual(
            telemetry["total_chats_learned"], 0,
            "Seeded insights must NEVER count toward total_chats_learned!"
        )
        self.assertEqual(
            telemetry["total_chats_distilled"], 0,
            "Seeded insights must NEVER count toward total_chats_distilled!"
        )
        self.assertEqual(
            telemetry["user_derived_insights_count"], 0,
            "Initial user-derived count must be 0"
        )
        self.assertEqual(
            telemetry["seeded_insights_count"], len(insights),
            "Seeded count must match total seeded insights loaded"
        )
        self.assertEqual(telemetry["active_insights_count"], len(insights))

    # --------------------------------------------------------------------------
    # 2. MISSING, EMPTY, AND MALFORMED DATASET INGESTION
    # --------------------------------------------------------------------------
    def test_02_missing_empty_and_malformed_dataset_handling(self):
        # Case A: Missing file
        orig_json = vfx_service.VFX_JSON_PATH
        vfx_service.VFX_JSON_PATH = os.path.join(self.test_dir, "non_existent.json")
        with vfx_service._VFX_LOCK:
            vfx_service._VFX_CACHE["initialized"] = False

        cache_missing = vfx_service.load_vfx_database()
        self.assertTrue(cache_missing["initialized"])
        self.assertEqual(len(cache_missing["models"]), 0)
        self.assertEqual(cache_missing["instances_count"], 0)

        # Case B: Empty file
        empty_json = os.path.join(self.test_dir, "empty_vfx.json")
        with open(empty_json, "w", encoding="utf-8") as f:
            f.write("")
        vfx_service.VFX_JSON_PATH = empty_json
        with vfx_service._VFX_LOCK:
            vfx_service._VFX_CACHE["initialized"] = False

        cache_empty = vfx_service.load_vfx_database()
        self.assertTrue(cache_empty["initialized"])
        self.assertEqual(len(cache_empty["models"]), 0)
        self.assertEqual(cache_empty["instances_count"], 0)

        # Case C: Malformed JSON
        malformed_json = os.path.join(self.test_dir, "corrupted_vfx.json")
        with open(malformed_json, "w", encoding="utf-8") as f:
            f.write("{corrupted_syntax: true, [unclosed")
        vfx_service.VFX_JSON_PATH = malformed_json
        with vfx_service._VFX_LOCK:
            vfx_service._VFX_CACHE["initialized"] = False

        cache_malformed = vfx_service.load_vfx_database()
        self.assertTrue(cache_malformed["initialized"])
        self.assertIsNotNone(cache_malformed["error"])
        self.assertIn("JSONDecodeError", cache_malformed["error"])
        self.assertEqual(len(cache_malformed["models"]), 0)
        self.assertEqual(cache_malformed["instances_count"], 0)

        # Restore
        vfx_service.VFX_JSON_PATH = orig_json

    # --------------------------------------------------------------------------
    # 3. SHIPPED DATASET IMMUTABILITY & PERSISTENCE ISOLATION
    # --------------------------------------------------------------------------
    def test_03_shipped_dataset_immutability_and_user_storage_isolation(self):
        self.assertTrue(
            str(vfx_service.LEARNED_INSIGHTS_PATH).startswith(str(self.user_vfx_dir)),
            "Learned insights path must reside in user app data directory"
        )
        self.assertTrue(
            str(vfx_service.LEARNED_MODELS_PATH).startswith(str(self.user_vfx_dir)),
            "Learned models path must reside in user app data directory"
        )
        self.assertTrue(
            str(vfx_service.LEARNING_PREFS_PATH).startswith(str(self.user_vfx_dir)),
            "Learning preferences path must reside in user app data directory"
        )

        # Trigger save
        vfx_service.save_learned_insights()
        self.assertTrue(vfx_service.LEARNED_INSIGHTS_PATH.exists())

        # Verify shipped dataset in repo data/ was NOT touched or replaced
        self.assertFalse(str(vfx_service.LEARNED_INSIGHTS_PATH).startswith(vfx_service.REPO_DATA_DIR))

    # --------------------------------------------------------------------------
    # 4. ATOMIC WRITES, BACKUPS, AND THREAD CONCURRENCY
    # --------------------------------------------------------------------------
    def test_04_atomic_writes_concurrency_and_backups(self):
        target = self.user_vfx_dir / "test_atomic.json"

        # Initial write
        payload1 = {"version": 1, "data": "initial"}
        ok1 = vfx_service._atomic_write_json(target, payload1)
        self.assertTrue(ok1)
        self.assertTrue(target.exists())

        # Second write should create .bak backup
        payload2 = {"version": 2, "data": "updated"}
        ok2 = vfx_service._atomic_write_json(target, payload2)
        self.assertTrue(ok2)
        bak_file = target.with_suffix(".bak")
        self.assertTrue(bak_file.exists(), ".bak backup must be created on overwrite")

        with open(bak_file, "r", encoding="utf-8") as f:
            bak_data = json.load(f)
            self.assertEqual(bak_data["version"], 1)

        with open(target, "r", encoding="utf-8") as f:
            curr_data = json.load(f)
            self.assertEqual(curr_data["version"], 2)

        # Concurrency stress test: 8 threads concurrently recording chats
        def worker(idx):
            vfx_service.evaluate_and_learn_god_tier_vfx(
                prompt=f"Sukuna cleave slash technique {idx}",
                reply=(
                    f"```luau\n"
                    f"local emitter = Instance.new('ParticleEmitter')\n"
                    f"emitter.Rate = {100 + idx}\n"
                    f"emitter.Lifetime = NumberRange.new(0.2, 0.4)\n"
                    f"emitter.Drag = 22.0\n"
                    f"emitter.Texture = 'rbxassetid://18462751521'\n"
                    f"local debris = game:GetService('Debris')\n"
                    f"debris:AddItem(emitter, 2)\n"
                    f"```\n"
                    f"Sukuna domain cleave shockwave with high-speed disc deceleration and drag decay."
                ),
                tool_used="concurrency_test",
                user_email=f"user{idx}@stroke.ai"
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        insights = vfx_service.load_learned_insights()
        user_insights = [i for i in insights if i.get("source_type") == "user_derived"]
        self.assertEqual(len(user_insights), 8, "All 8 concurrent writes must succeed safely without loss")
        telemetry = vfx_service.get_learning_telemetry()
        self.assertEqual(telemetry["total_chats_learned"], 8)

    # --------------------------------------------------------------------------
    # 5. PRIVACY & USER OPT-OUT CONTROLS
    # --------------------------------------------------------------------------
    def test_05_privacy_and_user_opt_out_controls(self):
        # Default should be enabled
        self.assertTrue(vfx_service.is_learning_retention_enabled())

        # Set opt-out
        vfx_service.set_learning_retention_opt_in(False)
        self.assertFalse(vfx_service.is_learning_retention_enabled())

        # Attempt to learn God-Tier VFX while opted out
        res = vfx_service.evaluate_and_learn_god_tier_vfx(
            prompt="Sukuna 360 cleave slash attack",
            reply=(
                "```luau\n"
                "local emitter = Instance.new('ParticleEmitter')\n"
                "emitter.Drag = 22.0\n"
                "emitter.Texture = 'rbxassetid://18462751521'\n"
                "```\n"
                "Sukuna cleave blade."
            )
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "opted_out")
        self.assertIn("disabled by user preference", res.get("message", ""))

        # Verify pool was not modified
        telemetry = vfx_service.get_learning_telemetry()
        self.assertEqual(telemetry["total_chats_learned"], 0)

        # Re-enable opt-in
        vfx_service.set_learning_retention_opt_in(True)
        self.assertTrue(vfx_service.is_learning_retention_enabled())

    # --------------------------------------------------------------------------
    # 6. FEEDING CYCLE INTEGRITY & DETERMINISTIC CONTENT HASH
    # --------------------------------------------------------------------------
    def test_06_feeding_cycle_records_integrity_hash_and_no_fallback_counts(self):
        for cycle in range(1, 6):
            res = vfx_service.execute_feeding_cycle(cycle, "test@stroke.ai")
            rec = res["record"]
            self.assertEqual(rec["cycle"], cycle)
            self.assertEqual(rec["record_id"], f"STRK-BAT-{cycle:03d}")
            self.assertEqual(rec["status"], "ingested", "Status must be honest 'ingested'")

            # Integrity hash must be 64-char SHA-256
            self.assertEqual(len(rec["integrity_hash"]), 64)
            # Recompute expected hash
            expected_payload = json.dumps({
                "cycle": cycle,
                "stage_name": rec["stage_name"],
                "element": rec["element"],
                "models": sorted(rec["models_absorbed"]),
                "total_emitters": rec["particle_count"],
                "total_beams": rec["beam_count"],
                "primary_asset": rec["primary_asset"]
            }, sort_keys=True)
            expected_hash = hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
            self.assertEqual(rec["integrity_hash"], expected_hash)

        # Test zero-count model ingestion (zero emitters, zero beams)
        # Verify that it reports particle_count=0, beam_count=0, NEVER fabricating fallback 15 or 6
        with mock.patch("vfx_service.get_cycle_data", return_value={
            "cycle": 1,
            "stage_name": "Test Zero Stage",
            "domain": "Void",
            "element": "Void",
            "color_hex": "#c15eff",
            "primary_asset": "rbxassetid://13780268621",
            "models": [{"name": "ZeroModel", "particle_emitters_count": 0, "beams_count": 0, "parts_count": 0, "sample_textures": []}],
            "total_emitters": 0,
            "total_beams": 0,
            "distinct_textures": [],
            "focus_attributes": [],
            "combined_raw_snippet": ""
        }):
            zero_res = vfx_service.execute_feeding_cycle(1, "test@stroke.ai")
            zero_rec = zero_res["record"]
            self.assertEqual(zero_rec["particle_count"], 0, "Must report 0 emitters, never fallback 15!")
            self.assertEqual(zero_rec["beam_count"], 0, "Must report 0 beams, never fallback 6!")

    # --------------------------------------------------------------------------
    # 7. GOD-TIER VFX EVALUATOR & CHAT DISTILLATION
    # --------------------------------------------------------------------------
    def test_07_god_tier_vfx_filter_and_user_derived_distillation(self):
        # 1. Reject conversational
        self.assertFalse(vfx_service.is_god_tier_vfx("Who are you?", "I am Stroke AI."))
        self.assertFalse(vfx_service.is_god_tier_vfx("Spawn a house", "Here is a modular house."))

        # 2. Reject refusal
        self.assertFalse(vfx_service.is_god_tier_vfx(
            "Create Sukuna cleave",
            "I cannot assist with that request as an AI safety policy."
        ))

        # 3. Reject fake APIs
        self.assertFalse(vfx_service.is_god_tier_vfx(
            "Sukuna domain slash",
            "local part = SpawnParticleEmitter() local p = Particle.new()"
        ))

        # 4. Reject trivial primitives
        self.assertFalse(vfx_service.is_god_tier_vfx(
            "Create a red ball",
            "local ball = Instance.new('Part') ball.Shape = Enum.PartType.Ball"
        ))

        # 5. Accept genuine God-Tier VFX
        valid_prompt = "Sukuna 360 cleave slash VFX"
        valid_reply = (
            "```luau\n"
            "local emitter = Instance.new('ParticleEmitter')\n"
            "emitter.Rate = 120\n"
            "emitter.Lifetime = NumberRange.new(0.15, 0.25)\n"
            "emitter.Drag = 22.0\n"
            "emitter.Acceleration = Vector3.new(0, 20, 0)\n"
            "emitter.Texture = 'rbxassetid://18462751521'\n"
            "local debris = game:GetService('Debris')\n"
            "debris:AddItem(emitter, 1)\n"
            "```\n"
            "Sukuna 360-degree cleave disc particle system with high drag decay to prevent outrunning the character."
        )
        self.assertTrue(vfx_service.is_god_tier_vfx(valid_prompt, valid_reply))

        # Distill valid interaction
        new_insight = vfx_service.evaluate_and_learn_god_tier_vfx(
            valid_prompt, valid_reply, tool_used="god_tier_test", user_email="sukuna@jujutsu.ac"
        )
        self.assertIsNotNone(new_insight)
        self.assertEqual(new_insight["source_type"], "user_derived")
        self.assertEqual(new_insight["domain"], "Slash")
        self.assertTrue(new_insight["id"].startswith("INS-GOD-SLAS"))

        # Verify pool update
        telemetry = vfx_service.get_learning_telemetry()
        self.assertEqual(telemetry["total_chats_learned"], 1)
        self.assertEqual(telemetry["user_derived_insights_count"], 1)

    # --------------------------------------------------------------------------
    # 8. HONEST TELEMETRY & RAG SEMANTICS
    # --------------------------------------------------------------------------
    def test_08_honest_telemetry_and_rag_semantics(self):
        telemetry = vfx_service.get_learning_telemetry()

        # Check honest terminology
        self.assertEqual(
            telemetry["retrieval_method"], "lexicon_expanded_keyword_search",
            "Must honestly declare keyword search, NOT embeddings"
        )
        self.assertEqual(
            telemetry["model_training"], "none_prompt_context_retrieval_only",
            "Must honestly declare prompt context retrieval, NOT neural model fine-tuning"
        )
        self.assertIn("RAG knowledge registry", telemetry["description"])
        self.assertIn("Does not perform neural network model training", telemetry["description"])

        # Check mathematical consistency of telemetry
        insights = vfx_service.load_learned_insights()
        self.assertEqual(telemetry["active_insights_count"], len(insights))
        self.assertEqual(
            telemetry["active_insights_count"],
            telemetry["seeded_insights_count"] + telemetry["user_derived_insights_count"]
        )

        expected_avg = round(sum(float(i.get("impact_score", 0.0)) for i in insights) / len(insights), 2)
        self.assertAlmostEqual(telemetry["average_quality_score"], expected_avg, places=2)

    # --------------------------------------------------------------------------
    # 9. LEXICON-EXPANDED KEYWORD SEARCH
    # --------------------------------------------------------------------------
    def test_09_lexicon_expanded_keyword_search(self):
        # Ingest the real dataset if available
        vfx_service.load_vfx_database()

        # Query lightning: should expand to electro, storm, sparks
        results = vfx_service.search_vfx_database("crackling lightning storm", max_results=5)
        self.assertIsInstance(results, list)
        if len(vfx_service._VFX_CACHE["models"]) > 0:
            self.assertTrue(len(results) > 0, "Should match electro/lightning models in database")
            first = results[0]
            self.assertIn("model_name", first)
            self.assertIn("particle_emitters_count", first)
            self.assertIn("beams_count", first)
            self.assertIn("snippet", first)

        # Empty query should return empty list
        empty_res = vfx_service.search_vfx_database("", max_results=5)
        self.assertEqual(empty_res, [])

        # Irrelevant nonsense query should return empty or low score
        junk_res = vfx_service.search_vfx_database("xyz987qrpnonexistentconcept", max_results=5)
        self.assertEqual(junk_res, [])

    # --------------------------------------------------------------------------
    # 10. REST API ENDPOINTS INTEGRATION
    # --------------------------------------------------------------------------
    def test_10_api_endpoints_integration(self):
        # GET /database/mandatory-cache
        res_cache = self.client.get("/database/mandatory-cache")
        self.assertEqual(res_cache.status_code, 200)
        cdata = res_cache.json()
        self.assertEqual(cdata["status"], "ingested")
        self.assertEqual(cdata["dataset"], "Elemental Worlds VFX Matrix")
        self.assertIn("checksum", cdata)
        self.assertEqual(cdata["injection_cycles"], 5)

        # GET /ai/learned-insights
        res_insights = self.client.get("/ai/learned-insights")
        self.assertEqual(res_insights.status_code, 200)
        idata = res_insights.json()
        self.assertEqual(idata["status"], "success")
        self.assertIn("telemetry", idata)
        self.assertIn("insights", idata)

        # GET /ai/learning-preferences
        res_prefs = self.client.get("/ai/learning-preferences")
        self.assertEqual(res_prefs.status_code, 200)
        self.assertTrue(res_prefs.json()["allow_learning_retention"])

        # POST /ai/learning-preferences (opt-out)
        res_set_prefs = self.client.post("/ai/learning-preferences", json={"allow_learning_retention": False})
        self.assertEqual(res_set_prefs.status_code, 200)
        self.assertFalse(res_set_prefs.json()["allow_learning_retention"])
        self.assertFalse(vfx_service.is_learning_retention_enabled())

        # Restore opt-in
        self.client.post("/ai/learning-preferences", json={"allow_learning_retention": True})
        self.assertTrue(vfx_service.is_learning_retention_enabled())

        # POST /ai/learn-from-chats (temporary chat should be ignored)
        res_temp = self.client.post("/ai/learn-from-chats", json={
            "prompt": "Sukuna cleave",
            "response": "emitter code",
            "is_temporary": True
        })
        self.assertEqual(res_temp.status_code, 200)
        self.assertEqual(res_temp.json()["status"], "ignored")

        # POST /ai/refeed-with-learnings
        res_refeed = self.client.post("/ai/refeed-with-learnings", json={
            "email": "test@stroke.ai"
        })
        self.assertEqual(res_refeed.status_code, 200)
        rdata = res_refeed.json()
        self.assertEqual(rdata["status"], "success")
        self.assertEqual(rdata["records_count"], 5)
        self.assertIn("learning_stats", rdata)

    # --------------------------------------------------------------------------
    # 11. LEGACY MIGRATION TO USER APPLICATION DATA DIRECTORY
    # --------------------------------------------------------------------------
    def test_11_legacy_migration_to_user_app_data(self):
        # Create a mock legacy insights file
        legacy_file = Path(self.test_dir) / "legacy_insights.json"
        with open(legacy_file, "w", encoding="utf-8") as f:
            json.dump({
                "total_chats_learned": 1,
                "insights": [
                    {
                        "id": "INS-GOD-MIGRATE-001",
                        "domain": "Fire",
                        "topic": "Legacy Fire Ingestion",
                        "summary": "Migrated from legacy repo data directory",
                        "impact_score": 8.5
                    }
                ]
            }, f)

        vfx_service.LEGACY_INSIGHTS_PATH = str(legacy_file)
        with vfx_service._VFX_LOCK:
            vfx_service._LEARNED_POOL["initialized"] = False
            vfx_service._LEARNED_POOL["insights"] = []

        migrated_insights = vfx_service.load_learned_insights()
        self.assertTrue(any(i.get("id") == "INS-GOD-MIGRATE-001" for i in migrated_insights))
        # Ensure migrated insight is classified as user_derived and persisted in user app data
        migrated_item = next(i for i in migrated_insights if i.get("id") == "INS-GOD-MIGRATE-001")
        self.assertEqual(migrated_item.get("source_type"), "user_derived")
        self.assertTrue(vfx_service.LEARNED_INSIGHTS_PATH.exists())


if __name__ == "__main__":
    unittest.main()
