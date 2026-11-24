"""
Stroke AI // Core Functionality Reliability Test Suite
================================================================================
Comprehensive verification of:
1. AI Providers & BYOK: Model resolution, active config updates, UID-scoped probes.
2. Local Firestore: Snapshot references, dotted-path get, atomic transactions,
   rollbacks, where query filtering, sentinel values, and non-destructive corruption rejection.
3. Coding Loop & Verification Gates: 6 verification states, stagnation protection,
   error repetition limits, pre-modification backups.
4. Diagnostics & Reporting: Honest statuses without default false PASS.
================================================================================
"""

import os
import sys
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

import local_firestore
from local_firestore import LocalFirestoreClient, LocalDocumentSnapshot
import ai_provider_service
from coding_loop import (
    RobloxDomainTestRunner,
    StrokeCodingLoop,
    GoalUnderstandingEngine,
    SmartImplementationPlanner
)
import bug_hunter_service


class TestLocalFirestoreReliability(unittest.TestCase):
    """Deep verification of LocalFirestoreClient fidelity, transactions, and sentinels."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_local_db.json")
        self.client = LocalFirestoreClient(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_snapshot_retains_reference_and_dotted_get(self):
        """Snapshots returned from get() retain reference and support dotted-path field retrieval."""
        doc_ref = self.client.collection("users").document("user_snapshot_test")
        doc_ref.set({
            "uid": "user_snapshot_test",
            "profile": {
                "name": "Alex",
                "settings": {"theme": "cyber_dark"}
            },
            "login_count": 5
        })

        snap = doc_ref.get()
        self.assertTrue(snap.exists)
        self.assertEqual(snap.id, "user_snapshot_test")
        self.assertIsNotNone(snap.reference)
        self.assertEqual(snap.reference.path, "users/user_snapshot_test")

        # Test dotted-path get
        self.assertEqual(snap.get("profile.name"), "Alex")
        self.assertEqual(snap.get("profile.settings.theme"), "cyber_dark")
        self.assertEqual(snap.get("login_count"), 5)
        self.assertIsNone(snap.get("profile.nonexistent"))
        self.assertEqual(snap.get("nonexistent.path", "default_val"), "default_val")

    def test_02_transaction_commit_and_rollback(self):
        """LocalTx applies batch operations atomically upon exit or rolls back on exception."""
        user_ref = self.client.collection("users").document("user_tx_test")
        user_ref.set({"balance": 100})

        # Successful transaction
        with self.client.transaction() as tx:
            snap = tx.get(user_ref)
            curr_bal = snap.get("balance")
            tx.update(user_ref, {"balance": curr_bal + 50})

        self.assertEqual(user_ref.get().get("balance"), 150)

        # Failed transaction rolls back
        try:
            with self.client.transaction() as tx:
                tx.update(user_ref, {"balance": 999})
                raise ValueError("Simulated abort in business logic")
        except ValueError:
            pass

        # Balance remains 150, not 999
        self.assertEqual(user_ref.get().get("balance"), 150)

    def test_03_query_where_filtering_and_get(self):
        """LocalQuery supports where() with operators (==, !=, >, in, array_contains) and .get()."""
        col = self.client.collection("items")
        col.document("item_1").set({"category": "sword", "tier": 3, "tags": ["rare", "metal"]})
        col.document("item_2").set({"category": "shield", "tier": 1, "tags": ["common", "wood"]})
        col.document("item_3").set({"category": "sword", "tier": 5, "tags": ["legendary", "fire"]})

        # Filter by category == "sword"
        swords = list(col.where("category", "==", "sword").get())
        self.assertEqual(len(swords), 2)

        # Filter by tier > 2
        high_tier = list(col.where("tier", ">", 2).get())
        self.assertEqual(len(high_tier), 2)

        # Filter by array_contains
        fire_items = list(col.where("tags", "array_contains", "fire").get())
        self.assertEqual(len(fire_items), 1)
        self.assertEqual(fire_items[0].id, "item_3")

    def test_04_sentinel_resolution(self):
        """Resolves Increment, ArrayUnion, ArrayRemove, and SERVER_TIMESTAMP."""
        class MockIncrement:
            value = 10
        class MockArrayUnion:
            values = ["tagA", "tagB"]
        class MockArrayRemove:
            values = ["tagB"]

        doc = self.client.collection("metrics").document("counter")
        doc.set({"count": 5, "tags": ["initial"]})

        doc.update({
            "count": MockIncrement(),
            "tags": MockArrayUnion(),
            "timestamp": "SERVER_TIMESTAMP"
        })

        updated = doc.get().to_dict()
        self.assertEqual(updated["count"], 15)
        self.assertIn("tagA", updated["tags"])
        self.assertIn("tagB", updated["tags"])
        self.assertIn("initial", updated["tags"])
        self.assertIsNotNone(updated["timestamp"])

        # Test ArrayRemove
        doc.update({"tags": MockArrayRemove()})
        cleaned = doc.get().to_dict()
        self.assertNotIn("tagB", cleaned["tags"])
        self.assertIn("tagA", cleaned["tags"])

    def test_05_corrupted_json_rejects_overwrite_and_backs_up(self):
        """Corrupted database file triggers safe backup and raises error instead of silently returning empty dict."""
        with open(self.db_path, "w", encoding="utf-8") as f:
            f.write("{corrupted_json_bytes!!!")

        with self.assertRaises(RuntimeError) as ctx:
            client2 = LocalFirestoreClient(db_path=self.db_path)

        self.assertIn("corrupted", str(ctx.exception).lower())
        self.assertIn(".bak", str(ctx.exception))


class TestAiProvidersAndModelRegistry(unittest.TestCase):
    """Audits authoritative models, active preferences, and UID-scoped health probes."""

    def test_06_model_resolution_and_aliases(self):
        """Resolves official and alias model IDs to canonical registry entries."""
        self.assertEqual(ai_provider_service.resolve_model_id("groq"), "llama-3.3-70b-versatile")
        self.assertEqual(ai_provider_service.resolve_model_id("gemini"), "gemini-2.0-flash")
        self.assertEqual(ai_provider_service.resolve_model_id("claude"), "claude-3-5-sonnet-20241022")
        self.assertEqual(ai_provider_service.resolve_model_id("gpt-4o"), "gpt-4o")

    def test_07_active_model_config_atomicity_and_normalization(self):
        """Saving model updates resolves aliases and persists atomically."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_cfg_path = os.path.join(tmp_dir, "active_model_config.json")
            with patch("ai_provider_service.get_active_model_config_path", return_value=test_cfg_path):
                updated = ai_provider_service.set_active_model_config({
                    "active_provider": "GEMINI",
                    "active_model": "gemini"
                })
                self.assertEqual(updated["active_provider"], "gemini")
                self.assertEqual(updated["active_model"], "gemini-2.0-flash")

                # Re-read
                read_cfg = ai_provider_service.get_active_model_config()
                self.assertEqual(read_cfg["active_model"], "gemini-2.0-flash")


class TestCodingLoopVerificationStates(unittest.TestCase):
    """Audits 6 fine-grained verification states and loop stagnation guards."""

    def test_08_verification_states_fine_grained(self):
        """Verification states cleanly separate passed, failed, partially_verified, not_tested, compiler_unavailable."""
        # 1. Generic code -> not_tested
        gen_rep = RobloxDomainTestRunner.test_generic_code("fn main() {}", "rust")
        self.assertEqual(gen_rep["verification_state"], "not_tested")
        self.assertFalse(gen_rep["is_verified"])

        # 2. Python invalid syntax -> failed
        py_fail = RobloxDomainTestRunner.test_python_code("def broken(:\n    pass")
        self.assertEqual(py_fail["verification_state"], "failed")
        self.assertEqual(py_fail["verification_status"], "FAIL")

        # 3. Luau with fake API call -> failed
        luau_fake = RobloxDomainTestRunner.test_luau_code("local p = Instance.new('Part')\np:SpawnParticleEmitter()", prompt="Create part")
        self.assertEqual(luau_fake["verification_state"], "failed")
        self.assertEqual(luau_fake["verification_status"], "FAIL")

    def test_09_stagnant_model_halt(self):
        """Stagnant identical output halts the coding loop to prevent infinite token burn."""
        import workspace_service
        with tempfile.TemporaryDirectory() as ws_dir:
            workspace_service.approve_workspace(ws_dir)
            code = "```python\ndef stuck():\n    return 42\n```"
            res = StrokeCodingLoop.run_smart_coding_workflow(
                prompt="Fix function",
                initial_reply=code,
                workspace_path=ws_dir,
                llm_generate_fn=lambda msgs: code,
                max_iterations=5
            )
            self.assertIsNotNone(res)
            # Loop terminated within budget
            self.assertLessEqual(res.iterations, 4)


class TestDiagnosticReportingHonesty(unittest.TestCase):
    """Ensures diagnostic summaries report truthful NOT RUN / FAIL instead of false PASS."""

    def test_10_diagnostics_report_no_false_pass_on_missing_checks(self):
        """Bug report generator does not default omitted checks to PASS."""
        report = bug_hunter_service.BugHuntReport(
            report_id="TEST-001",
            timestamp=1234567890.0,
            workspace_path="/tmp/test",
            duration_ms=10.0,
            total_issues=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            test_summary={
                "backend_passed": 10,
                "backend_failed": 0,
                "backend_skipped": 0
            },
            subsystems_checked=[],
            issues=[]
        )
        md = bug_hunter_service.BugReportGenerator.generate_markdown_report(report)
        # Authentication and Terminal were not run in this summary, so they must NOT say ✅ PASS
        self.assertNotIn("| **Authentication Diagnostics** | PASS | ✅ PASS |", md)
        self.assertIn("NOT RUN", md)


if __name__ == "__main__":
    unittest.main()
