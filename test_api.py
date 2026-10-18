import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database_connected"] is True
    assert data["database_graph"] != ""
    assert data["details"]["node_count"] > 0


def test_list_systems():
    response = client.get("/api/systems")
    assert response.status_code == 200
    data = response.json()
    system_names = [s["name"] for s in data["systems"]]
    assert "Payments Service" in system_names
    assert "API Gateway" in system_names
    assert "Analytics Pipeline" in system_names


def test_query_owners_and_experts():
    response = client.post("/api/query/owners-and-experts", json={"system": "Payments Service"})
    assert response.status_code == 200
    data = response.json()
    assert data["system"]["name"] == "Payments Service"

    owner_names = [o["name"] for o in data["owners"]]
    assert "Arjun Rao" in owner_names

    expert_names = [e["name"] for e in data["experts"]]
    assert "Priya Shah" in expert_names
    assert "Noah Williams" in expert_names


def test_query_downstream_dependencies():
    response = client.post("/api/query/downstream-dependencies", json={"system": "Payments Service"})
    assert response.status_code == 200
    data = response.json()
    downstream_names = [d["name"] for d in data["downstream"]]
    assert "Ledger Service" in downstream_names
    assert "Notification Service" in downstream_names

    upstream_names = [u["name"] for u in data["upstream"]]
    assert "API Gateway" in upstream_names


def test_query_decisions_and_sources():
    response = client.post("/api/query/decisions-and-sources", json={"system": "Payments Service"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["decisions"]) >= 2

    dec_titles = [d["title"] for d in data["decisions"]]
    assert any("queue-backed" in t.lower() for t in dec_titles)

    source_ids = [s["id"] for s in data["sources"]]
    assert "doc-001" in source_ids


def test_agent_demo_question():
    demo_q = "Payments is experiencing high latency. Who should investigate, why was our architecture designed this way, and what downstream systems could be affected?"
    response = client.post("/api/agent/query", json={"question": demo_q})
    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == "high"
    assert data["is_uncertain"] is False
    assert len(data["citations"]) > 0

    answer = data["answer"]
    assert "Arjun Rao" in answer
    assert "Priya Shah" in answer
    assert "Ledger Service" in answer


def test_agent_uncertainty_handling():
    uncertain_q = "What is the encryption standard for Quantum Hyperdrive?"
    response = client.post("/api/agent/query", json={"question": uncertain_q})
    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == "uncertain"
    assert data["is_uncertain"] is True
    assert data["uncertainty_reason"] is not None
    assert "could not find verified records" in data["answer"].lower()


def test_graph_overview():
    response = client.get("/api/graph/overview")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) > 0
    assert len(data["edges"]) > 0


def test_proposal_and_approval_workflow():
    # 1. Propose task write
    prop_res = client.post(
        "/api/tasks/propose",
        json={
            "action_type": "create_task",
            "title": "Investigate payment retry queue backlog",
            "description": "Triggered by latency spike alerts in FalkorDB",
            "target_id": "sys-payments",
            "proposed_changes": {
                "task_id": "test-task-latency-001",
                "title": "Investigate payment retry queue backlog",
                "system_id": "sys-payments",
                "assignee_id": "p2",
            },
            "requested_by": "Test Suite Runner",
            "target_name": "Payments Service",
        },
    )
    assert prop_res.status_code == 200
    task_id = prop_res.json()["id"]

    # 2. Check pending
    list_res = client.get("/api/tasks?status_filter=pending_approval")
    assert list_res.status_code == 200
    pending_ids = [t["id"] for t in list_res.json()]
    assert task_id in pending_ids

    # 3. Approve task
    appr_res = client.post(
        "/api/tasks/approve",
        json={
            "task_id": task_id,
            "approved": True,
            "actor": "Incident Commander Maya",
            "reason": "Authorized incident mitigation",
        },
    )
    assert appr_res.status_code == 200
    appr_data = appr_res.json()
    assert appr_data["applied"] is True
    assert appr_data["status"] == "approved"
    assert appr_data["re_queried_state"] is not None


def test_task_deduplication_by_stable_id():
    """Verify tasks associated with a system are deduplicated by stable task ID."""
    response = client.get("/api/system/sys-payments/investigation")
    assert response.status_code == 200
    data = response.json()
    tasks = data["active_tasks"]
    task_ids = [t["id"] for t in tasks]
    # Check that each task ID is unique (no duplicate rows)
    assert len(task_ids) == len(set(task_ids)), f"Duplicate task IDs found: {task_ids}"
    assert "test-task-latency-001" in task_ids
    assert "task-001" in task_ids


def test_demo_placeholder_url_labeling():
    """Verify that example.com URLs are clearly labeled as demo placeholders."""
    response = client.post(
        "/api/agent/query",
        json={"question": "Payments is experiencing high latency. Who should investigate?"},
    )
    assert response.status_code == 200
    data = response.json()
    # Check citations for example.com demo placeholder labeling
    for c in data["citations"]:
        if c.get("url") and "example.com" in c["url"]:
            assert "Demo Placeholder" in c["label"] or "Demo Placeholder" in c["detail"]

    # Check answer text explicitly mentions demo placeholders
    assert "demo placeholder" in data["answer"].lower()


def test_citations_correspond_to_evidence_records():
    """Verify every citation in the API response corresponds to an actual evidence record."""
    response = client.post(
        "/api/agent/query",
        json={"question": "Payments is experiencing high latency. Who should investigate, why was our architecture designed this way, and what downstream systems could be affected?"},
    )
    assert response.status_code == 200
    data = response.json()
    citations = data["citations"]
    summary = data["evidence_summary"]

    assert len(citations) == 10

    # Build known IDs from evidence summary
    owner_ids = {f"person-{o['id']}" for o in summary.get("owners", [])}
    expert_ids = {f"expert-{e['id']}" for e in summary.get("experts", [])}
    dec_ids = {d["id"] for d in summary.get("decisions", [])}
    source_ids = {s["id"] for s in summary.get("sources", [])}
    dep_ids = {f"dep-{d['id']}" for d in summary.get("downstream_dependencies", [])}

    all_evidence_ids = owner_ids | expert_ids | dec_ids | source_ids | dep_ids

    for c in citations:
        cid = c["citation_id"]
        assert cid in all_evidence_ids, f"Citation {cid} has no corresponding record in evidence_summary"


def test_distinct_queries_trigger_specific_retrieval_and_differing_answers():
    """Verify that different questions trigger relevant retrieval and produce distinct, grounded answers."""
    # 1. Who owns the Payments Service?
    res_pay_owner = client.post("/api/agent/query", json={"question": "Who owns the Payments Service?"})
    assert res_pay_owner.status_code == 200
    data_pay_owner = res_pay_owner.json()
    assert data_pay_owner["is_uncertain"] is False
    assert "Arjun Rao" in data_pay_owner["answer"]
    pay_owner_cids = {c["citation_id"] for c in data_pay_owner["citations"]}
    assert "person-p2" in pay_owner_cids
    assert "person-p1" not in pay_owner_cids
    assert "dec-002" not in pay_owner_cids

    # 2. Why was the queue-backed payment workflow adopted?
    res_rationale = client.post("/api/agent/query", json={"question": "Why was the queue-backed payment workflow adopted?"})
    assert res_rationale.status_code == 200
    data_rationale = res_rationale.json()
    assert data_rationale["is_uncertain"] is False
    assert "dec-002" in data_rationale["answer"] or "queue-backed" in data_rationale["answer"].lower()
    rationale_cids = {c["citation_id"] for c in data_rationale["citations"]}
    assert "dec-002" in rationale_cids
    assert "dec-001" in rationale_cids
    assert "doc-001" in rationale_cids
    assert "person-p1" not in rationale_cids

    # 3. What systems could be affected if the Payments Service goes down?
    res_deps = client.post("/api/agent/query", json={"question": "What systems could be affected if the Payments Service goes down?"})
    assert res_deps.status_code == 200
    data_deps = res_deps.json()
    assert data_deps["is_uncertain"] is False
    assert "Ledger Service" in data_deps["answer"]
    assert "Notification Service" in data_deps["answer"]
    deps_cids = {c["citation_id"] for c in data_deps["citations"]}
    assert "dep-sys-ledger" in deps_cids
    assert "dep-sys-notify" in deps_cids
    assert "dec-002" not in deps_cids

    # 4. Who owns the API Gateway?
    res_api_owner = client.post("/api/agent/query", json={"question": "Who owns the API Gateway?"})
    assert res_api_owner.status_code == 200
    data_api_owner = res_api_owner.json()
    assert data_api_owner["is_uncertain"] is False
    assert "Maya Chen" in data_api_owner["answer"]
    assert "Arjun Rao" not in data_api_owner["answer"]
    api_owner_cids = {c["citation_id"] for c in data_api_owner["citations"]}
    assert "person-p1" in api_owner_cids
    assert "person-p2" not in api_owner_cids
    assert "dec-002" not in api_owner_cids

    # Verify answers differ across different questions
    answers = [
        data_pay_owner["answer"],
        data_rationale["answer"],
        data_deps["answer"],
        data_api_owner["answer"],
    ]
    assert len(set(answers)) == 4, "Expected all 4 questions to have distinct grounded answers"
    assert pay_owner_cids != api_owner_cids, "Owners of Payments and API Gateway must have different citation sets"


def test_unknown_topics_return_clear_uncertainty_without_hallucinating():
    """Verify that ungrounded queries return explicit uncertainty refusal without inventing facts."""
    for q in ["Who owns the Inventory Service?", "Why was GraphQL adopted?"]:
        res = client.post("/api/agent/query", json={"question": q})
        assert res.status_code == 200
        data = res.json()
        assert data["is_uncertain"] is True
        assert len(data["citations"]) == 0
        assert "could not find verified records" in data["answer"].lower()


