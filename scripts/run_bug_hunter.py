#!/usr/bin/env python3
"""
Stroke AI // Automated Bug-Hunting & Diagnostic CLI
Runs complete subsystem verification, discovers tests, executes test suites,
probes API endpoints, audits security and permissions, and generates docs/STROKE_TEST_REPORT.md.
"""

import os
import sys
from pathlib import Path

# Ensure root dir is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import argparse
from bug_hunter_service import StrokeBugHunter


def main():
    parser = argparse.ArgumentParser(description="Stroke Bug Hunter Diagnostic CLI")
    parser.add_argument("--workspace", default=str(ROOT_DIR), help="Target project workspace")
    parser.add_argument("--fast", action="store_true", help="Fast diagnostics only (skips full pytest/vitest run)")
    args = parser.parse_args()

    print("=" * 70)
    print("STROKE // AUTOMATED BUG-HUNTING & SYSTEM DIAGNOSTICS")
    print("=" * 70)
    print(f"Workspace: {args.workspace}")
    print(f"Mode: {'Fast Diagnostics' if args.fast else 'Full Test Suite + Diagnostics'}")
    print("-" * 70)

    hunter = StrokeBugHunter(args.workspace)
    report = hunter.hunt_bugs(run_full_tests=not args.fast)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)
    print(f"Report ID:        {report.report_id}")
    print(f"Duration:         {report.duration_ms} ms")
    print(f"Total Issues:     {report.total_issues}")
    print(f"Critical Issues:  {report.critical_count}")
    print(f"High Issues:      {report.high_count}")
    print(f"Medium Issues:    {report.medium_count}")
    print(f"Low Issues:       {report.low_count}")
    print("-" * 70)
    print(f"Backend Pytest:   {report.test_summary.get('backend_passed', 0)} passed, {report.test_summary.get('backend_failed', 0)} failed, {report.test_summary.get('backend_skipped', 0)} skipped")
    print(f"Frontend Vitest:  {report.test_summary.get('frontend_passed', 0)} passed, {report.test_summary.get('frontend_failed', 0)} failed, {report.test_summary.get('frontend_skipped', 0)} skipped")
    print(f"API Probes:       {report.test_summary.get('api_probes_passed', 0)} / {report.test_summary.get('api_probes_total', 0)} passed")
    print(f"Broken Imports:   {report.test_summary.get('broken_imports', 0)}")
    print(f"Report File:      {hunter.docs_file}")
    print("=" * 70)

    if report.critical_count > 0 or report.high_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
