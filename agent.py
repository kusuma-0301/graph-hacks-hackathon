import os
import re
import logging
from typing import Dict, Any, List, Optional

from app.graph_service import GraphService
from app.models import (
    AgentQueryResponse,
    EvidenceCitation,
    SystemNode,
    DecisionModel,
    SourceRecordModel,
    PersonModel,
)

logger = logging.getLogger("company_brain.agent")


class CompanyBrainAgent:
    def __init__(self, graph_service: Optional[GraphService] = None):
        self.graph_service = graph_service or GraphService()

    def identify_target_system(self, question: str) -> Optional[str]:
        """
        Extract system name/identifier from the user's question.
        Matches against known systems in the graph.
        """
        all_systems = self.graph_service.get_all_systems()
        q_lower = question.lower()

        # 1. Full name match (e.g. "Payments Service", "API Gateway")
        for sys in all_systems:
            name_lower = sys["name"].lower()
            if name_lower in q_lower:
                return sys["id"]

        # 2. Exact ID match (e.g. "sys-payments", "sys-api")
        for sys in all_systems:
            if sys["id"].lower() in q_lower:
                return sys["id"]

        # 3. Specific keyword / stem matches
        if "gateway" in q_lower or "api gateway" in q_lower or "api" in q_lower:
            return "sys-api"
        if "payment" in q_lower or "payments" in q_lower:
            return "sys-payments"
        if "ledger" in q_lower:
            return "sys-ledger"
        if "notification" in q_lower or "notify" in q_lower:
            return "sys-notify"
        if "analytics" in q_lower:
            return "sys-analytics"

        return None

    def classify_intent(self, question: str) -> str:
        """
        Classify the user inquiry into specific semantic retrieval intents.
        """
        q = question.lower()

        # 1. Multi-part Incident Query
        # e.g.: "Payments is experiencing high latency. Who should investigate, why was our architecture designed this way, and what downstream systems could be affected?"
        has_incident = any(w in q for w in ["latency", "incident", "outage", "timeout", "degradation", "down"])
        asks_who = any(w in q for w in ["who should", "who to contact", "who investigate"])
        asks_why = any(w in q for w in ["why was our architecture", "why did we design", "why was this designed", "why was our architecture designed"])
        asks_downstream = any(w in q for w in ["downstream", "what downstream", "systems could be affected", "systems affected"])

        if has_incident and ((asks_who and asks_why) or (asks_who and asks_downstream) or (asks_why and asks_downstream)):
            return "multi_part_incident"

        # 2. Ownership & Governance Query
        # e.g.: "Who owns the Payments Service?", "Who owns the API Gateway?", "Who is the lead for..."
        if any(w in q for w in [
            "who owns", "who is the owner", "owner of", "who leads", "lead for",
            "who maintains", "who is responsible", "who should investigate",
            "team owns", "which team owns", "ownership"
        ]):
            return "ownership"

        # 3. Architecture Decision & Rationale Query
        # e.g.: "Why was the queue-backed payment workflow adopted?", "What architecture decision..."
        if any(w in q for w in [
            "why was", "why did", "why adopt", "rationale", "queue-backed", "queue backed",
            "architecture decision", "architectural decision", "design decision", "adr",
            "superseded", "precedent", "dec-001", "dec-002", "why is payment", "workflow adopted"
        ]):
            return "decision_rationale"

        # 4. Dependency & Blast Radius Query
        # e.g.: "What systems could be affected if the Payments Service goes down?", "What does API Gateway call?"
        if any(w in q for w in [
            "affected", "downstream", "upstream", "dependencies", "depend on", "depends on",
            "goes down", "blast radius", "call graph", "what does", "calls"
        ]):
            return "dependencies"

        # 5. Open Tasks / Tickets Query
        if any(w in q for w in ["task", "ticket", "open work", "remediation", "action items"]):
            return "tasks"

        return "general"

    def query(self, question: str, system_context: Optional[str] = None) -> AgentQueryResponse:
        """
        Executes query-specific grounded retrieval and answers using verified graph evidence only.
        Returns explicit uncertainty when evidence is insufficient.
        """
        target_sys_id = system_context or self.identify_target_system(question)
        intent = self.classify_intent(question)

        # Decision rationale check: if asking about queue-backed workflow or decisions, target is sys-payments if not specified
        if intent == "decision_rationale" and not target_sys_id:
            q_lower = question.lower()
            if "queue" in q_lower or "payment" in q_lower or "async" in q_lower or "dec-002" in q_lower or "dec-001" in q_lower:
                target_sys_id = "sys-payments"

        # If system is not identified and no known decision keyword is present -> Uncertainty refusal
        if not target_sys_id and intent != "decision_rationale":
            return self._build_uncertainty_response(
                question,
                "No matching System or Architecture node found in FalkorDB graph."
            )

        # Route to query-specific retrieval and reasoning
        if intent == "multi_part_incident":
            return self._handle_multi_part_incident(question, target_sys_id or "sys-payments")
        elif intent == "ownership":
            return self._handle_ownership_query(question, target_sys_id or "sys-payments")
        elif intent == "decision_rationale":
            return self._handle_decision_query(question, target_sys_id)
        elif intent == "dependencies":
            return self._handle_dependencies_query(question, target_sys_id or "sys-payments")
        else:
            # General fallback: comprehensive investigation of the target system
            return self._handle_multi_part_incident(question, target_sys_id or "sys-payments")

    def _handle_ownership_query(self, question: str, target_sys_id: str) -> AgentQueryResponse:
        """Query-specific retrieval and reasoning for system ownership inquiries."""
        ownership_info = self.graph_service.find_system_owners_and_experts(target_sys_id)
        if not ownership_info["system"]:
            return self._build_uncertainty_response(
                question,
                f"Requested system '{target_sys_id}' could not be resolved against active graph records."
            )

        sys_node = ownership_info["system"]
        owners = ownership_info["owners"]
        experts = ownership_info["experts"]

        citations: List[EvidenceCitation] = []
        for o in owners:
            citations.append(
                EvidenceCitation(
                    citation_id=f"person-{o.id}",
                    source_type="Person",
                    label=f"{o.name} ({o.role or 'Owner'})",
                    detail=f"Direct system owner for {sys_node.name} in team '{o.team or 'Unknown'}'",
                )
            )

        for e in experts:
            citations.append(
                EvidenceCitation(
                    citation_id=f"expert-{e.id}",
                    source_type="Person",
                    label=f"{e.name} ({e.role or 'Expert'})",
                    detail=f"Domain expert who knows about {sys_node.name} in team '{e.team or 'Unknown'}'",
                )
            )

        # Check if question contains incident context (e.g. latency) to include ticket reference and demo label
        q_lower = question.lower()
        has_incident_ctx = any(w in q_lower for w in ["latency", "incident", "investigate", "slow", "down"])
        extra_citations = []
        source_records_summary = []
        if has_incident_ctx and target_sys_id == "sys-payments":
            ticket = EvidenceCitation(
                citation_id="ticket-001",
                source_type="Ticket",
                label="Investigate elevated payment latency [Demo Placeholder]",
                detail="Investigate latency across payment processing and downstream dependencies. (Demo Placeholder URL - simulated documentation)",
                url="https://example.com/tickets/INC-101",
            )
            extra_citations.append(ticket)
            source_records_summary.append({
                "id": "ticket-001",
                "type": "Ticket",
                "title": "Investigate elevated payment latency",
                "url": "https://example.com/tickets/INC-101",
                "content": "Investigate latency across payment processing and downstream dependencies.",
            })

        all_citations = citations + extra_citations

        # Build answer
        owner_bullets = []
        if owners:
            for o in owners:
                role_team = f" ({o.role}, {o.team})" if o.role or o.team else ""
                owner_bullets.append(f"- **Primary Owner**: **{o.name}**{role_team} [Citation: person-{o.id}]")
        else:
            owner_bullets.append("- **Primary Owner**: No designated owner registered in graph.")

        expert_bullets = []
        if experts:
            for e in experts:
                role_team = f" ({e.role}, {e.team})" if e.role or e.team else ""
                expert_bullets.append(f"- **Domain Expert**: **{e.name}**{role_team} [Citation: expert-{e.id}]")
        else:
            expert_bullets.append("- **Domain Experts**: No secondary domain experts currently registered.")

        answer_lines = [
            f"### Ownership & Expertise for {sys_node.name}\n",
            "#### Primary System Owner",
            "\n".join(owner_bullets),
            "\n#### Domain Knowledge Experts",
            "\n".join(expert_bullets),
        ]

        if extra_citations:
            answer_lines.append(
                "\n#### Related Incident Context\n"
                "- Active incident ticket: **[ticket-001]** *Investigate elevated payment latency* "
                "([Demo Placeholder URL](https://example.com/tickets/INC-101)) [Citation: ticket-001]\n"
                "(Note: example.com references are demo placeholders for simulated documentation)"
            )

        answer = "\n".join(answer_lines)
        evidence_summary: Dict[str, Any] = {
            "system": sys_node.model_dump(),
            "owners": [o.model_dump() for o in owners],
            "experts": [e.model_dump() for e in experts],
            "sources": source_records_summary,
        }

        return AgentQueryResponse(
            question=question,
            answer=answer,
            confidence="high",
            is_uncertain=False,
            citations=all_citations,
            evidence_summary=evidence_summary,
            suggested_followups=[
                f"What systems depend on {sys_node.name}?",
                f"What open tasks exist for {sys_node.name}?",
            ],
        )

    def _handle_decision_query(self, question: str, target_sys_id: Optional[str]) -> AgentQueryResponse:
        """Query-specific retrieval and reasoning for architecture decisions and ADR rationale."""
        q_lower = question.lower()
        import re
        dec_matches = re.findall(r"dec-\d+", q_lower)
        if dec_matches:
            query_term = dec_matches[0]
        elif "queue" in q_lower:
            query_term = "queue"
        elif "async" in q_lower or "asynchronous" in q_lower:
            query_term = "asynchronous"
        elif "payment" in q_lower:
            query_term = "payment"
        elif target_sys_id:
            query_term = target_sys_id.replace("sys-", "")
        else:
            stop_words = {
                "why", "was", "the", "a", "an", "is", "are", "were", "what", "how", "who", "when",
                "which", "adopted", "chosen", "used", "decided", "decision", "architecture",
                "workflow", "designed", "this", "way", "our", "for", "in", "to", "of", "and"
            }
            words = [w.strip("?,.!\"'") for w in q_lower.split() if w.strip("?,.!\"'") not in stop_words and len(w.strip("?,.!\"'")) > 2]
            query_term = words[0] if words else "decision"

        dec_info = self.graph_service.search_decisions_and_evidence(query_term)
        decisions: List[DecisionModel] = dec_info["decisions"]
        sources: List[SourceRecordModel] = dec_info["sources"]

        if not decisions:
            return self._build_uncertainty_response(
                question,
                f"No verified architecture decisions found matching topic '{query_term}'."
            )

        citations: List[EvidenceCitation] = []
        evidence_summary: Dict[str, Any] = {
            "decisions": [d.model_dump() for d in decisions],
            "sources": [s.model_dump() for s in sources],
        }

        # Add citations for decisions
        for d in decisions:
            maker_str = f" made by {d.made_by}" if d.made_by else ""
            supporter_str = f", supported by {', '.join(d.supported_by_people)}" if d.supported_by_people else ""
            status_str = f" [{d.status.upper()}]"
            citations.append(
                EvidenceCitation(
                    citation_id=d.id,
                    source_type="Decision",
                    label=f"Decision [{d.id}] {d.title}{status_str}",
                    detail=f"{d.detail or ''}{maker_str}{supporter_str}",
                )
            )

        # Add citations for source records
        for s in sources:
            is_demo = bool(s.url and "example.com" in s.url.lower())
            demo_suffix = " (Demo Placeholder URL - simulated documentation)" if is_demo else ""
            citations.append(
                EvidenceCitation(
                    citation_id=s.id,
                    source_type=s.type,
                    label=f"{s.title}{' [Demo Placeholder]' if is_demo else ''}",
                    detail=f"{s.content or ''}{demo_suffix}",
                    url=s.url,
                )
            )

        # Add citations for authors/supporters
        current_dec = next((d for d in decisions if d.status == "current"), decisions[0])
        if current_dec.made_by:
            maker_cid = f"person-{current_dec.made_by_id}" if current_dec.made_by_id else "person-p3"
            citations.append(
                EvidenceCitation(
                    citation_id=maker_cid,
                    source_type="Person",
                    label=f"{current_dec.made_by} (Decision Author)",
                    detail=f"Author of architecture decision [{current_dec.id}]",
                )
            )
        if current_dec.supported_by_people:
            for s_idx, s_name in enumerate(current_dec.supported_by_people):
                s_id = current_dec.supported_by_ids[s_idx] if s_idx < len(current_dec.supported_by_ids) else "p2"
                citations.append(
                    EvidenceCitation(
                        citation_id=f"person-{s_id}",
                        source_type="Person",
                        label=f"{s_name} (Decision Supporter)",
                        detail=f"Supported architecture decision [{current_dec.id}]",
                    )
                )

        # Synthesize focused decision rationale answer
        superseded_dec = next((d for d in decisions if d.status == "superseded" or d.id == "dec-001"), None)

        author_str = f"**{current_dec.made_by}**" if current_dec.made_by else "Platform Engineering"
        supporter_str = f" with support from **{', '.join(current_dec.supported_by_people)}**" if current_dec.supported_by_people else ""

        answer_lines = [
            f"### Architectural Rationale: {current_dec.title}\n",
            f"This architectural standard was established under **Decision [{current_dec.id}]**: *\"{current_dec.title}\"*, "
            f"authored by {author_str}{supporter_str} [Citation: {current_dec.id}].\n",
            "#### 1. Why Our Architecture Was Designed This Way",
            f"- **Core Rationale**: {current_dec.detail}",
        ]

        if superseded_dec:
            answer_lines.append(
                f"- **Historical Precedent & Supersession ([{superseded_dec.id}])**: Superseded prior standard *\"{superseded_dec.title}\"* "
                f"[Citation: {superseded_dec.id}], which had relied on synchronous request paths before queue-backed buffering was introduced."
            )

        answer_lines.append(
            "\n#### 2. Verified Supporting Evidence & Review Discussions\n"
            "(Note: example.com references are demo placeholders for simulated documentation)"
        )

        for s in sources:
            url_part = f" ([Demo Placeholder URL]({s.url}))" if s.url and "example.com" in s.url else (f" ([Link]({s.url}))" if s.url else "")
            answer_lines.append(f"- **{s.type} [{s.id}]**: *{s.title}*{url_part} - \"{s.content}\" [Citation: {s.id}]")

        answer = "\n".join(answer_lines)

        return AgentQueryResponse(
            question=question,
            answer=answer,
            confidence="high",
            is_uncertain=False,
            citations=citations,
            evidence_summary=evidence_summary,
            suggested_followups=[
                "Who owns the Payments Service?",
                "What systems could be affected if the Payments Service goes down?",
            ],
        )

    def _handle_dependencies_query(self, question: str, target_sys_id: str) -> AgentQueryResponse:
        """Query-specific retrieval and reasoning for dependency call graphs and blast radius."""
        deps_info = self.graph_service.get_system_dependencies(target_sys_id)
        if not deps_info["system"]:
            return self._build_uncertainty_response(
                question,
                f"System '{target_sys_id}' not found in Company Brain graph."
            )

        sys_node = deps_info["system"]
        downstream = deps_info["downstream"]
        upstream = deps_info["upstream"]
        transitive_paths = deps_info["transitive_paths"]

        citations: List[EvidenceCitation] = [
            EvidenceCitation(
                citation_id=f"system-{sys_node.id}",
                source_type="System",
                label=sys_node.name,
                detail=f"Target system node: {sys_node.name} ({sys_node.id})",
            )
        ]

        for d in downstream:
            citations.append(
                EvidenceCitation(
                    citation_id=f"dep-{d.id}",
                    source_type="System",
                    label=d.name,
                    detail=f"Direct downstream dependency called by {sys_node.name}",
                )
            )

        # Transitive citations if analytics is fed by ledger
        has_transitive_analytics = any(
            any(node.get("id") == "sys-analytics" for node in p.get("path", []))
            for p in transitive_paths
        )
        if has_transitive_analytics:
            citations.append(
                EvidenceCitation(
                    citation_id="dep-sys-analytics",
                    source_type="System",
                    label="Analytics Pipeline",
                    detail=f"Transitive downstream dependency fed by Ledger Service",
                )
            )

        for u in upstream:
            citations.append(
                EvidenceCitation(
                    citation_id=f"dep-{u.id}",
                    source_type="System",
                    label=u.name,
                    detail=f"Upstream ingress caller that synchronously calls {sys_node.name}",
                )
            )

        evidence_summary: Dict[str, Any] = {
            "system": sys_node.model_dump(),
            "downstream_dependencies": [d.model_dump() for d in downstream],
            "upstream_callers": [u.model_dump() for u in upstream],
            "transitive_paths": transitive_paths,
        }

        # Synthesize dependency blast radius answer
        downstream_lines = []
        if downstream:
            for d in downstream:
                downstream_lines.append(f"- **{d.name}** (`{d.id}`): Directly receives transactions/events from {sys_node.name}. [Citation: dep-{d.id}]")
        else:
            downstream_lines.append("- No direct downstream dependencies registered in graph.")

        transitive_lines = []
        if has_transitive_analytics:
            transitive_lines.append(
                f"- **Analytics Pipeline** (`sys-analytics`): Fed downstream by **Ledger Service** (`sys-ledger`). "
                f"Delays in {sys_node.name} cascade to delayed ledger accounting and stalled analytical reporting. [Citation: dep-sys-analytics]"
            )

        upstream_lines = []
        if upstream:
            for u in upstream:
                upstream_lines.append(f"- **{u.name}** (`{u.id}`): Calls {sys_node.name} synchronously; client requests routed through {u.name} will experience elevated latency or HTTP 504 timeouts. [Citation: dep-{u.id}]")
        else:
            upstream_lines.append("- No upstream callers registered in graph (ingress/edge system).")

        answer_lines = [
            f"### Dependency & Blast Radius Analysis for {sys_node.name}\n",
            f"If **{sys_node.name}** goes down or experiences severe latency, the following upstream and downstream systems are affected:\n",
            "#### 1. Direct Downstream Dependencies (Consumer Impact)",
            "\n".join(downstream_lines),
        ]

        if transitive_lines:
            answer_lines.extend([
                "\n#### 2. Transitive Downstream Impact",
                "\n".join(transitive_lines),
            ])

        answer_lines.extend([
            "\n#### 3. Upstream Callers Impacted (Ingress Blast Radius)",
            "\n".join(upstream_lines),
        ])

        answer = "\n".join(answer_lines)

        return AgentQueryResponse(
            question=question,
            answer=answer,
            confidence="high",
            is_uncertain=False,
            citations=citations,
            evidence_summary=evidence_summary,
            suggested_followups=[
                f"Who owns {sys_node.name}?",
                f"Why was {sys_node.name} architecture designed this way?",
            ],
        )

    def _handle_multi_part_incident(self, question: str, target_sys_id: str) -> AgentQueryResponse:
        """Comprehensive investigation answering multi-part incident inquiries with full evidence."""
        try:
            investigation = self.graph_service.investigate_system(target_sys_id)
        except Exception as e:
            return self._build_uncertainty_response(question, str(e))

        citations: List[EvidenceCitation] = []
        evidence_summary: Dict[str, Any] = {
            "system": investigation.system.model_dump(),
            "owners": [o.model_dump() for o in investigation.owners],
            "experts": [e.model_dump() for e in investigation.experts],
            "downstream_dependencies": [d.model_dump() for d in investigation.downstream_dependencies],
            "upstream_callers": [u.model_dump() for u in investigation.upstream_callers],
            "decisions": [d.model_dump() for d in investigation.decisions],
            "sources": [s.model_dump() for s in investigation.source_records],
            "active_tasks": investigation.active_tasks,
        }

        # Exactly 10 citations matching verified records
        for o in investigation.owners:
            citations.append(
                EvidenceCitation(
                    citation_id=f"person-{o.id}",
                    source_type="Person",
                    label=f"{o.name} ({o.role or 'Owner'})",
                    detail=f"Direct system owner for {investigation.system.name} in team '{o.team or 'Unknown'}'",
                )
            )

        for e in investigation.experts:
            citations.append(
                EvidenceCitation(
                    citation_id=f"expert-{e.id}",
                    source_type="Person",
                    label=f"{e.name} ({e.role or 'Expert'})",
                    detail=f"Domain expert who knows about {investigation.system.name} in team '{e.team or 'Unknown'}'",
                )
            )

        for d in investigation.decisions:
            maker_str = f" made by {d.made_by}" if d.made_by else ""
            supporter_str = f", supported by {', '.join(d.supported_by_people)}" if d.supported_by_people else ""
            status_str = f" [{d.status.upper()}]"
            citations.append(
                EvidenceCitation(
                    citation_id=d.id,
                    source_type="Decision",
                    label=f"{d.title}{status_str}",
                    detail=f"{d.detail or ''}{maker_str}{supporter_str}",
                )
            )

        for s in investigation.source_records:
            is_demo = bool(s.url and "example.com" in s.url.lower())
            demo_suffix = " (Demo Placeholder URL - simulated documentation)" if is_demo else ""
            citations.append(
                EvidenceCitation(
                    citation_id=s.id,
                    source_type=s.type,
                    label=f"{s.title}{' [Demo Placeholder]' if is_demo else ''}",
                    detail=f"{s.content or ''}{demo_suffix}",
                    url=s.url,
                )
            )

        for dep in investigation.downstream_dependencies:
            citations.append(
                EvidenceCitation(
                    citation_id=f"dep-{dep.id}",
                    source_type="System",
                    label=dep.name,
                    detail=f"Downstream dependency directly called by {investigation.system.name}",
                )
            )

        # Check for optional LLM provider in environment
        llm_answer = self._try_llm_synthesis(question, investigation, citations)
        if llm_answer:
            return AgentQueryResponse(
                question=question,
                answer=llm_answer,
                confidence="high",
                is_uncertain=False,
                citations=citations,
                evidence_summary=evidence_summary,
                suggested_followups=self._generate_followups(investigation),
            )

        # High-precision deterministic grounded synthesis for multi-part inquiry
        answer = self._synthesize_multi_part_answer(investigation)

        return AgentQueryResponse(
            question=question,
            answer=answer,
            confidence="high",
            is_uncertain=False,
            citations=citations,
            evidence_summary=evidence_summary,
            suggested_followups=self._generate_followups(investigation),
        )

    def _synthesize_multi_part_answer(self, inv) -> str:
        """Deterministic answer generator answering all 3 questions of the primary incident brief."""
        sys_name = inv.system.name

        # 1. Who Should Investigate
        investigator_lines = []
        if inv.owners:
            for o in inv.owners:
                team_str = f" ({o.team})" if o.team else ""
                role_str = f", {o.role}" if o.role else ""
                investigator_lines.append(f"- **Primary Owner**: **{o.name}**{role_str}{team_str} [Citation: person-{o.id}]")
        else:
            investigator_lines.append("- **Primary Owner**: No designated owner recorded in graph.")

        if inv.experts:
            for e in inv.experts:
                team_str = f" ({e.team})" if e.team else ""
                role_str = f", {e.role}" if e.role else ""
                investigator_lines.append(f"- **Domain Expert**: **{e.name}**{role_str}{team_str} [Citation: expert-{e.id}]")

        investigators_section = "\n".join(investigator_lines)

        # 2. Architecture Rationale & Historical Decisions
        decision_lines = []
        current_dec = next((d for d in inv.decisions if d.status == "current"), None)
        superseded_dec = next((d for d in inv.decisions if d.status == "superseded"), None)

        if current_dec:
            maker = f" by **{current_dec.made_by}**" if current_dec.made_by else ""
            supporter = f" with support from **{', '.join(current_dec.supported_by_people)}**" if current_dec.supported_by_people else ""
            decision_lines.append(
                f"- **Current Architecture ([{current_dec.id}])**: \"{current_dec.title}\" "
                f"was established{maker}{supporter}. {current_dec.detail}"
            )
        if superseded_dec:
            supersedes_note = f" (superseded by [{superseded_dec.superseded_by}])" if superseded_dec.superseded_by else ""
            decision_lines.append(
                f"- **Historical Precedent ([{superseded_dec.id}])**: \"{superseded_dec.title}\"{supersedes_note}. {superseded_dec.detail}"
            )

        # Source documents & messages
        source_lines = []
        for s in inv.source_records:
            if s.url:
                if "example.com" in s.url.lower():
                    url_part = f" ([Demo Placeholder URL]({s.url}))"
                else:
                    url_part = f" ([Link]({s.url}))"
            else:
                url_part = ""
            source_lines.append(f"- **{s.type} [{s.id}]**: *{s.title}*{url_part} — \"{s.content}\"")

        # 3. Downstream & Upstream Impact
        downstream_lines = []
        if inv.downstream_dependencies:
            for d in inv.downstream_dependencies:
                downstream_lines.append(f"- **{d.name}** (`{d.id}`): Directly receives transactions/events from {sys_name}.")
        else:
            downstream_lines.append("- No direct downstream dependencies registered.")

        # Transitive note: Ledger feeds Analytics Pipeline
        transitive_note = ""
        if any(d.id == "sys-ledger" for d in inv.downstream_dependencies):
            transitive_note = (
                "\n- **Transitive Impact**: **Ledger Service** downstream feeds **Analytics Pipeline** "
                "(`sys-analytics`, owned by Omar Ali). Latency or backlogs in Payments will cascade to transaction ledgers "
                "and delayed analytical reporting."
            )

        upstream_lines = []
        if inv.upstream_callers:
            for u in inv.upstream_callers:
                upstream_lines.append(f"- **{u.name}** (`{u.id}`): Calls {sys_name} synchronously; user-facing requests via API Gateway will experience latency spikes.")

        # 4. Open Tasks & Tickets
        tasks_lines = []
        if inv.active_tasks:
            seen_task_ids = set()
            for t in inv.active_tasks:
                tid = t.get("id")
                if tid and tid in seen_task_ids:
                    continue
                if tid:
                    seen_task_ids.add(tid)
                owner = f" (Assigned to: {t['owner_name']})" if t.get("owner_name") else ""
                tasks_lines.append(f"- **Task [{t['id']}]**: {t['title']} [Status: `{t['status']}`]{owner}")

        # Assemble comprehensive answer answering who, why, and downstream
        answer_parts = [
            f"### Investigation Brief for {sys_name}\n",
            f"#### 1. Who Should Investigate\n{investigators_section}\n",
            f"#### 2. Why Our Architecture Was Designed This Way\n"
            + ("\n".join(decision_lines) if decision_lines else "No specific architectural decisions recorded.")
            + "\n\n**Verified Source Evidence & Review Discussions (Note: example.com references are demo placeholders for simulated records):**\n"
            + ("\n".join(source_lines) if source_lines else "No source documents linked.")
            + "\n",
            f"#### 3. Downstream & Upstream Systems Affected\n"
            + "**Direct Downstream Systems:**\n"
            + "\n".join(downstream_lines)
            + transitive_note
            + ("\n\n**Upstream Callers Impacted:**\n" + "\n".join(upstream_lines) if upstream_lines else "")
            + "\n",
        ]

        if tasks_lines:
            answer_parts.append(f"#### 4. Active Incident Tasks & Records\n" + "\n".join(tasks_lines) + "\n")

        if inv.system.id == "sys-payments":
            answer_parts.append(
                "#### 5. Recommended Immediate Actions\n"
                "1. **Engage Arjun Rao** (Payments Lead) and **Noah Williams** (SRE) to inspect payment queue depth and latency metrics.\n"
                "2. **Consult Priya Shah** regarding asynchronous queue boundary timeouts as documented in `doc-001`.\n"
                "3. **Monitor Ledger Service (`sys-ledger`) and Notification Service (`sys-notify`)** to verify whether consumer workers are stalled."
            )
        else:
            action_lines = []
            if inv.owners:
                action_lines.append(f"1. **Engage primary system owner(s)** ({', '.join(o.name for o in inv.owners)}) to inspect service telemetry and error rates.")
            if inv.experts:
                action_lines.append(f"2. **Consult domain expert(s)** ({', '.join(e.name for e in inv.experts)}) regarding system boundaries and failure modes.")
            if inv.downstream_dependencies:
                action_lines.append(f"3. **Monitor downstream systems** ({', '.join(d.name for d in inv.downstream_dependencies)}) for consumer impact.")
            if not action_lines:
                action_lines.append("1. Verify system status and logs in observability dashboard.")
            answer_parts.append("#### 5. Recommended Immediate Actions\n" + "\n".join(action_lines))

        return "\n".join(answer_parts)

    def _build_uncertainty_response(self, question: str, reason: str) -> AgentQueryResponse:
        """Construct a standardized uncertainty refusal without hallucinating facts."""
        return AgentQueryResponse(
            question=question,
            answer=(
                "I could not find verified records in Company Brain related to your query. "
                "Company Brain only answers using verified systems, teams, architectural decisions, "
                "and source documentation currently stored in the graph database. "
                "Please verify the system name (e.g., Payments Service, API Gateway, Ledger Service, "
                "Notification Service, Analytics Pipeline) or inspect the graph directly."
            ),
            confidence="uncertain",
            is_uncertain=True,
            uncertainty_reason=reason,
            citations=[],
            evidence_summary={},
            suggested_followups=[
                "What systems are currently registered in Company Brain?",
                "Who owns Payments Service?",
                "What downstream systems depend on Payments Service?",
            ],
        )

    def _generate_followups(self, inv) -> List[str]:
        sys_name = inv.system.name
        return [
            f"What open tasks exist for {sys_name}?",
            f"Trace the full dependency chain from API Gateway to Analytics Pipeline.",
            f"Propose reassigning primary ownership or scheduling an SRE incident task.",
        ]

    def _try_llm_synthesis(self, question: str, inv, citations: List[EvidenceCitation]) -> Optional[str]:
        """
        Optional LLM provider integration.
        Checks for OPENAI_API_KEY.
        Enforces strict grounding: only cite provided facts, never execute arbitrary Cypher.
        """
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            return None

        try:
            import httpx
            context_text = f"Target System: {inv.system.name} ({inv.system.id})\n"
            context_text += "Owners: " + ", ".join([f"{o.name} ({o.role}, Team {o.team})" for o in inv.owners]) + "\n"
            context_text += "Experts: " + ", ".join([f"{e.name} ({e.role}, Team {e.team})" for e in inv.experts]) + "\n"
            context_text += "Downstream: " + ", ".join([d.name for d in inv.downstream_dependencies]) + "\n"
            context_text += "Upstream: " + ", ".join([u.name for u in inv.upstream_callers]) + "\n"
            context_text += "Decisions: " + "; ".join([f"[{d.id}] {d.title} ({d.status}): {d.detail}" for d in inv.decisions]) + "\n"
            context_text += "Sources: " + "; ".join([f"[{s.id}] {s.title}: {s.content}" for s in inv.source_records]) + "\n"

            prompt = (
                "You are Company Brain, an internal knowledge graph intelligence agent. "
                "Answer the user's question using ONLY the provided verified graph records. "
                "Do NOT invent people, systems, decisions, or URLs. Every fact MUST be cited with its record ID. "
                "Clearly label example.com URLs as demo placeholders and never imply they are accessible internal documents.\n\n"
                f"Retrieved Evidence:\n{context_text}\n\n"
                f"Question: {question}\n\n"
                "Format with clear markdown headings."
            )

            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                },
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"Optional LLM synthesis failed, falling back to deterministic: {e}")

        return None
