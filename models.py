from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    database_graph: str
    message: str
    details: Optional[Dict[str, Any]] = None


class PersonModel(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    team: Optional[str] = None
    relationship: str  # e.g., 'OWNS', 'KNOWS_ABOUT'


class SourceRecordModel(BaseModel):
    id: str
    type: str  # Document, Message, Ticket
    title: str
    url: Optional[str] = None
    content: Optional[str] = None


class DecisionModel(BaseModel):
    id: str
    title: str
    status: str  # 'current', 'superseded', etc.
    detail: Optional[str] = None
    made_by: Optional[str] = None
    made_by_id: Optional[str] = None
    supported_by_people: List[str] = Field(default_factory=list)
    supported_by_ids: List[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    sources: List[SourceRecordModel] = Field(default_factory=list)


class SystemNode(BaseModel):
    id: str
    name: str


class DependencyLink(BaseModel):
    source_id: str
    source_name: str
    target_id: str
    target_name: str
    type: str = "DEPENDS_ON"
    depth: int = 1


class SystemInvestigation(BaseModel):
    system: SystemNode
    owners: List[PersonModel] = Field(default_factory=list)
    experts: List[PersonModel] = Field(default_factory=list)
    downstream_dependencies: List[SystemNode] = Field(default_factory=list)
    upstream_callers: List[SystemNode] = Field(default_factory=list)
    decisions: List[DecisionModel] = Field(default_factory=list)
    source_records: List[SourceRecordModel] = Field(default_factory=list)
    active_tasks: List[Dict[str, Any]] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    citation_id: str
    source_type: str  # 'Person', 'Decision', 'Document', 'Message', 'Ticket', 'System'
    label: str
    detail: str
    url: Optional[str] = None


class AgentQueryRequest(BaseModel):
    question: str
    system_context: Optional[str] = None


class AgentQueryResponse(BaseModel):
    question: str
    answer: str
    confidence: str  # 'high', 'moderate', 'uncertain'
    is_uncertain: bool = False
    uncertainty_reason: Optional[str] = None
    citations: List[EvidenceCitation] = Field(default_factory=list)
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)
    suggested_followups: List[str] = Field(default_factory=list)


class ProposedTask(BaseModel):
    id: str
    action_type: str  # 'update_owner', 'update_decision_status', 'create_task'
    title: str
    description: str
    target_id: str
    target_name: Optional[str] = None
    proposed_changes: Dict[str, Any]
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None
    requested_by: str = "Company Brain Agent"
    status: str = "pending_approval"  # 'pending_approval', 'approved', 'rejected'
    created_at: str
    resolution_note: Optional[str] = None


class TaskApprovalRequest(BaseModel):
    task_id: str
    approved: bool
    actor: str
    reason: Optional[str] = None


class TaskApprovalResponse(BaseModel):
    task_id: str
    status: str
    applied: bool
    message: str
    re_queried_state: Optional[Dict[str, Any]] = None


class GraphOverview(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
