"""Customer Potential Prediction 派生实体与 V1 计算服务。"""

import json
from datetime import datetime, timezone
from typing import Any


MODEL_VERSION = "customer-potential-v1"


def _number(value: Any) -> float:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or "").replace(",", "").replace("，", "")
        return float(text) if text else 0.0
    except (TypeError, ValueError):
        return 0.0


def _value_json(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _level(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def get_latest_customer_potential_prediction(db: Any, customer_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT cpp.*, c.name AS customer_name
           FROM customer_potential_predictions cpp
           JOIN customers c ON c.id = cpp.customer_id
           WHERE cpp.customer_id = ?
           ORDER BY cpp.assessed_at DESC, cpp.id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["dimensions"] = json.loads(result.pop("dimensions_json") or "{}")
    result["inputSnapshot"] = json.loads(result.pop("input_snapshot_json") or "{}")
    return result


def predict_customer_potential(db: Any, customer_id: int, now: str | None = None) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise LookupError("customer not found")

    profile = db.execute(
        """SELECT * FROM customer_profiles
           WHERE customer_id = ? AND status = 'active'
           ORDER BY version_no DESC, id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    profile_facts = []
    profile_score = 0
    profile_confidence = 0
    if profile:
        profile_facts = db.execute(
            "SELECT fact_code, value_json, confidence FROM customer_profile_facts WHERE profile_id = ? AND status = 'current'",
            (profile["id"],),
        ).fetchall()
        score_row = db.execute(
            """SELECT score, dimensions_json FROM customer_profile_scores
               WHERE profile_id = ? ORDER BY assessed_at DESC, id DESC LIMIT 1""",
            (profile["id"],),
        ).fetchone()
        if score_row:
            profile_score = int(score_row["score"] or 0)
        profile_confidence = int(profile["confidence_score"] or 0)

    purchase_facts = db.execute(
        """SELECT fact_name, fact_value, fact_content, confidence_score, valid_from, valid_to
           FROM customer_facts
           WHERE customer_id = ? AND fact_type = 'PURCHASE' AND status = 'ACTIVE'""",
        (customer_id,),
    ).fetchall()
    purchase_total = sum(_number(row["fact_value"] or row["fact_content"]) for row in purchase_facts)
    annual_purchase = 0.0
    for row in profile_facts:
        if row["fact_code"] in {"annual_purchase_value", "annual_revenue", "customer_value"}:
            annual_purchase = max(annual_purchase, _number(_value_json(row["value_json"])))
    annual_purchase = max(annual_purchase, purchase_total)

    opportunities = db.execute(
        """SELECT amount, stage FROM opportunities
           WHERE customer_id = ? OR (customer_id IS NULL AND customer = ?)""",
        (customer_id, customer["name"]),
    ).fetchall()
    open_pipeline = sum(
        _number(row["amount"]) for row in opportunities
        if str(row["stage"] or "").lower() not in {"赢单", "输单", "lost", "closed_lost"}
    )

    fact_completeness = min(100, len(profile_facts) * 15)
    purchase_signal = min(100, round(annual_purchase / 100000 * 10)) if annual_purchase else 0
    pipeline_signal = min(100, round(open_pipeline / 200000 * 10)) if open_pipeline else 0
    profile_signal = max(profile_score, fact_completeness)
    confidence_signal = profile_confidence or min(100, 50 + len(purchase_facts) * 10)
    potential_score = round(
        profile_signal * 0.30
        + purchase_signal * 0.30
        + pipeline_signal * 0.25
        + confidence_signal * 0.15
    )
    potential_score = max(0, min(100, potential_score))
    annual_potential = round(max(annual_purchase, open_pipeline * 0.5) * (1 + potential_score / 100), 2)
    priority = "P0" if potential_score >= 80 else "P1" if potential_score >= 60 else "P2" if potential_score >= 40 else "P3"
    dimensions = {
        "profileSignal": profile_signal,
        "purchaseSignal": purchase_signal,
        "pipelineSignal": pipeline_signal,
        "confidenceSignal": confidence_signal,
        "purchaseFactCount": len(purchase_facts),
        "openOpportunityAmount": open_pipeline,
    }
    snapshot = {
        "customerId": customer_id,
        "profileId": profile["id"] if profile else None,
        "profileFactCount": len(profile_facts),
        "purchaseFactCount": len(purchase_facts),
        "annualPurchase": annual_purchase,
        "openPipeline": open_pipeline,
        "calculatedAt": timestamp,
    }
    cursor = db.execute(
        """INSERT INTO customer_potential_predictions
           (customer_id, potential_score, potential_level, annual_potential,
            development_priority, dimensions_json, input_snapshot_json,
            model_version, assessed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, potential_score, _level(potential_score), annual_potential,
         priority, json.dumps(dimensions, ensure_ascii=False),
         json.dumps(snapshot, ensure_ascii=False), MODEL_VERSION, timestamp, timestamp),
    )
    return get_prediction_by_id(db, cursor.lastrowid)


def get_prediction_by_id(db: Any, prediction_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT cpp.*, c.name AS customer_name
           FROM customer_potential_predictions cpp
           JOIN customers c ON c.id = cpp.customer_id WHERE cpp.id = ?""",
        (prediction_id,),
    ).fetchone()
    if not row:
        raise LookupError("customer potential prediction not found")
    result = dict(row)
    result["dimensions"] = json.loads(result.pop("dimensions_json") or "{}")
    result["inputSnapshot"] = json.loads(result.pop("input_snapshot_json") or "{}")
    return result
