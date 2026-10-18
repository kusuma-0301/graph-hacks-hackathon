from app.db import get_graph

graph = get_graph()

# Test 1: plain query
res1 = graph.query("MATCH (s:System {id: 'sys-payments'}) RETURN s.id, s.name")
print("Test 1 (direct literal):", res1.result_set)

# Test 2: parameterized query with params argument
try:
    res2 = graph.query("MATCH (s:System) WHERE s.id = $sys_id RETURN s.id, s.name", params={"sys_id": "sys-payments"})
    print("Test 2 (params dict):", res2.result_set)
except Exception as e:
    print("Test 2 error:", e)

# Test 3: without $
try:
    res3 = graph.query("CYPHER sys_id='sys-payments' MATCH (s:System) WHERE s.id = $sys_id RETURN s.id, s.name")
    print("Test 3 (manual header with $):", res3.result_set)
except Exception as e:
    print("Test 3 error:", e)
