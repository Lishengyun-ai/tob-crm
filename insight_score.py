from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InsightScore:
    """Insight 优先级评分结果，所有分项和总分范围均为 0-100。"""

    id: int
    insightId: int
    confidence: int
    businessValue: int
    urgency: int
    actionability: int
    score: int
    created_time: str

    @classmethod
    def from_row(cls, row: Any) -> "InsightScore":
        data = dict(row)
        return cls(
            id=data["id"],
            insightId=data["insight_id"],
            confidence=data["confidence"],
            businessValue=data["business_value"],
            urgency=data["urgency"],
            actionability=data["actionability"],
            score=data["score"],
            created_time=data["created_time"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
