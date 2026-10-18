import os
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.db import get_graph
from app.models import (
    HealthResponse,
    SystemInvestigation,
    AgentQueryRequest,
    AgentQueryResponse,
    ProposedTask,
    TaskApprovalRequest,
    TaskApprovalResponse,
    GraphOverview,
)
from app.graph_service import GraphService
from app.agent import CompanyBrainAgent
from app.task_manager import TaskManager

logger = logging.getLogger("company_brain.api")

app = FastAPI(
    title="Company Brain API",
    description="Knowledge graph intelligence engine powered by FalkorDB for the iMakeDevs Hackathon",
    version="1.0.0",
)

# Enable CORS for Next.js frontend (default ports 3000, 3001, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

graph_service = GraphService()
agent = CompanyBrainAgent(graph_service=graph_service)
task_manager = TaskManager(graph_service=graph_service)


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Verify FalkorDB connectivity and return graph status."""
    try:
        g = get_graph()
        # Verify FalkorDB graph connectivity
        ping_res = g.query("RETURN 1")
        if not ping_res.result_set or ping_res.result_set[0][0] != 1:
            raise RuntimeError("Unexpected ping response from FalkorDB graph.")

        graph_name = os.getenv("FALKORDB_GRAPH", "company_brain")
        # Verify basic node count
        count_res = g.query("MATCH (n) RETURN count(n)")
        node_count = count_res.result_set[0][0] if count_res.result_set else 0

        return HealthResponse(
            status="healthy",
            database_connected=True,
            database_graph=graph_name,
            message="FalkorDB graph database is online and reachable.",
            details={"node_count": node_count},
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            database_connected=False,
            database_graph=os.getenv("FALKORDB_GRAPH", "company_brain"),
            message=f"Database connection error: {str(e)}",
            details=None,
        )


@app.get("/api/systems")
def list_systems():
    """Return all systems registered in Company Brain."""
    try:
        systems = graph_service.get_all_systems()
        return {"systems": systems, "count": len(systems)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/people")
def list_people():
    """Return all team members and their assignments."""
    try:
        people = graph_service.get_all_people()
        return {"people": people, "count": len(people)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system/{system_identifier}/investigation", response_model=SystemInvestigation)
def get_system_investigation(system_identifier: str):
    """Deep-dive investigation bundle for a given system."""
    try:
        return graph_service.investigate_system(system_identifier)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SystemQueryPayload(BaseModel):
    system: str


@app.post("/api/query/owners-and-experts")
def query_owners_and_experts(payload: SystemQueryPayload):
    """Retrieve verified system owner and experts via parameterized query."""
    try:
        result = graph_service.find_system_owners_and_experts(payload.system)
        if not result["system"]:
            raise HTTPException(status_code=404, detail=f"System '{payload.system}' not found in graph.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/query/decisions-and-sources")
def query_decisions_and_sources(payload: SystemQueryPayload):
    """Trace architectural decisions and supporting sources for a system."""
    try:
        return graph_service.get_architecture_decisions_and_sources(payload.system)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/query/downstream-dependencies")
def query_downstream_dependencies(payload: SystemQueryPayload):
    """Retrieve direct & transitive downstream dependencies and upstream callers."""
    try:
        result = graph_service.get_system_dependencies(payload.system)
        if not result["system"]:
            raise HTTPException(status_code=404, detail=f"System '{payload.system}' not found in graph.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/overview", response_model=GraphOverview)
def get_graph_overview():
    """Return all nodes and relationships to power the interactive visual graph explorer."""
    try:
        data = graph_service.get_full_graph_overview()
        return GraphOverview(nodes=data["nodes"], edges=data["edges"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/query", response_model=AgentQueryResponse)
def run_agent_query(payload: AgentQueryRequest):
    """
    Company Brain intelligent agent endpoint.
    Answers inquiries using strictly retrieved graph evidence and cites source records.
    Returns explicit uncertainty when evidence is insufficient.
    """
    try:
        return agent.query(question=payload.question, system_context=payload.system_context)
    except Exception as e:
        logger.error(f"Agent query failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks", response_model=List[ProposedTask])
def list_tasks(status_filter: Optional[str] = None):
    """List pending or all proposed tasks for human review."""
    return task_manager.list_tasks(status=status_filter)


class ProposeTaskPayload(BaseModel):
    action_type: str
    title: str
    description: str
    target_id: str
    proposed_changes: Dict[str, Any]
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None
    requested_by: str = "Company Brain Agent"
    target_name: Optional[str] = None


@app.post("/api/tasks/propose", response_model=ProposedTask)
def propose_task(payload: ProposeTaskPayload):
    """Propose an update or task. Does not write to graph until approved."""
    return task_manager.propose(
        action_type=payload.action_type,
        title=payload.title,
        description=payload.description,
        target_id=payload.target_id,
        proposed_changes=payload.proposed_changes,
        current_value=payload.current_value,
        proposed_value=payload.proposed_value,
        requested_by=payload.requested_by,
        target_name=payload.target_name,
    )


@app.post("/api/tasks/approve", response_model=TaskApprovalResponse)
def approve_task(payload: TaskApprovalRequest):
    """
    Human-in-the-loop task review endpoint.
    Applies the proposed write to FalkorDB only upon explicit approval,
    preserves audit provenance, and immediately returns the re-queried graph state.
    """
    try:
        return task_manager.review_task(
            task_id=payload.task_id,
            approved=payload.approved,
            actor=payload.actor,
            reason=payload.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
