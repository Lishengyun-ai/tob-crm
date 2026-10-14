from __future__ import annotations

from typing import Any

from opportunity_insight import OpportunityInsight
from opportunity_insight_repository import OpportunityInsightRepository


class OpportunityInsightService:
    """商机洞察关联领域服务。"""

    def __init__(self, repository: OpportunityInsightRepository):
        self.repository = repository

    def createRelation(self, opportunity_id: int, insight_id: int) -> OpportunityInsight:
        return self.repository.create(opportunity_id, insight_id)

    def getOpportunityInsights(self, opportunity_id: int) -> dict[str, list[dict[str, Any]]]:
        return self.repository.grouped_insights_for_opportunity(opportunity_id)
