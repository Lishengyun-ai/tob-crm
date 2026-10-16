"""统一 Forecast Engine：基于可解释规则的客户增长与商机预测底座。"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any


DOMAINS = {"CUSTOMER_GROWTH", "OPPORTUNITY"}
FORECAST_STATUSES = {"DRAFT", "RUNNING", "READY", "PARTIAL", "STALE", "FAILED", "RETIRED"}
MODES = {"PUBLISHED", "SIMULATION"}
DEFAULT_MODELS = {
    "CUSTOMER_GROWTH": ("customer-growth-unified", "1.0", ["GROWTH_POTENTIAL", "CUSTOMER_VALUE", "EXPANSION_OPPORTUNITY"]),
    "OPPORTUNITY": ("opportunity-intelligence-unified", "1.0", ["WIN_PROBABILITY", "CLOSE_DATE", "FORECAST_REVENUE", "RISK_LEVEL"]),
}


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _json(value: Any, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _number(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "").replace("，", ""))
    except (TypeError, ValueError):
        return 0.0


def _ratio(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _iso_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _subject_exists(db: Any, subject_type: str, subject_id: str) -> bool:
    table = {"Customer": "customers", "Opportunity": "opportunities"}.get(subject_type)
    if not table:
        return False
    try:
        return bool(db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (int(subject_id),)).fetchone())
    except (TypeError, ValueError):
        return False


def ensure_forecast_schema(db: Any, now: str | None = None) -> None:
    """创建统一预测表。可重复执行，用于新库和旧库迁移。"""
    db.executescript("""
    CREATE TABLE IF NOT EXISTS forecast_model_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      model_version_id TEXT NOT NULL UNIQUE,
      model_name TEXT NOT NULL,
      version TEXT NOT NULL,
      domain TEXT NOT NULL,
      target_types_json TEXT NOT NULL DEFAULT '[]',
      model_type TEXT NOT NULL DEFAULT 'RULE',
      feature_set_version TEXT NOT NULL DEFAULT 'v1',
      label_definition_json TEXT NOT NULL DEFAULT '{}',
      calibration_method TEXT NOT NULL DEFAULT 'rule_baseline',
      training_window_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'PUBLISHED',
      metrics_json TEXT NOT NULL DEFAULT '{}',
      approved_by TEXT,
      created_at TEXT NOT NULL,
      published_at TEXT,
      CHECK (status IN ('DRAFT','TESTING','PUBLISHED','RETIRED'))
    );
    CREATE TABLE IF NOT EXISTS forecasts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      domain TEXT NOT NULL,
      subject_type TEXT NOT NULL,
      subject_id TEXT NOT NULL,
      target_types_json TEXT NOT NULL DEFAULT '[]',
      as_of_time TEXT NOT NULL,
      model_version_id TEXT NOT NULL,
      feature_set_version TEXT NOT NULL DEFAULT 'v1',
      status TEXT NOT NULL DEFAULT 'RUNNING',
      mode TEXT NOT NULL DEFAULT 'PUBLISHED',
      data_completeness REAL NOT NULL DEFAULT 0,
      freshness_score REAL NOT NULL DEFAULT 0,
      overall_confidence REAL NOT NULL DEFAULT 0,
      trigger_type TEXT NOT NULL DEFAULT 'MANUAL',
      parent_forecast_id INTEGER,
      error_message TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      completed_at TEXT,
      FOREIGN KEY(model_version_id) REFERENCES forecast_model_versions(model_version_id),
      FOREIGN KEY(parent_forecast_id) REFERENCES forecasts(id) ON DELETE SET NULL,
      CHECK (status IN ('DRAFT','RUNNING','READY','PARTIAL','STALE','FAILED','RETIRED')),
      CHECK (mode IN ('PUBLISHED','SIMULATION'))
    );
    CREATE TABLE IF NOT EXISTS forecast_features (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      forecast_id INTEGER NOT NULL,
      feature_code TEXT NOT NULL,
      feature_group TEXT NOT NULL DEFAULT 'business',
      value_type TEXT NOT NULL DEFAULT 'JSON',
      value_json TEXT NOT NULL DEFAULT 'null',
      unit TEXT,
      normalized_value REAL,
      missing_flag INTEGER NOT NULL DEFAULT 0,
      stale_flag INTEGER NOT NULL DEFAULT 0,
      feature_as_of_time TEXT NOT NULL,
      source_entity_type TEXT,
      source_entity_id TEXT,
      source_field TEXT,
      source_event_id TEXT,
      quality_score REAL NOT NULL DEFAULT 1,
      UNIQUE(forecast_id, feature_code),
      FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS prediction_results (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      forecast_id INTEGER NOT NULL,
      target_type TEXT NOT NULL,
      value_type TEXT NOT NULL,
      value_json TEXT NOT NULL DEFAULT 'null',
      lower_bound_json TEXT,
      upper_bound_json TEXT,
      unit TEXT,
      confidence REAL NOT NULL DEFAULT 0,
      calibration_status TEXT NOT NULL DEFAULT 'UNCALIBRATED',
      result_status TEXT NOT NULL DEFAULT 'PUBLISHED',
      created_at TEXT NOT NULL,
      UNIQUE(forecast_id, target_type),
      FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS forecast_explanations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      forecast_id INTEGER NOT NULL,
      prediction_result_id INTEGER,
      factor_code TEXT NOT NULL,
      direction TEXT NOT NULL DEFAULT 'NEUTRAL',
      contribution REAL NOT NULL DEFAULT 0,
      feature_ids_json TEXT NOT NULL DEFAULT '[]',
      evidence_ids_json TEXT NOT NULL DEFAULT '[]',
      summary TEXT NOT NULL DEFAULT '',
      FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE,
      FOREIGN KEY(prediction_result_id) REFERENCES prediction_results(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS forecast_feedback (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      forecast_id INTEGER NOT NULL,
      target_type TEXT,
      actual_value_json TEXT NOT NULL DEFAULT 'null',
      feedback_type TEXT NOT NULL DEFAULT 'actual_outcome',
      actor TEXT NOT NULL DEFAULT 'system',
      notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      FOREIGN KEY(forecast_id) REFERENCES forecasts(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_forecasts_subject ON forecasts(subject_type, subject_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_forecasts_domain_status ON forecasts(domain, status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_forecast_features_forecast ON forecast_features(forecast_id);
    CREATE INDEX IF NOT EXISTS idx_prediction_results_forecast ON prediction_results(forecast_id);
    CREATE INDEX IF NOT EXISTS idx_forecast_feedback_forecast ON forecast_feedback(forecast_id, created_at DESC);
    """)
    timestamp = _now(now)
    for domain, (name, version, targets) in DEFAULT_MODELS.items():
        db.execute(
            """INSERT OR IGNORE INTO forecast_model_versions
               (model_version_id, model_name, version, domain, target_types_json,
                model_type, feature_set_version, label_definition_json,
                calibration_method, status, created_at, published_at)
               VALUES (?, ?, ?, ?, ?, 'RULE', 'v1', ?, 'rule_baseline', 'PUBLISHED', ?, ?)""",
            (name + "-v" + version, name, version, domain, json.dumps(targets),
             json.dumps({"targets": targets, "confidenceUnit": "0-1"}), timestamp, timestamp),
        )


def _model(db: Any, domain: str, requested: str | None, now: str) -> dict[str, Any]:
    default_id = DEFAULT_MODELS[domain][0] + "-v" + DEFAULT_MODELS[domain][1]
    model_id = requested or default_id
    row = db.execute("SELECT * FROM forecast_model_versions WHERE model_version_id = ?", (model_id,)).fetchone()
    if not row:
        raise LookupError("forecast model version not found")
    result = dict(row)
    if result["status"] == "RETIRED":
        raise ValueError("forecast model version is retired")
    return result


def _feature(code: str, value: Any, *, group: str = "business", value_type: str = "JSON", unit: str | None = None,
             normalized: float | None = None, missing: bool = False, stale: bool = False, as_of: str,
             source_type: str | None, source_id: Any, source_field: str | None, quality: float = 1.0) -> dict[str, Any]:
    return {"feature_code": code, "feature_group": group, "value_type": value_type,
            "value": value, "unit": unit, "normalized_value": normalized,
            "missing_flag": int(missing), "stale_flag": int(stale), "feature_as_of_time": as_of,
            "source_entity_type": source_type, "source_entity_id": str(source_id) if source_id is not None else None,
            "source_field": source_field, "quality_score": _ratio(quality, 1.0)}


def _customer_features(db: Any, subject_id: str, as_of: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cid = int(subject_id)
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    if not customer:
        raise LookupError("customer not found")
    facts = db.execute("SELECT * FROM customer_facts WHERE customer_id = ? AND status = 'ACTIVE'", (cid,)).fetchall()
    opps = db.execute("SELECT amount, stage, updated_at FROM opportunities WHERE customer_id = ? OR (customer_id IS NULL AND customer = ?)", (cid, customer["name"])).fetchall()
    rel_count = db.execute("SELECT COUNT(*) AS c FROM customer_persons WHERE customer_id = ?", (cid,)).fetchone()["c"]
    purchase = sum(_number(r["fact_value"] or r["fact_content"]) for r in facts if str(r["fact_type"] or "").upper() == "PURCHASE")
    conflict_count = 0
    fact_groups: dict[str, set[str]] = {}
    for fact in facts:
        code = str(fact["fact_name"] or fact["fact_type"] or "unknown")
        fact_groups.setdefault(code, set()).add(str(fact["fact_value"] or fact["fact_content"] or ""))
    conflict_count = sum(1 for values in fact_groups.values() if len(values) > 1)
    open_pipeline = sum(_number(r["amount"]) for r in opps if str(r["stage"] or "").lower() not in {"赢单", "输单", "won", "lost", "closed_lost", "closed_won"})
    stale = False
    for r in facts:
        observed = r["valid_from"] if "valid_from" in r.keys() else None
        if observed:
            try:
                stale = stale or (_iso_date(as_of) - _iso_date(str(observed))).days > 365
            except ValueError:
                pass
    values = [
        _feature("customer.purchase_value", purchase, group="business", value_type="NUMBER", unit="CNY", normalized=min(1, purchase / 1000000), missing=not bool(facts), stale=stale, as_of=as_of, source_type="CustomerFact", source_id=subject_id, source_field="fact_value", quality=0.7 if stale else 1),
        _feature("customer.open_pipeline", open_pipeline, group="opportunity", value_type="NUMBER", unit="CNY", normalized=min(1, open_pipeline / 3000000), missing=not bool(opps), as_of=as_of, source_type="Opportunity", source_id=subject_id, source_field="amount", quality=1 if opps else 0.4),
        _feature("customer.relationship_coverage", rel_count, group="relationship", value_type="NUMBER", normalized=min(1, rel_count / 4), missing=rel_count == 0, as_of=as_of, source_type="Customer", source_id=subject_id, source_field="customer_persons", quality=1 if rel_count else 0.5),
        _feature("customer.fact_count", len(facts), group="quality", value_type="NUMBER", normalized=min(1, len(facts) / 10), missing=len(facts) == 0, as_of=as_of, source_type="CustomerFact", source_id=subject_id, source_field="count", quality=1 if facts else 0.3),
        _feature("customer.fact_conflict_count", conflict_count, group="quality", value_type="NUMBER", normalized=min(1, conflict_count / 3), missing=False, as_of=as_of, source_type="CustomerFact", source_id=subject_id, source_field="conflict", quality=max(0.2, 1 - conflict_count * 0.2)),
    ]
    return values, {"purchase": purchase, "open_pipeline": open_pipeline, "relationship_count": rel_count, "fact_count": len(facts), "conflict_count": conflict_count, "stale": stale}


def _opportunity_features(db: Any, subject_id: str, as_of: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    oid = int(subject_id)
    row = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
    if not row:
        raise LookupError("opportunity not found")
    actions = db.execute("SELECT status, due_at, created_at FROM actions WHERE opportunity_id = ?", (oid,)).fetchall()
    amount = _number(row["amount"])
    stage = str(row["stage"] or "")
    stage_signal = {"赢单": 0.95, "won": 0.95, "商务谈判": 0.78, "方案与报价": 0.65, "需求确认": 0.52, "初步接触": 0.30, "输单": 0.05, "lost": 0.05}.get(stage, 0.40)
    completed = sum(1 for a in actions if str(a["status"] or "").lower() in {"completed", "done", "已完成"})
    overdue = sum(1 for a in actions if a["due_at"] and str(a["due_at"]) < as_of[:10] and str(a["status"] or "").lower() not in {"completed", "cancelled", "已完成", "已取消"})
    features = [
        _feature("opportunity.amount", amount, group="business", value_type="NUMBER", unit="CNY", normalized=min(1, amount / 3000000), missing=amount <= 0, as_of=as_of, source_type="Opportunity", source_id=subject_id, source_field="amount", quality=1 if amount > 0 else 0.3),
        _feature("opportunity.stage_signal", stage_signal, group="business", value_type="NUMBER", normalized=stage_signal, missing=not bool(stage), as_of=as_of, source_type="Opportunity", source_id=subject_id, source_field="stage", quality=1 if stage else 0.4),
        _feature("opportunity.action_count", len(actions), group="behavior", value_type="NUMBER", normalized=min(1, len(actions) / 5), missing=not bool(actions), as_of=as_of, source_type="Action", source_id=subject_id, source_field="count", quality=1 if actions else 0.4),
        _feature("opportunity.completed_action_count", completed, group="behavior", value_type="NUMBER", normalized=min(1, completed / 3), missing=not bool(actions), as_of=as_of, source_type="Action", source_id=subject_id, source_field="status", quality=1 if actions else 0.4),
        _feature("opportunity.overdue_action_count", overdue, group="risk", value_type="NUMBER", normalized=min(1, overdue / 3), missing=False, as_of=as_of, source_type="Action", source_id=subject_id, source_field="due_at", quality=1),
    ]
    return features, {"amount": amount, "stage": stage, "stage_signal": stage_signal, "actions": len(actions), "completed": completed, "overdue": overdue}


def _calculate(domain: str, targets: list[str], info: dict[str, Any], confidence: float, mode: str, as_of: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    explanations: list[dict[str, Any]] = []
    if domain == "CUSTOMER_GROWTH":
        growth = max(0.0, min(1.0, info["purchase"] / 1000000 * 0.35 + info["open_pipeline"] / 3000000 * 0.40 + min(1, info["relationship_count"] / 4) * 0.25))
        value = max(0.0, min(1.0, info["purchase"] / 1000000 * 0.45 + info["open_pipeline"] / 3000000 * 0.35 + min(1, info["fact_count"] / 10) * 0.20))
        mapping = {"GROWTH_POTENTIAL": (growth, "ratio", "采购与在途商机共同构成增长信号"), "CUSTOMER_VALUE": (value, "ratio", "历史采购和当前管道构成客户价值信号"), "EXPANSION_OPPORTUNITY": (min(1, info["open_pipeline"] / 2000000), "ratio", "在途商机金额代表可扩展空间")}
        for target in targets:
            if target in mapping:
                val, unit, summary = mapping[target]
                results.append({"target_type": target, "value_type": "PROBABILITY", "value": round(val, 4), "confidence": round(confidence, 4), "unit": unit, "result_status": "SIMULATION" if mode == "SIMULATION" else "PUBLISHED"})
                explanations.append({"factor_code": "customer.growth_signals", "direction": "POSITIVE" if val >= 0.5 else "NEUTRAL", "contribution": round(val, 4), "summary": summary})
    else:
        win = max(0.0, min(1.0, info["stage_signal"] * 0.65 + min(1, info["completed"] / 3) * 0.20 + (0.15 if info["actions"] else 0)))
        if info["overdue"]:
            win = max(0, win - min(0.25, info["overdue"] * 0.08))
        close_days = max(7, round(120 - win * 80 + info["overdue"] * 14))
        close_date = (_iso_date(as_of) + timedelta(days=close_days)).date().isoformat()
        mapping = {
            "WIN_PROBABILITY": (win, "PROBABILITY", "阶段、已完成行动和逾期行动共同决定赢单概率", None, None),
            "CLOSE_DATE": (close_date, "DATE", "基于赢单概率和行动逾期估计成交日期", (_iso_date(as_of) + timedelta(days=max(7, close_days - 14))).date().isoformat(), (_iso_date(as_of) + timedelta(days=close_days + 21)).date().isoformat()),
            "FORECAST_REVENUE": (round(info["amount"] * win, 2), "AMOUNT", "商机金额按赢单概率加权", round(info["amount"] * max(0, win - 0.15), 2), round(info["amount"] * min(1, win + 0.15), 2)),
            "RISK_LEVEL": ("HIGH" if win < 0.4 or info["overdue"] >= 2 else "MEDIUM" if win < 0.7 else "LOW", "CATEGORY", "低赢单概率或逾期行动触发风险分级", None, None),
        }
        for target in targets:
            if target not in mapping:
                continue
            val, value_type, summary, lower, upper = mapping[target]
            results.append({"target_type": target, "value_type": value_type, "value": val, "confidence": round(confidence, 4), "unit": "CNY" if value_type == "AMOUNT" else None, "lower_bound": lower, "upper_bound": upper, "result_status": "SIMULATION" if mode == "SIMULATION" else "PUBLISHED"})
            explanations.append({"factor_code": "opportunity.stage_and_execution", "direction": "POSITIVE" if win >= 0.6 else "NEGATIVE", "contribution": round(win, 4), "summary": summary})
    return results, explanations


def _insert_forecast(db: Any, payload: dict[str, Any], model: dict[str, Any], features: list[dict[str, Any]], info: dict[str, Any], now: str, parent_id: int | None = None) -> dict[str, Any]:
    targets = [str(x).strip().upper() for x in (payload.get("targetTypes") or payload.get("target_types") or []) if str(x).strip()]
    if not targets:
        targets = _json(model["target_types_json"], [])
    missing = sum(f["missing_flag"] for f in features)
    stale = sum(f["stale_flag"] for f in features)
    completeness = max(0.0, 1 - missing / max(1, len(features)))
    freshness = max(0.0, 1 - stale / max(1, len(features)))
    quality = sum(f["quality_score"] for f in features) / max(1, len(features))
    confidence = max(0.0, min(1.0, 0.80 * completeness * freshness * quality))
    mode = str(payload.get("mode", "PUBLISHED") or "PUBLISHED").upper()
    if mode not in MODES:
        raise ValueError("mode must be PUBLISHED or SIMULATION")
    cur = db.execute("""INSERT INTO forecasts
      (domain, subject_type, subject_id, target_types_json, as_of_time, model_version_id,
       feature_set_version, status, mode, data_completeness, freshness_score, overall_confidence,
       trigger_type, parent_forecast_id, created_at, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?, ?, ?, ?, ?, ?, ?)""", (
        payload["domain"], payload["subjectType"], str(payload["subjectId"]), json.dumps(targets), payload["asOfTime"], model["model_version_id"], model["feature_set_version"], mode,
        completeness, freshness, confidence, str(payload.get("triggerType", "MANUAL")).upper(), parent_id, now, None))
    forecast_id = cur.lastrowid
    for feature in features:
        db.execute("""INSERT INTO forecast_features
          (forecast_id, feature_code, feature_group, value_type, value_json, unit, normalized_value,
           missing_flag, stale_flag, feature_as_of_time, source_entity_type, source_entity_id, source_field, quality_score)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (forecast_id, feature["feature_code"], feature["feature_group"], feature["value_type"], json.dumps(feature["value"], ensure_ascii=False), feature["unit"], feature["normalized_value"], feature["missing_flag"], feature["stale_flag"], feature["feature_as_of_time"], feature["source_entity_type"], feature["source_entity_id"], feature["source_field"], feature["quality_score"]))
    results, explanations = _calculate(payload["domain"], targets, info, confidence, mode, payload["asOfTime"])
    for result in results:
        row = db.execute("""INSERT INTO prediction_results
          (forecast_id, target_type, value_type, value_json, lower_bound_json, upper_bound_json, unit, confidence, calibration_status, result_status, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'UNCALIBRATED', ?, ?)""", (forecast_id, result["target_type"], result["value_type"], json.dumps(result["value"], ensure_ascii=False), json.dumps(result.get("lower_bound"), ensure_ascii=False) if result.get("lower_bound") is not None else None, json.dumps(result.get("upper_bound"), ensure_ascii=False) if result.get("upper_bound") is not None else None, result.get("unit"), result["confidence"], result["result_status"], now))
        explanation = explanations[results.index(result)] if explanations else {"factor_code": "rule_baseline", "direction": "NEUTRAL", "contribution": 0, "summary": "规则基线结果"}
        db.execute("""INSERT INTO forecast_explanations
          (forecast_id, prediction_result_id, factor_code, direction, contribution, feature_ids_json, evidence_ids_json, summary)
          VALUES (?, ?, ?, ?, ?, ?, '[]', ?)""", (forecast_id, row.lastrowid, explanation["factor_code"], explanation["direction"], explanation["contribution"], json.dumps([f["feature_code"] for f in features]), explanation["summary"]))
    status = "READY" if results and completeness >= 0.5 else "PARTIAL" if results else "FAILED"
    db.execute("UPDATE forecasts SET status = ?, completed_at = ?, error_message = ? WHERE id = ?", (status, now, "" if results else "no prediction result", forecast_id))
    return get_forecast(db, forecast_id)


def run_forecast(db: Any, payload: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    timestamp = _now(now)
    domain = str(payload.get("domain", "")).strip().upper()
    if domain not in DOMAINS:
        raise ValueError("domain must be CUSTOMER_GROWTH or OPPORTUNITY")
    subject_type = str(payload.get("subjectType", "")).strip()
    if subject_type not in {"Customer", "Opportunity"} or (domain == "CUSTOMER_GROWTH" and subject_type != "Customer") or (domain == "OPPORTUNITY" and subject_type != "Opportunity"):
        raise ValueError("subjectType does not match domain")
    if payload.get("subjectId") is None or not _subject_exists(db, subject_type, str(payload["subjectId"])):
        raise LookupError("forecast subject not found")
    as_of = str(payload.get("asOfTime") or timestamp)
    try:
        _iso_date(as_of)
    except ValueError as exc:
        raise ValueError("invalid asOfTime") from exc
    ensure_forecast_schema(db, timestamp)
    model = _model(db, domain, payload.get("modelVersionId"), timestamp)
    features, info = _customer_features(db, str(payload["subjectId"]), as_of) if domain == "CUSTOMER_GROWTH" else _opportunity_features(db, str(payload["subjectId"]), as_of)
    return _insert_forecast(db, {**payload, "domain": domain, "subjectType": subject_type, "asOfTime": as_of}, model, features, info, timestamp)


def _serialize_result(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["value"] = _json(item.pop("value_json"), None)
    item["lowerBound"] = _json(item.pop("lower_bound_json"), None)
    item["upperBound"] = _json(item.pop("upper_bound_json"), None)
    item["targetType"] = item.get("target_type")
    item["valueType"] = item.get("value_type")
    return item


def get_forecast(db: Any, forecast_id: int) -> dict[str, Any]:
    row = db.execute("SELECT * FROM forecasts WHERE id = ?", (forecast_id,)).fetchone()
    if not row:
        raise LookupError("forecast not found")
    item = dict(row)
    if item["status"] == "READY" and item["mode"] == "PUBLISHED":
        try:
            if (_iso_date(_now()) - _iso_date(item["as_of_time"])).days > 30:
                db.execute("UPDATE forecasts SET status = 'STALE' WHERE id = ?", (forecast_id,))
                item["status"] = "STALE"
        except ValueError:
            pass
    item["targetTypes"] = _json(item.pop("target_types_json"), [])
    item.update({
        "forecastId": item["id"], "subjectType": item["subject_type"], "subjectId": item["subject_id"],
        "modelVersionId": item["model_version_id"], "asOfTime": item["as_of_time"],
        "featureSetVersion": item["feature_set_version"], "dataCompleteness": item["data_completeness"],
        "freshnessScore": item["freshness_score"], "overallConfidence": item["overall_confidence"],
        "triggerType": item["trigger_type"], "parentForecastId": item["parent_forecast_id"],
    })
    item["results"] = [_serialize_result(r) for r in db.execute("SELECT * FROM prediction_results WHERE forecast_id = ? ORDER BY id", (forecast_id,)).fetchall()]
    item["features"] = []
    for r in db.execute("SELECT * FROM forecast_features WHERE forecast_id = ? ORDER BY id", (forecast_id,)).fetchall():
        feature = dict(r)
        feature["value"] = _json(feature.pop("value_json"), None)
        feature["missing"] = bool(feature.pop("missing_flag"))
        feature["stale"] = bool(feature.pop("stale_flag"))
        item["features"].append(feature)
    item["explanations"] = []
    for r in db.execute("SELECT * FROM forecast_explanations WHERE forecast_id = ? ORDER BY id", (forecast_id,)).fetchall():
        explanation = dict(r)
        explanation["featureIds"] = _json(explanation.pop("feature_ids_json"), [])
        explanation["evidenceIds"] = _json(explanation.pop("evidence_ids_json"), [])
        item["explanations"].append(explanation)
    return item


def list_forecasts(db: Any, subject_type: str, subject_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute("SELECT id FROM forecasts WHERE subject_type = ? AND subject_id = ? ORDER BY created_at DESC, id DESC LIMIT ?", (subject_type, str(subject_id), max(1, min(200, int(limit))))).fetchall()
    return [get_forecast(db, r["id"]) for r in rows]


def replay_forecast(db: Any, forecast_id: int, now: str | None = None) -> dict[str, Any]:
    original = get_forecast(db, forecast_id)
    model = _model(db, original["domain"], original["model_version_id"], _now(now))
    features = []
    for f in original["features"]:
        features.append({"feature_code": f["feature_code"], "feature_group": f["feature_group"], "value_type": f["value_type"], "value": f["value"], "unit": f["unit"], "normalized_value": f["normalized_value"], "missing_flag": int(f["missing"]), "stale_flag": int(f["stale"]), "feature_as_of_time": f["feature_as_of_time"], "source_entity_type": f["source_entity_type"], "source_entity_id": f["source_entity_id"], "source_field": f["source_field"], "quality_score": f["quality_score"]})
    info: dict[str, Any] = {}
    for f in features:
        code = f["feature_code"]
        if original["domain"] == "CUSTOMER_GROWTH":
            info.update({"purchase": f["value"] if code.endswith("purchase_value") else info.get("purchase", 0), "open_pipeline": f["value"] if code.endswith("open_pipeline") else info.get("open_pipeline", 0), "relationship_count": f["value"] if code.endswith("relationship_coverage") else info.get("relationship_count", 0), "fact_count": f["value"] if code.endswith("fact_count") else info.get("fact_count", 0)})
        else:
            info.update({"amount": f["value"] if code.endswith("amount") else info.get("amount", 0), "stage_signal": f["value"] if code.endswith("stage_signal") else info.get("stage_signal", 0), "actions": f["value"] if code.endswith("action_count") else info.get("actions", 0), "completed": f["value"] if code.endswith("completed_action_count") else info.get("completed", 0), "overdue": f["value"] if code.endswith("overdue_action_count") else info.get("overdue", 0)})
    payload = {"domain": original["domain"], "subjectType": original["subject_type"], "subjectId": original["subject_id"], "targetTypes": original["targetTypes"], "asOfTime": original["as_of_time"], "mode": "SIMULATION", "triggerType": "MANUAL"}
    return _insert_forecast(db, payload, model, features, info, _now(now), parent_id=forecast_id)


def add_feedback(db: Any, forecast_id: int, payload: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    get_forecast(db, forecast_id)
    timestamp = _now(now)
    db.execute("INSERT INTO forecast_feedback (forecast_id, target_type, actual_value_json, feedback_type, actor, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (forecast_id, payload.get("targetType"), json.dumps(payload.get("actualValue"), ensure_ascii=False), payload.get("feedbackType", "actual_outcome"), payload.get("actor", "user"), payload.get("notes", ""), timestamp))
    return {"forecastId": forecast_id, "feedbackId": db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"], "createdAt": timestamp}
