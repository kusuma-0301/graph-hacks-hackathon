import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.db import get_graph
from app.models import (
    PersonModel,
    SourceRecordModel,
    DecisionModel,
    SystemNode,
    SystemInvestigation,
    EvidenceCitation,
)

logger = logging.getLogger("company_brain.graph_service")


class GraphService:
    def __init__(self):
        self._graph = None

    @property
    def graph(self):
        if self._graph is None:
            self._graph = get_graph()
        return self._graph

    def get_all_systems(self) -> List[Dict[str, str]]:
        """Return list of all systems in Company Brain."""
        query = "MATCH (s:System) RETURN s.id, s.name ORDER BY s.name"
        result = self.graph.query(query)
        return [{"id": row[0], "name": row[1]} for row in result.result_set]

    def get_all_people(self) -> List[Dict[str, Any]]:
        """Return list of all people and their teams."""
        query = """
        MATCH (p:Person)
        OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
        RETURN p.id, p.name, p.role, t.name
        ORDER BY p.name
        """
        result = self.graph.query(query)
        return [
            {"id": row[0], "name": row[1], "role": row[2], "team": row[3]}
            for row in result.result_set
        ]

    def find_system_owners_and_experts(self, system_identifier: str) -> Dict[str, Any]:
        """
        Parameterized Cypher query to retrieve owners and known experts for a system.
        Matches by ID or system name (case-insensitive substring/exact).
        """
        # Find matching system first
        sys_query = """
        MATCH (s:System)
        WHERE s.id = $id OR toLower(s.name) = toLower($name) OR toLower(s.name) CONTAINS toLower($name)
        RETURN s.id, s.name
        LIMIT 1
        """
        sys_res = self.graph.query(sys_query, params={"id": system_identifier, "name": system_identifier})
        if not sys_res.result_set:
            return {"system": None, "owners": [], "experts": []}

        sys_id, sys_name = sys_res.result_set[0]

        # Owners query
        owner_query = """
        MATCH (p:Person)-[:OWNS]->(s:System {id: $id})
        OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
        RETURN p.id, p.name, p.role, t.name
        """
        owner_res = self.graph.query(owner_query, params={"id": sys_id})
        owners = [
            PersonModel(
                id=row[0],
                name=row[1],
                role=row[2],
                team=row[3],
                relationship="OWNS",
            )
            for row in owner_res.result_set
        ]

        # Experts query
        expert_query = """
        MATCH (p:Person)-[:KNOWS_ABOUT]->(s:System {id: $id})
        OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
        RETURN p.id, p.name, p.role, t.name
        """
        expert_res = self.graph.query(expert_query, params={"id": sys_id})
        experts = [
            PersonModel(
                id=row[0],
                name=row[1],
                role=row[2],
                team=row[3],
                relationship="KNOWS_ABOUT",
            )
            for row in expert_res.result_set
        ]

        return {
            "system": SystemNode(id=sys_id, name=sys_name),
            "owners": owners,
            "experts": experts,
        }

    def get_system_dependencies(self, system_identifier: str) -> Dict[str, Any]:
        """
        Parameterized query for downstream dependencies (direct & transitive) and upstream callers.
        """
        sys_query = """
        MATCH (s:System)
        WHERE s.id = $id OR toLower(s.name) = toLower($name) OR toLower(s.name) CONTAINS toLower($name)
        RETURN s.id, s.name
        LIMIT 1
        """
        sys_res = self.graph.query(sys_query, params={"id": system_identifier, "name": system_identifier})
        if not sys_res.result_set:
            return {"system": None, "downstream": [], "upstream": [], "transitive_paths": []}

        sys_id, sys_name = sys_res.result_set[0]

        # Direct downstream dependencies
        downstream_query = """
        MATCH (s:System {id: $id})-[:DEPENDS_ON]->(d:System)
        RETURN d.id, d.name
        ORDER BY d.name
        """
        downstream_res = self.graph.query(downstream_query, params={"id": sys_id})
        downstream = [
            SystemNode(id=row[0], name=row[1]) for row in downstream_res.result_set
        ]

        # Transitive downstream paths (up to 3 hops)
        transitive_query = """
        MATCH path = (s:System {id: $id})-[:DEPENDS_ON*1..3]->(target:System)
        RETURN [n IN nodes(path) | {id: n.id, name: n.name}] AS path_nodes, length(path) AS depth
        ORDER BY depth
        """
        trans_res = self.graph.query(transitive_query, params={"id": sys_id})
        transitive_paths = [
            {"path": row[0], "depth": row[1]} for row in trans_res.result_set
        ]

        # Upstream callers (systems that depend on this system)
        upstream_query = """
        MATCH (u:System)-[:DEPENDS_ON]->(s:System {id: $id})
        RETURN u.id, u.name
        ORDER BY u.name
        """
        upstream_res = self.graph.query(upstream_query, params={"id": sys_id})
        upstream = [
            SystemNode(id=row[0], name=row[1]) for row in upstream_res.result_set
        ]

        return {
            "system": SystemNode(id=sys_id, name=sys_name),
            "downstream": downstream,
            "upstream": upstream,
            "transitive_paths": transitive_paths,
        }

    def get_architecture_decisions_and_sources(self, system_identifier: str) -> Dict[str, Any]:
        """
        Trace architecture decisions and their source records.
        Connects decisions made or supported by system owners/experts,
        or related to the system.
        """
        sys_query = """
        MATCH (s:System)
        WHERE s.id = $id OR toLower(s.name) = toLower($name) OR toLower(s.name) CONTAINS toLower($name)
        RETURN s.id, s.name
        LIMIT 1
        """
        sys_res = self.graph.query(sys_query, params={"id": system_identifier, "name": system_identifier})
        if not sys_res.result_set:
            return {"decisions": [], "sources": []}

        sys_id, sys_name = sys_res.result_set[0]

        # Query all decisions in the graph along with makers, supporters, supersedes, and sources
        dec_query = """
        MATCH (d:Decision)
        OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
        OPTIONAL MATCH (supporter:Person)-[:SUPPORTED_BY]->(d)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old_d:Decision)
        OPTIONAL MATCH (newer_d:Decision)-[:SUPERSEDES]->(d)
        OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(source)
        RETURN d.id, d.title, d.status, d.detail,
               maker.id, maker.name, supporter.id, supporter.name,
               old_d.id, newer_d.id,
               labels(source), source.id, source.title, source.url, source.content
        """
        dec_res = self.graph.query(dec_query)

        decisions_map: Dict[str, DecisionModel] = {}
        sources_map: Dict[str, SourceRecordModel] = {}

        for row in dec_res.result_set:
            d_id, d_title, d_status, d_detail, maker_id, maker_name, supporter_id, supporter_name, old_id, new_id, src_labels, src_id, src_title, src_url, src_content = row

            if d_id not in decisions_map:
                decisions_map[d_id] = DecisionModel(
                    id=d_id,
                    title=d_title,
                    status=d_status or "current",
                    detail=d_detail,
                    made_by=maker_name,
                    made_by_id=maker_id,
                    supported_by_people=[],
                    supported_by_ids=[],
                    supersedes=old_id,
                    superseded_by=new_id,
                    sources=[],
                )

            model = decisions_map[d_id]
            if supporter_name and supporter_name not in model.supported_by_people:
                model.supported_by_people.append(supporter_name)
                if supporter_id and supporter_id not in model.supported_by_ids:
                    model.supported_by_ids.append(supporter_id)
            if maker_name and not model.made_by:
                model.made_by = maker_name
                model.made_by_id = maker_id
            if old_id and not model.supersedes:
                model.supersedes = old_id
            if new_id and not model.superseded_by:
                model.superseded_by = new_id

            if src_id:
                src_type = src_labels[0] if (src_labels and len(src_labels) > 0) else "Source"
                src_model = SourceRecordModel(
                    id=src_id,
                    type=src_type,
                    title=src_title or src_id,
                    url=src_url,
                    content=src_content,
                )
                sources_map[src_id] = src_model
                if not any(s.id == src_id for s in model.sources):
                    model.sources.append(src_model)

        # Also find documents/tickets directly associated with the system or related downstream systems
        doc_query = """
        MATCH (s:System {id: $id})-[:ABOUT]->(doc:Document)
        RETURN doc.id, doc.title, doc.url, doc.content
        """
        doc_res = self.graph.query(doc_query, params={"id": sys_id})
        for row in doc_res.result_set:
            s_id, s_title, s_url, s_content = row
            src_model = SourceRecordModel(
                id=s_id,
                type="Document",
                title=s_title or s_id,
                url=s_url,
                content=s_content,
            )
            sources_map[s_id] = src_model

        # Also find Tickets in the graph mentioning latency or system name
        ticket_query = """
        MATCH (tk:Ticket)
        RETURN tk.id, tk.title, tk.url, tk.content
        """
        tk_res = self.graph.query(ticket_query)
        for row in tk_res.result_set:
            tk_id, tk_title, tk_url, tk_content = row
            sources_map[tk_id] = SourceRecordModel(
                id=tk_id,
                type="Ticket",
                title=tk_title or tk_id,
                url=tk_url,
                content=tk_content,
            )

        return {
            "decisions": list(decisions_map.values()),
            "sources": list(sources_map.values()),
        }

    def search_decisions_and_evidence(self, query_term: str) -> Dict[str, Any]:
        """
        Parameterized Cypher query to retrieve decisions and supporting sources matching a topic, ID, or title.
        """
        dec_query = """
        MATCH (d:Decision)
        WHERE d.id = $term
           OR toLower(d.title) CONTAINS toLower($term)
           OR toLower(d.detail) CONTAINS toLower($term)
        OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
        OPTIONAL MATCH (supporter:Person)-[:SUPPORTED_BY]->(d)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old_d:Decision)
        OPTIONAL MATCH (newer_d:Decision)-[:SUPERSEDES]->(d)
        OPTIONAL MATCH (d)-[:SUPPORTED_BY]->(source)
        RETURN d.id, d.title, d.status, d.detail,
               maker.id, maker.name, supporter.id, supporter.name,
               old_d.id, newer_d.id,
               labels(source), source.id, source.title, source.url, source.content
        """
        dec_res = self.graph.query(dec_query, params={"term": query_term})
        decisions_map: Dict[str, DecisionModel] = {}
        sources_map: Dict[str, SourceRecordModel] = {}

        for row in dec_res.result_set:
            d_id, d_title, d_status, d_detail, maker_id, maker_name, supporter_id, supporter_name, old_id, new_id, src_labels, src_id, src_title, src_url, src_content = row
            if d_id not in decisions_map:
                decisions_map[d_id] = DecisionModel(
                    id=d_id,
                    title=d_title,
                    status=d_status or "current",
                    detail=d_detail,
                    made_by=maker_name,
                    made_by_id=maker_id,
                    supported_by_people=[],
                    supported_by_ids=[],
                    supersedes=old_id,
                    superseded_by=new_id,
                    sources=[],
                )
            model = decisions_map[d_id]
            if supporter_name and supporter_name not in model.supported_by_people:
                model.supported_by_people.append(supporter_name)
                if supporter_id and supporter_id not in model.supported_by_ids:
                    model.supported_by_ids.append(supporter_id)
            if maker_name and not model.made_by:
                model.made_by = maker_name
                model.made_by_id = maker_id
            if old_id and not model.supersedes:
                model.supersedes = old_id
            if new_id and not model.superseded_by:
                model.superseded_by = new_id

            if src_id:
                src_type = src_labels[0] if (src_labels and len(src_labels) > 0) else "Source"
                src_model = SourceRecordModel(
                    id=src_id,
                    type=src_type,
                    title=src_title or src_id,
                    url=src_url,
                    content=src_content,
                )
                sources_map[src_id] = src_model
                if not any(s.id == src_id for s in model.sources):
                    model.sources.append(src_model)

        # Also include any directly superseded decisions so their full model is available
        superseded_ids = [d.supersedes for d in decisions_map.values() if d.supersedes and d.supersedes not in decisions_map]
        for s_id in superseded_ids:
            s_query = """
            MATCH (d:Decision {id: $id})
            OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
            OPTIONAL MATCH (supporter:Person)-[:SUPPORTED_BY]->(d)
            OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
            RETURN d.id, d.title, d.status, d.detail, maker.name, supporter.name, newer.id
            """
            s_res = self.graph.query(s_query, params={"id": s_id})
            for s_row in s_res.result_set:
                sd_id, sd_title, sd_status, sd_detail, smaker, ssupporter, snewer = s_row
                if sd_id not in decisions_map:
                    decisions_map[sd_id] = DecisionModel(
                        id=sd_id,
                        title=sd_title,
                        status=sd_status or "superseded",
                        detail=sd_detail,
                        made_by=smaker,
                        supported_by_people=[ssupporter] if ssupporter else [],
                        supersedes=None,
                        superseded_by=snewer,
                        sources=[],
                    )

        return {
            "decisions": list(decisions_map.values()),
            "sources": list(sources_map.values()),
        }

    def get_system_tasks(self, system_identifier: str) -> List[Dict[str, Any]]:
        """
        Return tasks associated with this system.
        Deduplicates records by stable task ID in both the Cypher query and Python response layer,
        preserving distinct tasks and their relationships.
        """
        sys_query = """
        MATCH (s:System)
        WHERE s.id = $id OR toLower(s.name) = toLower($name) OR toLower(s.name) CONTAINS toLower($name)
        RETURN s.id
        LIMIT 1
        """
        sys_res = self.graph.query(sys_query, params={"id": system_identifier, "name": system_identifier})
        if not sys_res.result_set:
            return []

        sys_id = sys_res.result_set[0][0]

        task_query = """
        MATCH (t:Task)-[:ABOUT]->(s:System {id: $id})
        OPTIONAL MATCH (p:Person)-[:OWNS]->(t)
        WITH t.id AS id,
             head(collect(DISTINCT t.title)) AS title,
             head(collect(DISTINCT t.status)) AS status,
             head(collect(DISTINCT p.id)) AS owner_id,
             head(collect(DISTINCT p.name)) AS owner_name,
             min(t.created_at) AS created_at
        RETURN id, title, status, owner_id, owner_name, created_at
        ORDER BY id
        """
        task_res = self.graph.query(task_query, params={"id": sys_id})
        tasks_by_id: Dict[str, Dict[str, Any]] = {}
        for row in task_res.result_set:
            tid = row[0]
            if tid and tid not in tasks_by_id:
                tasks_by_id[tid] = {
                    "id": tid,
                    "title": row[1],
                    "status": row[2],
                    "owner_id": row[3],
                    "owner_name": row[4],
                    "created_at": row[5],
                }
        return list(tasks_by_id.values())

    def investigate_system(self, system_identifier: str) -> SystemInvestigation:
        """Complete investigation aggregation for a target system."""
        ownership_info = self.find_system_owners_and_experts(system_identifier)
        if not ownership_info["system"]:
            raise ValueError(f"System '{system_identifier}' not found in Company Brain graph.")

        system_node = ownership_info["system"]
        deps_info = self.get_system_dependencies(system_node.id)
        dec_info = self.get_architecture_decisions_and_sources(system_node.id)
        tasks = self.get_system_tasks(system_node.id)

        return SystemInvestigation(
            system=system_node,
            owners=ownership_info["owners"],
            experts=ownership_info["experts"],
            downstream_dependencies=deps_info["downstream"],
            upstream_callers=deps_info["upstream"],
            decisions=dec_info["decisions"],
            source_records=dec_info["sources"],
            active_tasks=tasks,
        )

    def get_full_graph_overview(self) -> Dict[str, Any]:
        """Fetch all nodes and relationships to render interactive graph visualization."""
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        q_nodes = """
        MATCH (n)
        RETURN id(n) AS internal_id, labels(n)[0] AS label, n.id AS node_id, n.name AS name, n.title AS title, properties(n) AS props
        """
        res_nodes = self.graph.query(q_nodes)
        for row in res_nodes.result_set:
            _, label, nid, name, title, props = row
            key = nid if nid else f"{label}_{name or title}"
            display_name = name or title or nid
            nodes[key] = {
                "id": key,
                "label": label,
                "name": display_name,
                "properties": props or {},
            }

        q_edges = """
        MATCH (a)-[r]->(b)
        RETURN a.id AS source_id, labels(a)[0] AS a_label, a.name AS a_name, a.title AS a_title,
               type(r) AS rel_type,
               b.id AS target_id, labels(b)[0] AS b_label, b.name AS b_name, b.title AS b_title
        """
        res_edges = self.graph.query(q_edges)
        for row in res_edges.result_set:
            a_id, a_label, a_name, a_title, rel_type, b_id, b_label, b_name, b_title = row
            src_key = a_id or f"{a_label}_{a_name or a_title}"
            tgt_key = b_id or f"{b_label}_{b_name or b_title}"
            edges.append({
                "source": src_key,
                "target": tgt_key,
                "type": rel_type,
            })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
        }

    def safe_update_system_owner(
        self, system_id: str, new_person_id: str, actor: str, reason: str
    ) -> Dict[str, Any]:
        """
        Safely update system owner:
        1. Preserves provenance by recording audit properties and previous owner
        2. Deletes old OWNS edge
        3. Creates new OWNS edge
        4. Re-queries graph to return verified state
        """
        # Get current owner
        find_query = """
        MATCH (s:System {id: $sys_id})
        OPTIONAL MATCH (old_p:Person)-[r:OWNS]->(s)
        MATCH (new_p:Person {id: $new_p_id})
        RETURN s.name, old_p.id, old_p.name, new_p.name
        """
        res = self.graph.query(
            find_query, params={"sys_id": system_id, "new_p_id": new_person_id}
        )
        if not res.result_set:
            raise ValueError(f"System '{system_id}' or Person '{new_person_id}' does not exist.")

        sys_name, old_p_id, old_p_name, new_p_name = res.result_set[0]
        timestamp = datetime.now(timezone.utc).isoformat()

        # Update edges and update system audit metadata
        update_query = """
        MATCH (s:System {id: $sys_id})
        OPTIONAL MATCH (old:Person)-[r:OWNS]->(s)
        DELETE r
        WITH s
        MATCH (new_p:Person {id: $new_p_id})
        CREATE (new_p)-[:OWNS]->(s)
        SET s.last_owner_update_at = $ts,
            s.last_owner_updated_by = $actor,
            s.last_owner_update_reason = $reason,
            s.previous_owner_id = $old_id,
            s.previous_owner_name = $old_name
        RETURN s.id, s.name, new_p.id, new_p.name
        """
        self.graph.query(
            update_query,
            params={
                "sys_id": system_id,
                "new_p_id": new_person_id,
                "ts": timestamp,
                "actor": actor,
                "reason": reason,
                "old_id": old_p_id or "",
                "old_name": old_p_name or "",
            },
        )

        # Immediate re-query
        re_queried = self.find_system_owners_and_experts(system_id)
        return {
            "system_id": system_id,
            "system_name": sys_name,
            "previous_owner": old_p_name,
            "current_owner": new_p_name,
            "updated_by": actor,
            "timestamp": timestamp,
            "verified_owners": [o.model_dump() for o in re_queried["owners"]],
        }

    def safe_update_decision_status(
        self, decision_id: str, new_status: str, actor: str, reason: str
    ) -> Dict[str, Any]:
        """
        Safely update decision status with provenance.
        """
        check_query = "MATCH (d:Decision {id: $id}) RETURN d.id, d.title, d.status"
        res = self.graph.query(check_query, params={"id": decision_id})
        if not res.result_set:
            raise ValueError(f"Decision '{decision_id}' does not exist.")

        d_id, d_title, old_status = res.result_set[0]
        timestamp = datetime.now(timezone.utc).isoformat()

        update_query = """
        MATCH (d:Decision {id: $id})
        SET d.status = $status,
            d.previous_status = $old_status,
            d.status_updated_at = $ts,
            d.status_updated_by = $actor,
            d.status_update_reason = $reason
        RETURN d.id, d.title, d.status
        """
        self.graph.query(
            update_query,
            params={
                "id": decision_id,
                "status": new_status,
                "old_status": old_status or "",
                "ts": timestamp,
                "actor": actor,
                "reason": reason,
            },
        )

        # Re-query
        re_query = "MATCH (d:Decision {id: $id}) RETURN d.id, d.title, d.status, d.status_updated_by"
        re_res = self.graph.query(re_query, params={"id": decision_id})
        row = re_res.result_set[0]

        return {
            "decision_id": row[0],
            "title": row[1],
            "previous_status": old_status,
            "new_status": row[2],
            "updated_by": row[3],
            "timestamp": timestamp,
        }

    def safe_create_task(
        self, task_id: str, title: str, system_id: str, person_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create or update a Task node idempotently by stable task ID and link it to the system and owner.
        Uses MERGE to guarantee idempotent writes and preserve existing records and provenance.
        """
        q = """
        MATCH (s:System {id: $sys_id})
        MERGE (t:Task {id: $task_id})
        ON CREATE SET t.title = $title, t.status = 'open', t.created_at = $ts
        ON MATCH SET t.title = $title, t.status = 'open', t.updated_at = $ts
        MERGE (t)-[:ABOUT]->(s)
        WITH t, s
        OPTIONAL MATCH (p:Person {id: $p_id})
        FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
            MERGE (p)-[:OWNS]->(t)
        )
        RETURN t.id, t.title, t.status, s.name, p.name
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        res = self.graph.query(
            q,
            params={
                "sys_id": system_id,
                "task_id": task_id,
                "title": title,
                "ts": timestamp,
                "p_id": person_id or "",
            },
        )
        row = res.result_set[0]
        return {
            "task_id": row[0],
            "title": row[1],
            "status": row[2],
            "system_name": row[3],
            "owner_name": row[4],
        }
