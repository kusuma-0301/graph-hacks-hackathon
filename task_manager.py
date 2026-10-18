import uuid
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from app.models import ProposedTask, TaskApprovalResponse
from app.graph_service import GraphService

logger = logging.getLogger("company_brain.task_manager")


class TaskManager:
    def __init__(self, graph_service: Optional[GraphService] = None):
        self.graph_service = graph_service or GraphService()
        self.tasks: Dict[str, ProposedTask] = {}
        # Pre-seed with a realistic proposed task related to the Payments latency incident
        self._seed_default_proposals()

    def _seed_default_proposals(self):
        sample_task_id = "prop-latency-001"
        self.tasks[sample_task_id] = ProposedTask(
            id=sample_task_id,
            action_type="create_task",
            title="Create incident triage task: Payments queue depth alert",
            description="Agent recommendation: Assign SRE incident response task to Noah Williams and Arjun Rao.",
            target_id="sys-payments",
            target_name="Payments Service",
            proposed_changes={
                "task_id": "task-inc-101",
                "title": "Investigate payment queue depth & timeout threshold",
                "system_id": "sys-payments",
                "assignee_id": "p4",
            },
            current_value="No active SRE task assigned",
            proposed_value="Assigned to Noah Williams (SRE)",
            requested_by="Company Brain Incident Agent",
            status="pending_approval",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        sample_owner_task = "prop-owner-002"
        self.tasks[sample_owner_task] = ProposedTask(
            id=sample_owner_task,
            action_type="update_owner",
            title="Designate Priya Shah as co-owner for Payments Service",
            description="Agent proposal: Given architectural dependencies, update ownership of Payments Service.",
            target_id="sys-payments",
            target_name="Payments Service",
            proposed_changes={
                "system_id": "sys-payments",
                "new_person_id": "p3",
            },
            current_value="Arjun Rao (Payments Engineer)",
            proposed_value="Priya Shah (Distributed Systems Expert)",
            requested_by="Company Brain Governance Agent",
            status="pending_approval",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def propose(
        self,
        action_type: str,
        title: str,
        description: str,
        target_id: str,
        proposed_changes: Dict[str, Any],
        current_value: Optional[Any] = None,
        proposed_value: Optional[Any] = None,
        requested_by: str = "Company Brain Agent",
        target_name: Optional[str] = None,
    ) -> ProposedTask:
        task_id = f"prop-{uuid.uuid4().hex[:8]}"
        task = ProposedTask(
            id=task_id,
            action_type=action_type,
            title=title,
            description=description,
            target_id=target_id,
            target_name=target_name or target_id,
            proposed_changes=proposed_changes,
            current_value=current_value,
            proposed_value=proposed_value,
            requested_by=requested_by,
            status="pending_approval",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> Optional[ProposedTask]:
        return self.tasks.get(task_id)

    def list_tasks(self, status: Optional[str] = None) -> List[ProposedTask]:
        """Return proposed tasks deduplicated by stable task ID."""
        seen: Dict[str, ProposedTask] = {}
        for t in self.tasks.values():
            if status and t.status != status:
                continue
            if t.id not in seen:
                seen[t.id] = t
        return list(seen.values())

    def review_task(
        self, task_id: str, approved: bool, actor: str, reason: Optional[str] = None
    ) -> TaskApprovalResponse:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Proposed task '{task_id}' not found.")

        if task.status != "pending_approval":
            return TaskApprovalResponse(
                task_id=task_id,
                status=task.status,
                applied=False,
                message=f"Task has already been processed with status '{task.status}'.",
            )

        if not approved:
            task.status = "rejected"
            task.resolution_note = f"Rejected by {actor}: {reason or 'No reason provided'}"
            return TaskApprovalResponse(
                task_id=task_id,
                status="rejected",
                applied=False,
                message=f"Proposal '{task.title}' was rejected by {actor}.",
            )

        # Apply the proposed write to FalkorDB
        re_queried_state = None
        applied_msg = ""
        action = task.action_type
        changes = task.proposed_changes

        try:
            if action == "update_owner":
                sys_id = changes.get("system_id") or task.target_id
                new_person_id = changes.get("new_person_id")
                re_queried_state = self.graph_service.safe_update_system_owner(
                    system_id=sys_id,
                    new_person_id=new_person_id,
                    actor=actor,
                    reason=reason or f"Approved proposal {task_id}: {task.title}",
                )
                applied_msg = f"System owner updated successfully to {re_queried_state.get('current_owner')}."

            elif action == "update_decision_status":
                dec_id = changes.get("decision_id") or task.target_id
                new_status = changes.get("new_status") or task.proposed_value
                re_queried_state = self.graph_service.safe_update_decision_status(
                    decision_id=dec_id,
                    new_status=new_status,
                    actor=actor,
                    reason=reason or f"Approved proposal {task_id}: {task.title}",
                )
                applied_msg = f"Decision status updated to '{new_status}' with provenance recorded."

            elif action == "create_task":
                new_t_id = changes.get("task_id", f"task-{uuid.uuid4().hex[:6]}")
                title = changes.get("title", task.title)
                sys_id = changes.get("system_id", task.target_id)
                assignee_id = changes.get("assignee_id")
                re_queried_state = self.graph_service.safe_create_task(
                    task_id=new_t_id,
                    title=title,
                    system_id=sys_id,
                    person_id=assignee_id,
                )
                applied_msg = f"New task '{new_t_id}' created and linked to system in FalkorDB."

            else:
                raise ValueError(f"Unknown action type '{action}'")

            task.status = "approved"
            task.resolution_note = f"Approved and applied by {actor}. Note: {reason or 'Approved'}"

            return TaskApprovalResponse(
                task_id=task_id,
                status="approved",
                applied=True,
                message=applied_msg,
                re_queried_state=re_queried_state,
            )

        except Exception as e:
            logger.error(f"Failed to apply task write: {e}")
            raise
