"""
================================================================================
STROKE // DEDICATED TERMINAL STRESS TEST SUITE
================================================================================
Exhaustively verifies:
  1. Concurrent Sessions & Thread-Safe Isolation
  2. Lock-Free LRU Reaping Under High Concurrency
  3. Long-Running Processes & Stderr Streaming Deadlock Prevention
  4. Process Tree & Grandchild Cleanup on Timeout (No Orphan Processes)
  5. Process Tree Cleanup on Cancellation (terminal_stop)
  6. Post-Cancellation & Post-Reap Output Retention
  7. Output Ring Buffering & Line Length Capping Under Extreme Output Load
  8. Accurate Exit Codes & Failure Diagnostic Capture
  9. Model Tool-Calling Parser Stress & Edge Case Resilience
================================================================================
"""

import os
import sys
import time
import json
import signal
import unittest
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from terminal_service import (
    TerminalManager,
    TerminalSession,
    ToolDispatcher,
    MAX_SESSIONS,
    MAX_OUTPUT_LINES,
)


class TestTerminalStress(unittest.TestCase):

    def setUp(self):
        # Clean any remaining sessions before each test
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
    # TEST 1: Concurrent Sessions & Thread-Safe Isolation
    # ==========================================================================
    def test_01_concurrent_sessions_isolation(self):
        print("\n--- [STRESS TEST 1] Concurrent Sessions & Data Isolation ---")
        num_threads = 15
        results = {}
        errors = []

        def worker(thread_idx: int):
            try:
                # Each worker creates a session and runs a unique print
                created = TerminalManager.terminal_create_session()
                sid = created["session_id"]
                marker = f"UNIQUE_THREAD_PAYLOAD_{thread_idx:03d}_{time.time()}"
                
                # Execute Python command with delay to simulate concurrent runtime
                run_res = TerminalManager.terminal_run(
                    session_id=sid,
                    executable="python",
                    arguments=["-c", f"import time; time.sleep(0.05); print('{marker}')"],
                    timeout_sec=10
                )
                
                # Read output
                read_res = TerminalManager.terminal_read_output(sid)
                output = read_res.get("output", "")
                results[thread_idx] = {
                    "session_id": sid,
                    "marker": marker,
                    "run_res": run_res,
                    "output": output
                }
            except Exception as e:
                errors.append((thread_idx, str(e)))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(worker, i) for i in range(num_threads)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(len(errors), 0, f"Encountered concurrency errors: {errors}")
        self.assertEqual(len(results), num_threads)

        # Verify no cross-talk between sessions
        for i, data in results.items():
            self.assertEqual(data["run_res"]["exit_code"], 0)
            self.assertIn(data["marker"], data["output"], f"Session output missing expected marker for thread {i}")
            # Ensure no OTHER thread's marker leaked into this session
            for other_i, other_data in results.items():
                if i != other_i:
                    self.assertNotIn(
                        other_data["marker"],
                        data["output"],
                        f"Cross-contamination detected! Session {data['session_id']} contains marker of thread {other_i}"
                    )

        print(f"  [PASS] {num_threads} concurrent sessions executed cleanly with 0 cross-contamination or deadlocks.")

    # ==========================================================================
    # TEST 2: Lock-Free LRU Reaping Under High Concurrency
    # ==========================================================================
    def test_02_lock_free_lru_reaping_under_high_load(self):
        print("\n--- [STRESS TEST 2] Lock-Free LRU Reaping Under Concurrency ---")
        total_sessions = 25
        created_ids = []
        lock = threading.Lock()

        def spawn_session(idx: int):
            res = TerminalManager.terminal_create_session()
            sid = res["session_id"]
            # Write unique marker so we can verify reaped history retrieval later
            TerminalManager.terminal_run(
                session_id=sid,
                executable="python",
                arguments=["-c", f"print('SESSION_MARKER_{idx}')"]
            )
            with lock:
                created_ids.append((idx, sid))

        start_t = time.time()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(spawn_session, i) for i in range(total_sessions)]
            for f in as_completed(futures):
                f.result()
        duration = time.time() - start_t

        self.assertEqual(len(created_ids), total_sessions)
        # Active sessions in manager must never exceed MAX_SESSIONS
        active_count = len(TerminalManager._sessions)
        self.assertLessEqual(active_count, MAX_SESSIONS)
        self.assertGreater(len(TerminalManager._reaped_history), 0)

        # Verify that output from reaped sessions can still be queried via terminal_read_output
        reaped_verified = 0
        for idx, sid in created_ids:
            out_res = TerminalManager.terminal_read_output(sid)
            if out_res.get("status") != "error":
                self.assertIn(f"SESSION_MARKER_{idx}", out_res.get("output", ""))
                reaped_verified += 1

        self.assertGreaterEqual(reaped_verified, MAX_SESSIONS + 5, "Reaped sessions must retain output history")
        print(f"  [PASS] {total_sessions} sessions rapidly spawned/reaped in {duration:.2f}s; active bounded <= {MAX_SESSIONS}; reaped output preserved.")

    # ==========================================================================
    # TEST 3: Long-Running Process & Stderr Streaming Deadlock Prevention
    # ==========================================================================
    def test_03_long_running_process_and_stderr_streaming(self):
        print("\n--- [STRESS TEST 3] Long-Running Process & Stderr Streaming ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        # Python script that interleaves stdout and stderr
        script = (
            "import sys, time\n"
            "for i in range(10):\n"
            "    sys.stdout.write(f'OUT_LINE_{i}\\n')\n"
            "    sys.stdout.flush()\n"
            "    sys.stderr.write(f'ERR_LINE_{i}\\n')\n"
            "    sys.stderr.flush()\n"
            "    time.sleep(0.04)\n"
        )

        bg_res = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", script],
            is_background=True
        )

        self.assertEqual(bg_res["state"], "running")
        self.assertTrue(bg_res["is_background"])
        self.assertIsNotNone(bg_res["pid"])

        # Poll output while process is running to verify non-blocking dual-stream capture
        time.sleep(0.2)
        mid_out = TerminalManager.terminal_read_output(sid)
        output_text = mid_out.get("output", "")
        self.assertIn("[stdout]", output_text)
        self.assertIn("[stderr]", output_text)

        # Wait for completion
        time.sleep(0.4)
        status = TerminalManager.terminal_get_status(sid)
        final_out = TerminalManager.terminal_read_output(sid)
        final_text = final_out.get("output", "")

        self.assertIn("OUT_LINE_9", final_text)
        self.assertIn("ERR_LINE_9", final_text)

        # Stop terminal session
        TerminalManager.terminal_stop(sid)
        print("  [PASS] Background process concurrently streamed stdout and stderr without pipe deadlock.")

    # ==========================================================================
    # TEST 4: Process Tree Cleanup on Timeout (No Orphan Grandchildren)
    # ==========================================================================
    def test_04_process_tree_cleanup_on_timeout(self):
        print("\n--- [STRESS TEST 4] Process Tree Cleanup on Timeout ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        # Script that spawns a distinct grandchild sleep process
        grandchild_marker = "grandchild_sleep_stress_test_marker"
        script = (
            "import subprocess, time, sys\n"
            f"p = subprocess.Popen(['sleep', '35'])\n"
            "print(f'SPAWNED_GRANDCHILD_{p.pid}')\n"
            "sys.stdout.flush()\n"
            "time.sleep(20)\n"
        )

        start_t = time.time()
        timeout_val = 1
        res = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", script],
            timeout_sec=timeout_val
        )
        elapsed = time.time() - start_t

        # Must time out swiftly within ~2 seconds (not 20s or 35s!)
        self.assertLess(elapsed, 3.0, f"Command hung on timeout! Elapsed: {elapsed:.2f}s")
        self.assertTrue(res["timed_out"])
        self.assertEqual(res["state"], "timed_out")
        self.assertEqual(res["exit_code"], -signal.SIGKILL)

        # Verify whether any orphaned 'sleep 35' remains in OS process table
        time.sleep(0.3)
        check_cmd = ["pgrep", "-f", "sleep 35"]
        try:
            pids = subprocess.check_output(check_cmd).decode().strip().split()
        except subprocess.CalledProcessError:
            pids = []

        self.assertEqual(len(pids), 0, f"Found orphaned grandchild processes still running: {pids}")
        TerminalManager.terminal_stop(sid)
        print(f"  [PASS] Process tree terminated in {elapsed:.2f}s; 0 orphaned grandchild processes left.")

    # ==========================================================================
    # TEST 5: Process Tree Cleanup on Cancellation (terminal_stop)
    # ==========================================================================
    def test_05_process_tree_cleanup_on_cancellation(self):
        print("\n--- [STRESS TEST 5] Process Tree Cleanup on Cancellation ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        script = (
            "import subprocess, time, sys\n"
            "p = subprocess.Popen(['sleep', '40'])\n"
            "print(f'PARENT_PID_{p.pid}')\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )

        res = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", script],
            is_background=True
        )
        time.sleep(0.4)

        # Stop terminal explicitly
        stop_res = TerminalManager.terminal_stop(sid)
        self.assertEqual(stop_res["status"], "terminated")
        self.assertTrue(stop_res["process_killed"])

        time.sleep(0.3)
        try:
            pids = subprocess.check_output(["pgrep", "-f", "sleep 40"]).decode().strip().split()
        except subprocess.CalledProcessError:
            pids = []

        self.assertEqual(len(pids), 0, f"Found orphaned sleep processes after terminal_stop: {pids}")
        print("  [PASS] terminal_stop killed entire process tree with 0 orphan processes remaining.")

    # ==========================================================================
    # TEST 6: Post-Cancellation & Post-Reap Output Retention
    # ==========================================================================
    def test_06_post_cancellation_output_retention(self):
        print("\n--- [STRESS TEST 6] Post-Cancellation Output Retention ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        magic_marker = "MAGIC_PRE_TERMINATION_OUTPUT_8877"
        TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", f"print('{magic_marker}')"]
        )

        # Terminate session
        TerminalManager.terminal_stop(sid)

        # Verify output is still queryable through read_terminal_output
        out_res = TerminalManager.terminal_read_output(sid)
        self.assertIn(magic_marker, out_res.get("output", ""))
        print("  [PASS] Output retained and queryable after session termination.")

    # ==========================================================================
    # TEST 7: Output Ring Buffering & Line Length Capping Under Load
    # ==========================================================================
    def test_07_output_ring_buffer_and_line_length_capping(self):
        print("\n--- [STRESS TEST 7] Output Buffering & Line Capping ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        # Generate 4000 lines, with some lines having 6000 characters
        script = (
            "import sys\n"
            "for i in range(4000):\n"
            "    if i == 2500:\n"
            "        sys.stdout.write('X' * 6000 + '\\n')\n"
            "    else:\n"
            "        sys.stdout.write(f'LINE_{i:04d}\\n')\n"
            "sys.stdout.flush()\n"
        )

        res = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", script],
            timeout_sec=15
        )

        self.assertEqual(res["exit_code"], 0)
        # Check context protection in run response
        self.assertIn("Output truncated", res["stdout"])

        # Check session ring buffer limits
        out_res = TerminalManager.terminal_read_output(sid, tail_lines=5000)
        lines = out_res.get("output", "").splitlines()
        self.assertLessEqual(len(lines), MAX_OUTPUT_LINES + 5)

        # Verify that the 6000-char line was clamped to 4000 chars
        has_clamped_line = any("...[line truncated]" in l for l in lines)
        self.assertTrue(has_clamped_line, "Oversized lines must be truncated to prevent memory saturation")

        TerminalManager.terminal_stop(sid)
        print("  [PASS] Ring buffer bounded to MAX_OUTPUT_LINES; individual lines clamped to 4000 chars.")

    # ==========================================================================
    # TEST 8: Accurate Exit Codes & Failure Diagnostic Capture
    # ==========================================================================
    def test_08_accurate_exit_codes_and_diagnostics(self):
        print("\n--- [STRESS TEST 8] Exit Codes & Failure Diagnostics ---")
        created = TerminalManager.terminal_create_session()
        sid = created["session_id"]

        # Case 1: Custom exit code (42)
        res1 = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", "import sys; sys.exit(42)"]
        )
        self.assertEqual(res1["exit_code"], 42)
        self.assertEqual(res1["state"], "failed")

        # Case 2: Missing binary (127) - luau-analyze is in SAFE_ROUTINE_COMMANDS but not on PATH
        res2 = TerminalManager.terminal_run(
            session_id=sid,
            executable="luau-analyze",
            arguments=["test.luau"]
        )
        self.assertEqual(res2["exit_code"], 127)
        self.assertEqual(res2["state"], "failed")
        self.assertIn("Binary not found", res2["stderr"])

        # Case 3: Python runtime syntax error
        res3 = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-c", "def broken():"]
        )
        self.assertNotEqual(res3["exit_code"], 0)
        self.assertTrue("SyntaxError" in res3["stderr"] or "IndentationError" in res3["stderr"])

        TerminalManager.terminal_stop(sid)
        print("  [PASS] Accurate exit codes (42, 127, SyntaxError) and diagnostics captured cleanly.")

    # ==========================================================================
    # TEST 9: Model Tool-Calling Parser Stress & Edge Case Resilience
    # ==========================================================================
    def test_09_model_tool_calling_parser_stress_and_edge_cases(self):
        print("\n--- [STRESS TEST 9] Model Tool-Calling Parser & Dispatcher ---")
        
        # 1. Embedded JSON with nested arguments dictionary in natural language
        msg1 = (
            "I will run the compiler check now.\n"
            "{\"name\": \"terminal_run\", \"arguments\": {\"executable\": \"python\", \"arguments\": [\"-c\", \"print('DISPATCH_NESTED_OK')\"]}}\n"
            "Please check the result."
        )
        calls1 = ToolDispatcher.parse_and_execute_calls(msg1)
        self.assertEqual(len(calls1), 1)
        self.assertEqual(calls1[0]["tool"], "terminal_run")
        self.assertEqual(calls1[0]["result"]["exit_code"], 0)
        self.assertIn("DISPATCH_NESTED_OK", calls1[0]["result"]["stdout"])

        # 2. Stringified arguments JSON
        msg2 = {
            "name": "terminal_run",
            "arguments": json.dumps({"executable": "python", "arguments": ["-c", "print('DISPATCH_STRINGIFIED_OK')"]})
        }
        res2 = ToolDispatcher.dispatch("terminal_run", msg2["arguments"])
        self.assertEqual(res2["exit_code"], 0)
        self.assertIn("DISPATCH_STRINGIFIED_OK", res2["stdout"])

        # 3. XML Tool Call Format
        msg3 = (
            "<tool_call>\n"
            "{\"name\": \"terminal_run\", \"arguments\": {\"executable\": \"python\", \"arguments\": [\"-c\", \"print('DISPATCH_XML_OK')\"]}}\n"
            "</tool_call>"
        )
        calls3 = ToolDispatcher.parse_and_execute_calls(msg3)
        self.assertEqual(len(calls3), 1)
        self.assertIn("DISPATCH_XML_OK", calls3[0]["result"]["stdout"])

        # 4. Graceful handling of malformed input (no crash)
        calls4 = ToolDispatcher.parse_and_execute_calls("{malformed: true, 'broken'")
        self.assertEqual(calls4, [])

        res_unknown = ToolDispatcher.dispatch("non_existent_tool", {})
        self.assertEqual(res_unknown["status"], "error")
        self.assertIn("Unknown terminal tool", res_unknown["message"])

        print("  [PASS] ToolDispatcher handled nested JSON, stringified args, XML tags, and malformed inputs gracefully.")


if __name__ == "__main__":
    unittest.main()
