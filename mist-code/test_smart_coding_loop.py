"""
================================================================================
STROKE // TEST SMART CODING LOOP SUITE
Validates the rebuilt 10-stage Smart Coding Workflow:
  1. Understand the user's actual goal.
  2. Inspect the relevant project files & record baseline SHA-256.
  3. Create an implementation plan.
  4. Make controlled code changes (pre-modification backups, conflict checks).
  5. Run appropriate tests (Roblox Luau AST & Python compiler).
  6. Read actual error output.
  7. Fix failures (targeted self-healing loop).
  8. Re-run tests (StateLedger evidence).
  9. Review its own changes (ChangeReviewer).
  10. Report what genuinely succeeded (Zero false claims).
Guarantees:
  - Infinite loops prevented.
  - Repeated failed edits prevented.
  - Fabricated success messages prevented.
  - Unnecessary file modifications prevented.
  - User changes preserved (conflict detection).
  - Never deletes project files automatically (No-Delete policy).
================================================================================
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import workspace_service
import backup_service
from coding_loop import (
    GoalUnderstandingEngine,
    ProjectInspectionEngine,
    SmartImplementationPlanner,
    ControlledChangeManager,
    ChangeReviewer,
    StrokeCodingLoop,
    SmartCodingWorkflowResult,
    RobloxDomainTestRunner,
    ErrorAnalyser,
    StateLedger
)


class TestSmartCodingLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = self.temp_dir.name
        workspace_service.approve_workspace(self.workspace_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_stage_1_goal_understanding_detects_language_files_requirements(self):
        """Stage 1: Correctly parses user goal, referenced files, language, and explicit requirements."""
        prompt = (
            "Create a server combat hitbox in hitboxes/sword.luau with spatial query "
            "and multi-hit debounce protection. Do not delete existing files."
        )
        spec = GoalUnderstandingEngine.analyze_goal(prompt, target_file="hitboxes/sword.luau")
        self.assertEqual(spec.target_language, "luau")
        self.assertEqual(spec.detected_framework, "roblox_luau")
        self.assertIn("hitboxes/sword.luau", spec.target_files)
        self.assertTrue(any("debounce" in req.lower() for req in spec.explicit_requirements))
        self.assertTrue(any("spatial" in req.lower() for req in spec.explicit_requirements))
        self.assertTrue(any("delete" in req.lower() for req in spec.explicit_requirements))
        self.assertIn("combat hitbox", spec.primary_objective.lower())

    def test_02_stage_2_project_inspection_and_baseline_sha256(self):
        """Stage 2: Inspects existing files in workspace and records baseline SHA-256 for conflict detection."""
        ws = Path(self.workspace_path)
        existing_file = ws / "helper.py"
        content = "def calculate_speed(distance, time_s):\n    return distance / max(1, time_s)\n"
        existing_file.write_text(content, encoding="utf-8")

        prompt = "Modify helper.py to add acceleration calculation"
        spec = GoalUnderstandingEngine.analyze_goal(prompt, target_file="helper.py")
        inspected = ProjectInspectionEngine.inspect_workspace(self.workspace_path, spec)

        self.assertEqual(len(inspected), 1)
        self.assertEqual(inspected[0].relative_path, "helper.py")
        self.assertEqual(inspected[0].language, "python")
        self.assertTrue(len(inspected[0].initial_sha256) > 20)
        self.assertIn("calculate_speed", inspected[0].symbols)

    def test_03_stage_3_smart_implementation_plan_bounds_modifications(self):
        """Stage 3: Creates a structured plan that strictly bounds files to modify and create."""
        ws = Path(self.workspace_path)
        existing_file = ws / "main_game.luau"
        existing_file.write_text("local Players = game:GetService('Players')\n", encoding="utf-8")

        spec = GoalUnderstandingEngine.analyze_goal("Update main_game.luau and create combat.luau")
        inspected = ProjectInspectionEngine.inspect_workspace(self.workspace_path, spec)
        plan = SmartImplementationPlanner.create_plan(spec, inspected)

        self.assertIn("main_game.luau", plan.target_files_to_modify)
        self.assertIn("combat.luau", plan.target_files_to_create)
        self.assertTrue(len(plan.implementation_steps) >= 3)
        self.assertIn("Zero deletions", plan.risk_mitigation)

    def test_04_stage_4_controlled_changes_preserves_user_changes_on_conflict(self):
        """Stage 4: Detects external user modification conflicts and halts to protect user work."""
        ws = Path(self.workspace_path)
        target = ws / "config.py"
        target.write_text("MAX_PLAYERS = 10\n", encoding="utf-8")
        original_sha = backup_service.compute_file_sha256(target)

        # Simulate user editing the file externally while Stroke was planning
        target.write_text("MAX_PLAYERS = 20  # user customized\n", encoding="utf-8")

        # Stroke attempts to apply change expecting original_sha
        res = ControlledChangeManager.apply_change(
            workspace_path=self.workspace_path,
            relative_path="config.py",
            new_content="MAX_PLAYERS = 50\n",
            expected_initial_sha256=original_sha
        )

        self.assertEqual(res.action, "conflict")
        self.assertIn("User modification conflict", res.error)
        # Verify user's external edit was NOT overwritten
        self.assertIn("user customized", target.read_text(encoding="utf-8"))

    def test_05_stage_4_atomic_write_creates_pre_modification_backup(self):
        """Stage 4: Automatically creates timestamped pre-modification backup before writing."""
        ws = Path(self.workspace_path)
        target = ws / "logic.py"
        target.write_text("val = 1\n", encoding="utf-8")
        current_sha = backup_service.compute_file_sha256(target)

        res = ControlledChangeManager.apply_change(
            workspace_path=self.workspace_path,
            relative_path="logic.py",
            new_content="val = 2\n",
            expected_initial_sha256=current_sha
        )

        self.assertEqual(res.action, "modified")
        self.assertIsNotNone(res.backup_path)
        self.assertTrue(os.path.exists(res.backup_path))
        # Backup content must equal original content
        with open(res.backup_path, "r", encoding="utf-8") as bf:
            self.assertEqual(bf.read(), "val = 1\n")

    def test_06_stage_4_avoids_unnecessary_modifications_when_content_identical(self):
        """Stage 4: Avoids unnecessary file modification if proposed content is already identical."""
        ws = Path(self.workspace_path)
        target = ws / "same.py"
        target.write_text("def ping(): return 'pong'\n", encoding="utf-8")
        sha = backup_service.compute_file_sha256(target)

        res = ControlledChangeManager.apply_change(
            workspace_path=self.workspace_path,
            relative_path="same.py",
            new_content="def ping(): return 'pong'\n",
            expected_initial_sha256=sha
        )

        self.assertEqual(res.action, "skipped")
        self.assertIn("identical", res.diff)

    def test_07_stage_5_and_6_runs_tests_and_reads_actual_compiler_errors(self):
        """Stage 5 & 6: Runs compiler checks and extracts real compiler error lines and suggestions."""
        # Deliberate syntax error in Python
        broken_code = "def syntax_fail():\n    if True\n        return False\n"
        rep = RobloxDomainTestRunner.test_python_code(broken_code)

        self.assertFalse(rep["is_verified"])
        self.assertEqual(rep["syntax_status"], "FAIL")
        errors = [f for f in rep["failed_checks"] if f.get("type") == "error"]
        self.assertTrue(len(errors) >= 1)
        self.assertEqual(errors[0]["line"], 2)
        self.assertIn("SyntaxError", errors[0]["message"])

        # ErrorAnalyser synthesizes targeted correction prompt
        prompt = ErrorAnalyser.build_correction_prompt(broken_code, rep["failed_checks"], language="python")
        self.assertIn("SyntaxError", prompt)
        self.assertIn("line 2", prompt.lower())

    def test_08_stage_7_and_8_self_healing_fixes_failure_and_retests(self):
        """Stage 7 & 8: Self-healing loop fixes compiler failure, re-runs tests, and updates ledger."""
        broken_draft = "```python\ndef run_task():\n    await fetch_data()\n```"
        clean_fix = "```python\nasync def run_task():\n    await fetch_data()\n    return True\n```"

        repair_calls = []
        def mock_llm_fixer(messages):
            repair_calls.append(messages)
            return clean_fix

        result = StrokeCodingLoop.run_smart_coding_workflow(
            prompt="Write an async function run_task",
            workspace_path=self.workspace_path,
            initial_reply=broken_draft,
            llm_generate_fn=mock_llm_fixer,
            max_iterations=5
        )

        self.assertTrue(result.success)
        self.assertTrue(result.test_report["is_verified"])
        self.assertEqual(result.test_report["syntax_status"], "PASS")
        self.assertEqual(len(repair_calls), 1)
        self.assertIn("async def run_task", result.final_reply)

    def test_09_stage_9_change_reviewer_approves_clean_bounded_changes(self):
        """Stage 9: Reviewer approves changes matching plan without unnecessary file modifications."""
        spec = GoalUnderstandingEngine.analyze_goal("Implement hitboxes/blade.luau")
        plan = SmartImplementationPlanner.create_plan(spec, [])
        edits = [
            ControlledChangeManager.apply_change(
                workspace_path=self.workspace_path,
                relative_path="hitboxes/blade.luau",
                new_content="-- Blade logic\nreturn {}\n"
            )
        ]
        test_report = {
            "is_verified": True,
            "static_status": "PASS",
            "failed_checks": []
        }

        review = ChangeReviewer.review_changes(spec, plan, edits, test_report)
        self.assertEqual(review["verdict"], "APPROVED")
        self.assertTrue(review["approved"])
        self.assertEqual(len(review["unplanned_files"]), 0)

    def test_10_stage_9_change_reviewer_rejects_unplanned_file_modifications(self):
        """Stage 9: Reviewer rejects changes if unnecessary files outside the plan were touched."""
        spec = GoalUnderstandingEngine.analyze_goal("Implement server/auth.luau")
        plan = SmartImplementationPlanner.create_plan(spec, [])
        # Simulated edit modifying an unrelated file
        edits = [
            ControlledChangeManager.apply_change(
                workspace_path=self.workspace_path,
                relative_path="unrelated/deleted_settings.json",
                new_content="{\"hacked\": true}"
            )
        ]
        test_report = {"is_verified": True, "static_status": "PASS", "failed_checks": []}

        review = ChangeReviewer.review_changes(spec, plan, edits, test_report)
        self.assertEqual(review["verdict"], "CHANGES_REQUESTED")
        self.assertFalse(review["approved"])
        self.assertIn("unrelated/deleted_settings.json", review["unplanned_files"])

    def test_11_stage_10_report_never_fabricates_success(self):
        """Stage 10: Report reports genuine evidence and never claims unproven code is verified."""
        # Generic unverified language (e.g. C++)
        result = StrokeCodingLoop.run_smart_coding_workflow(
            prompt="Write a C++ sorting function",
            initial_reply="```cpp\n#include <iostream>\nint main() { return 0; }\n```",
            workspace_path=self.workspace_path,
            max_iterations=1
        )

        self.assertFalse(result.test_report["is_verified"])
        self.assertEqual(result.test_report["verification_status"], "UNVERIFIED")
        # Markdown report must state UNVERIFIED and never fake VERIFIED badge
        self.assertIn("UNVERIFIED", result.markdown_report)
        self.assertNotIn("`VERIFIED`", result.markdown_report)

    def test_12_infinite_loop_prevention_on_repeated_identical_edits(self):
        """Loop Guard: Halts when model generates identical code repeatedly without spinning infinitely."""
        stuck_draft = "```python\ndef loop_forever():\n    if True\n```"

        attempts = {"count": 0}
        def repeating_broken_llm(messages):
            attempts["count"] += 1
            # Model repeats the exact same broken code
            return stuck_draft

        result = StrokeCodingLoop.run_smart_coding_workflow(
            prompt="Fix loop_forever",
            workspace_path=self.workspace_path,
            initial_reply=stuck_draft,
            llm_generate_fn=repeating_broken_llm,
            max_iterations=10
        )

        # Must have halted early (far below 10 iterations) due to identical code repetition guard
        self.assertLess(attempts["count"], 5)
        self.assertFalse(result.success)
        halt_stages = [s for s in result.stages_executed if "identical code previously seen" in s.get("detail", "")]
        self.assertTrue(len(halt_stages) >= 1)

    def test_13_no_delete_policy_preserves_all_project_files(self):
        """No-Delete Policy: Project files are never deleted by the coding loop."""
        ws = Path(self.workspace_path)
        precious_file = ws / "precious_data.json"
        precious_file.write_text("{\"important\": true}\n", encoding="utf-8")

        prompt = "Refactor everything in the project"
        result = StrokeCodingLoop.run_smart_coding_workflow(
            prompt=prompt,
            workspace_path=self.workspace_path,
            initial_reply="```python\ndef refactored(): return True\n```"
        )

        # Precious file must still exist untouched
        self.assertTrue(precious_file.exists())
        self.assertEqual(precious_file.read_text(encoding="utf-8"), "{\"important\": true}\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
