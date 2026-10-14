from __future__ import annotations

from insight_score import InsightScore
from insight_score_repository import InsightScoreRepository


class InsightScoreService:
    def __init__(self, repository: InsightScoreRepository):
        self.repository = repository

    def scoreInsight(self, insight_id: int, now: str | None = None) -> InsightScore:
        return self.repository.score(insight_id, now)

    def getInsightScore(self, insight_id: int) -> InsightScore | None:
        return self.repository.get(insight_id)

    def listScores(self, minimum_score: int | None = None) -> list[InsightScore]:
        return self.repository.list(minimum_score)
