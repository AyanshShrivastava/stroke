"""
Regression tests for Stroke application security hardening:
- Compromised .vault_key removal & no legacy migration
- Zero unsigned/forged/expired JWT trust & local per-session auth
- Mandatory single-use, target/action/user/server-bound MCP approvals
- SSRF, localhost substring bypass, cross-origin redirect credential stripping
- Host/Origin validation, terminal authorization, workspace traversal & symlink escapes
- Packaging manifest hygiene
"""

import os
import sys
import time
import json
import base64
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth_service
import credentials_vault_service
import github_service
import mcp_client
import mcp_bridge
import terminal_service
import workspace_service
import build_desktop
import main


def _make_unsigned_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}."


def _make_fake_hs256_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"forged_signature_bytes").rstrip(b"=").decode()
    return f"{header}.{body}.{sig}"


class TestCompromisedVaultKeyRemediation:
    def test_compromised_vault_key_absent_from_repo(self):
        repo_key = Path(__file__).parent / "data" / ".vault_key"
        assert not repo_key.exists(), "Compromised mist-code/data/.vault_key must not exist in repository"

    def test_no_legacy_vault_key_migration_references(self):
        for mod in (credentials_vault_service, github_service, mcp_client):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            assert "_LEGACY_KEY_FILE" not in src
            assert "legacy_key_file" not in src

    def test_key_not_stored_beside_ciphertext(self, tmp_path):
        with patch("paths_service.get_app_data_dir", return_value=tmp_path):
            cipher = credentials_vault_service._get_or_create_cipher()
            assert cipher is not None
            vault_dir = tmp_path / "credentials"
            assert not (vault_dir / "byok_vault.key").exists()


class TestAuthenticationHardening:
    def test_unsigned_clerk_jwt_rejected(self):
        client = TestClient(main.app)
        forged_none = _make_unsigned_jwt({
            "iss": "https://clerk.example.com",
            "sub": "user_attacker123",
            "exp": int(time.time()) + 3600,
        })
        forged_hs = _make_fake_hs256_jwt({
            "iss": "https://clerk.example.com",
            "sub": "user_attacker123",
            "exp": int(time.time()) + 3600,
        })
        for tok in (forged_none, forged_hs):
            resp = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
            assert resp.status_code == 401
            resp_opt = client.get("/api/models/providers", headers={"Authorization": f"Bearer {tok}"})
            assert resp_opt.status_code == 401
            resp_term = client.post("/terminal/create", headers={"Authorization": f"Bearer {tok}"})
            assert resp_term.status_code == 401

    def test_expired_token_rejected(self):
        client = TestClient(main.app)
        expired = _make_fake_hs256_jwt({
            "iss": "https://securetoken.google.com/stroke-cyber-matrix",
            "aud": "stroke-cyber-matrix",
            "sub": "uid_123",
            "exp": int(time.time()) - 3600,
        })
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401

    def test_github_status_requires_authentication(self):
        client = TestClient(main.app)
        resp = client.get("/github/status")
        assert resp.status_code == 401

    def test_local_session_token_works_offline(self):
        client = TestClient(main.app)
        with patch.dict(os.environ, {"STROKE_INTERNAL_SECRET": "test_local_secret_987654321"}):
            resp = client.get("/auth/me", headers={"X-Internal-Token": "test_local_secret_987654321"})
            assert resp.status_code == 200
            bad_resp = client.get("/auth/me", headers={"X-Internal-Token": "wrong_secret"})
            assert bad_resp.status_code == 401


class TestHostAndOriginValidation:
    def test_untrusted_host_and_origin_rejected(self):
        client = TestClient(main.app)
        bad_host = client.get("/health", headers={"Host": "evil.attacker.com:8501"})
        assert bad_host.status_code == 400

        bad_origin = client.post(
            "/terminal/create",
            headers={"Origin": "https://evil.attacker.com"},
        )
        assert bad_origin.status_code == 403


class TestMcpSecurityAndApprovals:
    def test_mcp_connect_requires_approval_id(self):
        client = TestClient(main.app)
        with patch.dict(os.environ, {"STROKE_INTERNAL_SECRET": "mcp_test_secret_12345"}):
            resp = client.post(
                "/mcp/connect",
                headers={"X-Internal-Token": "mcp_test_secret_12345"},
                json={
                    "server_id": "srv1",
                    "name": "Srv1",
                    "url": "https://example.com/mcp",
                    "allow_local": False,
                },
            )
            assert resp.status_code == 403

    def test_approval_bound_to_action_target_and_single_use(self):
        mgr = mcp_client.McpApprovalManager()
        rec = mgr.create_approval(
            server_id="srv1",
            action="connect",
            target="https://trusted.example.com/mcp",
            user_uid="user_1",
            ttl_seconds=60,
        )
        # Wrong action
        assert not mgr.consume_approval(rec.approval_id, "srv1", "user_1", action="delete", target="https://trusted.example.com/mcp")
        # Wrong target
        assert not mgr.consume_approval(rec.approval_id, "srv1", "user_1", action="connect", target="https://evil.example.com/mcp")
        # Exact match succeeds once
        assert mgr.consume_approval(rec.approval_id, "srv1", "user_1", action="connect", target="https://trusted.example.com/mcp")
        # Replay fails
        assert not mgr.consume_approval(rec.approval_id, "srv1", "user_1", action="connect", target="https://trusted.example.com/mcp")

    def test_durable_approvals_and_oauth_state_survive_restart(self, tmp_path):
        store_file = str(tmp_path / "mcp_approvals.json")
        mgr1 = mcp_client.McpApprovalManager(store_path=store_file)
        rec = mgr1.create_approval(
            server_id="srv_restart",
            action="connect",
            target="https://trusted.example.com/mcp",
            user_uid="user_restart",
            ttl_seconds=120,
        )
        # Simulate fresh instance / process restart reading from shared durable store
        mgr2 = mcp_client.McpApprovalManager(store_path=store_file)
        assert mgr2.get_approval(rec.approval_id) is not None
        assert mgr2.consume_approval(rec.approval_id, "srv_restart", "user_restart", action="connect", target="https://trusted.example.com/mcp")
        # Replay on third instance fails
        mgr3 = mcp_client.McpApprovalManager(store_path=store_file)
        assert not mgr3.consume_approval(rec.approval_id, "srv_restart", "user_restart", action="connect", target="https://trusted.example.com/mcp")

        # OAuth state persists across instances and is single-use
        with patch("paths_service.get_app_data_dir", return_value=tmp_path):
            main._save_oauth_state("STRK_test_state_1", {"uid": "u1", "origin": "http://127.0.0.1:8501", "expires_at": time.time() + 120})
            main._OAUTH_STATE_REGISTRY.clear()  # Simulate process restart losing in-memory dict
            popped = main._pop_oauth_state("STRK_test_state_1")
            assert popped is not None and popped["uid"] == "u1"
            assert main._pop_oauth_state("STRK_test_state_1") is None

    def test_register_custom_mcp_server_no_substring_bypass_and_not_connected_prematurely(self):
        with pytest.raises(mcp_client.McpError):
            mcp_bridge.register_custom_mcp_server(
                server_id="sneaky",
                name="Sneaky",
                description="test",
                url="http://127.0.0.1.nip.io:8080/mcp",
            )
        entry = mcp_bridge.register_custom_mcp_server(
            server_id="valid_remote",
            name="Valid Remote",
            description="test",
            url="https://example.com/mcp",
        )
        assert entry["connected"] is False
        mcp_bridge.remove_custom_mcp_server("valid_remote")

    def test_ssrf_blocks_metadata_and_private_ips(self):
        for bad_url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1:8080/mcp",
            "http://192.168.1.1/mcp",
            "http://0x7f000001/mcp",
            "http://127.0.0.1.nip.io/mcp",
            "file:///etc/passwd",
        ):
            with pytest.raises(mcp_client.McpError):
                mcp_client.SsrfProtector.validate_url(bad_url, allow_local=True)

    def test_cross_origin_redirect_strips_credentials(self):
        import asyncio

        async def _run():
            transport = mcp_client.StreamableHttpTransport(
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer super_secret_token", "X-Api-Key": "secret_key"},
                allow_local=False,
            )
            await transport.connect()

            redirect_resp = MagicMock()
            redirect_resp.status_code = 302
            redirect_resp.headers = {"Location": "https://other.example.org/mcp2"}

            final_resp = MagicMock()
            final_resp.status_code = 200
            final_resp.headers = {"Content-Type": "application/json"}
            final_resp.text = '{"jsonrpc":"2.0","id":"1","result":{}}'
            final_resp.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": {}}

            captured_redirect_headers = {}

            class FakeRedirectClient:
                def __init__(self, headers=None, **kwargs):
                    captured_redirect_headers.update(headers or {})

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

                async def post(self, *args, **kwargs):
                    return final_resp

            with patch.object(mcp_client.SsrfProtector, "validate_url", side_effect=lambda u, allow_local=False: u):
                with patch.object(transport.client, "post", new=AsyncMock(return_value=redirect_resp)):
                    with patch("httpx.AsyncClient", side_effect=FakeRedirectClient):
                        resp = await transport._safe_post("https://example.com/mcp", {"jsonrpc": "2.0"}, timeout=5.0)
                        assert resp.status_code == 200

            lowered = {k.lower() for k in captured_redirect_headers}
            assert "authorization" not in lowered
            assert "x-api-key" not in lowered
            await transport.close()

        asyncio.run(_run())


class TestWorkspaceTerminalAndPackagingSecurity:
    def test_workspace_traversal_and_symlink_escape_blocked(self, tmp_path):
        approved = tmp_path / "approved_proj"
        outside = tmp_path / "outside_secret"
        approved.mkdir()
        outside.mkdir()
        secret_file = outside / "secret.txt"
        secret_file.write_text("top_secret", encoding="utf-8")

        escape_link = approved / "escape_link"
        escape_link.symlink_to(secret_file)

        mgr = workspace_service.WorkspaceManager()
        with patch.object(mgr, "get_approved_workspaces", return_value=[str(approved.resolve())]):
            with pytest.raises(workspace_service.WorkspaceSecurityError):
                mgr.validate_path_access(str(approved / ".." / "outside_secret" / "secret.txt"))
            with pytest.raises(workspace_service.WorkspaceSecurityError):
                mgr.validate_path_access(str(escape_link))

    def test_ai_destructive_commands_denied(self):
        decision, _ = terminal_service.evaluate_command_security("rm", ["-rf", "."], is_ai_initiated=True)
        assert decision == terminal_service.SecurityDecision.DENIED

    def test_bundle_manifest_blocks_sensitive_files(self):
        sep = ":"
        violations = build_desktop.validate_bundle_manifest(
            [f"data/.vault_key{sep}data", f"byok_vault.key{sep}.", f".github_token.enc{sep}."],
            sep,
        )
        assert len(violations) == 3
        clean_data = build_desktop.get_bundle_add_data("Darwin", sep)
        assert build_desktop.validate_bundle_manifest(clean_data, sep) == []

    def test_pty_session_stop_terminates_process_and_reclaims_fd(self, tmp_path):
        ws = str(tmp_path.resolve())
        with patch.object(terminal_service, "is_allowed_workspace_root", return_value=True):
            created = terminal_service.TerminalManager.create_terminal(ws)
            sid = created["session_id"]
            try:
                started = terminal_service.TerminalManager.start_interactive_shell(sid)
                assert started["status"] == "success"
                sess = terminal_service.TerminalManager.get_session(sid)
                assert sess is not None
                proc = sess._pty_proc
                assert proc is not None and proc.poll() is None

                stopped = terminal_service.TerminalManager.stop_terminal(sid)
                assert stopped["status"] == "terminated"
                assert proc.poll() is not None
                assert sess._pty_master_fd is None
                assert sess._pty_proc is None
            finally:
                terminal_service.TerminalManager.delete_terminal(sid)

    def test_stdio_transport_rejects_pending_requests_on_early_eof(self):
        import asyncio

        async def _run():
            transport = mcp_client.StdioTransport(command=sys.executable, args=["-c", "pass"])
            fake_stdout = MagicMock()
            fake_stdout.readline = AsyncMock(return_value=b"")
            fake_proc = MagicMock()
            fake_proc.stdout = fake_stdout
            fake_proc.returncode = None
            transport.process = fake_proc
            transport._closed = False

            fut = asyncio.get_running_loop().create_future()
            transport._pending_requests["req-1"] = fut
            await transport._read_stdout_loop()
            assert fut.done()
            with pytest.raises(mcp_client.McpError):
                fut.result()

        asyncio.run(_run())
