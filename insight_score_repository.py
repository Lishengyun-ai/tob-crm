from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from insight_score import InsightScore


class InsightScoreRepository:
    """InsightScore 的 SQLite 持久化与计算。"""

    WEIGHTS = {
        "confidence": 0.30,
        "business_value": 0.30,
        "urgency": 0.20,
        "actionability": 0.20,
    }

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clamp(value: Any) -> int:
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError) as exc:
            raise ValueError("score components must be integers between 0 and 100") from exc

    def _ensure_insight(self, insight_id: int):
        row = self.db.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
        if not row:
            raise LookupError("insight not found")
        return row

    def calculate_components(self, insight: Any) -> dict[str, int]:
        insight_type = str(insight["type"])
        source = str(insight["source"] or "")
        description = str(insight["description"] or "")
        confidence = 85 if "Agent" in source else 70
        if len(description) >= 15:
            confidence += 5
        business_value = {
            "Opportunity": 90,
            "Risk": 85,
            "Breakthrough": 80,
            "Competition": 75,
            "Recommendation": 78,
        }.get(insight_type, 60)
        urgency = {
            "Risk": 90,
            "Competition": 80,
            "Recommendation": 80,
            "Opportunity": 72,
            "Breakthrough": 68,
        }.get(insight_type, 60)
        actionability = {
            "Recommendation": 95,
            "Breakthrough": 88,
            "Risk": 82,
            "Opportunity": 72,
            "Competition": 65,
        }.get(insight_type, 60)
        return {
            "confidence": self._clamp(confidence),
            "business_value": self._clamp(business_value),
            "urgency": self._clamp(urgency),
            "actionability": self._clamp(actionability),
        }

    def score(self, insight_id: int, now: str | None = None) -> InsightScore:
        insight = self._ensure_insight(insight_id)
        components = self.calculate_components(insight)
        total = round(sum(components[key] * self.WEIGHTS[key] for key in components))
        timestamp = now or self._now()
        self.db.execute(
            """INSERT INTO insight_scores
               (insight_id, confidence, business_value, urgency, actionability, score, created_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(insight_id) DO UPDATE SET
                 confidence = excluded.confidence,
                 business_value = excluded.business_value,
                 urgency = excluded.urgency,
                 actionability = excluded.actionability,
                 score = excluded.score,
                 created_time = excluded.created_time""",
            (
                insight_id,
                components["confidence"],
                components["business_value"],
                components["urgency"],
                components["actionability"],
                max(0, min(100, total)),
                timestamp,
            ),
        )
        return self.get(insight_id)  # type: ignore[return-value]

    def get(self, insight_id: int) -> InsightScore | None:
        row = self.db.execute(
            "SELECT * FROM insight_scores WHERE insight_id = ?", (insight_id,)
        ).fetchone()
        return InsightScore.from_row(row) if row else None

    def list(self, minimum_score: int | None = None) -> list[InsightScore]:
        if minimum_score is None:
            rows = self.db.execute("SELECT * FROM insight_scores ORDER BY score DESC, id DESC").fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM insight_scores WHERE score >= ? ORDER BY score DESC, id DESC",
                (self._clamp(minimum_score),),
            ).fetchall()
        return [InsightScore.from_row(row) for row in rows]
