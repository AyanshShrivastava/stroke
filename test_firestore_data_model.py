"""
Stroke AI // Firestore Data Model & Reliability Test Suite
Comprehensive verification of UID-based data modeling, strict authorization,
quota enforcement, batched pagination, failure handling, and migration integrity.
"""

import os
import sys
import time
import json
import shutil
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Set offline mode for local test client execution
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"
os.environ["FIREBASE_PROJECT_ID"] = "stroke-test-matrix"

from fastapi.testclient import TestClient
import main
from main import (
    app,
    db,
    initialize_firestore_client,
    record_user_firestore_memory,
    USER_MEMORY_QUOTA_BYTES
)
from local_firestore import LocalFirestoreClient
import migration_service
import auth_service


class TestFirestoreReliability(unittest.TestCase):
    """Audits Firestore credentials, fallback elimination, and local persistence."""

    def setUp(self):
        self.client = TestClient(app)
        self.test_data_dir = os.path.join(ROOT_DIR, "data", "test_scratch")
        os.makedirs(self.test_data_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_data_dir):
            shutil.rmtree(self.test_data_dir, ignore_errors=True)

    def test_01_no_anonymous_production_fallback(self):
        """
        Visible Failure: initialize_firestore_client must raise a visible RuntimeError
        when credentials and emulator are absent and STROKE_ALLOW_OFFLINE_DB is not set.
        """
        with patch.dict(os.environ, {
            "FIRESTORE_EMULATOR_HOST": "",
            "FIREBASE_SERVICE_ACCOUNT_JSON": "",
            "GOOGLE_APPLICATION_CREDENTIALS": "",
            "FIREBASE_CREDENTIALS": "",
            "STROKE_ALLOW_OFFLINE_DB": "0"
        }, clear=False):
            with patch("firebase_admin.credentials.ApplicationDefault", side_effect=Exception("No ADC found")):
                with self.assertRaises(RuntimeError) as ctx:
                    initialize_firestore_client()
                self.assertIn("Cloud Firestore credentials invalid or absent", str(ctx.exception))
                self.assertIn("Anonymous production fallback is disabled", str(ctx.exception))

    def test_02_genuine_local_storage_engine(self):
        """
        Verified Persistence: LocalFirestoreClient provides genuine disk-backed collections,
        subcollections, queries, batches, and transactions.
        """
        test_db_path = os.path.join(self.test_data_dir, "test_local_db.json")
        local_db = LocalFirestoreClient(db_path=test_db_path)

        # 1. Write user root document
        user_ref = local_db.collection("users").document("user_abc123")
        user_ref.set({"uid": "user_abc123", "email": "test@stroke.ai", "database_fed": False})

        # 2. Verify on-disk file was created
        self.assertTrue(os.path.exists(test_db_path))

        # 3. Write subcollection record
        rec_ref = user_ref.collection("records").document("STRK-BAT-001")
        rec_ref.set({"record_id": "STRK-BAT-001", "vfx_name": "Cosmic Flare", "cycle": 1})

        # 4. Stream subcollection
        recs = list(user_ref.collection("records").stream())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].to_dict()["record_id"], "STRK-BAT-001")

        # 5. Batch write and commit
        batch = local_db.batch()
        batch.set(user_ref.collection("records").document("STRK-BAT-002"), {"record_id": "STRK-BAT-002", "cycle": 2})
        batch.update(user_ref, {"database_fed": True})
        batch.commit()

        updated_user = user_ref.get().to_dict()
        self.assertTrue(updated_user["database_fed"])
        self.assertEqual(len(list(user_ref.collection("records").stream())), 2)


class TestMemoryReliabilityAndQuota(unittest.TestCase):
    """Audits memory quota pre-write enforcement and paginated batched deletion."""

    def setUp(self):
        self.client = TestClient(app)
        self.uid = f"test_mem_uid_{int(time.time() * 1000)}"
        self.email = f"{self.uid}@stroke.ai"
        self.mock_claims = {
            "user_id": self.uid,
            "email": self.email,
            "email_verified": True,
            "aud": "stroke-test-matrix",
            "iss": "https://securetoken.google.com/stroke-test-matrix",
            "exp": time.time() + 3600
        }
        self.auth_headers = {"Authorization": "Bearer mock-token-mem"}

    def test_03_pre_write_quota_rejection_over_100mb(self):
        """
        Quota Enforcement: A single memory entry exceeding 100 MB must be rejected
        immediately before write.
        """
        giant_reply = "A" * (USER_MEMORY_QUOTA_BYTES + 1024)
        with self.assertRaises(ValueError) as ctx:
            record_user_firestore_memory(
                uid=self.uid,
                prompt="Generate massive VFX dump",
                reply=giant_reply,
                tool_used="synthesis"
            )
        self.assertIn("exceeds entire 100 MB quota", str(ctx.exception))

    def test_04_memory_clear_scale_0_and_1(self):
        """
        Paginated Deletion: /memory/clear handles collections with 0 and 1 documents gracefully.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            # 1. Clear empty collection (0 documents)
            res0 = self.client.post("/memory/clear", headers=self.auth_headers)
            self.assertEqual(res0.status_code, 200)
            self.assertEqual(res0.json()["records_deleted"], 0)
            self.assertEqual(res0.json()["memory_bytes_used_estimate"], 0)

            # 2. Add 1 memory record
            record_user_firestore_memory(uid=self.uid, prompt="Test 1", reply="Reply 1")
            stats_res = self.client.get("/memory/stats", headers=self.auth_headers)
            self.assertGreater(stats_res.json()["memory_count"], 0)

            # 3. Clear 1 document
            res1 = self.client.post("/memory/clear", headers=self.auth_headers)
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res1.json()["records_deleted"], 1)
            self.assertEqual(res1.json()["memory_bytes_used_estimate"], 0)

    def test_05_memory_clear_scale_101_exceeds_legacy_100_limit(self):
        """
        Bug Fix Audit: /memory/clear must delete all documents when count exceeds 100 (e.g. 105),
        eliminating the previous .limit(100) bug.
        """
        scale_uid = "test_mem_uid_scale_105"
        scale_claims = dict(self.mock_claims)
        scale_claims["user_id"] = scale_uid
        scale_claims["sub"] = scale_uid

        with patch("auth_service.verify_firebase_id_token", return_value=scale_claims):
            user_ref = db.collection("users").document(scale_uid)
            batch = db.batch()
            for i in range(105):
                m_ref = user_ref.collection("memory").document(f"MEM-TEST-{i:04d}")
                batch.set(m_ref, {"memory_id": f"MEM-TEST-{i:04d}", "uid": scale_uid, "byte_size_estimate": 100})
            batch.commit()

            # Verify 105 docs exist
            docs_before = list(user_ref.collection("memory").stream())
            self.assertEqual(len(docs_before), 105)

            # Clear memory
            res = self.client.post("/memory/clear", headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["records_deleted"], 105)
            self.assertEqual(res.json()["memory_bytes_used_estimate"], 0)

            # Verify collection is completely empty
            docs_after = list(user_ref.collection("memory").stream())
            self.assertEqual(len(docs_after), 0)

    def test_06_injected_failure_during_clear_preserves_accounting(self):
        """
        Fault Tolerance: If batch commit fails during memory clear, the endpoint must return HTTP 502
        and NOT blindly reset the user's accounting to 0.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            user_ref = db.collection("users").document(self.uid)
            user_ref.set({
                "uid": self.uid,
                "memory_bytes_used_estimate": 50000,
                "memory_count": 50
            })
            # Add dummy memory doc
            user_ref.collection("memory").document("MEM-FAIL-01").set({"byte_size_estimate": 1000})

            # Mock batch commit failure
            mock_batch = MagicMock()
            mock_batch.commit.side_effect = RuntimeError("Simulated Firestore timeout")
            with patch.object(main.db, "batch", return_value=mock_batch):
                res = self.client.post("/memory/clear", headers=self.auth_headers)
                self.assertEqual(res.status_code, 502)
                self.assertIn("Memory clear failed during batch deletion", res.json()["detail"])

            # Verify accounting was NOT reset to 0
            user_data = user_ref.get().to_dict()
            self.assertEqual(user_data["memory_bytes_used_estimate"], 50000)
            self.assertEqual(user_data["memory_count"], 50)


class TestFiveCycleFeedEngine(unittest.TestCase):
    """Audits sequential ordering, idempotent replay, and verified persistence in the 5-cycle feed engine."""

    def setUp(self):
        self.client = TestClient(app)
        self.uid = "test_feed_user_101"
        self.email = "feed_tester@stroke.ai"
        self.mock_claims = {
            "user_id": self.uid,
            "email": self.email,
            "email_verified": True,
            "aud": "stroke-test-matrix",
            "iss": "https://securetoken.google.com/stroke-test-matrix",
            "exp": time.time() + 3600
        }
        self.auth_headers = {"Authorization": "Bearer mock-token-feed"}

    def test_07_out_of_order_cycle_rejected(self):
        """
        Sequential Ordering: Attempting cycle 2 before cycle 1 must return HTTP 400.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            # Reset feed state
            self.client.post("/database/feed/reset-state", headers=self.auth_headers)

            # Request cycle 2 directly
            res = self.client.post("/database/feed-cycle", json={"cycle": 2}, headers=self.auth_headers)
            self.assertEqual(res.status_code, 400)
            self.assertIn("Out-of-order cycle execution", res.json()["detail"])
            self.assertIn("requires cycle 1 to be completed first", res.json()["detail"])

    def test_08_sequential_cycle_progression_and_idempotence(self):
        """
        Idempotent & Ordered: Cycles execute 1 -> 2; replaying cycle 1 returns existing record.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            # Reset feed state
            self.client.post("/database/feed/reset-state", headers=self.auth_headers)

            # 1. Execute Cycle 1
            res1 = self.client.post("/database/feed-cycle", json={"cycle": 1}, headers=self.auth_headers)
            self.assertEqual(res1.status_code, 200)
            data1 = res1.json()
            self.assertEqual(data1["cycle"], 1)
            self.assertEqual(data1["record"]["record_id"], "STRK-BAT-001")
            self.assertFalse(data1["database_fed"])

            # 2. Idempotent Retry of Cycle 1
            res1_retry = self.client.post("/database/feed-cycle", json={"cycle": 1}, headers=self.auth_headers)
            self.assertEqual(res1_retry.status_code, 200)
            self.assertEqual(res1_retry.json()["status"], "already_persisted")
            self.assertTrue(res1_retry.json()["is_idempotent_replay"])

            # 3. Execute Cycle 2
            res2 = self.client.post("/database/feed-cycle", json={"cycle": 2}, headers=self.auth_headers)
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.json()["cycle"], 2)
            self.assertEqual(res2.json()["record"]["record_id"], "STRK-BAT-002")

    def test_09_all_5_cycles_atomic_batch_commit(self):
        """
        Atomic Ingestion: /database/feed-5-cycles persists all 5 records and flips database_fed to true.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            self.client.post("/database/feed/reset-state", headers=self.auth_headers)

            res = self.client.post("/database/feed-5-cycles", json={}, headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["database_fed"])
            self.assertEqual(data["cycles_completed"], 5)
            self.assertEqual(len(data["records"]), 5)

            # Verify in Firestore under users/{uid}/records
            user_ref = db.collection("users").document(self.uid)
            recs = list(user_ref.collection("records").stream())
            self.assertEqual(len(recs), 5)
            user_snap = user_ref.get().to_dict()
            self.assertTrue(user_snap["database_fed"])

    def test_10_injected_commit_failure_returns_502(self):
        """
        Zero False Success: If batch commit fails during 5-cycle ingestion, returns HTTP 502
        and does NOT report database_fed = True.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            mock_batch = MagicMock()
            mock_batch.commit.side_effect = RuntimeError("Injected Google Cloud API outage")

            with patch.object(main.db, "batch", return_value=mock_batch):
                res = self.client.post("/database/feed-5-cycles", json={}, headers=self.auth_headers)
                self.assertEqual(res.status_code, 502)
                self.assertIn("Firestore 5-cycle batch commit failed", res.json()["detail"])


class TestMigrationService(unittest.TestCase):
    """Audits the cryptographic backup, password exclusion, and idempotent UID migration."""

    def setUp(self):
        self.client = TestClient(app)
        self.uid = "migrated_dev_uid_777"
        self.email = "legacy_user@stroke.ai"
        self.mock_claims = {
            "user_id": self.uid,
            "email": self.email,
            "email_verified": True,
            "aud": "stroke-test-matrix",
            "iss": "https://securetoken.google.com/stroke-test-matrix",
            "exp": time.time() + 3600
        }
        self.auth_headers = {"Authorization": "Bearer mock-token-migration"}

    def test_11_migration_service_preserves_records_and_strips_sensitive_data(self):
        """
        Migration Integrity:
          1. Backs up database.
          2. Migrates email-keyed records, chats, and memory to UID.
          3. Explicitly strips passwords, hashes, and OTPs.
          4. Leaves legacy data intact for audit.
        """
        # 1. Create legacy user doc with sensitive fields
        legacy_ref = db.collection("users").document(self.email)
        legacy_ref.set({
            "email": self.email,
            "password": "legacy_plaintext_secret_123",
            "password_hash": "$pbkdf2$hash_value",
            "otp_code": "987654",
            "database_fed": True
        })
        # Add legacy subcollection record
        legacy_ref.collection("records").document("STRK-BAT-001").set({
            "record_id": "STRK-BAT-001",
            "vfx_name": "Legacy Blast",
            "status": "optimized"
        })

        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            res = self.client.post("/auth/migrate-legacy-data", headers=self.auth_headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertTrue(data["migration"]["migrated"])

            # 2. Inspect migrated UID document
            migrated_ref = db.collection("users").document(self.uid)
            migrated_data = migrated_ref.get().to_dict()

            # Ensure sensitive fields were STRIPPED
            self.assertNotIn("password", migrated_data)
            self.assertNotIn("password_hash", migrated_data)
            self.assertNotIn("otp_code", migrated_data)
            self.assertTrue(migrated_data["database_fed"])

            # Ensure subcollection was migrated
            migrated_recs = list(migrated_ref.collection("records").stream())
            self.assertEqual(len(migrated_recs), 1)
            self.assertEqual(migrated_recs[0].to_dict()["vfx_name"], "Legacy Blast")

            # Ensure legacy document is PRESERVED (never silently deleted)
            self.assertTrue(legacy_ref.get().exists)


if __name__ == "__main__":
    unittest.main()
