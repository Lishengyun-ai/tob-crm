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
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
