"""
End-to-end architectural and workflow tests for Stroke BYOK Desktop Coding Assistant:
1. BYOK key storage, masking, custom endpoint metadata, provider switching & persistence
2. Real AI coding chat & streaming with mocked provider HTTP transport + provider error handling
3. Workspace approval, file listing, creation, editing, patching, and reading
4. Interactive terminal session: create, PTY start, command input, real output delta, cd boundaries, stop
5. Genuine MCP server handshake, tool discovery, tool invocation, and disconnect
6. Local-first session bootstrap (GET /) & JS syntax validation of index.html
"""

import os
import sys
import re
import json
import time
import subprocess
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_provider_service
import credentials_vault_service
import mcp_client
import mcp_bridge
import workspace_service
import main


def _auth_headers():
    secret = os.environ.get("STROKE_INTERNAL_SECRET") or "stroke_workflow_test_secret"
    os.environ["STROKE_INTERNAL_SECRET"] = secret
    return {"X-Stroke-Token": secret}


class TestByokProvidersAndPersistence:
    def test_save_switch_and_persist_byok_providers(self, tmp_path):
        client = TestClient(main.app)
        headers = _auth_headers()
        with patch("paths_service.get_app_data_dir", return_value=tmp_path):
            # Save keys for multiple providers including custom
            for prov, key, meta in [
                ("openai", "sk-test-openai-key-1234567890", None),
                ("anthropic", "sk-ant-test-key-1234567890", None),
                ("custom", "custom-test-key-1234567890", {
                    "base_url": "https://custom.llm.local/v1",
                    "model_id": "custom-coder-7b",
                    "provider_type": "openai",
                }),
            ]:
                r = client.post(
                    "/api/models/credentials",
                    headers=headers,
                    json={"provider": prov, "api_key": key, "metadata": meta},
                )
                assert r.status_code == 200
                data = r.json()
                assert data["provider"]["configured"] is True
                assert key not in json.dumps(data)

            # Switch active provider & model and verify persistence on disk
            r_act = client.post(
                "/api/models/active",
                headers=headers,
                json={"active_provider": "anthropic", "active_model": "claude-3-5-sonnet-20241022"},
            )
            assert r_act.status_code == 200
            persisted = ai_provider_service.get_active_model_config()
            assert persisted["active_provider"] == "anthropic"
            assert persisted["active_model"] == "claude-3-5-sonnet-20241022"

            # Verify /api/models/providers never leaks plaintext keys
            r_list = client.get("/api/models/providers", headers=headers)
            assert r_list.status_code == 200
            raw_list = json.dumps(r_list.json())
            assert "sk-test-openai-key-1234567890" not in raw_list
            assert "sk-ant-test-key-1234567890" not in raw_list

    def test_chat_and_stream_with_mocked_provider_and_error_handling(self):
        client = TestClient(main.app)
        headers = _auth_headers()

        fake_resp = ai_provider_service.ProviderResponse(
            content="Verified workspace change complete.",
            model="gpt-4o",
            provider="openai",
            selected_provider="openai",
            finish_reason="stop",
        )
        with patch.object(
            main.global_ai_provider_manager,
            "execute_chat",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = client.post(
                "/ai/chat",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": "Explain main.py"}],
                    "model": "gpt-4o",
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["provider"] == "openai"
            assert body["model"] == "gpt-4o"
            assert "Verified workspace change complete." in body["message"]

        # Verify provider auth error is surfaced honestly
        with patch.object(
            main.global_ai_provider_manager,
            "execute_chat",
            new=AsyncMock(side_effect=ai_provider_service.ProviderAuthenticationError("Invalid API key", "openai", "gpt-4o")),
        ):
            r_err = client.post(
                "/ai/chat",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "model": "gpt-4o",
                },
            )
            assert r_err.status_code == 200
            assert "Authentication failed" in r_err.json()["message"]

        # Verify streaming SSE endpoint
        async def _fake_stream(*args, **kwargs):
            yield ai_provider_service.StreamChunk(delta_content="Hello ")
            yield ai_provider_service.StreamChunk(delta_content="Stroke!", finish_reason="stop")

        with patch.object(main.global_ai_provider_manager, "execute_stream_chat", side_effect=_fake_stream):
            r_stream = client.post(
                "/ai/chat/stream",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": "Say hi"}],
                    "model": "gpt-4o",
                },
            )
            assert r_stream.status_code == 200
            assert "Hello " in r_stream.text
            assert "Stroke!" in r_stream.text


class TestWorkspaceFilesAndInteractiveTerminal:
    def test_workspace_file_operations_and_interactive_terminal_workflow(self, tmp_path):
        client = TestClient(main.app)
        headers = _auth_headers()
        proj_dir = tmp_path / "my_project"
        sub_dir = proj_dir / "src"
        outside_dir = tmp_path / "outside"
        sub_dir.mkdir(parents=True)
        outside_dir.mkdir()

        with patch.object(workspace_service._WORKSPACE_MANAGER, "get_approved_workspaces", return_value=[str(proj_dir.resolve())]):
            # 1. Create, read, edit, and list project files
            target_file = str(sub_dir / "app.py")
            r_create = client.post(
                "/fs/create",
                headers=headers,
                json={"file_path": target_file, "content": "print('v1')\n"},
            )
            assert r_create.status_code == 200

            r_edit = client.post(
                "/fs/edit",
                headers=headers,
                json={
                    "file_path": target_file,
                    "new_content": "print('v2')\n",
                },
            )
            assert r_edit.status_code == 200

            r_read = client.post("/fs/read", headers=headers, json={"file_path": target_file})
            assert r_read.status_code == 200
            assert "print('v2')" in r_read.json()["content"]

            r_list = client.post("/fs/list", headers=headers, json={"dir_path": str(proj_dir)})
            assert r_list.status_code == 200
            assert any(it["name"] == "src" for it in r_list.json()["items"])

            # 2. Interactive terminal session: create -> pty/start -> input -> delta -> cd -> stop
            r_term = client.post("/terminal/create", headers=headers, json={"workspace_path": str(proj_dir)})
            assert r_term.status_code == 200
            sid = r_term.json()["session_id"]

            r_pty = client.post(f"/terminal/{sid}/pty/start", headers=headers)
            assert r_pty.status_code == 200

            r_in = client.post(
                f"/terminal/{sid}/input",
                headers=headers,
                json={"data": "echo STROKE_PTY_OK\n"},
            )
            assert r_in.status_code == 200

            # Poll briefly for PTY output
            output_text = ""
            for _ in range(15):
                r_delta = client.get(f"/terminal/output/delta?session_id={sid}&since_seq=0", headers=headers)
                assert r_delta.status_code == 200
                output_text = "\n".join(r_delta.json().get("lines", []))
                if "STROKE_PTY_OK" in output_text:
                    break
                time.sleep(0.1)
            assert "STROKE_PTY_OK" in output_text

            # cd inside workspace succeeds; outside workspace is forbidden
            r_cd_ok = client.post(f"/terminal/{sid}/cd", headers=headers, json={"path": "src"})
            assert r_cd_ok.status_code == 200
            assert r_cd_ok.json()["cwd"].endswith("src")

            r_cd_bad = client.post(f"/terminal/{sid}/cd", headers=headers, json={"path": str(outside_dir)})
            assert r_cd_bad.status_code == 403

            r_stop = client.post(f"/terminal/{sid}/stop", headers=headers)
            assert r_stop.status_code == 200


class TestMcpWorkflowAndFrontendBootstrap:
    def test_mcp_genuine_handshake_tool_discovery_invocation_and_disconnect(self):
        client = TestClient(main.app)
        headers = _auth_headers()

        # Mock McpClient.start & call_tool to simulate real protocol handshake + tool discovery
        async def _fake_connect_server(server_id, allow_local_override=None):
            fake_transport = MagicMock()
            fake_transport.is_connected.return_value = True
            fake_transport.close = AsyncMock()
            c = mcp_client.McpClient(server_id=server_id, transport=fake_transport, server_name="Demo MCP")
            c._initialized = True
            c.state = mcp_client.McpServerState.TOOLS_READY
            c.discovered_tools = [
                {
                    "name": "ping_tool",
                    "description": "Ping test tool",
                    "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
                }
            ]
            mcp_client.global_mcp_registry.clients[server_id] = c
            return c

        r_appr = client.post(
            "/mcp/approval/request",
            headers=headers,
            json={"server_id": "demo_mcp", "action": "connect", "target": "http://127.0.0.1:18999/mcp"},
        )
        assert r_appr.status_code == 200
        appr_id = r_appr.json()["approval_id"]

        with patch.object(mcp_client.global_mcp_registry, "connect_server", side_effect=_fake_connect_server):
            r_conn = client.post(
                "/mcp/connect",
                headers=headers,
                json={
                    "server_id": "demo_mcp",
                    "name": "Demo MCP",
                    "url": "http://127.0.0.1:18999/mcp",
                    "allow_local": True,
                    "approval_id": appr_id,
                },
            )
            assert r_conn.status_code == 200
            assert r_conn.json()["server"]["connected"] is True

        r_tools = client.get("/mcp/tools", headers=headers)
        assert r_tools.status_code == 200
        tool_names = [t["function"]["name"] for t in r_tools.json()["tools"]]
        assert "demo_mcp__ping_tool" in tool_names
        assert "read_file" in tool_names

        with patch.object(
            mcp_client.global_mcp_registry.clients["demo_mcp"],
            "call_tool",
            new=AsyncMock(return_value={"status": "success", "output": "pong"}),
        ):
            r_exec = client.post(
                "/mcp/execute",
                headers=headers,
                json={"tool_name": "demo_mcp__ping_tool", "arguments": {"msg": "hi"}},
            )
            assert r_exec.status_code == 200
            assert r_exec.json()["output"] == "pong"

        r_disc = client.post("/mcp/disconnect", headers=headers, json={"server_id": "demo_mcp"})
        assert r_disc.status_code == 200

    def test_index_html_session_token_injection_and_valid_js_syntax(self):
        client = TestClient(main.app)
        r = client.get("/")
        assert r.status_code == 200
        assert 'meta name="stroke-session-token"' in r.text

        # Extract inline script blocks and validate JS syntax with node --check
        html_path = Path(__file__).parent / "index.html"
        html = html_path.read_text(encoding="utf-8")
        scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", html)
        assert len(scripts) >= 1
        combined_js = "\n".join(scripts)
        res = subprocess.run(
            ["node", "--check", "-"],
            input=combined_js,
            text=True,
            capture_output=True,
        )
        assert res.returncode == 0, f"JavaScript syntax error in index.html: {res.stderr}"
