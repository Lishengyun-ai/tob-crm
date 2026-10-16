from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class InsightType(str, Enum):
    OPPORTUNITY = "Opportunity"
    RISK = "Risk"
    BREAKTHROUGH = "Breakthrough"
    COMPETITION = "Competition"
    RECOMMENDATION = "Recommendation"


INSIGHT_TYPES = {insight_type.value for insight_type in InsightType}


@dataclass(frozen=True)
class Insight:
    """AI Insight Ontology 的核心业务对象。"""

    id: int
    customerId: int
    name: str
    type: str
    description: str
    source: str
    created_time: str
    judgment: str = ""
    evidence: Any = None
    risk: str = ""
    recommendation: str = ""
    confidence: int = 0
    status: str = "active"
    expires_at: str | None = None
    updated_time: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "Insight":
        data = dict(row)
        return cls(
            id=data["id"],
            customerId=data["customer_id"],
            name=data["name"],
            type=data["type"],
            description=data["description"],
            source=data["source"],
            created_time=data["created_time"],
            judgment=data.get("judgment", ""),
            evidence=_json_value(data.get("evidence_json", "[]"), []),
            risk=data.get("risk", ""),
            recommendation=data.get("recommendation", ""),
            confidence=int(data.get("confidence", 0) or 0),
            status=data.get("status", "active"),
            expires_at=data.get("expires_at"),
            updated_time=data.get("updated_time") or data.get("created_time"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _json_value(value: Any, fallback: Any):
    import json
    try:
        return json.loads(value or "null")
    except (TypeError, ValueError):
        return fallback
