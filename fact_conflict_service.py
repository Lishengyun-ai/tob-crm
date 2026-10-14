from __future__ import annotations

from typing import Any


CONFLICT_TYPE = "SUBJECT_PREDICATE_OBJECT_MISMATCH"
OPEN_STATUS = "OPEN"


def detect_conflicts_for_fact(db: Any, fact_id: int) -> list[dict[str, Any]]:
    fact = db.execute("SELECT * FROM fact_candidates WHERE id = ?", (fact_id,)).fetchone()
    if not fact:
        return []
    rows = db.execute(
        """SELECT id FROM fact_candidates
           WHERE subject_type = ? AND subject_id = ? AND predicate = ?
             AND id <> ? AND object_value <> ? AND status <> 'REJECTED'
           UNION
           SELECT fact_candidate_id AS id FROM ontology_fact_values
           WHERE subject_type = ? AND subject_id = ? AND predicate = ?
             AND fact_candidate_id <> ? AND object_value <> ?""",
        (
            fact["subject_type"], fact["subject_id"], fact["predicate"], fact_id, fact["object_value"],
            fact["subject_type"], fact["subject_id"], fact["predicate"], fact_id, fact["object_value"],
        ),
    ).fetchall()
    conflicts = []
    for row in rows:
        fact_id_1, fact_id_2 = sorted((fact_id, int(row["id"])))
        db.execute(
            """INSERT OR IGNORE INTO fact_conflicts
               (fact_id_1, fact_id_2, conflict_type, resolution_status)
               VALUES (?, ?, ?, ?)""",
            (fact_id_1, fact_id_2, CONFLICT_TYPE, OPEN_STATUS),
        )
        conflict = db.execute(
            """SELECT fc.*, f1.object_value AS object_value_1, f2.object_value AS object_value_2,
                      f1.subject_type, f1.subject_id, f1.predicate
               FROM fact_conflicts fc
               JOIN fact_candidates f1 ON f1.id = fc.fact_id_1
               JOIN fact_candidates f2 ON f2.id = fc.fact_id_2
               WHERE fc.fact_id_1 = ? AND fc.fact_id_2 = ?""",
            (fact_id_1, fact_id_2),
        ).fetchone()
        if conflict:
            conflicts.append(dict(conflict))
    return conflicts


def list_fact_conflicts(db: Any, fact_id: int | None = None, open_only: bool = False) -> list[dict[str, Any]]:
    clauses = []
    values: list[Any] = []
    if fact_id is not None:
        clauses.append("(fc.fact_id_1 = ? OR fc.fact_id_2 = ?)")
        values.extend((fact_id, fact_id))
    if open_only:
        clauses.append("fc.resolution_status = 'OPEN'")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"""SELECT fc.*, f1.object_value AS object_value_1, f2.object_value AS object_value_2,
                   f1.subject_type, f1.subject_id, f1.predicate,
                   f1.status AS status_1, f2.status AS status_2
            FROM fact_conflicts fc
            JOIN fact_candidates f1 ON f1.id = fc.fact_id_1
            JOIN fact_candidates f2 ON f2.id = fc.fact_id_2
            {where}
            ORDER BY CASE fc.resolution_status WHEN 'OPEN' THEN 0 ELSE 1 END, fc.id DESC""",
        tuple(values),
    ).fetchall()
    return [dict(row) for row in rows]


def has_open_conflict(db: Any, fact_id: int) -> bool:
    return bool(list_fact_conflicts(db, fact_id, open_only=True))


def resolve_conflicts_for_fact(db: Any, fact_id: int) -> None:
    db.execute(
        """UPDATE fact_conflicts SET resolution_status = 'RESOLVED'
           WHERE resolution_status = 'OPEN' AND (fact_id_1 = ? OR fact_id_2 = ?)""",
        (fact_id, fact_id),
    )
