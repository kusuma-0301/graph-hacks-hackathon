import httpx

BASE_URL = "http://127.0.0.1:8000"

def verify_proposal_approval_flow():
    print("--- 1. Testing GET /api/tasks ---")
    r1 = httpx.get(f"{BASE_URL}/api/tasks?status_filter=pending_approval")
    assert r1.status_code == 200, f"Failed GET tasks: {r1.text}"
    pending = r1.json()
    print(f"Found {len(pending)} pending proposals initially.")

    print("\n--- 2. Testing POST /api/tasks/propose ---")
    prop_payload = {
        "action_type": "create_task",
        "title": "Automated Incident Verification Task",
        "description": "Triggered by end-to-end verification suite",
        "target_id": "sys-payments",
        "proposed_changes": {
            "task_id": "task-live-e2e-001",
            "title": "Automated Incident Verification Task",
            "system_id": "sys-payments",
            "assignee_id": "p2"
        },
        "requested_by": "Test Engineer",
        "target_name": "Payments Service"
    }
    r2 = httpx.post(f"{BASE_URL}/api/tasks/propose", json=prop_payload)
    assert r2.status_code == 200, f"Failed propose: {r2.text}"
    task = r2.json()
    task_id = task["id"]
    print(f"Created proposed task with ID: {task_id}")
    assert task["status"] == "pending_approval"

    print("\n--- 3. Testing POST /api/tasks/approve (Approval branch) ---")
    appr_payload = {
        "task_id": task_id,
        "approved": True,
        "actor": "Incident Lead Maya",
        "reason": "Authorized via live e2e verification"
    }
    r3 = httpx.post(f"{BASE_URL}/api/tasks/approve", json=appr_payload)
    assert r3.status_code == 200, f"Failed approve: {r3.text}"
    appr_data = r3.json()
    print("Approval response:", appr_data)
    assert appr_data["applied"] is True
    assert appr_data["status"] == "approved"
    assert appr_data["re_queried_state"] is not None
    print(f"Verified applied state in FalkorDB: {appr_data['re_queried_state']}")

    print("\n--- 4. Testing POST /api/tasks/approve (Rejection branch) ---")
    prop_reject = httpx.post(
        f"{BASE_URL}/api/tasks/propose",
        json={
            "action_type": "update_decision_status",
            "title": "Proposed status deprecation",
            "description": "Proposal meant to be rejected",
            "target_id": "dec-002",
            "proposed_changes": {"decision_id": "dec-002", "new_status": "deprecated"},
            "requested_by": "Test Engineer"
        }
    ).json()
    rej_id = prop_reject["id"]
    
    r4 = httpx.post(
        f"{BASE_URL}/api/tasks/approve",
        json={"task_id": rej_id, "approved": False, "actor": "Auditor", "reason": "Not justified"}
    )
    assert r4.status_code == 200
    rej_data = r4.json()
    print("Rejection response:", rej_data)
    assert rej_data["applied"] is False
    assert rej_data["status"] == "rejected"

    print("\nAll proposal and approval workflow checks PASSED!")

if __name__ == "__main__":
    verify_proposal_approval_flow()
