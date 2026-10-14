"""Customer Value Prediction 派生实体与 V1 计算服务。"""

import json
from datetime import datetime, timezone
from typing import Any


MODEL_VERSION = "customer-value-v1"


def _number(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "").replace("，", ""))
    except (TypeError, ValueError):
        return 0.0


def _json(value: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _result(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["dimensions"] = _json(result.pop("dimensions_json"))
    result["inputSnapshot"] = _json(result.pop("input_snapshot_json"))
    return result


def get_latest_customer_value_prediction(db: Any, customer_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT cvp.*, c.name AS customer_name
           FROM customer_value_predictions cvp
           JOIN customers c ON c.id = cvp.customer_id
           WHERE cvp.customer_id = ?
           ORDER BY cvp.assessed_at DESC, cvp.id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    return _result(row) if row else None


def get_customer_value_prediction(db: Any, prediction_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT cvp.*, c.name AS customer_name
           FROM customer_value_predictions cvp
           JOIN customers c ON c.id = cvp.customer_id
           WHERE cvp.id = ?""",
        (prediction_id,),
    ).fetchone()
    if not row:
        raise LookupError("customer value prediction not found")
    return _result(row)


def predict_customer_value(db: Any, customer_id: int, now: str | None = None) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise LookupError("customer not found")

    purchase_rows = db.execute(
        """SELECT fact_value, fact_content, valid_from, valid_to
           FROM customer_facts
           WHERE customer_id = ? AND fact_type = 'PURCHASE' AND status = 'ACTIVE'""",
        (customer_id,),
    ).fetchall()
    purchase_value = sum(_number(row["fact_value"] or row["fact_content"]) for row in purchase_rows)
    opportunities = db.execute(
        """SELECT amount, stage FROM opportunities
           WHERE customer_id = ? OR (customer_id IS NULL AND customer = ?)""",
        (customer_id, customer["name"]),
    ).fetchall()
    open_pipeline = sum(
        _number(row["amount"]) for row in opportunities
        if str(row["stage"] or "").lower() not in {"赢单", "输单", "lost", "closed_lost"}
    )
    won_value = sum(
        _number(row["amount"]) for row in opportunities
        if str(row["stage"] or "").lower() in {"赢单", "won", "closed_won"}
    )
    potential = db.execute(
        """SELECT id, potential_score, annual_potential
           FROM customer_potential_predictions WHERE customer_id = ?
           ORDER BY assessed_at DESC, id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    profile = db.execute(
        """SELECT completeness_score, confidence_score FROM customer_profiles
           WHERE customer_id = ? AND status = 'active'
           ORDER BY version_no DESC, id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()

    historical_value = max(purchase_value, won_value)
    potential_score = int(potential["potential_score"] or 0) if potential else 0
    profile_signal = int(max(profile["completeness_score"] or 0, profile["confidence_score"] or 0)) if profile else 0
    history_signal = min(100, round(historical_value / 100000 * 10)) if historical_value else 0
    pipeline_signal = min(100, round(open_pipeline / 200000 * 10)) if open_pipeline else 0
    value_score = max(0, min(100, round(
        history_signal * 0.35 + pipeline_signal * 0.25 + potential_score * 0.25 + profile_signal * 0.15
    )))
    future_revenue = round(max(historical_value, purchase_value) * (1 + value_score / 100) + open_pipeline * 0.55, 2)
    growth_space = round(max(0.0, future_revenue - historical_value), 2)
    dimensions = {
        "historySignal": history_signal,
        "pipelineSignal": pipeline_signal,
        "potentialSignal": potential_score,
        "profileSignal": profile_signal,
        "purchaseRecordCount": len(purchase_rows),
        "openPipeline": open_pipeline,
        "historicalValue": historical_value,
    }
    snapshot = {
        "customerId": customer_id,
        "purchaseValue": purchase_value,
        "wonValue": won_value,
        "openPipeline": open_pipeline,
        "potentialPredictionId": potential["id"] if potential else None,
        "calculatedAt": timestamp,
    }
    cursor = db.execute(
        """INSERT INTO customer_value_predictions
           (customer_id, value_score, future_revenue, growth_space,
            dimensions_json, input_snapshot_json, model_version, assessed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, value_score, future_revenue, growth_space,
         json.dumps(dimensions, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False),
         MODEL_VERSION, timestamp, timestamp),
    )
    return get_customer_value_prediction(db, cursor.lastrowid)
