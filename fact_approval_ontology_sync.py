from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _subject_table(subject_type: str) -> str:
    return {
        "Customer": "customers",
        "Person": "persons",
        "Opportunity": "opportunities",
        "Project": "projects",
    }[subject_type]


def _apply(db: Any, candidate: dict[str, Any], now: str) -> dict[str, Any]:
    subject_type = candidate["subject_type"]
    subject_id = candidate["subject_id"]
    if not db.execute(f"SELECT 1 FROM {_subject_table(subject_type)} WHERE id = ?", (subject_id,)).fetchone():
        raise LookupError(f"{subject_type} object not found")

    from fact_conflict_service import detect_conflicts_for_fact, has_open_conflict
    detect_conflicts_for_fact(db, candidate["id"])
    if has_open_conflict(db, candidate["id"]):
        raise ValueError("fact conflict must be resolved before ontology sync")

    existing = db.execute(
        """SELECT object_value FROM ontology_fact_values
           WHERE subject_type = ? AND subject_id = ? AND predicate = ?""",
        (subject_type, subject_id, candidate["predicate"]),
    ).fetchone()
    previous_value = existing["object_value"] if existing else None
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
    if subject_type == "Customer" and candidate["fact_type"] == "CustomerProfile":
        if predicate in {"customer_level", "customerlevel", "客户等级", "等级", "属于"}:
            db.execute("UPDATE customers SET customer_level = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "customers.customer_level"
    elif subject_type == "Person" and candidate["fact_type"] == "PersonRole":
        if predicate in {"role", "负责", "职责", "角色"}:
            db.execute("UPDATE persons SET role = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "persons.role"
    elif subject_type == "Opportunity" and candidate["fact_type"] == "OpportunityStatus":
        if predicate in {"stage", "status", "阶段", "状态"}:
            db.execute("UPDATE opportunities SET stage = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "opportunities.stage"
    elif subject_type == "Project" and candidate["fact_type"] == "ProjectInformation":
        if predicate in {"status", "项目状态", "状态"}:
            db.execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?", (object_value, now, subject_id))
            synced_field = "projects.status"

    return {
        "success": True,
        "subjectType": subject_type,
        "subjectId": subject_id,
        "projection": "ontology_fact_values",
        "syncedField": synced_field,
        "previousValue": previous_value,
        "newValue": object_value,
    }


def sync_approved_fact(db: Any, candidate: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    """同步已审核事实；失败时回滚本体写入但保留失败尝试日志。"""
    timestamp = now or _now()
    attempt = db.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM fact_ontology_sync_logs WHERE fact_candidate_id = ?",
        (candidate["id"],),
    ).fetchone()[0]
    cursor = db.execute(
        """INSERT INTO fact_ontology_sync_logs
           (fact_candidate_id, attempt_no, action, status, subject_type, subject_id,
            created_time)
           VALUES (?, ?, 'SYNC', 'STARTED', ?, ?, ?)""",
        (candidate["id"], attempt, candidate["subject_type"], candidate["subject_id"], timestamp),
    )
    log_id = cursor.lastrowid
    savepoint = f"fact_sync_{log_id}"
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        result = _apply(db, candidate, timestamp)
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
        db.execute(
            """UPDATE fact_ontology_sync_logs
               SET status = 'SUCCESS', target_field = ?, previous_value = ?, new_value = ?, completed_time = ?
               WHERE id = ?""",
            (result["syncedField"], result["previousValue"], result["newValue"], timestamp, log_id),
        )
        result["syncLogId"] = log_id
        result["attemptNo"] = attempt
        return result
    except Exception as exc:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")
        db.execute(
            """UPDATE fact_ontology_sync_logs
               SET status = 'FAILED', error_message = ?, completed_time = ?
               WHERE id = ?""",
            (str(exc), timestamp, log_id),
        )
        return {
            "success": False,
            "syncLogId": log_id,
            "attemptNo": attempt,
            "error": str(exc),
            "retryable": not isinstance(exc, ValueError),
        }


def retry_ontology_sync(db: Any, fact_candidate_id: int, now: str | None = None) -> dict[str, Any]:
    candidate = db.execute("SELECT * FROM fact_candidates WHERE id = ?", (fact_candidate_id,)).fetchone()
    if not candidate:
        raise LookupError("fact candidate not found")
    if candidate["status"] not in {"APPROVED", "MODIFIED"}:
        raise ValueError("only APPROVED or MODIFIED facts can be synchronized")
    return sync_approved_fact(db, dict(candidate), now)


def list_sync_logs(db: Any, fact_candidate_id: int) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            "SELECT * FROM fact_ontology_sync_logs WHERE fact_candidate_id = ? ORDER BY attempt_no DESC",
            (fact_candidate_id,),
        ).fetchall()
    ]
