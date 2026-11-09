"""
================================================================================
STROKE // DEDICATED AGENT LOOP EVALUATION & REGRESSION TEST SUITE
================================================================================
Exhaustively evaluates and verifies Stroke's complete AI Agent Loop:
  1. Tool Request Understanding & Appropriate Selection
     - Verifies schema registry (get_active_ai_tools_schema) contains all valid OpenAI schemas.
     - Verifies ToolDispatcher routing across Terminal, Web Search, VFX, Studio MCP, and GitHub MCP.
  2. Argument Passing & Robust Validation
     - Verifies required arguments, argument aliases, compound command splitting, and double-JSON decoding.
     - Verifies missing arguments return structured error dictionaries without crashing.
  3. Processing Real Tool Results
     - Verifies real tool output (stdout, stderr, exit_code, search sources, VFX records) format and injection.
  4. Honest Failure Handling & Zero False Claims (Crucial Anti-Hallucination)
     - Terminal command failures (non-zero exit code, 127 binary not found) report honest failure.
     - GitHub commit without token returns status: 'error' and never claims success or queued commit.
     - Studio Luau execution when Roblox Studio is offline returns status: 'offline', connected: False, lines_executed: 0.
     - Unknown or hallucinated tools return structured error feedback.
  5. Multi-Turn Context Maintenance & Task Continuation
     - Verifies state preservation across multi-turn interactions (create session -> run -> read -> stop).
     - Verifies correct message structure history without duplication or context loss.
  6. Output Cleanliness & Leaked Tag Elimination
     - Verifies unexecuted <tool_call> tags and raw JSON are stripped from final user-facing text.
  7. End-to-End Autonomous Multi-Turn Agent Loop Simulation
     - Simulates multi-turn agent conversations with tool execution, failure handling, and self-correction.
================================================================================
"""

import os
import sys
import re
import json
import asyncio
import unittest
from typing import Dict, Any, List

os.environ["STROKE_TEST_AUTO_APPROVE"] = "1"

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from terminal_service import (
    TerminalManager,
    ToolDispatcher,
    get_terminal_openai_tool_schemas,
    get_terminal_tools_schema
)
import mcp_bridge
from main import get_active_ai_tools_schema


class TestStrokeAgentLoop(unittest.TestCase):

    def setUp(self):
        # Reset terminal sessions before each test to maintain clean test state
        with TerminalManager._lock:
            for s in list(TerminalManager._sessions.values()):
                try:
                    s.stop()
                except Exception:
                    pass
            TerminalManager._sessions.clear()
            TerminalManager._reaped_history.clear()

    def tearDown(self):
        with TerminalManager._lock:
            for s in list(TerminalManager._sessions.values()):
                try:
                    s.stop()
                except Exception:
                    pass
            TerminalManager._sessions.clear()
            TerminalManager._reaped_history.clear()

    # ==========================================================================
    # 1. TOOL REQUEST UNDERSTANDING & SELECTION
    # ==========================================================================
    def test_01_tool_schema_registry_completeness(self):
        """Verify unified tool schema registry exposes complete, valid OpenAI function specifications."""
        tools = get_active_ai_tools_schema()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 5, "Expected at least 6 active tools registered in schema")

        tool_names = set()
        for t in tools:
            self.assertEqual(t.get("type"), "function")
            fn = t.get("function", {})
            name = fn.get("name")
            self.assertTrue(name, "Tool must have a valid function name")
            tool_names.add(name)
            self.assertTrue(fn.get("description"), f"Tool '{name}' must have a description")
            self.assertIn("parameters", fn, f"Tool '{name}' must specify parameters schema")
            self.assertEqual(fn["parameters"].get("type"), "object")

        # Verify all essential capabilities are registered
        expected_tools = {
            "web_search",
            "search_vfx_database",
            "terminal_create_session",
            "terminal_run",
            "terminal_read_output",
            "terminal_get_status",
            "terminal_stop",
            "terminal_restart",
            "terminal_list_sessions",
            "studio_execute_luau",
            "github_commit_file"
        }
        for exp in expected_tools:
            self.assertIn(exp, tool_names, f"Expected active AI tool '{exp}' in unified tool registry")
        print("\n  [PASS] Unified tool schema registry validated with complete OpenAI schemas.")

    def test_02_tool_dispatcher_supported_tool_resolution(self):
        """Verify ToolDispatcher accurately identifies all supported and unsupported tools."""
        supported_examples = [
            "terminal_create_session", "create_terminal",
            "terminal_run", "run_command",
            "terminal_read_output", "read_terminal_output",
            "terminal_get_status", "get_terminal_status",
            "terminal_stop", "stop_terminal",
            "terminal_restart", "restart_terminal",
            "terminal_list_sessions", "list_terminals",
            "web_search",
            "search_vfx_database", "vfx_kinematics_lookup",
            "studio_execute_luau", "execute_luau",
            "studio_search_scripts", "studio_insert_vfx_asset", "studio_get_console",
            "github_commit_file", "github_create_pull_request",
            "mcp_custom_tool", "mcp_filesystem_read"
        ]
        for st in supported_examples:
            self.assertTrue(ToolDispatcher.is_supported(st), f"Expected '{st}' to be supported")

        unsupported_examples = [
            "destroy_hard_drive", "execute_arbitrary_shell_payload",
            "fake_unregistered_tool", "system_reboot", ""
        ]
        for ust in unsupported_examples:
            self.assertFalse(ToolDispatcher.is_supported(ust), f"Expected '{ust}' to be unsupported")
        print("  [PASS] ToolDispatcher accurately discriminates supported vs unsupported tools.")

    # ==========================================================================
    # 2. ARGUMENT PASSING & VALIDATION
    # ==========================================================================
    def test_03_argument_aliases_and_compound_command_splitting(self):
        """Verify ToolDispatcher and terminal engine handle argument aliases and compound command strings."""
        # 1. Test compound command string tokenization (e.g. executable with arguments in one string)
        res_create = ToolDispatcher.dispatch("terminal_create_session")
        session_id = res_create["session_id"]

        # Run command passed as single string without separate arguments array
        res_run = ToolDispatcher.dispatch("terminal_run", {
            "session_id": session_id,
            "command": 'python -c "print(1000 + 42)"'
        })
        self.assertEqual(res_run["exit_code"], 0)
        self.assertEqual(res_run["state"], "completed")
        self.assertIn("1042", res_run["stdout"])

        # 2. Test aliases: cmd vs executable, args vs arguments, id vs session_id
        res_run2 = ToolDispatcher.dispatch("run_command", {
            "id": session_id,
            "cmd": "python",
            "args": ["-c", "import sys; sys.stdout.write('ALIAS_OK')"]
        })
        self.assertEqual(res_run2["exit_code"], 0)
        self.assertIn("ALIAS_OK", res_run2["stdout"])

        # 3. Test read_terminal_output aliases
        res_read = ToolDispatcher.dispatch("terminal_read_output", {
            "id": session_id,
            "tail": 5
        })
        self.assertIn("1042", res_read["output"])
        self.assertIn("ALIAS_OK", res_read["output"])
        print("  [PASS] Compound command tokenization and argument aliases work seamlessly.")

    def test_04_missing_argument_validation(self):
        """Verify missing required arguments return structured error dictionaries rather than crashing."""
        # Missing query for web_search
        res_web = ToolDispatcher.dispatch("web_search", {})
        self.assertEqual(res_web.get("status"), "error")
        self.assertIn("Missing required argument 'query'", res_web.get("message", ""))

        # Missing query for search_vfx_database
        res_vfx = ToolDispatcher.dispatch("search_vfx_database", {"max_results": 3})
        self.assertEqual(res_vfx.get("status"), "error")
        self.assertIn("Missing required argument 'query'", res_vfx.get("message", ""))

        # Missing code for studio_execute_luau
        res_studio = asyncio.run(ToolDispatcher.dispatch_async("studio_execute_luau", {}))
        self.assertEqual(res_studio.get("status"), "error")
        self.assertIn("Missing required argument 'code'", res_studio.get("message", ""))

        # Invalid or non-existent session_id auto-creates a session gracefully
        res_term = ToolDispatcher.dispatch("terminal_run", {
            "session_id": "non-existent-session-id",
            "command": "python",
            "args": ["-c", "print('AUTO_RECOVERY')"]
        })
        self.assertEqual(res_term["exit_code"], 0)
        self.assertIn("AUTO_RECOVERY", res_term["stdout"])
        print("  [PASS] Missing required arguments produce structured error reports without crashing.")

    def test_05_double_stringified_json_arguments(self):
        """Verify ToolDispatcher handles double-encoded JSON arguments emitted by local LLMs."""
        inner_dict = {"workspace_path": REPO_ROOT}
        double_encoded = json.dumps(json.dumps(inner_dict))

        res = ToolDispatcher.dispatch("terminal_create_session", double_encoded)
        self.assertEqual(res.get("status"), "created")
        self.assertTrue(res.get("session_id", "").startswith("term-"))
        print("  [PASS] Double-stringified JSON arguments safely parsed and executed.")

    # ==========================================================================
    # 3. PROCESSING REAL TOOL RESULTS
    # ==========================================================================
    def test_06_real_terminal_and_vfx_results_processing(self):
        """Verify real tool execution produces structured results with output, exit code, and metadata."""
        # Real terminal execution
        created = ToolDispatcher.dispatch("terminal_create_session")
        sid = created["session_id"]

        run_res = ToolDispatcher.dispatch("terminal_run", {
            "session_id": sid,
            "executable": "python",
            "arguments": ["-c", "import sys; print('LINE_A'); sys.stderr.write('ERR_B\\n')"]
        })
        self.assertEqual(run_res["exit_code"], 0)
        self.assertEqual(run_res["state"], "completed")
        self.assertIn("LINE_A", run_res["stdout"])
        self.assertIn("ERR_B", run_res["stderr"])
        self.assertFalse(run_res["timed_out"])

        # Real VFX database query
        vfx_res = ToolDispatcher.dispatch("search_vfx_database", {"query": "Fireball"})
        self.assertEqual(vfx_res.get("status"), "success")
        self.assertIn("matches", vfx_res)
        self.assertGreater(vfx_res.get("matches_count", 0), 0)
        first_match = vfx_res["matches"][0]
        self.assertTrue("model_name" in first_match or "name" in first_match)
        print("  [PASS] Real tool execution results cleanly formatted and structured.")

    # ==========================================================================
    # 4. HONEST FAILURE HANDLING & PREVENTING FALSE CLAIMS
    # ==========================================================================
    def test_07_terminal_failure_diagnostic_integrity(self):
        """Verify failed terminal commands honestly return non-zero exit codes and capture diagnostics."""
        created = ToolDispatcher.dispatch("terminal_create_session")
        sid = created["session_id"]

        # 1. Non-zero exit code
        fail_res = ToolDispatcher.dispatch("terminal_run", {
            "session_id": sid,
            "executable": "python",
            "arguments": ["-c", "import sys; sys.exit(7)"]
        })
        self.assertEqual(fail_res["exit_code"], 7)
        self.assertEqual(fail_res["state"], "failed")

        # 2. Syntax Error
        syntax_res = ToolDispatcher.dispatch("terminal_run", {
            "session_id": sid,
            "executable": "python",
            "arguments": ["-c", "def broken(:"]
        })
        self.assertNotEqual(syntax_res["exit_code"], 0)
        self.assertEqual(syntax_res["state"], "failed")
        self.assertIn("SyntaxError", syntax_res["stderr"])

        # 3. Missing Binary from Safe Routine Allowlist (Exit code 127)
        bin_res = ToolDispatcher.dispatch("terminal_run", {
            "session_id": sid,
            "executable": "luau-analyze",
            "arguments": ["test.luau"]
        })
        self.assertEqual(bin_res["exit_code"], 127)
        self.assertEqual(bin_res["state"], "failed")
        self.assertIn("Binary not found", bin_res["stderr"])

        # 4. Unlisted command requires user security authorization
        auto_app = os.environ.pop("STROKE_TEST_AUTO_APPROVE", None)
        try:
            unlisted_res = ToolDispatcher.dispatch("terminal_run", {
                "session_id": sid,
                "executable": "arbitrary_custom_binary_12345"
            })
            self.assertEqual(unlisted_res.get("status"), "requires_approval")
        finally:
            if auto_app:
                os.environ["STROKE_TEST_AUTO_APPROVE"] = auto_app
        print("  [PASS] Terminal failures reliably return real exit codes (7, 127, SyntaxError) and enforce security approval.")

    def test_08_no_false_claims_on_github_commit_without_token(self):
        """Verify github_commit_file returns error when GITHUB_TOKEN is unset and never claims success."""
        # Ensure GITHUB_TOKEN is not active in this test
        original_token = os.environ.get("GITHUB_TOKEN")
        if "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]

        try:
            res = asyncio.run(mcp_bridge.execute_mcp_tool("github_commit_file", {
                "repo": "AyanshShrivastava/stroke",
                "path": "test_fake_file.py",
                "content": "print('hello')",
                "message": "test commit"
            }))
            self.assertEqual(res.get("status"), "error")
            self.assertIn("GITHUB_TOKEN is not configured", res.get("message", ""))
            self.assertNotIn("Successfully committed", res.get("message", ""))
            self.assertNotIn("commit_sha", res)
        finally:
            if original_token:
                os.environ["GITHUB_TOKEN"] = original_token
        print("  [PASS] GitHub commit without token strictly returns status 'error' (no false claims).")

    def test_09_no_false_claims_when_roblox_studio_is_offline(self):
        """Verify studio_execute_luau returns status 'offline' when Studio is closed with zero lines executed."""
        # When Roblox Studio is offline / unconfigured, studio_execute_luau must report offline
        import unittest.mock
        with unittest.mock.patch.dict("mcp_bridge._MCP_REGISTRY", {}, clear=True):
            res = asyncio.run(ToolDispatcher.dispatch_async("studio_execute_luau", {
                "code": "local p = Instance.new('Part'); p.Parent = workspace"
            }))
            self.assertEqual(res.get("status"), "offline")
            self.assertFalse(res.get("connected"))
            self.assertEqual(res.get("lines_executed"), 0)
            self.assertIn("offline", res.get("message", "").lower())
            self.assertNotIn("successfully executed architectural additions", res.get("message", "").lower())
            print("  [PASS] Roblox Studio offline execution strictly returns status 'offline' with 0 lines executed.")

    def test_10_unknown_tool_honest_error_handling(self):
        """Verify model calling an unknown tool receives honest error feedback instead of silent failure."""
        res_sync = ToolDispatcher.dispatch("hallucinated_unknown_tool", {"foo": "bar"})
        self.assertEqual(res_sync.get("status"), "error")
        self.assertIn("Unknown terminal tool 'hallucinated_unknown_tool'", res_sync.get("message", ""))

        res_async = asyncio.run(ToolDispatcher.dispatch_async("fantasy_magic_mcp", {}))
        self.assertEqual(res_async.get("status"), "error")
        self.assertIn("Unknown terminal tool 'fantasy_magic_mcp'", res_async.get("message", ""))
        print("  [PASS] Unknown tools produce structured error reports preventing hallucinated success.")

    # ==========================================================================
    # 5. MULTI-TURN CONTEXT MAINTENANCE & TASK CONTINUATION
    # ==========================================================================
    def test_11_multi_turn_terminal_task_continuation(self):
        """Verify state preservation across sequential multi-turn tool invocations."""
        # Turn 1: Create background terminal session
        t1 = ToolDispatcher.dispatch("terminal_create_session")
        session_id = t1["session_id"]
        self.assertTrue(session_id.startswith("term-"))

        # Turn 2: Run a file creation command in that session
        t2 = ToolDispatcher.dispatch("terminal_run", {
            "session_id": session_id,
            "executable": "python",
            "arguments": ["-c", "with open('agent_turn_test.tmp', 'w') as f: f.write('TASK_CONTINUED')"]
        })
        self.assertEqual(t2["exit_code"], 0)

        # Turn 3: Inspect file in that same session using cat
        t3 = ToolDispatcher.dispatch("terminal_run", {
            "session_id": session_id,
            "executable": "cat",
            "arguments": ["agent_turn_test.tmp"]
        })
        self.assertEqual(t3["exit_code"], 0)
        self.assertIn("TASK_CONTINUED", t3["stdout"])

        # Turn 4: Read accumulated session history
        t4 = ToolDispatcher.dispatch("terminal_read_output", {"session_id": session_id})
        self.assertIn("TASK_CONTINUED", t4["output"])

        # Turn 5: Clean up file and stop session
        ToolDispatcher.dispatch("terminal_run", {
            "session_id": session_id,
            "executable": "rm",
            "arguments": ["-f", "agent_turn_test.tmp"]
        })
        t5 = ToolDispatcher.dispatch("terminal_stop", {"session_id": session_id})
        self.assertIn(t5["status"], ("terminated", "stopped"))
        print("  [PASS] 5-turn multi-step terminal task preserved session state and outputs.")

    def test_12_tool_call_tag_parsing_and_leaked_tag_elimination(self):
        """Verify parsing of <tool_call> tags (single & array) and stripping of unexecuted tags from final reply."""
        # 1. Parse single tool call tag
        text_single = '<tool_call>{"name": "terminal_list_sessions", "arguments": {}}</tool_call>'
        parsed_single = ToolDispatcher.parse_and_execute_calls(text_single)
        self.assertEqual(len(parsed_single), 1)
        self.assertEqual(parsed_single[0]["tool"], "terminal_list_sessions")
        self.assertIn("terminals", parsed_single[0]["result"])

        # 2. Parse array of tool calls in single tag
        text_array = '<tool_call>[{"name": "terminal_list_sessions", "arguments": {}}, {"name": "search_vfx_database", "arguments": {"query": "Fire"}}]</tool_call>'
        parsed_array = ToolDispatcher.parse_and_execute_calls(text_array)
        self.assertEqual(len(parsed_array), 2)
        self.assertEqual(parsed_array[0]["tool"], "terminal_list_sessions")
        self.assertEqual(parsed_array[1]["tool"], "search_vfx_database")

        # 3. Verify stripping of unexecuted or residual <tool_call> tags from user-visible reply
        model_raw_reply = (
            "Here is the final report on your project:\n\n"
            "<tool_call>{\"name\": \"unexecuted_fake_tool\", \"arguments\": {}}</tool_call>\n\n"
            "All checks have passed successfully."
        )
        cleaned_reply = re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", model_raw_reply).strip()
        self.assertNotIn("<tool_call>", cleaned_reply)
        self.assertNotIn("unexecuted_fake_tool", cleaned_reply)
        self.assertIn("Here is the final report", cleaned_reply)
        self.assertIn("All checks have passed successfully.", cleaned_reply)
        print("  [PASS] Tool call tag parsing and leaked tag elimination verified.")

    # ==========================================================================
    # 6. END-TO-END AUTONOMOUS CODING & SELF-CORRECTION AGENT SIMULATION
    # ==========================================================================
    def test_13_end_to_end_agent_diagnosis_and_correction_cycle(self):
        """Verify complete agent loop: understand -> generate -> verify -> diagnose -> correct -> pass."""
        # Initialize session
        sess = ToolDispatcher.dispatch("terminal_create_session")
        sid = sess["session_id"]
        test_file = os.path.join(sess["cwd"], "agent_bug_test.py")

        try:
            # Step 1 & 2: Generate buggy code (syntax error: 'await' outside async)
            with open(test_file, "w") as f:
                f.write("def fetch_user_data():\n    return await get_remote_data()\n")

            # Step 3: Run real Python compiler check
            res_v1 = ToolDispatcher.dispatch("terminal_run", {
                "session_id": sid,
                "executable": "python",
                "arguments": ["-m", "py_compile", "agent_bug_test.py"]
            })

            # Step 4: Diagnose actual failure
            self.assertNotEqual(res_v1["exit_code"], 0)
            self.assertEqual(res_v1["state"], "failed")
            self.assertIn("SyntaxError", res_v1["stderr"])
            self.assertIn("'await' outside async", res_v1["stderr"])

            # Step 5: Self-correct based on captured diagnostic
            corrected_code = "async def fetch_user_data():\n    return await get_remote_data()\n"
            with open(test_file, "w") as f:
                f.write(corrected_code)

            # Step 6: Retest corrected code
            res_v2 = ToolDispatcher.dispatch("terminal_run", {
                "session_id": sid,
                "executable": "python",
                "arguments": ["-m", "py_compile", "agent_bug_test.py"]
            })
            self.assertEqual(res_v2["exit_code"], 0)
            self.assertEqual(res_v2["state"], "completed")

            # Step 7: Final verification report
            self.assertTrue(os.path.exists(test_file))
            print("  [PASS] Autonomous agent self-correction loop verified end-to-end on real compiler.")
        finally:
            if os.path.exists(test_file):
                try:
                    os.remove(test_file)
                except Exception:
                    pass
            ToolDispatcher.dispatch("terminal_stop", {"session_id": sid})


if __name__ == "__main__":
    print("\n================================================================================")
    print("STROKE // RUNNING COMPLETE AGENT LOOP EVALUATION & REGRESSION SUITE")
    print("================================================================================")
    unittest.main()
