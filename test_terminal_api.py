"""
Tests for Stroke Private Terminal REST API endpoints in main.py
"""

import sys
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_terminal_api():
    print("\n--- Testing /terminal REST API Endpoints ---")
    
    # 1. GET /terminal/tools/schema
    res = client.get("/terminal/tools/schema")
    assert res.status_code == 200
    tools = res.json().get("tools", [])
    assert len(tools) == 6
    print(f"  [OK] /terminal/tools/schema returned {len(tools)} tools")

    # 2. POST /terminal/create
    res = client.post("/terminal/create", json={})
    assert res.status_code == 200
    created = res.json()
    session_id = created["session_id"]
    print(f"  [OK] /terminal/create created session: {session_id}")

    # 3. POST /terminal/run
    res = client.post("/terminal/run", json={
        "session_id": session_id,
        "command": "python",
        "args": ["-c", "import sys; print(f'Python API Test {sys.version_info.major}')"]
    })
    assert res.status_code == 200
    run_data = res.json()
    assert run_data["exit_code"] == 0
    assert "Python API Test" in run_data["stdout"]
    print(f"  [OK] /terminal/run executed command successfully: {run_data['stdout'].strip()}")

    # 4. GET /terminal/{session_id}/output
    res = client.get(f"/terminal/{session_id}/output?tail=10")
    assert res.status_code == 200
    out_data = res.json()
    assert "Python API Test" in out_data["output"]
    print(f"  [OK] /terminal/{session_id}/output fetched {out_data['lines_count']} lines")

    # 5. GET /terminal/{session_id}/status
    res = client.get(f"/terminal/{session_id}/status")
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["state"] == "completed"
    print(f"  [OK] /terminal/{session_id}/status state: {status_data['state']}")

    # 6. GET /terminal/list
    res = client.get("/terminal/list")
    assert res.status_code == 200
    term_list = res.json().get("terminals", [])
    assert any(t["session_id"] == session_id for t in term_list)
    print(f"  [OK] /terminal/list found active session in list of {len(term_list)}")

    # 7. Security block on traversal
    res = client.post("/terminal/run", json={
        "session_id": session_id,
        "command": "cd",
        "args": ["/etc"]
    })
    assert res.status_code == 200
    assert res.json()["exit_code"] != 0
    print(f"  [OK] Blocked traversal attempt to /etc")

    # 8. Approval requirement on destructive command
    res = client.post("/terminal/run", json={
        "session_id": session_id,
        "command": "rm",
        "args": ["-rf", "something"]
    })
    assert res.status_code == 200
    appr_data = res.json()
    assert appr_data.get("status") == "requires_approval"
    approval_id = appr_data["approval_id"]
    print(f"  [OK] Destructive command gated by approval: {approval_id}")

    # 9. Respond to approval (Deny)
    res = client.post("/terminal/approval/respond", json={
        "approval_id": approval_id,
        "approved": False
    })
    assert res.status_code == 200
    assert res.json()["status"] == "denied"
    print(f"  [OK] Approval denial recorded successfully")

    # 10. POST /terminal/{session_id}/stop
    res = client.post(f"/terminal/{session_id}/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "terminated"
    print(f"  [OK] Session {session_id} cleanly reaped")

    print("\nALL REST API TESTS PASSED!")

if __name__ == "__main__":
    test_terminal_api()
