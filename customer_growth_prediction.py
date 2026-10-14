"""Customer Growth Prediction 派生实体与 V1 计算服务。"""

import json
from datetime import datetime, timezone
from typing import Any


MODEL_VERSION = "customer-growth-v1"


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
    result["growth_reason"] = _json(result.pop("growth_reason_json"))
    result["growthReason"] = result["growth_reason"]
    result["inputSnapshot"] = _json(result.pop("input_snapshot_json"))
    return result


def get_latest_customer_growth_prediction(db: Any, customer_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT cgp.*, c.name AS customer_name
           FROM customer_growth_predictions cgp JOIN customers c ON c.id = cgp.customer_id
           WHERE cgp.customer_id = ? ORDER BY cgp.assessed_at DESC, cgp.id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    return _result(row) if row else None


def get_customer_growth_prediction(db: Any, prediction_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT cgp.*, c.name AS customer_name
           FROM customer_growth_predictions cgp JOIN customers c ON c.id = cgp.customer_id
           WHERE cgp.id = ?""",
        (prediction_id,),
    ).fetchone()
    if not row:
        raise LookupError("customer growth prediction not found")
    return _result(row)


def predict_customer_growth(db: Any, customer_id: int, now: str | None = None) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise LookupError("customer not found")
    purchases = db.execute(
        """SELECT fact_name, fact_value, fact_content, valid_from FROM customer_facts
           WHERE customer_id = ? AND fact_type = 'PURCHASE' AND status = 'ACTIVE'
           ORDER BY valid_from, fact_id""", (customer_id,)
    ).fetchall()
    opportunities = db.execute(
        """SELECT amount, stage, business_type FROM opportunities
           WHERE customer_id = ? OR (customer_id IS NULL AND customer = ?)""",
        (customer_id, customer["name"]),
    ).fetchall()
    product_names = {str(row["fact_name"] or "").strip() for row in purchases if str(row["fact_name"] or "").strip()}
    purchase_values = [_number(row["fact_value"] or row["fact_content"]) for row in purchases]
    purchase_total = sum(purchase_values)
    recent_purchase = sum(purchase_values[-3:]) if purchase_values else 0
    earlier_purchase = sum(purchase_values[:-3]) if len(purchase_values) > 3 else 0
    purchase_trend = 100 if recent_purchase > earlier_purchase and recent_purchase else 50 if recent_purchase == earlier_purchase and recent_purchase else 20
    open_pipeline = sum(_number(row["amount"]) for row in opportunities if str(row["stage"] or "").lower() not in {"赢单", "输单", "lost", "closed_lost"})
    pipeline_signal = min(100, round(open_pipeline / 200000 * 10)) if open_pipeline else 0
    product_signal = min(100, len(product_names) * 25)
    growth_score = max(0, min(100, round(purchase_trend * 0.45 + pipeline_signal * 0.35 + product_signal * 0.20)))
    direction = "UP" if growth_score >= 65 else "FLAT" if growth_score >= 40 else "DOWN"
    reasons = [
        {"code": "PURCHASE_TREND", "direction": "positive" if purchase_trend >= 65 else "negative", "message": f"采购趋势信号为 {purchase_trend}"},
        {"code": "OPPORTUNITY_PIPELINE", "direction": "positive" if pipeline_signal >= 50 else "neutral", "message": f"在途商机金额为 {open_pipeline:g}"},
        {"code": "PRODUCT_COVERAGE", "direction": "positive" if product_signal >= 50 else "neutral", "message": f"已识别产品或采购类别 {len(product_names)} 个"},
    ]
    snapshot = {"customerId": customer_id, "purchaseCount": len(purchases), "purchaseTotal": purchase_total, "openPipeline": open_pipeline, "productCount": len(product_names), "calculatedAt": timestamp}
    cursor = db.execute(
        """INSERT INTO customer_growth_predictions
           (customer_id, growth_score, growth_direction, growth_reason_json, input_snapshot_json, model_version, assessed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, growth_score, direction, json.dumps(reasons, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False), MODEL_VERSION, timestamp, timestamp),
    )
    return get_customer_growth_prediction(db, cursor.lastrowid)
