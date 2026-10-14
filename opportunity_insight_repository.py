from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from insight import Insight
from opportunity_insight import OpportunityInsight


class OpportunityInsightRepository:
    """OpportunityInsight 关联的 SQLite 数据访问层。"""

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_opportunity(self, opportunity_id: int) -> None:
        if not self.db.execute("SELECT 1 FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone():
            raise LookupError("opportunity not found")

    def _ensure_insight(self, insight_id: int) -> None:
        if not self.db.execute("SELECT 1 FROM insights WHERE id = ?", (insight_id,)).fetchone():
            raise LookupError("insight not found")

    def create(self, opportunity_id: int, insight_id: int, now: str | None = None) -> OpportunityInsight:
        self._ensure_opportunity(opportunity_id)
        self._ensure_insight(insight_id)
        timestamp = now or self._now()
        try:
            cursor = self.db.execute(
                """INSERT INTO opportunity_insights (opportunity_id, insight_id, created_time)
                   VALUES (?, ?, ?)""",
                (opportunity_id, insight_id, timestamp),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("opportunity insight relation already exists") from exc
            raise
        relation = self.get(cursor.lastrowid)
        if relation is None:
            raise LookupError("opportunity insight relation could not be created")
        return relation

    def get(self, relation_id: int) -> OpportunityInsight | None:
        row = self.db.execute(
            "SELECT * FROM opportunity_insights WHERE id = ?", (relation_id,)
        ).fetchone()
        return OpportunityInsight.from_row(row) if row else None

    def list_for_opportunity(self, opportunity_id: int) -> list[OpportunityInsight]:
        self._ensure_opportunity(opportunity_id)
        rows = self.db.execute(
            """SELECT * FROM opportunity_insights
               WHERE opportunity_id = ? ORDER BY created_time DESC, id DESC""",
            (opportunity_id,),
        ).fetchall()
        return [OpportunityInsight.from_row(row) for row in rows]

    def list_insights_for_opportunity(self, opportunity_id: int) -> list[Insight]:
        self._ensure_opportunity(opportunity_id)
        rows = self.db.execute(
            """SELECT i.*
               FROM insights i
               JOIN opportunity_insights oi ON oi.insight_id = i.id
               WHERE oi.opportunity_id = ?
               ORDER BY i.created_time DESC, i.id DESC""",
            (opportunity_id,),
        ).fetchall()
        return [Insight.from_row(row) for row in rows]

    def grouped_insights_for_opportunity(self, opportunity_id: int) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {
            "opportunities": [],
            "risks": [],
            "breakthrough": [],
            "competition": [],
        }
        key_by_type = {
            "Opportunity": "opportunities",
            "Risk": "risks",
            "Breakthrough": "breakthrough",
            "Competition": "competition",
        }
        for insight in self.list_insights_for_opportunity(opportunity_id):
            key = key_by_type.get(insight.type)
            if key:
                groups[key].append(insight.to_dict())
        return groups
