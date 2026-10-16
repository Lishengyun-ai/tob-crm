from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import json

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
            "judgment": data.get("judgment", existing.judgment if existing else ""),
            "evidence": data.get("evidence", existing.evidence if existing else []),
            "risk": data.get("risk", existing.risk if existing else ""),
            "recommendation": data.get("recommendation", existing.recommendation if existing else ""),
            "confidence": data.get("confidence", existing.confidence if existing else 0),
            "status": data.get("status", existing.status if existing else "active"),
            "expires_at": data.get("expiresAt", existing.expires_at if existing else None),
            "source_agent_id": data.get("sourceAgentId"),
            "source_agent_run_id": data.get("sourceAgentRunId"),
        }
        status = str(values["status"] or "active").strip() or "active"
        if status not in {"active", "recommended", "accepted", "dismissed", "expired", "completed"}:
            raise ValueError("invalid insight status")
        return {
            "customer_id": self._customer_id(values["customerId"]),
            "name": self._required_text(values, "name"),
            "type": self._insight_type(values["type"]),
            "description": self._required_text(values, "description"),
            "source": self._required_text(values, "source"),
            "judgment": str(values["judgment"] or "").strip(),
            "evidence": values["evidence"] if isinstance(values["evidence"], (list, dict)) else [],
            "risk": str(values["risk"] or "").strip(),
            "recommendation": str(values["recommendation"] or "").strip(),
            "confidence": max(0, min(100, int(values["confidence"] or 0))),
            "status": status,
            "expires_at": values["expires_at"],
            "source_agent_id": values["source_agent_id"],
            "source_agent_run_id": values["source_agent_run_id"],
        }

    def _has_columns(self, names: list[str]) -> bool:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(insights)").fetchall()}
        return all(name in columns for name in names)

    def _audit(self, insight_id: int, event_type: str, from_status: str | None, to_status: str | None, actor: str = "system", metadata: Any = None, now: str | None = None):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='insight_action_audits'").fetchone():
            return
        self.db.execute("INSERT INTO insight_action_audits (insight_id, event_type, from_status, to_status, actor, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (insight_id, event_type, from_status, to_status, actor, json.dumps(metadata or {}, ensure_ascii=False), now or self._now()))

    def get(self, insight_id: int) -> Optional[Insight]:
        self._expire_if_needed(insight_id)
        row = self.db.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
        return Insight.from_row(row) if row else None

    def _expire_if_needed(self, insight_id: int) -> None:
        if not self._has_columns(["expires_at", "status"]):
            return
        row = self.db.execute("SELECT status, expires_at FROM insights WHERE id = ?", (insight_id,)).fetchone()
        if row and row["expires_at"] and row["status"] not in {"dismissed", "completed", "expired"} and str(row["expires_at"]) <= self._now():
            self.db.execute("UPDATE insights SET status = 'expired', updated_time = ? WHERE id = ?", (self._now(), insight_id))
            self._audit(insight_id, "expired", row["status"], "expired")

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
        for row in rows:
            self._expire_if_needed(row["id"])
        if rows and self._has_columns(["expires_at", "status"]):
            rows = self.db.execute(f"SELECT * FROM insights{where} ORDER BY created_time DESC, id DESC", tuple(values)).fetchall()
        return [Insight.from_row(row) for row in rows]

    def create(self, data: dict[str, Any], now: Optional[str] = None) -> Insight:
        values = self._normalize(data)
        timestamp = now or self._now()
        if self._has_columns(["judgment", "evidence_json", "status"]):
            cursor = self.db.execute("""INSERT INTO insights
              (customer_id, name, type, description, source, judgment, evidence_json, risk, recommendation, confidence, status, expires_at, source_agent_id, source_agent_run_id, updated_time, created_time)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (values["customer_id"], values["name"], values["type"], values["description"], values["source"], values["judgment"], json.dumps(values["evidence"], ensure_ascii=False), values["risk"], values["recommendation"], values["confidence"], values["status"], values["expires_at"], values["source_agent_id"], values["source_agent_run_id"], timestamp, timestamp))
        else:
            cursor = self.db.execute("INSERT INTO insights (customer_id, name, type, description, source, created_time) VALUES (?, ?, ?, ?, ?, ?)", (values["customer_id"], values["name"], values["type"], values["description"], values["source"], timestamp))
        insight = self.get(cursor.lastrowid)
        if insight is None:
            raise LookupError("insight could not be created")
        self._audit(insight.id, "recommended", None, insight.status, actor=values["source"], metadata={"source": values["source"]}, now=timestamp)
        return insight

    def update(self, insight_id: int, data: dict[str, Any]) -> Insight:
        existing = self.get(insight_id)
        if existing is None:
            raise LookupError("insight not found")
        values = self._normalize(data, existing)
        previous_status = existing.status
        if self._has_columns(["judgment", "evidence_json", "status"]):
            self.db.execute("""UPDATE insights SET customer_id = ?, name = ?, type = ?, description = ?, source = ?, judgment = ?, evidence_json = ?, risk = ?, recommendation = ?, confidence = ?, status = ?, expires_at = ?, source_agent_id = ?, source_agent_run_id = ?, updated_time = ? WHERE id = ?""", (values["customer_id"], values["name"], values["type"], values["description"], values["source"], values["judgment"], json.dumps(values["evidence"], ensure_ascii=False), values["risk"], values["recommendation"], values["confidence"], values["status"], values["expires_at"], values["source_agent_id"], values["source_agent_run_id"], self._now(), insight_id))
        else:
            self.db.execute("UPDATE insights SET customer_id = ?, name = ?, type = ?, description = ?, source = ? WHERE id = ?", (values["customer_id"], values["name"], values["type"], values["description"], values["source"], insight_id))
        if values["status"] != previous_status:
            event = "accepted" if values["status"] == "accepted" else "dismissed" if values["status"] == "dismissed" else "completed" if values["status"] == "completed" else "status_changed"
            self._audit(insight_id, event, previous_status, values["status"], actor=str(data.get("actor", "sales")), metadata=data)
        return self.get(insight_id)  # type: ignore[return-value]

    def delete(self, insight_id: int) -> None:
        cursor = self.db.execute("DELETE FROM insights WHERE id = ?", (insight_id,))
        if not cursor.rowcount:
            raise LookupError("insight not found")
