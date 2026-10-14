from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional


REVIEW_ACTIONS = {"approve", "reject", "modify"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(row: Any) -> Optional[dict[str, Any]]:
    return dict(row) if row else None


def _candidate(db: Any, candidate_id: int) -> Optional[dict[str, Any]]:
    return _row_dict(db.execute("SELECT * FROM fact_candidates WHERE id = ?", (candidate_id,)).fetchone())


def list_pending_fact_candidates(db: Any, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    from fact_quality_score import refresh_pending_quality_scores
    refresh_pending_quality_scores(db)
    rows = db.execute(
        """SELECT fc.*,
                  (SELECT COUNT(*) FROM fact_conflicts c
                   WHERE c.resolution_status = 'OPEN'
                     AND (c.fact_id_1 = fc.id OR c.fact_id_2 = fc.id)) AS conflict_count
           FROM fact_candidates fc
           WHERE status = 'PENDING'
           ORDER BY fact_quality_score DESC, confidence DESC, created_time DESC, id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    result = [dict(row) for row in rows]
    from fact_quality_score import calculate_fact_quality
    for item in result:
        item["factQuality"] = calculate_fact_quality(db, item)
    return result


def get_fact_candidate(db: Any, candidate_id: int) -> Optional[dict[str, Any]]:
    candidate = _candidate(db, candidate_id)
    if not candidate:
        return None
    from fact_quality_score import refresh_fact_quality_score, calculate_fact_quality
    if candidate.get("fact_quality_score") is None:
        refresh_fact_quality_score(db, candidate_id)
        candidate = _candidate(db, candidate_id)
    candidate["factQuality"] = calculate_fact_quality(db, candidate)
    from fact_conflict_service import list_fact_conflicts
    candidate["conflicts"] = list_fact_conflicts(db, candidate_id)
    from fact_approval_ontology_sync import list_sync_logs
    candidate["syncLogs"] = list_sync_logs(db, candidate_id)
    candidate["reviewLogs"] = [
        dict(row)
        for row in db.execute(
            """SELECT id, action, before_json, after_json, review_user, review_time, ontology_result_json
               FROM fact_candidate_review_logs
               WHERE fact_candidate_id = ? ORDER BY id DESC""",
            (candidate_id,),
        ).fetchall()
    ]
    for log in candidate["reviewLogs"]:
        log["before"] = json.loads(log.pop("before_json") or "{}")
        log["after"] = json.loads(log.pop("after_json") or "{}")
        log["ontologyResult"] = json.loads(log.pop("ontology_result_json") or "{}")
    return candidate


def apply_ontology_fact(db: Any, candidate: dict[str, Any], now: str) -> dict[str, Any]:
    """把审核后的事实写入语义投影，并同步少量已有本体字段。"""
    from fact_approval_ontology_sync import sync_approved_fact
    return sync_approved_fact(db, candidate, now)

    # 保留旧版同步实现的代码路径，便于历史文档对照；实际同步统一走上面的可重试服务。
    subject_type = candidate["subject_type"]
    subject_id = candidate["subject_id"]
    subject_table = {
        "Customer": "customers",
        "Person": "persons",
        "Opportunity": "opportunities",
        "Project": "projects",
    }[subject_type]
    if not db.execute(f"SELECT 1 FROM {subject_table} WHERE id = ?", (subject_id,)).fetchone():
        raise LookupError(f"{subject_type} object not found")
    from fact_conflict_service import detect_conflicts_for_fact, has_open_conflict
    detect_conflicts_for_fact(db, candidate["id"])
    if has_open_conflict(db, candidate["id"]):
        raise ValueError("fact conflict must be resolved before approval")

    db.execute(
        """INSERT INTO ontology_fact_values
           (subject_type, subject_id, predicate, object_value, object_type,
            fact_candidate_id, created_time, updated_time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(subject_type, subject_id, predicate) DO UPDATE SET
             object_value = excluded.object_value,
             object_type = excluded.object_type,
             fact_candidate_id = excluded.fact_candidate_id,
             updated_time = excluded.updated_time""",
        (
            subject_type, subject_id, candidate["predicate"], candidate["object_value"],
            candidate["object_type"], candidate["id"], now, now,
        ),
    )

    predicate = str(candidate["predicate"]).strip().lower()
    object_value = candidate["object_value"]
    synced_field = None
    if subject_type == "Person" and candidate["fact_type"] == "PersonRole":
        db.execute("UPDATE persons SET title = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
        synced_field = "persons.title"
    elif subject_type == "Opportunity" and candidate["fact_type"] == "OpportunityStatus":
        if predicate in {"stage", "status", "阶段", "状态"}:
            db.execute("UPDATE opportunities SET stage = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "opportunities.stage"
    elif subject_type == "Project" and candidate["fact_type"] == "ProjectInformation":
        if predicate in {"status", "项目状态", "状态"}:
            db.execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "projects.status"

    return {
        "subjectType": subject_type,
        "subjectId": subject_id,
        "projection": "ontology_fact_values",
        "syncedField": synced_field,
    }


def review_fact_candidate(
    db: Any,
    candidate_id: int,
    action: str,
    review_user: str,
    payload: Optional[dict[str, Any]] = None,
    now: Optional[str] = None,
) -> dict[str, Any]:
    action = str(action).strip().lower()
    if action not in REVIEW_ACTIONS:
        raise ValueError("action must be approve, reject, or modify")
    review_user = str(review_user or "").strip()
    if not review_user:
        raise ValueError("review_user is required")
    candidate = _candidate(db, candidate_id)
    if not candidate:
        raise LookupError("fact candidate not found")
    if candidate["status"] != "PENDING":
        raise ValueError("only PENDING fact candidates can be reviewed")

    payload = payload or {}
    updated = dict(candidate)
    if action == "modify":
        for key in ("predicate", "object_value", "object_type"):
            if key in payload and str(payload[key]).strip():
                updated[key] = str(payload[key]).strip()
        if updated["object_value"] == candidate["object_value"] and updated["predicate"] == candidate["predicate"]:
            raise ValueError("modify requires predicate or object_value")
        new_status = "MODIFIED"
    elif action == "approve":
        new_status = "APPROVED"
    else:
        new_status = "REJECTED"

    timestamp = now or _now()
    ontology_result: dict[str, Any] = {}
    if action in {"approve", "modify"}:
        ontology_result = apply_ontology_fact(db, updated, timestamp)
        if not ontology_result.get("success", True):
            result = get_fact_candidate(db, candidate_id)
            result["ontologyResult"] = ontology_result
            return result
    else:
        from fact_conflict_service import resolve_conflicts_for_fact
        resolve_conflicts_for_fact(db, candidate_id)

    db.execute(
        """UPDATE fact_candidates
           SET predicate = ?, object_value = ?, object_type = ?, status = ?,
               review_user = ?, review_time = ?
           WHERE id = ?""",
        (updated["predicate"], updated["object_value"], updated["object_type"], new_status, review_user, timestamp, candidate_id),
    )
    db.execute(
        """INSERT INTO fact_candidate_review_logs
           (fact_candidate_id, action, before_json, after_json, review_user,
            review_time, ontology_result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            candidate_id, action.upper(), json.dumps(candidate, ensure_ascii=False),
            json.dumps({**updated, "status": new_status, "review_user": review_user, "review_time": timestamp}, ensure_ascii=False),
            review_user, timestamp, json.dumps(ontology_result, ensure_ascii=False),
        ),
    )
    result = get_fact_candidate(db, candidate_id)
    result["ontologyResult"] = ontology_result
    return result
