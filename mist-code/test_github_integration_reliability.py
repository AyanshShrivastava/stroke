"""
================================================================================
STROKE V1 // GITHUB INTEGRATION RELIABILITY TEST SUITE
Comprehensive verification of token lifecycle, machine vault security (0600 mode),
strict environment vs vault separation, zero token leakage, bound cryptographic
write approvals, robust RFC 5988 pagination, rate limit defenses, and get_file_contents
edge case handling (directories, empty, text, binary, large blobs, errors).
================================================================================
"""

import os
import sys
import json
import base64
import hashlib
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

# Ensure Stroke root is on sys.path
STROKE_DIR = os.path.dirname(os.path.abspath(__file__))
if STROKE_DIR not in sys.path:
    sys.path.insert(0, STROKE_DIR)

import github_service
import mcp_bridge


class TestGitHubTokenLifecycleAndVault(unittest.TestCase):
    """Verifies token vault encryption, 0600 file modes, and env vs vault separation."""

    def setUp(self):
        self.test_token = "ghp_MockStrokePatSecret2026SecureVaultTokenXYZ"
        # Clean any existing vault token for test isolation
        github_service.clear_stored_github_token()

    def tearDown(self):
        github_service.clear_stored_github_token()

    def test_vault_encryption_roundtrip_and_0600_permissions(self):
        # 1. Default path (OS keyring on supported systems, else encrypted vault)
        saved_default = github_service.save_github_token(self.test_token)
        self.assertTrue(saved_default)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(github_service.get_stored_github_token(), self.test_token)
        github_service.clear_stored_github_token()

        # 2. Encrypted local file vault fallback enforces 0600 permissions & decrypts cleanly
        with patch("github_service._is_keyring_usable", return_value=False):
            saved = github_service.save_github_token(self.test_token)
            self.assertTrue(saved)
            self.assertTrue(os.path.exists(github_service.TOKEN_VAULT_FILE))

            mode = os.stat(github_service.TOKEN_VAULT_FILE).st_mode & 0o777
            self.assertEqual(mode, 0o600)

            with patch.dict(os.environ, {}, clear=True):
                retrieved = github_service.get_stored_github_token()
                self.assertEqual(retrieved, self.test_token)

    def test_environment_vs_vault_credential_distinction(self):
        # Case 1: Vault only
        github_service.save_github_token(self.test_token)
        with patch.dict(os.environ, {}, clear=True):
            state = github_service.get_github_credential_state()
            self.assertTrue(state["has_token"])
            self.assertEqual(state["source"], "vault")
            self.assertTrue(state["is_vault_managed"])
            self.assertFalse(state["is_environment_managed"])

        # Case 2: Environment only
        github_service.clear_stored_github_token()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_EnvironmentManagedToken123"}, clear=True):
            state = github_service.get_github_credential_state()
            self.assertTrue(state["has_token"])
            self.assertEqual(state["source"], "environment")
            self.assertFalse(state["is_vault_managed"])
            self.assertTrue(state["is_environment_managed"])
            self.assertEqual(github_service.get_stored_github_token(), "ghp_EnvironmentManagedToken123")

        # Case 3: Both present
        github_service.save_github_token(self.test_token)
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_EnvironmentManagedToken123"}, clear=True):
            state = github_service.get_github_credential_state()
            self.assertTrue(state["has_token"])
            self.assertTrue(state["is_vault_managed"])
            self.assertTrue(state["is_environment_managed"])
            # Environment has priority by default
            self.assertEqual(github_service.get_stored_github_token(), "ghp_EnvironmentManagedToken123")
            # Explicit preferred source retrieval
            self.assertEqual(github_service.get_stored_github_token(preferred_source="vault"), self.test_token)

        # Case 4: Neither present
        github_service.clear_stored_github_token()
        with patch.dict(os.environ, {}, clear=True):
            state = github_service.get_github_credential_state()
            self.assertFalse(state["has_token"])
            self.assertEqual(state["source"], "none")
            self.assertFalse(state["is_vault_managed"])
            self.assertFalse(state["is_environment_managed"])

    def test_clear_stored_github_token_disconnect_behavior(self):
        # When environment token is present:
        github_service.save_github_token(self.test_token)
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_EnvToken"}, clear=True):
            res = github_service.clear_stored_github_token()
            self.assertEqual(res["status"], "vault_cleared_env_remains")
            self.assertTrue(res["vault_cleared"])
            self.assertTrue(res["environment_token_present"])
            self.assertEqual(res["active_source"], "environment")
            # Verify os.environ was NOT mutated
            self.assertEqual(os.environ.get("GITHUB_TOKEN"), "ghp_EnvToken")
            # Verify vault file is gone
            self.assertFalse(os.path.exists(github_service.TOKEN_VAULT_FILE))

        # When environment token is absent:
        github_service.save_github_token(self.test_token)
        with patch.dict(os.environ, {}, clear=True):
            res = github_service.clear_stored_github_token()
            self.assertEqual(res["status"], "success")
            self.assertTrue(res["vault_cleared"])
            self.assertFalse(res["environment_token_present"])
            self.assertEqual(res["active_source"], "none")

    def test_no_token_leakage_in_credential_state_or_previews(self):
        github_service.save_github_token("ghp_SensitiveSecretNeverLeakThis123456")
        state = github_service.get_github_credential_state()
        state_str = json.dumps(state)
        self.assertNotIn("ghp_", state_str)
        self.assertNotIn("SensitiveSecret", state_str)
        self.assertNotIn("123456", state_str)


class TestOneTimeCryptographicWriteApprovals(unittest.IsolatedAsyncioTestCase):
    """Verifies that all external GitHub writes require one-time approval bound to diff/content hash."""

    def setUp(self):
        self.repo = "owner/stroke-repo"
        self.path = "scripts/init.luau"
        self.content = "print('Stroke V1 initialized')"
        self.commit_msg = "feat: add init script"
        self.test_token = "ghp_TestTokenForApprovals2026"
        github_service.save_github_token(self.test_token)

    def tearDown(self):
        github_service.clear_stored_github_token()

    async def test_commit_file_unconfirmed_issues_approval_record(self):
        res = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content=self.content,
            commit_message=self.commit_msg,
            confirmed=False
        )
        self.assertEqual(res["status"], "requires_confirmation")
        self.assertTrue(res["requires_confirmation"])
        self.assertIn("approval_id", res)
        self.assertIn("operation_hash", res)
        self.assertIn("content_sha256", res)
        self.assertEqual(res["content_sha256"], hashlib.sha256(self.content.encode("utf-8")).hexdigest())

    async def test_commit_file_confirmed_true_without_approval_id_rejected(self):
        # Mere confirmed=True without server-issued approval_id must be rejected
        res = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content=self.content,
            commit_message=self.commit_msg,
            confirmed=True,
            approval_id=None
        )
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error_type"], "approval_required")

    async def test_commit_file_valid_approval_record_succeeds(self):
        # Step 1: Request approval
        req = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content=self.content,
            commit_message=self.commit_msg,
            confirmed=False
        )
        approval_id = req["approval_id"]

        # Step 2: Mock GitHub API response
        mock_res = MagicMock(spec=httpx.Response)
        mock_res.status_code = 201
        mock_res.json.return_value = {"commit": {"sha": "c0ffee1234567890"}}
        mock_res.headers = httpx.Headers({})

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("httpx.AsyncClient.put", new_callable=AsyncMock) as mock_put:
            # File check 404 (new file)
            check_res = MagicMock(spec=httpx.Response)
            check_res.status_code = 404
            mock_get.return_value = check_res
            mock_put.return_value = mock_res

            # Step 3: Execute with valid approval_id
            exec_res = await github_service.commit_file(
                repo=self.repo,
                path=self.path,
                content=self.content,
                commit_message=self.commit_msg,
                confirmed=True,
                approval_id=approval_id
            )
            self.assertEqual(exec_res["status"], "success")
            self.assertEqual(exec_res["commit_sha"], "c0ffee1234567890")

    async def test_commit_file_replay_attack_rejected(self):
        # Step 1: Issue approval
        req = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content=self.content,
            commit_message=self.commit_msg,
            confirmed=False
        )
        approval_id = req["approval_id"]

        # Mock API
        mock_put = AsyncMock()
        mock_put.return_value = MagicMock(status_code=201, json=lambda: {"commit": {"sha": "sha1"}}, headers=httpx.Headers({}))
        mock_get = AsyncMock()
        mock_get.return_value = MagicMock(status_code=404)

        with patch("httpx.AsyncClient.get", mock_get), patch("httpx.AsyncClient.put", mock_put):
            # First execution succeeds
            first = await github_service.commit_file(
                repo=self.repo, path=self.path, content=self.content,
                commit_message=self.commit_msg, confirmed=True, approval_id=approval_id
            )
            self.assertEqual(first["status"], "success")

            # Replay attempt with same approval_id MUST fail
            replay = await github_service.commit_file(
                repo=self.repo, path=self.path, content=self.content,
                commit_message=self.commit_msg, confirmed=True, approval_id=approval_id
            )
            self.assertEqual(replay["status"], "error")
            self.assertEqual(replay["error_type"], "approval_rejected")
            self.assertIn("replay", replay["message"].lower())

    async def test_commit_file_payload_tampering_rejected(self):
        # Issue approval for content A
        req = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content="Original Safe Content",
            commit_message=self.commit_msg,
            confirmed=False
        )
        approval_id = req["approval_id"]

        # Attempt to execute with modified malicious content B using the same approval_id
        tampered_res = await github_service.commit_file(
            repo=self.repo,
            path=self.path,
            content="MALICIOUS TAMPERED CODE INJECTION",
            commit_message=self.commit_msg,
            confirmed=True,
            approval_id=approval_id
        )
        self.assertEqual(tampered_res["status"], "error")
        self.assertEqual(tampered_res["error_type"], "approval_rejected")
        self.assertIn("hash mismatch", tampered_res["message"].lower())

    async def test_create_branch_approval_lifecycle(self):
        # Request approval
        req = await github_service.create_branch(repo=self.repo, new_branch="feature/vfx", from_branch="main", confirmed=False)
        self.assertEqual(req["status"], "requires_confirmation")
        approval_id = req["approval_id"]

        # Tampered branch name fails
        bad = await github_service.create_branch(repo=self.repo, new_branch="evil-branch", from_branch="main", confirmed=True, approval_id=approval_id)
        self.assertEqual(bad["status"], "error")
        self.assertEqual(bad["error_type"], "approval_rejected")

        # Valid branch succeeds
        mock_ref = MagicMock(status_code=200, json=lambda: {"object": {"sha": "abc123"}})
        mock_create = MagicMock(status_code=201, json=lambda: {"ref": "refs/heads/feature/vfx"})
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_ref)), \
             patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_create)):
            ok = await github_service.create_branch(repo=self.repo, new_branch="feature/vfx", from_branch="main", confirmed=True, approval_id=approval_id)
            self.assertEqual(ok["status"], "success")
            self.assertEqual(ok["branch"], "feature/vfx")


class TestGitHubApiCorrectnessAndPagination(unittest.IsolatedAsyncioTestCase):
    """Verifies RFC 5988 Link header parsing, auto-pagination, rate-limit defense, and errors."""

    def setUp(self):
        github_service.save_github_token("ghp_TestTokenForPagination2026")

    def tearDown(self):
        github_service.clear_stored_github_token()

    def test_rfc5988_link_header_parser(self):
        header = '<https://api.github.com/user/repos?page=2&per_page=30>; rel="next", <https://api.github.com/user/repos?page=5&per_page=30>; rel="last"'
        parsed = github_service._parse_link_header(header)
        self.assertIn("next", parsed)
        self.assertIn("last", parsed)
        self.assertEqual(github_service._extract_page_number_from_url(parsed["next"]), 2)
        self.assertEqual(github_service._extract_page_number_from_url(parsed["last"]), 5)

        # Empty / malformed headers
        self.assertEqual(github_service._parse_link_header(""), {})
        self.assertEqual(github_service._parse_link_header(None), {})
        self.assertEqual(github_service._parse_link_header("invalid; format"), {})

    async def test_list_repositories_auto_pagination(self):
        page1_res = MagicMock(spec=httpx.Response)
        page1_res.status_code = 200
        page1_res.json.return_value = [{"full_name": "owner/repo1", "name": "repo1", "private": False}]
        page1_res.headers = httpx.Headers({"Link": '<https://api.github.com/user/repos?page=2&per_page=1>; rel="next"'})

        page2_res = MagicMock(spec=httpx.Response)
        page2_res.status_code = 200
        page2_res.json.return_value = [{"full_name": "owner/repo2", "name": "repo2", "private": True}]
        page2_res.headers = httpx.Headers({})  # Last page, no next link

        async def mock_get(url, headers=None, params=None):
            page = params.get("page", 1) if params else 1
            if page == 1:
                return page1_res
            return page2_res

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            res = await github_service.list_repositories(per_page=1, auto_paginate=True, max_pages=3)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["count"], 2)
            self.assertEqual(res["pages_fetched"], 2)
            self.assertEqual(res["repos"][0]["full_name"], "owner/repo1")
            self.assertEqual(res["repos"][1]["full_name"], "owner/repo2")

    async def test_rate_limit_and_secondary_abuse_handling(self):
        # 429 Rate limited
        rl_res = MagicMock(spec=httpx.Response)
        rl_res.status_code = 429
        rl_res.text = "API rate limit exceeded"
        rl_res.headers = httpx.Headers({
            "x-ratelimit-remaining": "0",
            "retry-after": "45",
            "x-ratelimit-reset": "1731660000"
        })

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=rl_res)):
            res = await github_service.list_repositories()
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "rate_limited")
            self.assertEqual(res["retry_after"], 45)

        # 403 Secondary rate limit
        abuse_res = MagicMock(spec=httpx.Response)
        abuse_res.status_code = 403
        abuse_res.text = "You have exceeded a secondary rate limit. Please wait."
        abuse_res.headers = httpx.Headers({"retry-after": "60"})

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=abuse_res)):
            res = await github_service.list_branches("owner/repo")
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "rate_limited")
            self.assertEqual(res["retry_after"], 60)

    async def test_auth_failure_401_and_forbidden_403(self):
        # 401 Bad credentials
        auth_res = MagicMock(spec=httpx.Response)
        auth_res.status_code = 401
        auth_res.text = "Bad credentials"
        auth_res.headers = httpx.Headers({})

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=auth_res)):
            res = await github_service.verify_pat_connection()
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "bad_credentials")
            self.assertFalse(res["connected"])

        # 403 Forbidden scopes
        forb_res = MagicMock(spec=httpx.Response)
        forb_res.status_code = 403
        forb_res.text = "Resource not accessible by personal access token"
        forb_res.headers = httpx.Headers({"x-ratelimit-remaining": "4900"})

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=forb_res)):
            res = await github_service.list_issues("owner/repo")
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "forbidden")


class TestGetFileContentsEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Verifies get_file_contents handling of directory, empty, text, binary, large blob, and decoding errors."""

    def setUp(self):
        github_service.save_github_token("ghp_TestTokenForContents2026")

    def tearDown(self):
        github_service.clear_stored_github_token()

    async def test_directory_response_not_treated_as_empty_file(self):
        # GitHub returns a list of items for directories
        dir_res = MagicMock(spec=httpx.Response)
        dir_res.status_code = 200
        dir_res.headers = httpx.Headers({})
        dir_res.json.return_value = [
            {"name": "index.luau", "path": "src/index.luau", "type": "file", "size": 1024, "sha": "sha1"},
            {"name": "utils", "path": "src/utils", "type": "dir", "size": 0, "sha": "sha2"}
        ]

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=dir_res)):
            res = await github_service.get_file_contents("owner/repo", "src")
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "is_directory")
            self.assertEqual(res["entries_count"], 2)
            self.assertEqual(res["entries"][0]["name"], "index.luau")

    async def test_empty_file_size_zero(self):
        empty_res = MagicMock(spec=httpx.Response)
        empty_res.status_code = 200
        empty_res.headers = httpx.Headers({})
        empty_res.json.return_value = {
            "name": ".gitkeep",
            "path": ".gitkeep",
            "sha": "sha_empty",
            "size": 0,
            "content": "",
            "encoding": "base64"
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=empty_res)):
            res = await github_service.get_file_contents("owner/repo", ".gitkeep")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["content"], "")
            self.assertTrue(res["is_empty"])
            self.assertFalse(res["is_binary"])

    async def test_utf8_text_file(self):
        text = "local Workspace = game:GetService('Workspace')\nprint('Ready')"
        b64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")

        text_res = MagicMock(spec=httpx.Response)
        text_res.status_code = 200
        text_res.headers = httpx.Headers({})
        text_res.json.return_value = {
            "name": "main.luau",
            "path": "main.luau",
            "sha": "sha_text",
            "size": len(text),
            "content": b64,
            "encoding": "base64"
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=text_res)):
            res = await github_service.get_file_contents("owner/repo", "main.luau")
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["content"], text)
            self.assertFalse(res["is_binary"])
            self.assertFalse(res["is_empty"])

    async def test_binary_file_detection(self):
        binary_bytes = b"ROBLOX\x00\x01\x02\xFFPNG\x00data"
        b64 = base64.b64encode(binary_bytes).decode("utf-8")

        bin_res = MagicMock(spec=httpx.Response)
        bin_res.status_code = 200
        bin_res.headers = httpx.Headers({})
        bin_res.json.return_value = {
            "name": "model.rbxm",
            "path": "assets/model.rbxm",
            "sha": "sha_bin",
            "size": len(binary_bytes),
            "content": b64,
            "encoding": "base64"
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=bin_res)):
            res = await github_service.get_file_contents("owner/repo", "assets/model.rbxm")
            self.assertEqual(res["status"], "success")
            self.assertTrue(res["is_binary"])
            self.assertIsNone(res["content"])
            self.assertEqual(res["raw_base64"], b64)

    async def test_large_file_under_10mb_fetches_git_blob(self):
        # File > 1MB: Contents API omits content but provides blob SHA
        large_content = "DATA" * 300_000  # 1.2 MB
        blob_b64 = base64.b64encode(large_content.encode("utf-8")).decode("utf-8")

        contents_res = MagicMock(spec=httpx.Response)
        contents_res.status_code = 200
        contents_res.headers = httpx.Headers({})
        contents_res.json.return_value = {
            "name": "dataset.json",
            "path": "data/dataset.json",
            "sha": "blob_sha_123",
            "size": 1_200_000,
            "content": None  # Omitted by Contents API
        }

        blob_res = MagicMock(spec=httpx.Response)
        blob_res.status_code = 200
        blob_res.headers = httpx.Headers({})
        blob_res.json.return_value = {
            "sha": "blob_sha_123",
            "size": 1_200_000,
            "content": blob_b64,
            "encoding": "base64"
        }

        async def mock_get(url, headers=None, params=None):
            if "/git/blobs/" in url:
                return blob_res
            return contents_res

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            res = await github_service.get_file_contents("owner/repo", "data/dataset.json")
            self.assertEqual(res["status"], "success")
            self.assertEqual(len(res["content"]), 1_200_000)
            self.assertFalse(res["is_binary"])

    async def test_file_too_large_over_10mb_safely_rejected(self):
        huge_res = MagicMock(spec=httpx.Response)
        huge_res.status_code = 200
        huge_res.headers = httpx.Headers({})
        huge_res.json.return_value = {
            "name": "huge_place.rbxl",
            "path": "huge_place.rbxl",
            "sha": "sha_huge",
            "size": 50_000_000  # 50 MB
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=huge_res)):
            res = await github_service.get_file_contents("owner/repo", "huge_place.rbxl")
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "file_too_large")

    async def test_malformed_base64_decoding_error(self):
        bad_b64_res = MagicMock(spec=httpx.Response)
        bad_b64_res.status_code = 200
        bad_b64_res.headers = httpx.Headers({})
        bad_b64_res.json.return_value = {
            "name": "corrupt.txt",
            "path": "corrupt.txt",
            "sha": "sha_corrupt",
            "size": 100,
            "content": "!!!NOT_VALID_BASE64@@@!!!",
            "encoding": "base64"
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=bad_b64_res)):
            res = await github_service.get_file_contents("owner/repo", "corrupt.txt")
            self.assertEqual(res["status"], "error")
            self.assertEqual(res["error_type"], "decoding_error")

    def test_input_validation_prevents_ssrf_and_path_traversal(self):
        # Invalid repo formats
        self.assertFalse(github_service.validate_repo_name("../../etc/passwd"))
        self.assertFalse(github_service.validate_repo_name("plain_name"))
        self.assertFalse(github_service.validate_repo_name("owner/repo/extra"))
        self.assertFalse(github_service.validate_repo_name("owner/repo\x00null"))
        self.assertTrue(github_service.validate_repo_name("AyanshShrivastava/stroke"))

        # Invalid paths
        self.assertFalse(github_service.validate_file_path("/leading_slash"))
        self.assertFalse(github_service.validate_file_path("../traversal"))
        self.assertFalse(github_service.validate_file_path("path/with\\backslash"))
        self.assertTrue(github_service.validate_file_path("src/client/VFX.luau"))


class TestMcpBridgeGitHubIntegration(unittest.IsolatedAsyncioTestCase):
    """Verifies mcp_bridge tool dispatch with one-time write approvals."""

    def setUp(self):
        github_service.save_github_token("ghp_TestTokenForMcp2026")

    def tearDown(self):
        github_service.clear_stored_github_token()

    async def test_mcp_bridge_commit_file_requires_confirmation(self):
        res = await mcp_bridge.execute_mcp_tool(
            "github_commit_file",
            {"repo": "owner/repo", "path": "file.luau", "content": "print(1)", "confirmed": False}
        )
        self.assertEqual(res["status"], "requires_confirmation")
        self.assertIn("approval_id", res)
        self.assertTrue(res["requires_confirmation"])

    async def test_mcp_bridge_commit_file_with_valid_approval_dispatches(self):
        # Step 1: Request approval
        req = await mcp_bridge.execute_mcp_tool(
            "github_commit_file",
            {"repo": "owner/repo", "path": "file.luau", "content": "print(1)", "confirmed": False}
        )
        approval_id = req["approval_id"]

        # Step 2: Dispatch with valid approval_id
        mock_put = AsyncMock(return_value=MagicMock(status_code=201, json=lambda: {"commit": {"sha": "sha_mcp"}}, headers=httpx.Headers({})))
        mock_get = AsyncMock(return_value=MagicMock(status_code=404))

        with patch("httpx.AsyncClient.get", mock_get), patch("httpx.AsyncClient.put", mock_put):
            res = await mcp_bridge.execute_mcp_tool(
                "github_commit_file",
                {
                    "repo": "owner/repo",
                    "path": "file.luau",
                    "content": "print(1)",
                    "confirmed": True,
                    "approval_id": approval_id
                }
            )
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["commit_sha"], "sha_mcp")


if __name__ == "__main__":
    unittest.main()
