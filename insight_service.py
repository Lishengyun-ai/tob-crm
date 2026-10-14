from __future__ import annotations

from typing import Any, Optional

from insight import Insight
from insight_repository import InsightRepository


class InsightService:
    """Insight 领域服务，保持 API 与持久化实现解耦。"""

    def __init__(self, repository: InsightRepository):
        self.repository = repository

    def listInsights(
        self,
        insight_type: Optional[str] = None,
        source: Optional[str] = None,
        customer_id: Optional[int] = None,
    ) -> list[Insight]:
        return self.repository.list(insight_type, source, customer_id)

    def getInsight(self, insight_id: int) -> Optional[Insight]:
        return self.repository.get(insight_id)

    def createInsight(self, data: dict[str, Any]) -> Insight:
        return self.repository.create(data)

    def updateInsight(self, insight_id: int, data: dict[str, Any]) -> Insight:
        return self.repository.update(insight_id, data)

    def deleteInsight(self, insight_id: int) -> None:
        self.repository.delete(insight_id)
