"""
================================================================================
STROKE // MCP CLIENT, OFFICIAL 35-TOOL ROBLOX STUDIO & GITHUB OVERHAUL TEST SUITE
================================================================================
Comprehensive verification for Stroke's overhaul systems:
  1. MCP Client Engine (Stdio & HTTP Transports, JSON-RPC 2.0, Tool Discovery)
  2. Roblox Studio Official 35-Tool Schema & Process Registry
  3. Dynamic Two-Tier Tool Selection & Meta Tools Search
  4. Secure GitHub PAT Service & Encrypted Key Vault
  5. Resilient JSON Parser for Llama 3.2 1B Outputs
  6. Incremental Delta Streaming Terminal Output Engine
================================================================================
"""

import os
import sys
import json
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import mcp_client
from mcp_client import McpServerConfig, McpClient, StdioTransport, StreamableHttpTransport, McpServerRegistry
import mcp_bridge
from mcp_bridge import (
    get_roblox_studio_tools,
    list_roblox_studios_sync,
    select_active_tools_for_query,
    tools_search,
    execute_mcp_tool
)
import github_service
from terminal_service import (
    robust_json_parse,
    TerminalSession,
    TerminalManager,
    ToolDispatcher
)


class TestRobloxStudio35Tools(unittest.TestCase):
    """Verifies that all 35 official Roblox Studio tools are properly registered and schema-compliant."""

    def test_official_35_tools_catalog_count(self):
        tools = get_roblox_studio_tools()
        self.assertGreaterEqual(len(tools), 35, f"Expected at least 35 tools, got {len(tools)}")

    def test_official_35_tools_openai_schema_conformance(self):
        tools = get_roblox_studio_tools()
        expected_tool_names = {
            # Script Management
            "execute_luau", "script_read", "multi_edit", "script_search", "script_grep",
            # Content Generation
            "generate_mesh", "generate_material", "generate_procedural_model",
            "generate_texture", "generate_animation", "generate_scene",
            "segment_mesh", "wait_job_finished", "search_asset",
            "insert_asset", "upload_image", "store_image",
            # DataModel Exploration
            "search_game_tree", "inspect_instance",
            # Simulation & Playtesting
            "get_studio_state", "start_stop_play", "get_console_output",
            # User Input & Navigation Automation
            "screen_capture", "character_navigation",
            "user_keyboard_input", "user_mouse_input", "auto_setup_avatar",
            # Studio Skills & Subagents
            "list_skills", "create_skill", "edit_skill", "skill", "subagent",
            # Cloud & Sandbox
            "http_get", "open_cloud_invoke",
            # Multi-Studio Session Tracking
            "list_roblox_studios"
        }
        found_names = {t["name"] for t in tools}
        for name in expected_tool_names:
            self.assertIn(name, found_names, f"Expected tool '{name}' in Roblox Studio tools")

        for t in tools:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("parameters", t)
            params = t["parameters"]
            self.assertEqual(params.get("type"), "object")
            self.assertIn("properties", params)

    def test_list_roblox_studios_sync(self):
        res = list_roblox_studios_sync()
        self.assertIn("studios", res)
        self.assertIn("count", res)
        self.assertIn("total_active", res)
        self.assertIn("summary", res)
        self.assertIsInstance(res["studios"], list)
        self.assertIsInstance(res["total_active"], int)


class TestDynamicToolSelectionAndDiscovery(unittest.TestCase):
    """Verifies two-tier dynamic tool selection preventing 1B context overflow."""

    def test_two_tier_selection_caps_prompt_size(self):
        tools = select_active_tools_for_query("I need to write and search a luau script in Roblox")
        names = [t["function"]["name"] for t in tools]
        self.assertLessEqual(len(tools), 9)
        self.assertTrue(any("execute_luau" in n for n in names))
        self.assertIn("tools_search", names)

    def test_two_tier_selection_github(self):
        tools = select_active_tools_for_query("Commit this file to my git repository")
        names = [t["function"]["name"] for t in tools]
        self.assertIn("github_commit_file", names)
        self.assertIn("tools_search", names)

    def test_tools_search_dynamic_discovery(self):
        res = tools_search("animation")
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["match_count"], 0)
        names = [m["name"] for m in res["matches"]]
        self.assertIn("generate_animation", names)


class TestRobustJsonParse(unittest.TestCase):
    """Verifies JSON resilience against typical Llama 3.2 1B edge-case outputs."""

    def test_trailing_commas_handling(self):
        malformed = '{"repo": "my-game", "path": "main.py", "content": "print(1)",}'
        parsed = robust_json_parse(malformed)
        self.assertEqual(parsed["repo"], "my-game")
        self.assertEqual(parsed["path"], "main.py")

    def test_single_quoted_python_dict(self):
        py_dict = "{'command': 'ls', 'args': ['-la']}"
        parsed = robust_json_parse(py_dict)
        self.assertEqual(parsed["command"], "ls")
        self.assertEqual(parsed["args"], ["-la"])

    def test_truncated_json_repair(self):
        truncated = '{"action": "test", "params": {"key": "val"'
        parsed = robust_json_parse(truncated)
        self.assertEqual(parsed["action"], "test")

    def test_double_stringified_json(self):
        double = json.dumps('{"command": "echo hello"}')
        parsed = robust_json_parse(double)
        self.assertEqual(parsed["command"], "echo hello")


class TestGitHubService(unittest.TestCase):
    """Verifies token encryption and secure GitHub PAT capabilities."""

    def setUp(self):
        self.test_token = "ghp_MockTestTokenForStrokeSecurityAudit2026XYZ"

    def test_encryption_vault_roundtrip(self):
        github_service.store_github_token(self.test_token)
        retrieved = github_service.get_stored_github_token()
        self.assertEqual(retrieved, self.test_token)
        github_service.clear_stored_github_token()
        self.assertIsNone(github_service.get_stored_github_token())

    def test_commit_file_requires_confirmation_gate(self):
        res = asyncio.run(github_service.commit_file(
            repo="owner/repo",
            path="README.md",
            content="# Hello",
            commit_message="Test commit",
            confirmed=False
        ))
        self.assertEqual(res["status"], "requires_confirmation")
        self.assertIn("confirmation_prompt", res)

    def test_commit_file_without_token_returns_error(self):
        github_service.clear_stored_github_token()
        with patch.dict(os.environ, {}, clear=True):
            res = asyncio.run(github_service.commit_file(
                repo="owner/repo",
                path="README.md",
                content="# Hello",
                commit_message="Test commit",
                confirmed=True
            ))
            self.assertEqual(res["status"], "error")
            self.assertIn("token", res["message"].lower())


class TestTerminalOutputDeltaStreaming(unittest.TestCase):
    """Verifies sequence-based incremental terminal streaming."""

    def test_incremental_delta_retrieval(self):
        session = TerminalSession(
            session_id="test_stream_01",
            workspace_path="/tmp"
        )
        session.append_output("line 1")
        session.append_output("line 2")
        session.append_output("line 3")

        # Read from sequence 0
        delta0 = session.read_output_delta(since_seq=0)
        self.assertEqual(len(delta0["lines"]), 3)
        self.assertEqual(delta0["latest_seq"], 3)

        # Append more
        session.append_output("line 4")
        session.append_output("line 5")

        # Read from sequence 3
        delta3 = session.read_output_delta(since_seq=3)
        self.assertEqual(len(delta3["lines"]), 2)
        self.assertEqual(delta3["lines"], ["[stdout] line 4", "[stdout] line 5"])
        self.assertEqual(delta3["latest_seq"], 5)

        # Read when up to date
        delta5 = session.read_output_delta(since_seq=5)
        self.assertEqual(len(delta5["lines"]), 0)
        self.assertEqual(delta5["latest_seq"], 5)


class TestMcpClientProtocol(unittest.TestCase):
    """Verifies MCP JSON-RPC client, tool schema registration, and namespacing."""

    def test_mcp_server_registry_registration(self):
        registry = McpServerRegistry()
        server_cfg = McpServerConfig(
            id="filesystem",
            name="FileSystem MCP Server",
            command="python",
            args=["-m", "http.server"]
        )
        client = registry.register_server(server_cfg)
        self.assertIsNotNone(client)
        self.assertIn("filesystem", registry.configs)

        # Test tool schema conversion with namespacing
        mock_raw_tool = {
            "name": "read_file",
            "description": "Reads a file from filesystem",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        }
        client.discovered_tools = [mock_raw_tool]
        all_schemas = registry.get_all_tool_schemas()
        self.assertEqual(len(all_schemas), 1)
        schema = all_schemas[0]
        self.assertEqual(schema["function"]["name"], "filesystem__read_file")
        self.assertIn("[FileSystem MCP Server]", schema["function"]["description"])


if __name__ == "__main__":
    unittest.main()
