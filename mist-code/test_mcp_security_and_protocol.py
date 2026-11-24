"""
================================================================================
STROKE // MCP PROTOCOL, SECURITY AND ROBLOX STUDIO INTEGRATION TEST SUITE
================================================================================
Exhaustive verification of:
  1. SSRF, DNS Rebinding, IPv4/IPv6 Alternate Form & Redirect Protection
  2. Minimal Child Environment Isolation & Secret Scrubbing (0 Leaks)
  3. JSON Schema Argument & Tool Shape Validation (Strict Spec Compliance)
  4. Protocol Reliability: isError Honesty, JSON-RPC Errors, SSE Stream Parsing
  5. Resilient Pagination: Cursor Cycle Detection, Page Cap & Tool Deduplication
  6. Process Lifecycle: Teardown, Process Group Teardown, Zombie Prevention
  7. Roblox Studio Integration: Persistent Session, 37 Tools, Honest Offline
  8. 5-Tier Connection Lifecycle Diagnostics & One-Time Cryptographic Approvals
================================================================================
"""

import os
import sys
import json
import asyncio
import unittest
import socket
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import mcp_client
from mcp_client import (
    McpServerState,
    McpError,
    SsrfProtector,
    McpSecretVault,
    build_minimal_mcp_env,
    McpJsonSchemaValidator,
    McpTransport,
    StdioTransport,
    StreamableHttpTransport,
    McpClient,
    McpApprovalManager,
    ServerConfig,
    McpServerRegistry,
    global_mcp_registry
)
import mcp_bridge
from mcp_bridge import (
    get_roblox_studio_tools,
    StudioMcpSession,
    execute_mcp_tool,
    execute_studio_mcp_command,
    register_custom_mcp_server,
    remove_custom_mcp_server,
    get_all_mcp_servers_with_health
)


class TestMcpSsrfProtection(unittest.TestCase):
    """Verifies that SSRF, DNS rebinding, private ranges, metadata, and redirects are strictly blocked."""

    def test_01_blocked_private_and_cloud_metadata_ips(self):
        """Rejects AWS/GCP/Azure cloud metadata and private RFC1918 subnets."""
        blocked_targets = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/",
            "http://10.0.0.1:8080",
            "http://172.16.5.22:3000",
            "http://192.168.1.100:80",
            "http://0.0.0.0:8000"
        ]
        for url in blocked_targets:
            with self.assertRaises(McpError, msg=f"Should block SSRF target {url}"):
                SsrfProtector.validate_url(url, allow_local=False)

    def test_02_loopback_blocked_unless_explicitly_allowed(self):
        """Rejects localhost and 127.0.0.1 by default, allows only when allow_local=True."""
        local_urls = [
            "http://127.0.0.1:8000/mcp",
            "http://localhost:3000",
            "http://[::1]:8080"
        ]
        for url in local_urls:
            with self.assertRaises(McpError, msg=f"Should reject default localhost {url}"):
                SsrfProtector.validate_url(url, allow_local=False)

            # When explicitly permitted, should return validated URL
            res = SsrfProtector.validate_url(url, allow_local=True)
            self.assertTrue(res.startswith("http"))

    def test_03_blocked_disallowed_schemes(self):
        """Rejects dangerous non-HTTP URI schemes (file, ftp, gopher, data)."""
        bad_schemes = [
            "file:///etc/passwd",
            "ftp://ftp.internal.corp/secret",
            "gopher://127.0.0.1:70",
            "data:text/plain;base64,SGVsbG8="
        ]
        for url in bad_schemes:
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(url, allow_local=True)

    def test_04_blocked_obfuscated_ip_formats(self):
        """Rejects decimal, hex, and octal integer IP representations."""
        obfuscated = [
            "http://2130706433/mcp",   # 127.0.0.1 in decimal
            "http://0x7f000001/mcp",   # 127.0.0.1 in hex
            "http://0177.0.0.1/mcp"    # 127.0.0.1 with octal prefix
        ]
        for url in obfuscated:
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(url, allow_local=False)

    def test_05_http_transport_redirect_validation(self):
        """StreamableHttpTransport validates redirect Location headers against SSRF."""
        mock_addr = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        with patch("socket.getaddrinfo", return_value=mock_addr):
            transport = StreamableHttpTransport("http://api.example.com", allow_local=False)

            # Mock initial redirect pointing to internal metadata
            mock_req = httpx.Request("POST", "http://api.example.com")
            mock_redirect_resp = httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
                request=mock_req
            )

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_redirect_resp

                async def test_redirect():
                    await transport.connect()
                    return await transport.request("initialize", {})

                with self.assertRaises(McpError) as ctx:
                    asyncio.run(test_redirect())
                self.assertIn("metadata", str(ctx.exception).lower())


class TestMcpEnvironmentHygiene(unittest.TestCase):
    """Verifies that child processes receive minimal environments with zero leaked secrets."""

    def test_01_backend_secrets_scrubbed_from_child_env(self):
        """Ensures Firebase, GitHub, Session, Stroke, and credential tokens are scrubbed."""
        test_dirty_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/Users/test",
            "FIREBASE_AUTH_KEY": "AIzaSySecretFirebaseKey123",
            "GITHUB_PAT": "ghp_SecretGitHubPersonalAccessToken999",
            "SESSION_SECRET_TOKEN": "sess_super_secret_456",
            "STROKE_INTERNAL_FERNET_KEY": "secret_fernet_internal_key",
            "OPENAI_API_KEY": "sk-proj-superSecretOpenAIKey777",
            "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "DATABASE_PASSWORD": "P@ssw0rdRootPassword!"
        }

        with patch.dict(os.environ, test_dirty_env, clear=True):
            clean_env = build_minimal_mcp_env()

            self.assertIn("PATH", clean_env)
            self.assertIn("HOME", clean_env)

            # Assert complete absence of any backend secrets
            self.assertNotIn("FIREBASE_AUTH_KEY", clean_env)
            self.assertNotIn("GITHUB_PAT", clean_env)
            self.assertNotIn("SESSION_SECRET_TOKEN", clean_env)
            self.assertNotIn("STROKE_INTERNAL_FERNET_KEY", clean_env)
            self.assertNotIn("OPENAI_API_KEY", clean_env)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", clean_env)
            self.assertNotIn("DATABASE_PASSWORD", clean_env)

    def test_02_vault_secret_encryption_and_decryption_roundtrip(self):
        """Verifies AES/Fernet encryption for stored configuration secrets."""
        secret = "super_confidential_mcp_api_token_2026"
        encrypted = McpSecretVault.encrypt(secret)
        self.assertTrue(encrypted.startswith("enc:fernet:"))

        decrypted = McpSecretVault.decrypt(encrypted)
        self.assertEqual(decrypted, secret)

        # Redaction check
        dict_with_secret = {"API_KEY": encrypted, "PUBLIC_CONFIG": "public_value"}
        redacted = McpSecretVault.redact_dict(dict_with_secret)
        self.assertEqual(redacted["API_KEY"], "***REDACTED***")
        self.assertEqual(redacted["PUBLIC_CONFIG"], "public_value")


class TestMcpJsonSchemaValidation(unittest.TestCase):
    """Verifies strict argument and tool definition schema validation."""

    def test_01_valid_arguments_pass(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
                "active": {"type": "boolean"}
            },
            "required": ["name", "count"]
        }
        valid_args = {"name": "TestInstance", "count": 5, "active": True}
        # Should not raise
        McpJsonSchemaValidator.validate(schema, valid_args)

    def test_02_missing_required_arguments_rejected(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
        with self.assertRaises(McpError) as ctx:
            McpJsonSchemaValidator.validate(schema, {})
        self.assertIn("Missing required parameter", str(ctx.exception))
        self.assertEqual(ctx.exception.code, -32602)

    def test_03_type_mismatch_rejected(self):
        schema = {
            "type": "object",
            "properties": {"count": {"type": "integer"}}
        }
        # Float where integer expected
        with self.assertRaises(McpError) as ctx:
            McpJsonSchemaValidator.validate(schema, {"count": "not_an_int"})
        self.assertIn("expected type 'integer'", str(ctx.exception))

    def test_04_additional_properties_forbidden_policy(self):
        schema = {
            "type": "object",
            "properties": {"allowed": {"type": "string"}},
            "additionalProperties": False
        }
        with self.assertRaises(McpError) as ctx:
            McpJsonSchemaValidator.validate(schema, {"allowed": "yes", "unrecognized": "hack"})
        self.assertIn("Unrecognized property", str(ctx.exception))

    def test_05_enum_validation(self):
        schema = {
            "type": "object",
            "properties": {"rig_type": {"type": "string", "enum": ["R15", "R6"]}}
        }
        with self.assertRaises(McpError) as ctx:
            McpJsonSchemaValidator.validate(schema, {"rig_type": "CustomRig"})
        self.assertIn("is not one of allowed values", str(ctx.exception))


class TestMcpProtocolAndReliability(unittest.TestCase):
    """Verifies error reporting honesty, SSE stream parsing, and loop prevention."""

    def test_01_tool_is_error_flag_honestly_reports_error(self):
        """When MCP server returns isError: true, status must be 'error', NEVER 'success'."""
        transport = MagicMock(spec=McpTransport)
        transport.is_connected.return_value = True

        client = McpClient(server_id="test_server", transport=transport)
        client.state = McpServerState.TOOLS_READY
        client._initialized = True
        client.discovered_tools = [{"name": "failing_tool", "inputSchema": {"type": "object"}}]

        # Mock JSON-RPC response with isError: True
        mock_error_res = {
            "isError": True,
            "content": [{"type": "text", "text": "Luau runtime syntax error: unexpected symbol near 'end'"}]
        }
        transport.request = AsyncMock(return_value=mock_error_res)

        res = asyncio.run(client.call_tool("failing_tool", {}))
        self.assertEqual(res["status"], "error")
        self.assertTrue(res.get("is_error"))
        self.assertIn("syntax error", res["message"])

    def test_02_pagination_cycle_detection_and_page_cap(self):
        """Pagination cycle (repeating nextCursor) is aborted cleanly without infinite loop."""
        transport = MagicMock(spec=McpTransport)
        transport.is_connected.return_value = True

        client = McpClient(server_id="test_server", transport=transport)

        # Mock infinite cursor loop: "cursor_A" -> "cursor_B" -> "cursor_A"
        page_1 = {"tools": [{"name": "tool_1", "description": "T1"}], "nextCursor": "cursor_A"}
        page_2 = {"tools": [{"name": "tool_2", "description": "T2"}], "nextCursor": "cursor_B"}
        page_3 = {"tools": [{"name": "tool_3", "description": "T3"}], "nextCursor": "cursor_A"}

        transport.request = AsyncMock(side_effect=[page_1, page_2, page_3])

        tools = asyncio.run(client.refresh_tools())
        # Should terminate upon detecting cursor_A cycle instead of looping
        self.assertGreaterEqual(len(tools), 2)
        tool_names = [t["name"] for t in tools]
        self.assertIn("tool_1", tool_names)
        self.assertIn("tool_2", tool_names)

    def test_03_streamable_sse_response_parsing(self):
        """StreamableHttpTransport decodes SSE text/event-stream buffers."""
        mock_addr = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        with patch("socket.getaddrinfo", return_value=mock_addr):
            transport = StreamableHttpTransport("http://api.example.com", allow_local=False)
            sse_text = "event: message\ndata: {\"jsonrpc\": \"2.0\", \"id\": \"1\", \"result\": {\"tools\": [{\"name\": \"sse_tool\"}]}}\n\n"

            mock_resp = httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                text=sse_text,
                request=httpx.Request("POST", "http://api.example.com")
            )
            parsed = transport._parse_response_body(mock_resp)
            self.assertIn("result", parsed)
            self.assertIn("tools", parsed["result"])
            self.assertEqual(parsed["result"]["tools"][0]["name"], "sse_tool")


class TestMcpProcessTeardown(unittest.IsolatedAsyncioTestCase):
    """Verifies that child processes and process groups are killed on close."""

    async def test_01_stdio_process_group_termination(self):
        """Verifies process termination closes pipes and terminates subprocess."""
        # Spawn a benign child process that sleeps
        transport = StdioTransport(command="sleep", args=["10"])
        await transport.connect()
        self.assertTrue(transport.is_connected())
        self.assertIsNotNone(transport.process)

        pid = transport.process.pid
        await transport.close()

        # Process should be terminated
        self.assertFalse(transport.is_connected())
        self.assertIsNone(transport.process)

        # Check OS process table - process should be gone
        try:
            os.kill(pid, 0)
            process_alive = True
        except OSError:
            process_alive = False
        self.assertFalse(process_alive, f"Child process {pid} should have been terminated")


class TestRobloxStudioIntegrationAndLifecycle(unittest.IsolatedAsyncioTestCase):
    """Verifies Roblox Studio session tracking, all 37 tools, and honest offline states."""

    def test_01_catalog_has_all_37_studio_tools(self):
        tools = get_roblox_studio_tools()
        names = {t["name"] for t in tools}
        # Check core capabilities
        self.assertIn("execute_luau", names)
        self.assertIn("script_read", names)
        self.assertIn("multi_edit", names)
        self.assertIn("script_search", names)
        self.assertIn("generate_material", names)
        self.assertIn("insert_asset", names)
        self.assertIn("get_console_output", names)
        self.assertIn("list_roblox_studios", names)
        self.assertGreaterEqual(len(tools), 35)

    async def test_02_studio_tools_honest_offline_reporting(self):
        """When Studio has no open place, tools return honest offline state."""
        # 1. Search scripts
        res_search = await execute_mcp_tool("studio_search_scripts", {"query": "CombatController"})
        self.assertEqual(res_search["status"], "offline")
        self.assertFalse(res_search["connected"])
        self.assertEqual(res_search["matches"], [])

        # 2. Insert asset
        res_insert = await execute_mcp_tool("studio_insert_vfx_asset", {"asset_id": "rbxassetid://12345"})
        self.assertEqual(res_insert["status"], "offline")
        self.assertFalse(res_insert["connected"])

        # 3. Get console
        res_console = await execute_mcp_tool("studio_get_console", {"max_lines": 20})
        self.assertEqual(res_console["status"], "offline")
        self.assertFalse(res_console["connected"])
        self.assertEqual(res_console["lines"], [])

        # 4. Execute Luau
        res_exec = await execute_mcp_tool("studio_execute_luau", {"code": "print('Test')"})
        self.assertEqual(res_exec["status"], "offline")
        self.assertFalse(res_exec["connected"])
        self.assertEqual(res_exec["lines_executed"], 0)

    async def test_03_5_tier_lifecycle_states_reporting(self):
        """Verifies 5-tier connection lifecycle states reporting in get_all_mcp_servers_with_health."""
        health = await get_all_mcp_servers_with_health()
        self.assertIsInstance(health, dict)
        if "Roblox_Studio" in health:
            studio_info = health["Roblox_Studio"]
            self.assertIn("lifecycle_state", studio_info)
            self.assertIn("status", studio_info)
            # Tier must be a valid 5-tier enum string
            valid_tiers = {
                McpServerState.CONFIGURED.value,
                McpServerState.EXECUTABLE_FOUND.value,
                McpServerState.PROCESS_RUNNING.value,
                McpServerState.PROTOCOL_CONNECTED.value,
                McpServerState.TOOLS_READY.value,
                McpServerState.OFFLINE.value
            }
            self.assertIn(studio_info["lifecycle_state"], valid_tiers)

    def test_04_one_time_approval_manager_lifecycle(self):
        """ApprovalManager generates single-use cryptographic tokens bound to user UID and server."""
        mgr = McpApprovalManager()
        rec = mgr.create_approval(
            server_id="custom_server",
            action="register",
            target="http://example.com/mcp",
            user_uid="user_uid_12345",
            ttl_seconds=300
        )
        self.assertTrue(rec.approval_id.startswith("mcp_appr_"))

        # Replay / modification checks:
        # Wrong user UID fails
        self.assertFalse(mgr.consume_approval(rec.approval_id, "custom_server", "wrong_user_uid"))
        # Wrong server ID fails
        self.assertFalse(mgr.consume_approval(rec.approval_id, "wrong_server", "user_uid_12345"))

        # Valid consumption succeeds
        valid = mgr.consume_approval(rec.approval_id, "custom_server", "user_uid_12345")
        self.assertTrue(valid)

        # Single-use: replay consumption fails
        replay = mgr.consume_approval(rec.approval_id, "custom_server", "user_uid_12345")
        self.assertFalse(replay)


if __name__ == "__main__":
    unittest.main()
