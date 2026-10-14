from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from insight_action import InsightAction


class InsightActionRepository:
    """InsightAction 关系的 SQLite 数据访问层。"""

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_insight(self, insight_id: int) -> None:
        if not self.db.execute("SELECT 1 FROM insights WHERE id = ?", (insight_id,)).fetchone():
            raise LookupError("insight not found")

    def _ensure_action(self, action_id: int) -> None:
        if not self.db.execute("SELECT 1 FROM actions WHERE id = ?", (action_id,)).fetchone():
            raise LookupError("action not found")

    def create(
        self,
        insight_id: int,
        action_id: int,
        priority: str,
        reason: str,
        now: str | None = None,
    ) -> InsightAction:
        self._ensure_insight(insight_id)
        self._ensure_action(action_id)
        priority = str(priority or "medium").strip() or "medium"
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        timestamp = now or self._now()
        try:
            cursor = self.db.execute(
                """INSERT INTO insight_actions
                   (insight_id, action_id, priority, reason, created_time)
                   VALUES (?, ?, ?, ?, ?)""",
                (insight_id, action_id, priority, reason, timestamp),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError("insight action relation already exists") from exc
            raise
        relation = self.get(cursor.lastrowid)
        if relation is None:
            raise LookupError("insight action relation could not be created")
        return relation

    def get(self, relation_id: int) -> InsightAction | None:
        row = self.db.execute(
            "SELECT * FROM insight_actions WHERE id = ?", (relation_id,)
        ).fetchone()
        return InsightAction.from_row(row) if row else None

    def list_for_insight(self, insight_id: int) -> list[dict[str, Any]]:
        self._ensure_insight(insight_id)
        rows = self.db.execute(
            """SELECT ia.*, a.*
               FROM insight_actions ia
               JOIN actions a ON a.id = ia.action_id
               WHERE ia.insight_id = ?
               ORDER BY ia.created_time DESC, ia.id DESC""",
            (insight_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.update({
                "insightActionId": row["id"],
                "insightId": row["insight_id"],
                "actionId": row["action_id"],
                "priority": row["priority"],
                "reason": row["reason"],
                "relationCreatedTime": row["created_time"],
            })
            result.append(item)
        return result
