import os
import sys
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

# Configure offline mode and test database
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import paths_service
import auth_service
from local_firestore import LocalFirestoreClient
import coding_loop


class TestPathsServiceRuntimeAuthority(unittest.TestCase):
    def setUp(self):
        self.temp_dir = str(Path(tempfile.mkdtemp(prefix="stroke_test_app_data_")).resolve())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_env_override_stroke_app_data(self):
        with patch.dict(os.environ, {"STROKE_APP_DATA": self.temp_dir}):
            app_dir = paths_service.get_app_data_dir()
            self.assertEqual(str(app_dir), self.temp_dir)
            self.assertTrue(app_dir.is_dir())

            chats_path = paths_service.get_user_chats_path()
            self.assertEqual(chats_path.parent, app_dir)
            self.assertEqual(chats_path.name, "local_chat_sessions.json")

            mcp_path = paths_service.get_mcp_config_path()
            self.assertEqual(mcp_path.parent, app_dir)
            self.assertEqual(mcp_path.name, "mcp_servers.json")

            ctx_path = paths_service.get_verified_project_context_path()
            self.assertEqual(ctx_path.parent, app_dir)
            self.assertEqual(ctx_path.name, "verified_project_context.json")

            vfx_dir = paths_service.get_vfx_dir()
            self.assertEqual(vfx_dir.parent, app_dir)
            self.assertEqual(vfx_dir.name, "vfx")

    def test_legacy_data_migration(self):
        # Create a mock legacy data directory
        legacy_dir = Path(self.temp_dir) / "source_repo" / "data"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "local_chat_sessions.json").write_text(json.dumps([{"id": "legacy-chat-1"}]), encoding="utf-8")
        (legacy_dir / "mcp_servers.json").write_text(json.dumps({"servers": {"test": {}}}), encoding="utf-8")

        target_app_dir = Path(self.temp_dir) / "user_app_data"
        target_app_dir.mkdir(parents=True)

        with patch.dict(os.environ, {"STROKE_APP_DATA": str(target_app_dir)}):
            migrated = paths_service.migrate_legacy_data(legacy_source_dir=legacy_dir)
            self.assertTrue(migrated.get("local_chat_sessions.json"))
            self.assertTrue(migrated.get("mcp_servers.json"))

            # Verify target files exist and content is preserved
            target_chats = target_app_dir / "local_chat_sessions.json"
            self.assertTrue(target_chats.is_file())
            chats_data = json.loads(target_chats.read_text(encoding="utf-8"))
            self.assertEqual(chats_data[0]["id"], "legacy-chat-1")


class TestReadOnlyBundleSafety(unittest.TestCase):
    def setUp(self):
        self.temp_base = Path(tempfile.mkdtemp(prefix="stroke_ro_test_")).resolve()
        self.mock_bundle = self.temp_base / "Applications" / "Stroke.app" / "Contents" / "Resources"
        self.mock_bundle.mkdir(parents=True)
        self.user_app_data = self.temp_base / "UserAppData"
        self.user_app_data.mkdir(parents=True)

        # Make bundle directory read-only
        os.chmod(self.mock_bundle, 0o555)

    def tearDown(self):
        try:
            os.chmod(self.mock_bundle, 0o755)
        except Exception:
            pass
        shutil.rmtree(self.temp_base, ignore_errors=True)

    def test_writes_succeed_when_app_bundle_is_read_only(self):
        """Verifies that user data writes route to user app data and succeed even if the app bundle is read-only."""
        with patch.dict(os.environ, {"STROKE_APP_DATA": str(self.user_app_data)}):
            # 1. User chats
            chats_file = paths_service.get_user_chats_path()
            test_chats = [{"id": "ro-chat-1", "title": "Test In RO Bundle", "messages": []}]
            paths_service.atomic_write_json(chats_file, test_chats)
            self.assertTrue(chats_file.is_file())
            self.assertEqual(json.loads(chats_file.read_text(encoding="utf-8")), test_chats)

            # 2. Project context
            ctx_file = paths_service.get_verified_project_context_path()
            test_ctx = {"summary": "RO bundle verified", "files": 5}
            paths_service.atomic_write_json(ctx_file, test_ctx)
            self.assertTrue(ctx_file.is_file())

            # 3. Local firestore client
            db_file = paths_service.get_local_firestore_db_path()
            client = LocalFirestoreClient(db_path=db_file)
            doc_ref = client.collection("test_col").document("doc_1")
            doc_ref.set({"name": "stroke_ro_safe", "status": "active"})
            fetched = doc_ref.get()
            self.assertTrue(fetched.exists)
            self.assertEqual(fetched.to_dict()["name"], "stroke_ro_safe")


class TestChatPersistenceEndpoints(unittest.TestCase):
    def setUp(self):
        self.temp_dir = str(Path(tempfile.mkdtemp(prefix="stroke_chat_api_")).resolve())
        self.env_patcher = patch.dict(os.environ, {"STROKE_APP_DATA": self.temp_dir})
        self.env_patcher.start()

        # Import main and FastAPI test client
        import main
        from fastapi.testclient import TestClient

        self.main = main
        self.main.LOCAL_CHATS_FILE = str(paths_service.get_user_chats_path())
        self.main._LOCAL_CHAT_SESSIONS.clear()

        # Setup test authentication
        self.test_user = auth_service.AuthenticatedUser(
            uid="tester_uid_101",
            email="tester@stroke.ai",
            auth_provider="email",
        )
        self.main.app.dependency_overrides[self.main.get_current_user] = lambda: self.test_user
        self.client = TestClient(self.main.app)

    def tearDown(self):
        self.main.app.dependency_overrides.clear()
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_retrieve_chat_session(self):
        payload = {
            "session_id": "session-xyz-1",
            "title": "Roblox Combat VFX",
            "version": 1,
            "last_archived_id": "msg-101",
            "messages": [
                {
                    "id": "msg-101",
                    "role": "user",
                    "content": "Create a sword slash particle effect.",
                    "status": "sent",
                },
                {
                    "id": "msg-102",
                    "role": "assistant",
                    "content": "Using ParticleEmitter with ColorSequence and NumberSequence transparency.",
                    "status": "sent",
                },
            ],
        }

        # 1. Save
        res = self.client.post("/api/chats/save", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["chat"]["session_id"], "session-xyz-1")
        self.assertEqual(data["chat"]["version"], 1)
        self.assertEqual(data["chat"]["last_archived_id"], "msg-101")
        self.assertEqual(len(data["chat"]["messages"]), 2)

        # 2. Retrieve by ID
        get_res = self.client.get("/api/chats/session-xyz-1")
        self.assertEqual(get_res.status_code, 200)
        session_data = get_res.json()["chat"]
        self.assertEqual(session_data["session_id"], "session-xyz-1")
        self.assertEqual(session_data["title"], "Roblox Combat VFX")
        self.assertEqual(len(session_data["messages"]), 2)

        # 3. Retrieve non-existent
        not_found = self.client.get("/api/chats/non-existent-999")
        self.assertEqual(not_found.status_code, 404)

    def test_optimistic_concurrency_and_message_deduplication(self):
        # Save version 1
        initial = {
            "session_id": "chat-concurrent-1",
            "title": "Concurrent Chat",
            "version": 1,
            "messages": [{"id": "m1", "role": "user", "content": "Hello", "status": "sent"}],
        }
        res1 = self.client.post("/api/chats/save", json=initial)
        self.assertEqual(res1.status_code, 200)

        # Update with version 2 adding message m2
        v2 = {
            "session_id": "chat-concurrent-1",
            "title": "Concurrent Chat V2",
            "version": 2,
            "messages": [
                {"id": "m1", "role": "user", "content": "Hello", "status": "sent"},
                {"id": "m2", "role": "assistant", "content": "Hi there", "status": "sent"},
            ],
        }
        res2 = self.client.post("/api/chats/save", json=v2)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["chat"]["version"], 2)
        self.assertEqual(len(res2.json()["chat"]["messages"]), 2)

        # Stale update with version 1 trying to overwrite with different title and message m3
        stale = {
            "session_id": "chat-concurrent-1",
            "title": "Stale Title",
            "version": 1,
            "messages": [
                {"id": "m1", "role": "user", "content": "Hello", "status": "sent"},
                {"id": "m3", "role": "user", "content": "Out-of-order message", "status": "sent"},
            ],
        }
        res_stale = self.client.post("/api/chats/save", json=stale)
        self.assertEqual(res_stale.status_code, 200)
        saved_chat = res_stale.json()["chat"]
        # Version 2 title must be preserved (not overwritten by stale version 1 title)
        self.assertEqual(saved_chat["title"], "Concurrent Chat V2")
        self.assertEqual(saved_chat["version"], 2)
        # Message m3 should be merged into messages without duplicating m1
        msg_ids = [m["id"] for m in saved_chat["messages"]]
        self.assertIn("m1", msg_ids)
        self.assertIn("m2", msg_ids)
        self.assertIn("m3", msg_ids)
        self.assertEqual(len(msg_ids), 3)

    def test_delete_chat_session(self):
        # Save a chat
        self.client.post("/api/chats/save", json={
            "session_id": "chat-to-delete",
            "title": "To Delete",
            "version": 1,
            "messages": [],
        })
        self.assertEqual(self.client.get("/api/chats/chat-to-delete").status_code, 200)

        # Delete it
        del_res = self.client.delete("/api/chats/chat-to-delete")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "success")

        # Confirm 404
        self.assertEqual(self.client.get("/api/chats/chat-to-delete").status_code, 404)

    def test_concurrent_multithreaded_atomic_saves(self):
        """Validates that concurrent writes from multiple threads never corrupt the JSON file."""
        num_threads = 8
        errors = []

        def worker(thread_idx):
            try:
                for i in range(5):
                    payload = {
                        "session_id": f"thread-chat-{thread_idx}",
                        "title": f"Thread Chat {thread_idx}",
                        "version": i + 1,
                        "messages": [
                            {"id": f"m-{thread_idx}-{i}", "role": "user", "content": f"msg {i}", "status": "sent"}
                        ],
                    }
                    r = self.client.post("/api/chats/save", json=payload)
                    if r.status_code != 200:
                        errors.append(f"Thread {thread_idx} step {i} status {r.status_code}")
            except Exception as e:
                errors.append(f"Thread {thread_idx} exception: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

        # Verify JSON file is intact and valid
        chats_file = Path(self.main.LOCAL_CHATS_FILE)
        self.assertTrue(chats_file.is_file())
        with open(chats_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)
        user_chats = data.get("tester@stroke.ai", [])
        # All 8 unique session IDs must be present in saved data
        session_ids = {s.get("session_id") for s in user_chats}
        for t in range(num_threads):
            self.assertIn(f"thread-chat-{t}", session_ids)


class TestProjectContextAndCodingLoopRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = str(Path(tempfile.mkdtemp(prefix="stroke_coding_loop_test_")).resolve())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_coding_loop_context_persistence_location(self):
        with patch.dict(os.environ, {"STROKE_APP_DATA": self.temp_dir}):
            ctx_path = paths_service.get_verified_project_context_path()
            self.assertTrue(str(ctx_path).startswith(self.temp_dir))

            # Simulate saving project context
            mock_payload = {
                "workspace_path": "/fake/workspace",
                "total_files": 42,
                "verified": True,
            }
            paths_service.atomic_write_json(ctx_path, mock_payload)
            self.assertTrue(ctx_path.is_file())

            loaded = json.loads(ctx_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["total_files"], 42)


if __name__ == "__main__":
    unittest.main()
