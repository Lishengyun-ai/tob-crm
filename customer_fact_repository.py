from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from customer_fact import FACT_TYPES, CustomerFact


class CustomerFactRepository:
    """CustomerFact 数据访问层。"""

    def __init__(self, db: Any):
        self.db = db

    def _query(self, where: str = "", values: tuple[Any, ...] = ()) -> list[CustomerFact]:
        sql = "SELECT * FROM customer_facts"
        if where:
            sql += f" WHERE {where}"
        sql += " ORDER BY updated_time DESC, fact_id DESC"
        rows = self.db.execute(sql, values).fetchall()
        return [CustomerFact.from_row(row) for row in rows]

    def find_by_customer_id(self, customer_id: int) -> list[CustomerFact]:
        return self._query("customer_id = ?", (customer_id,))

    def find_by_fact_type(self, fact_type: str) -> list[CustomerFact]:
        return self._query("fact_type = ?", (fact_type,))

    def find_active(self, customer_id: Optional[int] = None) -> list[CustomerFact]:
        if customer_id is None:
            return self._query("status = 'ACTIVE'")
        return self._query("customer_id = ? AND status = 'ACTIVE'", (customer_id,))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get(self, fact_id: int) -> Optional[CustomerFact]:
        row = self.db.execute("SELECT * FROM customer_facts WHERE fact_id = ?", (fact_id,)).fetchone()
        return CustomerFact.from_row(row) if row else None

    def create(self, customer_id: int, data: dict[str, Any], now: Optional[str] = None) -> CustomerFact:
        fact_type = str(data.get("factType", "")).strip().upper()
        if fact_type not in FACT_TYPES:
            raise ValueError("invalid factType")
        fact_name = str(data.get("factName", "")).strip()
        if not fact_name:
            raise ValueError("factName is required")
        timestamp = now or self._now()
        cursor = self.db.execute(
            """INSERT INTO customer_facts
               (customer_id, fact_type, fact_name, fact_content, fact_value,
                source_type, source_id, confidence_score, verification_status,
                valid_from, valid_to, status, created_by, created_time, updated_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, 'ACTIVE', ?, ?, ?)""",
            (
                customer_id,
                fact_type,
                fact_name,
                str(data.get("factContent", "") or ""),
                str(data.get("factValue", "") or ""),
                str(data.get("sourceType", "manual") or "manual"),
                str(data.get("sourceId", "") or ""),
                data.get("confidenceScore"),
                data.get("validFrom"),
                data.get("validTo"),
                str(data.get("createdBy", "system") or "system"),
                timestamp,
                timestamp,
            ),
        )
        fact = self.get(cursor.lastrowid)
        if fact is None:
            raise LookupError("customer fact could not be created")
        return fact

    def expire(self, fact_id: int, now: Optional[str] = None) -> CustomerFact:
        timestamp = now or self._now()
        cursor = self.db.execute(
            "UPDATE customer_facts SET status = 'INACTIVE', updated_time = ? WHERE fact_id = ?",
            (timestamp, fact_id),
        )
        if not cursor.rowcount:
            raise LookupError("customer fact not found")
        return self.get(fact_id)  # type: ignore[return-value]

    def verify(self, fact_id: int, now: Optional[str] = None) -> CustomerFact:
        timestamp = now or self._now()
        cursor = self.db.execute(
            """UPDATE customer_facts
               SET verification_status = 'VERIFIED', updated_time = ?
               WHERE fact_id = ?""",
            (timestamp, fact_id),
        )
        if not cursor.rowcount:
            raise LookupError("customer fact not found")
        return self.get(fact_id)  # type: ignore[return-value]
