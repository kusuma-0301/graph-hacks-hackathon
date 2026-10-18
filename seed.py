
from app.db import get_graph


def seed_database():
    graph = get_graph()

    # Clear existing demo data so rerunning the seed is safe.
    graph.query("MATCH (n) DETACH DELETE n")

    # Create teams and people.
    graph.query("""
    CREATE
      (platform:Team {id: 'team-platform', name: 'Platform Engineering'}),
      (payments:Team {id: 'team-payments', name: 'Payments'}),
      (data:Team {id: 'team-data', name: 'Data Engineering'}),
      (security:Team {id: 'team-security', name: 'Security'})
    """)

    graph.query("""
    CREATE
      (maya:Person {id: 'p1', name: 'Maya Chen', role: 'Platform Lead'}),
      (arjun:Person {id: 'p2', name: 'Arjun Rao', role: 'Payments Engineer'}),
      (priya:Person {id: 'p3', name: 'Priya Shah', role: 'Distributed Systems Expert'}),
      (noah:Person {id: 'p4', name: 'Noah Williams', role: 'SRE'}),
      (lena:Person {id: 'p5', name: 'Lena Ortiz', role: 'Security Engineer'}),
      (omar:Person {id: 'p6', name: 'Omar Ali', role: 'Data Engineer'})
    """)

    # Assign people to teams.
    graph.query("""
    MATCH (p:Person {id: 'p1'}), (t:Team {id: 'team-platform'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p2'}), (t:Team {id: 'team-payments'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p3'}), (t:Team {id: 'team-platform'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p4'}), (t:Team {id: 'team-platform'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p5'}), (t:Team {id: 'team-security'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p6'}), (t:Team {id: 'team-data'})
    CREATE (p)-[:MEMBER_OF]->(t)
    """)

    # Create systems and projects.
    graph.query("""
    CREATE
      (:System {id: 'sys-payments', name: 'Payments Service'}),
      (:System {id: 'sys-api', name: 'API Gateway'}),
      (:System {id: 'sys-ledger', name: 'Ledger Service'}),
      (:System {id: 'sys-notify', name: 'Notification Service'}),
      (:System {id: 'sys-analytics', name: 'Analytics Pipeline'})
    """)

    graph.query("""
    CREATE
      (:Project {id: 'proj-reliability', name: 'Payments Reliability'}),
      (:Project {id: 'proj-modernization', name: 'Platform Modernization'}),
      (:Project {id: 'proj-observability', name: 'Observability Upgrade'})
    """)

    # Ownership and expertise.
    graph.query("""
    MATCH (p:Person {id: 'p2'}), (s:System {id: 'sys-payments'})
    CREATE (p)-[:OWNS]->(s)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p1'}), (s:System {id: 'sys-api'})
    CREATE (p)-[:OWNS]->(s)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p3'}), (s:System {id: 'sys-payments'})
    CREATE (p)-[:KNOWS_ABOUT]->(s)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p4'}), (s:System {id: 'sys-payments'})
    CREATE (p)-[:KNOWS_ABOUT]->(s)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p6'}), (s:System {id: 'sys-analytics'})
    CREATE (p)-[:OWNS]->(s)
    """)

    # System dependencies.
    graph.query("""
    MATCH (a:System {id: 'sys-api'}), (b:System {id: 'sys-payments'})
    CREATE (a)-[:DEPENDS_ON]->(b)
    """)
    graph.query("""
    MATCH (a:System {id: 'sys-payments'}), (b:System {id: 'sys-ledger'})
    CREATE (a)-[:DEPENDS_ON]->(b)
    """)
    graph.query("""
    MATCH (a:System {id: 'sys-payments'}), (b:System {id: 'sys-notify'})
    CREATE (a)-[:DEPENDS_ON]->(b)
    """)
    graph.query("""
    MATCH (a:System {id: 'sys-ledger'}), (b:System {id: 'sys-analytics'})
    CREATE (a)-[:DEPENDS_ON]->(b)
    """)

    # Architecture decisions, with a superseding decision.
    graph.query("""
    CREATE
      (d1:Decision {
        id: 'dec-001',
        title: 'Use asynchronous payment processing',
        status: 'superseded',
        detail: 'The original design used a synchronous request path.'
      }),
      (d2:Decision {
        id: 'dec-002',
        title: 'Adopt a queue-backed payment workflow',
        status: 'current',
        detail: 'Payment requests enter a queue before ledger processing.'
      })
    """)

    graph.query("""
    MATCH (p:Person {id: 'p3'}), (d:Decision {id: 'dec-002'})
    CREATE (p)-[:MADE]->(d)
    """)
    graph.query("""
    MATCH (p:Person {id: 'p2'}), (d:Decision {id: 'dec-002'})
    CREATE (p)-[:SUPPORTED_BY]->(d)
    """)
    graph.query("""
    MATCH (old:Decision {id: 'dec-001'}), (new:Decision {id: 'dec-002'})
    CREATE (new)-[:SUPERSEDES]->(old)
    """)

    # Source records.
    graph.query("""
    CREATE
      (:Document {
        id: 'doc-001',
        title: 'Payment Architecture Proposal',
        url: 'https://example.com/docs/payment-architecture',
        content: 'Proposal for queue-backed asynchronous payment processing.'
      }),
      (:Message {
        id: 'msg-001',
        title: 'Architecture Review Discussion',
        url: 'https://example.com/messages/architecture-review',
        content: 'Priya recommended queue-backed processing to reduce request latency.'
      }),
      (:Ticket {
        id: 'ticket-001',
        title: 'Investigate elevated payment latency',
        url: 'https://example.com/tickets/INC-101',
        content: 'Investigate latency across payment processing and downstream dependencies.'
      }),
      (:Document {
        id: 'doc-002',
        title: 'Ledger Dependency Notes',
        url: 'https://example.com/docs/ledger-dependencies',
        content: 'Payments Service sends transaction data to Ledger Service.'
      })
    """)

    graph.query("""
    MATCH (d:Decision {id: 'dec-002'}), (doc:Document {id: 'doc-001'})
    CREATE (d)-[:SUPPORTED_BY]->(doc)
    """)
    graph.query("""
    MATCH (d:Decision {id: 'dec-002'}), (m:Message {id: 'msg-001'})
    CREATE (d)-[:SUPPORTED_BY]->(m)
    """)
    graph.query("""
    MATCH (s:System {id: 'sys-ledger'}), (doc:Document {id: 'doc-002'})
    CREATE (s)-[:ABOUT]->(doc)
    """)

    # Tasks.
    graph.query("""
    CREATE
      (:Task {id: 'task-001', title: 'Review payment queue latency', status: 'open'}),
      (:Task {id: 'task-002', title: 'Check ledger processing time', status: 'open'}),
      (:Task {id: 'task-003', title: 'Review notification backlog', status: 'open'}),
      (:Task {id: 'task-004', title: 'Verify API gateway metrics', status: 'open'})
    """)

    graph.query("""
    MATCH (p:Person {id: 'p2'}), (t:Task {id: 'task-001'})
    CREATE (p)-[:OWNS]->(t)
    """)
    graph.query("""
    MATCH (s:System {id: 'sys-payments'}), (t:Task {id: 'task-001'})
    CREATE (t)-[:ABOUT]->(s)
    """)

    print("Company Brain demo data seeded successfully!")


if __name__ == "__main__":
    seed_database()
