"""Fact Candidate 质量评分与审核队列排序支持。"""

from __future__ import annotations

from typing import Any, Optional


SOURCE_RELIABILITY = {
    "document": 90,
    "recording": 85,
    "chat": 80,
}
QUALITY_WEIGHTS = {
    "source_reliability": 0.30,
    "ai_confidence": 0.30,
    "historical_consistency": 0.20,
    "human_confirmation": 0.20,
}


def quality_level(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def _historical_consistency(db: Any, candidate: dict[str, Any]) -> int:
    rows = db.execute(
        """SELECT object_value FROM fact_candidates
           WHERE id <> ? AND subject_type = ? AND subject_id = ? AND predicate = ?
             AND status IN ('APPROVED', 'MODIFIED')""",
        (candidate["id"], candidate["subject_type"], candidate["subject_id"], candidate["predicate"]),
    ).fetchall()
    if not rows:
        return 70
    if any(row[0] == candidate["object_value"] for row in rows):
        return 100
    return 0


def _human_confirmation(db: Any, candidate: dict[str, Any]) -> int:
    count = db.execute(
        """SELECT COUNT(*) FROM fact_candidate_review_logs l
           JOIN fact_candidates fc ON fc.id = l.fact_candidate_id
           WHERE fc.subject_type = ? AND fc.subject_id = ? AND fc.predicate = ?
             AND l.action IN ('APPROVE', 'MODIFY')""",
        (candidate["subject_type"], candidate["subject_id"], candidate["predicate"]),
    ).fetchone()[0]
    return min(100, int(count) * 25)


def calculate_fact_quality(db: Any, candidate: dict[str, Any]) -> dict[str, Any]:
    """返回可解释的分项评分和总分，所有分项均为 0-100。"""
    dimensions = {
        "source_reliability": SOURCE_RELIABILITY.get(str(candidate["source_type"]).lower(), 50),
        "ai_confidence": max(0, min(100, int(candidate["confidence"]))),
        "historical_consistency": _historical_consistency(db, candidate),
        "human_confirmation": _human_confirmation(db, candidate),
    }
    score = round(sum(dimensions[key] * QUALITY_WEIGHTS[key] for key in dimensions))
    return {
        "fact_quality_score": score,
        "fact_quality_level": quality_level(score),
        "dimensions": dimensions,
        "weights": QUALITY_WEIGHTS.copy(),
    }


def refresh_fact_quality_score(db: Any, fact_id: int) -> Optional[dict[str, Any]]:
    row = db.execute("SELECT * FROM fact_candidates WHERE id = ?", (fact_id,)).fetchone()
    if not row:
        return None
    result = calculate_fact_quality(db, dict(row))
    db.execute(
        "UPDATE fact_candidates SET fact_quality_score = ?, fact_quality_level = ? WHERE id = ?",
        (result["fact_quality_score"], result["fact_quality_level"], fact_id),
    )
    return result


def refresh_pending_quality_scores(db: Any) -> None:
    """兼容迁移前已有候选，首次进入队列时惰性补齐评分。"""
    ids = db.execute("SELECT id FROM fact_candidates WHERE status = 'PENDING'").fetchall()
    for row in ids:
        refresh_fact_quality_score(db, row[0])


__all__ = [
    "calculate_fact_quality",
    "quality_level",
    "refresh_fact_quality_score",
    "refresh_pending_quality_scores",
]
