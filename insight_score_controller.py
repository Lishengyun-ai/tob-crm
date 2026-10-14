from __future__ import annotations

import re
from typing import Any

from insight_score_service import InsightScoreService


class InsightScoreController:
    def __init__(self, service: InsightScoreService):
        self.service = service

    def handle(
        self, method: str, path: str, now: str | None = None,
        minimum_score: int | None = None,
    ) -> tuple[int, Any]:
        if path == "/api/insight-scores" and method.upper() == "GET":
            return 200, [score.to_dict() for score in self.service.listScores(minimum_score)]
        match = re.fullmatch(r"/api/insights/(\d+)/score", path)
        if match:
            insight_id = int(match.group(1))
            if method.upper() == "GET":
                score = self.service.getInsightScore(insight_id)
                if score is None:
                    raise LookupError("insight score not found")
                return 200, score.to_dict()
            if method.upper() == "POST":
                return 201, self.service.scoreInsight(insight_id, now).to_dict()
        raise LookupError("insight score route not found")
