from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from insight import INSIGHT_TYPES, Insight


class InsightRepository:
    """Insight 的 SQLite 数据访问与字段校验。"""

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _required_text(data: dict[str, Any], key: str) -> str:
        value = str(data.get(key, "") or "").strip()
        if not value:
            raise ValueError(f"{key} is required")
        return value

    @staticmethod
    def _insight_type(value: Any) -> str:
        insight_type = str(value or "").strip()
        if insight_type not in INSIGHT_TYPES:
            raise ValueError(f"type must be one of: {', '.join(sorted(INSIGHT_TYPES))}")
        return insight_type

    def _customer_id(self, value: Any) -> int:
        try:
            customer_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("customerId must be an integer") from exc
        if not self.db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
            raise LookupError("customer not found")
        return customer_id

    def _normalize(self, data: dict[str, Any], existing: Optional[Insight] = None) -> dict[str, Any]:
        values = {
            "customerId": data.get("customerId", existing.customerId if existing else None),
            "name": data.get("name", existing.name if existing else ""),
            "type": data.get("type", existing.type if existing else ""),
            "description": data.get("description", existing.description if existing else ""),
            "source": data.get("source", existing.source if existing else ""),
        }
        return {
            "customer_id": self._customer_id(values["customerId"]),
            "name": self._required_text(values, "name"),
            "type": self._insight_type(values["type"]),
            "description": self._required_text(values, "description"),
            "source": self._required_text(values, "source"),
        }

    def get(self, insight_id: int) -> Optional[Insight]:
        row = self.db.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
        return Insight.from_row(row) if row else None

    def list(
        self,
        insight_type: Optional[str] = None,
        source: Optional[str] = None,
        customer_id: Optional[int] = None,
    ) -> list[Insight]:
        clauses: list[str] = []
        values: list[Any] = []
        if insight_type:
            clauses.append("type = ?")
            values.append(self._insight_type(insight_type))
        if source:
            clauses.append("source = ?")
            values.append(source.strip())
        if customer_id is not None:
            customer_id = self._customer_id(customer_id)
            clauses.append("customer_id = ?")
            values.append(customer_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM insights{where} ORDER BY created_time DESC, id DESC", tuple(values)
        ).fetchall()
        return [Insight.from_row(row) for row in rows]

    def create(self, data: dict[str, Any], now: Optional[str] = None) -> Insight:
        values = self._normalize(data)
        timestamp = now or self._now()
        cursor = self.db.execute(
            """INSERT INTO insights (customer_id, name, type, description, source, created_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (values["customer_id"], values["name"], values["type"], values["description"], values["source"], timestamp),
        )
        insight = self.get(cursor.lastrowid)
        if insight is None:
            raise LookupError("insight could not be created")
        return insight

    def update(self, insight_id: int, data: dict[str, Any]) -> Insight:
        existing = self.get(insight_id)
        if existing is None:
            raise LookupError("insight not found")
        values = self._normalize(data, existing)
        self.db.execute(
            """UPDATE insights
               SET customer_id = ?, name = ?, type = ?, description = ?, source = ?
               WHERE id = ?""",
            (values["customer_id"], values["name"], values["type"], values["description"], values["source"], insight_id),
        )
        return self.get(insight_id)  # type: ignore[return-value]

    def delete(self, insight_id: int) -> None:
        cursor = self.db.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
        if not cursor.rowcount:
            raise LookupError("insight not found")
