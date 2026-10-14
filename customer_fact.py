from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class FactType(str, Enum):
    CUSTOMER_BASIC = "CUSTOMER_BASIC"
    ORGANIZATION = "ORGANIZATION"
    PURCHASE = "PURCHASE"
    PROJECT = "PROJECT"
    RELATIONSHIP = "RELATIONSHIP"
    BEHAVIOR = "BEHAVIOR"
    COMPETITOR = "COMPETITOR"
    STRATEGY = "STRATEGY"


FACT_TYPES = {fact_type.value for fact_type in FactType}
VERIFICATION_STATUSES = {"PENDING", "VERIFIED", "REJECTED"}
FACT_STATUSES = {"ACTIVE", "INACTIVE", "ARCHIVED"}


@dataclass(frozen=True)
class CustomerFact:
    """客户事实 Entity；字段命名与 API/业务对象保持一致。"""

    id: int
    customerId: int
    factType: str
    factName: str
    factContent: str
    factValue: str
    confidenceScore: Optional[int]
    sourceType: str
    sourceId: Optional[str]
    status: str
    validFrom: Optional[str]
    validTo: Optional[str]

    @classmethod
    def from_row(cls, row: Any) -> "CustomerFact":
        data = dict(row)
        entity = cls(
            id=data["fact_id"],
            customerId=data["customer_id"],
            factType=data["fact_type"],
            factName=data["fact_name"],
            factContent=data["fact_content"],
            factValue=data["fact_value"],
            confidenceScore=data["confidence_score"],
            sourceType=data["source_type"],
            sourceId=data["source_id"],
            status=data["status"],
            validFrom=data["valid_from"],
            validTo=data["valid_to"],
        )
        # Repository 仍需要读取数据库审计时间，但它不是本 Entity 的业务字段。
        object.__setattr__(entity, "_created_time", data.get("created_time"))
        object.__setattr__(entity, "_updated_time", data.get("updated_time"))
        return entity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # 兼容当前 SQLite Repository 的内部命名，不增加 Entity 字段。
    @property
    def fact_id(self) -> int:
        return self.id

    @property
    def customer_id(self) -> int:
        return self.customerId

    @property
    def fact_type(self) -> str:
        return self.factType

    @property
    def fact_name(self) -> str:
        return self.factName

    @property
    def fact_content(self) -> str:
        return self.factContent

    @property
    def fact_value(self) -> str:
        return self.factValue

    @property
    def confidence_score(self) -> Optional[int]:
        return self.confidenceScore

    @property
    def source_type(self) -> str:
        return self.sourceType

    @property
    def source_id(self) -> Optional[str]:
        return self.sourceId

    @property
    def valid_from(self) -> Optional[str]:
        return self.validFrom

    @property
    def valid_to(self) -> Optional[str]:
        return self.validTo

    @property
    def created_time(self) -> Optional[str]:
        return getattr(self, "_created_time", None)

    @property
    def updated_time(self) -> Optional[str]:
        return getattr(self, "_updated_time", None)


class CustomerFactRepository:
    """SQLite 映射模型，封装 CustomerFact 的存取和领域校验。"""

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = str(payload.get(key, "")).strip()
        if not value:
            raise ValueError(f"{key} is required")
        return value

    @staticmethod
    def _optional_text(payload: dict[str, Any], key: str, default: str = "") -> str:
        value = payload.get(key, default)
        return default if value is None else str(value).strip()

    @staticmethod
    def _optional_score(payload: dict[str, Any], key: str = "confidenceScore") -> Optional[int]:
        value = payload.get(key)
        if value is None or value == "":
            return None
        try:
            score = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidenceScore must be an integer between 0 and 100") from exc
        if not 0 <= score <= 100:
            raise ValueError("confidenceScore must be between 0 and 100")
        return score

    def _customer_exists(self, customer_id: int) -> bool:
        return bool(self.db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone())

    def _normalize(self, payload: dict[str, Any], existing: Optional[CustomerFact] = None) -> dict[str, Any]:
        existing_fields = {
            "factType": "fact_type",
            "factName": "fact_name",
            "factContent": "fact_content",
            "factValue": "fact_value",
            "sourceType": "source_type",
            "sourceId": "source_id",
            "confidenceScore": "confidence_score",
            "verificationStatus": "verification_status",
            "validFrom": "valid_from",
            "validTo": "valid_to",
            "createdBy": "created_by",
        }

        def value(key: str, default: Any = "") -> Any:
            if key in payload:
                return payload[key]
            return getattr(existing, existing_fields.get(key, key), default) if existing else default

        fact_type = str(value("factType")).strip().upper()
        if fact_type not in FACT_TYPES:
            raise ValueError(f"factType must be one of: {', '.join(sorted(FACT_TYPES))}")
        verification_status = str(value("verificationStatus", "PENDING")).strip().upper()
        if verification_status not in VERIFICATION_STATUSES:
            raise ValueError(f"verificationStatus must be one of: {', '.join(sorted(VERIFICATION_STATUSES))}")
        status = str(value("status", "ACTIVE")).strip().upper()
        if status not in FACT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(FACT_STATUSES))}")
        fact_name = str(value("factName")).strip()
        if not fact_name:
            raise ValueError("factName is required")

        score_source = {"confidenceScore": value("confidenceScore", None)}
        return {
            "fact_type": fact_type,
            "fact_name": fact_name,
            "fact_content": "" if value("factContent") is None else str(value("factContent")).strip(),
            "fact_value": "" if value("factValue") is None else str(value("factValue")).strip(),
            "unit": "" if value("unit") is None else str(value("unit")).strip(),
            "source_type": str(value("sourceType", "manual")).strip() or "manual",
            "source_id": "" if value("sourceId") is None else str(value("sourceId")).strip(),
            "confidence_score": self._optional_score(score_source),
            "verification_status": verification_status,
            "valid_from": value("validFrom", None),
            "valid_to": value("validTo", None),
            "status": status,
            "created_by": str(value("createdBy", "system")).strip() or "system",
        }

    def get(self, fact_id: int) -> Optional[CustomerFact]:
        row = self.db.execute("SELECT * FROM customer_facts WHERE fact_id = ?", (fact_id,)).fetchone()
        return CustomerFact.from_row(row) if row else None

    def list_for_customer(self, customer_id: int, fact_type: Optional[str] = None, status: Optional[str] = None) -> list[CustomerFact]:
        if not self._customer_exists(customer_id):
            raise LookupError("customer not found")
        clauses = ["customer_id = ?"]
        values: list[Any] = [customer_id]
        if fact_type:
            normalized_type = fact_type.strip().upper()
            if normalized_type not in FACT_TYPES:
                raise ValueError(f"factType must be one of: {', '.join(sorted(FACT_TYPES))}")
            clauses.append("fact_type = ?")
            values.append(normalized_type)
        if status:
            normalized_status = status.strip().upper()
            if normalized_status not in FACT_STATUSES:
                raise ValueError(f"status must be one of: {', '.join(sorted(FACT_STATUSES))}")
            clauses.append("status = ?")
            values.append(normalized_status)
        rows = self.db.execute(
            f"SELECT * FROM customer_facts WHERE {' AND '.join(clauses)} ORDER BY updated_time DESC, fact_id DESC",
            tuple(values),
        ).fetchall()
        return [CustomerFact.from_row(row) for row in rows]

    def create(self, customer_id: int, payload: dict[str, Any], now: Optional[str] = None) -> CustomerFact:
        if not self._customer_exists(customer_id):
            raise LookupError("customer not found")
        data = self._normalize(payload)
        timestamp = now or self._now()
        cur = self.db.execute(
            """INSERT INTO customer_facts
               (customer_id, fact_type, fact_name, fact_content, fact_value, unit,
                source_type, source_id, confidence_score, verification_status,
                valid_from, valid_to, status, created_by, created_time, updated_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (customer_id, *data.values(), timestamp, timestamp),
        )
        return self.get(cur.lastrowid)  # type: ignore[return-value]

    def update(self, fact_id: int, payload: dict[str, Any], now: Optional[str] = None) -> CustomerFact:
        existing = self.get(fact_id)
        if not existing:
            raise LookupError("customer fact not found")
        data = self._normalize(payload, existing)
        timestamp = now or self._now()
        self.db.execute(
            """UPDATE customer_facts
               SET fact_type = ?, fact_name = ?, fact_content = ?, fact_value = ?, unit = ?,
                   source_type = ?, source_id = ?, confidence_score = ?, verification_status = ?,
                   valid_from = ?, valid_to = ?, status = ?, created_by = ?, updated_time = ?
               WHERE fact_id = ?""",
            (*data.values(), timestamp, fact_id),
        )
        return self.get(fact_id)  # type: ignore[return-value]

    def delete(self, fact_id: int) -> None:
        cur = self.db.execute("DELETE FROM customer_facts WHERE fact_id = ?", (fact_id,))
        if not cur.rowcount:
            raise LookupError("customer fact not found")
