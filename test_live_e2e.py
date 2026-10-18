import httpx
import json

BASE_URL = "http://127.0.0.1:8000"

def verify_agent_inquiry():
    question = "Payments is experiencing high latency. Who should investigate, why was our architecture designed this way, and what downstream systems could be affected?"
    print(f"--- Querying Agent: '{question}' ---")
    
    response = httpx.post(
        f"{BASE_URL}/api/agent/query",
        json={"question": question},
        timeout=15.0
    )
    assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"
    data = response.json()
    
    print("\n[AGENT RESPONSE STATUS]")
    print(f"Confidence: {data['confidence']}")
    print(f"Is Uncertain: {data['is_uncertain']}")
    print(f"Total Citations: {len(data['citations'])}")
    
    print("\n[CITATIONS RETRIEVED FROM FALKORDB]")
    for c in data['citations']:
        url_part = f" ({c['url']})" if c.get('url') else ""
        print(f"  * [{c['source_type']}] {c['citation_id']}: {c['label']} -> {c['detail']}{url_part}")
        
    print("\n[ANSWER SNIPPET]")
    print(data['answer'])
    
    # Assertions on real FalkorDB evidence
    answer = data['answer']
    assert "Arjun Rao" in answer, "Missing Arjun Rao (Payments owner)"
    assert "Priya Shah" in answer, "Missing Priya Shah (Architecture expert)"
    assert "dec-002" in str(data['citations']), "Missing dec-002 citation"
    assert "doc-001" in str(data['citations']), "Missing doc-001 citation"
    assert "sys-ledger" in str(data['evidence_summary']), "Missing Ledger Service dependency"
    assert "sys-notify" in str(data['evidence_summary']), "Missing Notification Service dependency"

    # Verify task deduplication: test-task-latency-001 should appear at most once
    assert answer.count("test-task-latency-001") <= 1, f"Task test-task-latency-001 repeated in answer: {answer}"

    # Verify demo placeholder URLs are explicitly labeled
    assert "demo placeholder" in answer.lower(), "Missing demo placeholder label in answer"

    # Verify 10 citations correspond to actual evidence records
    assert len(data['citations']) == 10, f"Expected 10 citations, got {len(data['citations'])}"

    print("\nAll live FalkorDB evidence assertions PASSED!")

if __name__ == "__main__":
    verify_agent_inquiry()
