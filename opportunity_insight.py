from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OpportunityInsight:
    """Opportunity 与 Insight 之间的可追踪关联 Entity。"""

    id: int
    opportunityId: int
    insightId: int
    created_time: str

    @classmethod
    def from_row(cls, row: Any) -> "OpportunityInsight":
        data = dict(row)
        return cls(
            id=data["id"],
            opportunityId=data["opportunity_id"],
            insightId=data["insight_id"],
            created_time=data["created_time"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
