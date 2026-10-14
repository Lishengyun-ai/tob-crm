from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InsightAction:
    """Insight 与现有 Action 之间的闭环关联 Entity。"""

    id: int
    insightId: int
    actionId: int
    priority: str
    reason: str
    created_time: str

    @classmethod
    def from_row(cls, row: Any) -> "InsightAction":
        data = dict(row)
        return cls(
            id=data["id"],
            insightId=data["insight_id"],
            actionId=data["action_id"],
            priority=data["priority"],
            reason=data["reason"],
            created_time=data["created_time"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
