from __future__ import annotations

from typing import Any, Callable

from insight_action import InsightAction
from insight_action_repository import InsightActionRepository


class InsightActionService:
    """Insight Action 闭环服务，复用既有 Action 创建工厂。"""

    def __init__(self, repository: InsightActionRepository):
        self.repository = repository

    def getInsightActions(self, insight_id: int) -> list[dict[str, Any]]:
        return self.repository.list_for_insight(insight_id)

    def createActionForInsight(
        self,
        insight_id: int,
        payload: dict[str, Any],
        action_creator: Callable[..., dict[str, Any] | None],
        now: str | None = None,
    ) -> tuple[InsightAction, dict[str, Any]]:
        insight = self.repository.db.execute(
            "SELECT * FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not insight:
            raise LookupError("insight not found")
        priority = str(payload.get("priority", "medium") or "medium").strip() or "medium"
        reason = str(payload.get("reason", insight["description"]) or "").strip()
        if not reason:
            raise ValueError("reason is required")
        title = str(payload.get("title", "") or "").strip() or f"跟进洞察：{insight['name']}"
        action = action_creator(
            title=title,
            description=payload.get("description", insight["description"]),
            action_type=payload.get("actionType", "follow_up"),
            status=payload.get("status", "pending"),
            priority=priority,
            assignee=payload.get("assignee", ""),
            due_at=payload.get("dueAt"),
            opportunity_id=payload.get("opportunityId"),
            project_id=payload.get("projectId"),
            customer_id=payload.get("customerId", insight["customer_id"]),
            customer_organization_id=payload.get("customerOrganizationId"),
            customer_development_id=payload.get("customerDevelopmentId"),
            person_id=payload.get("personId"),
            stage_code=payload.get("stageCode"),
            stage_name=payload.get("stageName"),
            source_type="insight",
            source_id=f"insight:{insight_id}",
            source_agent_id=payload.get("sourceAgentId"),
            source_agent_run_id=payload.get("sourceAgentRunId"),
            created_by=payload.get("createdBy", "AI Insight Agent"),
            dedupe_key=payload.get("dedupeKey", f"insight:{insight_id}:{title}"),
            now=now,
        )
        if not action:
            raise LookupError("action could not be created")
        relation = self.repository.create(insight_id, action["id"], priority, reason, now)
        return relation, action
