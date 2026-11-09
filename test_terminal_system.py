"""
Comprehensive Test Suite for Stroke Private Internal Background Terminal System
Validates all 10 core requirements:
  1. Multiple independent sessions (unique IDs, isolated cwd, state, ring-buffered output)
  2. Six internal tools (create_terminal, run_command, read_terminal_output, get_terminal_status, list_terminals, stop_terminal)
  3. Real process execution, stdout, stderr, and exit codes
  4. Timeouts & process termination
  5. Workspace confinement & traversal prevention
  6. Structured command invocation & security policy (allowed, approval required, denied)
  7. Approval workflow (respond_to_approval)
  8. Sensitive data redaction (PATs, API keys, JWTs, private keys)
  9. Session reaping & lifecycle management
  10. Coding loop integration with background terminal compilation
"""

import os
import sys
import time
import shutil

# Ensure workspace root is in python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from terminal_service import (
    TerminalManager,
    TerminalSession,
    redact_sensitive_data,
    evaluate_command_security,
    SecurityDecision,
    get_terminal_tools_schema,
)
from coding_loop import RobloxDomainTestRunner, StrokeCodingLoop


def test_secret_redaction():
    print("\n--- [TEST 1] Secret Redaction Engine ---")
    samples = [
        ("Using token ghp_123456789012345678901234567890123456 to push", "[REDACTED_GITHUB_PAT]"),
        ("Key: AIzaSyD9x8y7z6w5v4u3t2s1r0q9p8o7n6m5l4k", "[REDACTED_GOOGLE_API_KEY]"),
        ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.do_not_leak_this", "Bearer [REDACTED_JWT]"),
        ("password='SuperSecretPassword123!'", "password=[REDACTED_SECRET]"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...fake\n-----END RSA PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
    ]
    for text, expected_marker in samples:
        redacted = redact_sensitive_data(text)
        assert expected_marker in redacted, f"Expected '{expected_marker}' in '{redacted}'"
        print(f"  [OK] Redacted: {text[:35]}... -> {redacted[:45]}...")
    print("Test 1 passed successfully.")


def test_command_security_policy():
    print("\n--- [TEST 2] Command Security & Allowlist Policy ---")
    # Routine safe commands
    dec, rat = evaluate_command_security("python", ["--version"])
    assert dec == SecurityDecision.ALLOWED, f"Expected python to be allowed, got {dec}"
    print(f"  [OK] python: {dec} ({rat})")

    dec, rat = evaluate_command_security("git", ["status"])
    assert dec == SecurityDecision.ALLOWED, f"Expected git status to be allowed, got {dec}"
    print(f"  [OK] git status: {dec} ({rat})")

    dec, rat = evaluate_command_security("luau-analyze", ["script.luau"])
    assert dec == SecurityDecision.ALLOWED, f"Expected luau-analyze to be allowed, got {dec}"
    print(f"  [OK] luau-analyze: {dec} ({rat})")

    # Requires approval
    dec, rat = evaluate_command_security("git", ["push", "origin", "main"])
    assert dec == SecurityDecision.REQUIRES_APPROVAL, f"Expected git push to require approval, got {dec}"
    print(f"  [OK] git push: {dec} ({rat})")

    dec, rat = evaluate_command_security("npm", ["install", "express"])
    assert dec == SecurityDecision.REQUIRES_APPROVAL, f"Expected npm install to require approval, got {dec}"
    print(f"  [OK] npm install: {dec} ({rat})")

    dec, rat = evaluate_command_security("rm", ["-rf", "some_dir"])
    assert dec == SecurityDecision.REQUIRES_APPROVAL, f"Expected rm to require approval, got {dec}"
    print(f"  [OK] rm: {dec} ({rat})")

    # Strictly denied
    dec, rat = evaluate_command_security("sudo", ["reboot"])
    assert dec == SecurityDecision.DENIED, f"Expected sudo to be denied, got {dec}"
    print(f"  [OK] sudo: {dec} ({rat})")

    dec, rat = evaluate_command_security("dd", ["if=/dev/zero", "of=/dev/sda"])
    assert dec == SecurityDecision.DENIED, f"Expected dd to be denied, got {dec}"
    print(f"  [OK] dd: {dec} ({rat})")
    print("Test 2 passed successfully.")


def test_session_lifecycle_and_tools():
    print("\n--- [TEST 3] Six Internal Tools & Multiple Independent Sessions ---")
    # 1. create_terminal
    res1 = TerminalManager.create_terminal()
    session_id1 = res1["session_id"]
    print(f"  [OK] Created Session 1: {session_id1}")

    res2 = TerminalManager.create_terminal()
    session_id2 = res2["session_id"]
    print(f"  [OK] Created Session 2: {session_id2}")
    assert session_id1 != session_id2, "Session IDs must be distinct"

    # 2. list_terminals
    sessions = TerminalManager.list_terminals()
    assert len(sessions) >= 2, "Should list at least two active sessions"
    print(f"  [OK] list_terminals returned {len(sessions)} active sessions")

    # 3. run_command in Session 1
    run_res1 = TerminalManager.run_command(session_id1, "python", ["-c", "print('Hello from Session 1')"], approved=True)
    assert run_res1["exit_code"] == 0
    assert "Hello from Session 1" in run_res1["stdout"]
    print(f"  [OK] Session 1 run_command output: {run_res1['stdout'].strip()}")

    # 4. run_command in Session 2 (Independent cwd / state)
    run_res2 = TerminalManager.run_command(session_id2, "python", ["-c", "print('Hello from Session 2')"], approved=True)
    assert run_res2["exit_code"] == 0
    assert "Hello from Session 2" in run_res2["stdout"]
    print(f"  [OK] Session 2 run_command output: {run_res2['stdout'].strip()}")

    # 5. read_terminal_output
    out1 = TerminalManager.read_terminal_output(session_id1)
    assert "Hello from Session 1" in out1["output"]
    assert "Hello from Session 2" not in out1["output"], "Session 1 must not contain Session 2 output"
    print(f"  [OK] read_terminal_output isolated cleanly ({out1['lines_count']} lines)")

    # 6. get_terminal_status
    status1 = TerminalManager.get_terminal_status(session_id1)
    assert status1["session_id"] == session_id1
    assert status1["last_exit_code"] == 0
    print(f"  [OK] get_terminal_status: state={status1['state']}, exit_code={status1['last_exit_code']}")

    # 7. stop_terminal
    stop1 = TerminalManager.stop_terminal(session_id1)
    assert stop1["status"] == "terminated"
    print(f"  [OK] stop_terminal: Session 1 reaped")

    stop2 = TerminalManager.stop_terminal(session_id2)
    assert stop2["status"] == "terminated"
    print(f"  [OK] stop_terminal: Session 2 reaped")
    print("Test 3 passed successfully.")


def test_directory_traversal_prevention():
    print("\n--- [TEST 4] Workspace Sandboxing & Traversal Prevention ---")
    session_res = TerminalManager.create_terminal()
    session_id = session_res["session_id"]

    # Try changing to parent directory outside workspace
    cd_res = TerminalManager.run_command(session_id, "cd", ["../../.."])
    assert cd_res["exit_code"] != 0
    assert "traversal denied" in cd_res["stderr"].lower() or "outside designated workspace" in cd_res["stderr"].lower()
    print(f"  [OK] Traversal blocked: {cd_res['stderr']}")

    TerminalManager.stop_terminal(session_id)
    print("Test 4 passed successfully.")


def test_timeouts_and_cancellation():
    print("\n--- [TEST 5] Process Timeouts & Graceful Cancellation ---")
    session_res = TerminalManager.create_terminal()
    session_id = session_res["session_id"]

    # Run sleep command with a 2-second timeout
    t0 = time.time()
    res = TerminalManager.run_command(session_id, "python", ["-c", "import time; time.sleep(10)"], timeout_sec=2, approved=True)
    elapsed = time.time() - t0
    assert elapsed < 4.0, f"Process timeout took too long: {elapsed}s"
    assert res["state"] == "timed_out"
    print(f"  [OK] Timeout enforced in {elapsed:.2f}s (State: {res['state']}, Exit: {res['exit_code']})")

    TerminalManager.stop_terminal(session_id)
    print("Test 5 passed successfully.")


def test_approval_workflow():
    print("\n--- [TEST 6] User Authorization & Approval Workflow ---")
    session_res = TerminalManager.create_terminal()
    session_id = session_res["session_id"]

    # Trigger command requiring approval
    appr_res = TerminalManager.run_command(session_id, "git", ["push", "origin", "main"])
    assert appr_res.get("status") == "requires_approval"
    approval_id = appr_res["approval_id"]
    print(f"  [OK] Authorization requested: token={approval_id}, rationale={appr_res['rationale']}")

    # Test denial
    denial = TerminalManager.respond_to_approval(approval_id, approved=False)
    assert denial["status"] == "denied"
    print(f"  [OK] Denial processed cleanly: {denial['message']}")

    TerminalManager.stop_terminal(session_id)
    print("Test 6 passed successfully.")


def test_coding_loop_background_terminal_checks():
    print("\n--- [TEST 7] Autonomous Coding Loop Private Terminal Check ---")
    # Valid Python code
    py_code = "def calculate_matrix_norm(values):\n    return sum(v**2 for v in values) ** 0.5\n"
    report = RobloxDomainTestRunner.test_python_code(py_code)
    assert report["is_verified"] is True
    terminal_checks = [c for c in report["passed_checks"] if "private background terminal" in c.lower()]
    assert len(terminal_checks) > 0, "Expected private background terminal bytecode check in passed_checks"
    print(f"  [OK] Valid Python passed terminal check: {terminal_checks[0]}")

    # Invalid Python code
    bad_py_code = "def syntax_break(\n    broken = (123 +\n"
    bad_report = RobloxDomainTestRunner.test_python_code(bad_py_code)
    assert bad_report["is_verified"] is False
    assert len(bad_report["failed_checks"]) > 0
    print(f"  [OK] Invalid Python caught compiler error: {bad_report['failed_checks'][0]['message']}")

    # Valid Luau code with debounce table
    luau_code = """
local hitTargets = {}
local function onHitboxTriggered(hitPart: BasePart)
    local character = hitPart.Parent
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    if humanoid and humanoid.Health > 0 and not hitTargets[humanoid] then
        hitTargets[humanoid] = true
        humanoid:TakeDamage(25)
    end
end
"""
    luau_report = RobloxDomainTestRunner.test_luau_code(luau_code, "Roblox hitbox damage script")
    if shutil.which("luau-analyze"):
        assert luau_report["is_verified"] is True
    else:
        assert luau_report["is_verified"] is False
        assert "AST" in luau_report["compiler_used"]
    print(f"  [OK] Luau verified with {len(luau_report['passed_checks'])} passing checks.")
    print("Test 7 passed successfully.")


def test_tools_schema():
    print("\n--- [TEST 8] Tool Schemas for Model Tool-Calling ---")
    schemas = get_terminal_tools_schema()
    names = [s["name"] for s in schemas]
    expected = ["create_terminal", "run_command", "read_terminal_output", "get_terminal_status", "list_terminals", "stop_terminal"]
    for exp in expected:
        assert exp in names, f"Schema missing {exp}"
        print(f"  [OK] Tool schema registered: {exp}")
    print("Test 8 passed successfully.")


if __name__ == "__main__":
    print("=" * 65)
    print(" STROKE // PRIVATE BACKGROUND TERMINAL SYSTEM TEST SUITE")
    print("=" * 65)
    test_secret_redaction()
    test_command_security_policy()
    test_session_lifecycle_and_tools()
    test_directory_traversal_prevention()
    test_timeouts_and_cancellation()
    test_approval_workflow()
    test_coding_loop_background_terminal_checks()
    test_tools_schema()
    print("\n" + "=" * 65)
    print(" ALL 8 PRIVATE INTERNAL TERMINAL SUITES PASSED CLEANLY!")
    print("=" * 65)
