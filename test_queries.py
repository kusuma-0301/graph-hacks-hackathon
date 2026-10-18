from app.db import get_graph

graph = get_graph()

def test_queries():
    print("--- 1. Testing Owners and Experts ---")
    q1 = """
    MATCH (s:System)
    WHERE s.id = $id OR toLower(s.name) = toLower($name)
    OPTIONAL MATCH (owner:Person)-[:OWNS]->(s)
    OPTIONAL MATCH (owner)-[:MEMBER_OF]->(ot:Team)
    OPTIONAL MATCH (expert:Person)-[:KNOWS_ABOUT]->(s)
    OPTIONAL MATCH (expert)-[:MEMBER_OF]->(et:Team)
    RETURN s.id, s.name, owner.id, owner.name, owner.role, ot.name, expert.id, expert.name, expert.role, et.name
    """
    res1 = graph.query(q1, params={"id": "sys-payments", "name": "Payments Service"})
    print("Res1 (rows):", len(res1.result_set))
    for row in res1.result_set:
        print(" ", row)

    print("\n--- 2. Testing Dependencies ---")
    q2_down = """
    MATCH (s:System)-[:DEPENDS_ON]->(d:System)
    WHERE s.id = $id OR toLower(s.name) = toLower($name)
    RETURN s.name, d.id, d.name
    """
    res2_down = graph.query(q2_down, params={"id": "sys-payments", "name": "Payments Service"})
    print("Downstream direct:", res2_down.result_set)

    q2_down_transitive = """
    MATCH path = (s:System)-[:DEPENDS_ON*1..3]->(d:System)
    WHERE s.id = $id OR toLower(s.name) = toLower($name)
    RETURN [n IN nodes(path) | n.name] AS path_names, length(path) AS depth
    """
    res2_trans = graph.query(q2_down_transitive, params={"id": "sys-payments", "name": "Payments Service"})
    print("Downstream transitive:", res2_trans.result_set)

    q2_up = """
    MATCH (u:System)-[:DEPENDS_ON]->(s:System)
    WHERE s.id = $id OR toLower(s.name) = toLower($name)
    RETURN u.id, u.name
    """
    res2_up = graph.query(q2_up, params={"id": "sys-payments", "name": "Payments Service"})
    print("Upstream callers:", res2_up.result_set)

    print("\n--- 3. Testing Decisions & Sources ---")
    q3 = """
    MATCH (d:Decision)
    OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
    OPTIONAL MATCH (supporter:Person)-[:SUPPORTED_BY]->(d)
    OPTIONAL MATCH (d)-[:SUPERSEDES]->(old_d:Decision)
    OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(source)
    RETURN d.id, d.title, d.status, d.detail, maker.name, supporter.name, old_d.id, labels(source), source.id, source.title, source.url
    """
    res3 = graph.query(q3)
    print("Decisions count:", len(res3.result_set))
    for row in res3.result_set:
        print(" ", row)

if __name__ == "__main__":
    test_queries()
