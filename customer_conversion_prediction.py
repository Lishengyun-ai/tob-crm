"""Customer Conversion Prediction 派生实体与 V1 计算服务。"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any


MODEL_VERSION = "customer-conversion-v1"


def _json(value: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _result(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["blockers"] = _json(result.pop("blockers_json"))
    result["recommendedActions"] = _json(result.pop("recommended_actions_json"))
    result["evidenceSnapshot"] = _json(result.pop("evidence_snapshot_json"))
    return result


def get_latest_customer_conversion_prediction(db: Any, customer_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT ccp.*, c.name AS customer_name
           FROM customer_conversion_predictions ccp
           JOIN customers c ON c.id = ccp.customer_id
           WHERE ccp.customer_id = ?
           ORDER BY ccp.assessed_at DESC, ccp.id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    return _result(row) if row else None


def get_customer_conversion_prediction(db: Any, prediction_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT ccp.*, c.name AS customer_name
           FROM customer_conversion_predictions ccp
           JOIN customers c ON c.id = ccp.customer_id
           WHERE ccp.id = ?""",
        (prediction_id,),
    ).fetchone()
    if not row:
        raise LookupError("customer conversion prediction not found")
    return _result(row)


def predict_customer_conversion(db: Any, customer_id: int, now: str | None = None) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise LookupError("customer not found")

    people = db.execute(
        """SELECT p.id, p.name, p.title, p.person_type, cp.role, cp.is_primary
           FROM customer_persons cp JOIN persons p ON p.id = cp.person_id
           WHERE cp.customer_id = ? AND p.status = 'active'""",
        (customer_id,),
    ).fetchall()
    actions = db.execute(
        """SELECT id, title, action_type, status, priority, due_at, created_at
           FROM actions WHERE customer_id = ? ORDER BY created_at DESC, id DESC""",
        (customer_id,),
    ).fetchall()
    development = db.execute(
        """SELECT current_stage_code, current_stage_name, next_action, status
           FROM customer_developments WHERE customer_id = ? AND status = 'active'
           ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()

    decision_roles = {"决策人", "经济买家", "采购负责人", "技术负责人", "decision_maker", "economic_buyer"}
    decision_maker_count = sum(1 for person in people if str(person["role"] or "") in decision_roles or str(person["person_type"] or "") in decision_roles)
    completed_actions = sum(1 for action in actions if str(action["status"] or "").lower() in {"completed", "done", "已完成"})
    active_actions = sum(1 for action in actions if str(action["status"] or "").lower() not in {"completed", "done", "已完成", "cancelled", "已取消"})
    person_signal = min(100, len(people) * 25)
    decision_signal = min(100, decision_maker_count * 50)
    activity_signal = min(100, len(actions) * 20)
    execution_signal = min(100, completed_actions * 30 + active_actions * 10)
    stage_signal = 60 if development else 25
    if development and str(development["current_stage_code"] or "").upper() in {"AT4", "AT5", "AT6", "OPP_SIGNED"}:
        stage_signal = 90
    probability = round(person_signal * 0.25 + decision_signal * 0.30 + activity_signal * 0.20 + execution_signal * 0.15 + stage_signal * 0.10)
    probability = max(0, min(100, probability))

    blockers: list[dict[str, Any]] = []
    if not people:
        blockers.append({"code": "PERSON_MISSING", "message": "尚未建立客户关键人关系"})
    elif not decision_maker_count:
        blockers.append({"code": "DECISION_MAKER_MISSING", "message": "尚未识别决策人或采购负责人"})
    if not actions:
        blockers.append({"code": "ACTION_MISSING", "message": "缺少客户开发行动记录"})
    if development and not str(development["next_action"] or "").strip():
        blockers.append({"code": "NEXT_ACTION_MISSING", "message": "客户开发主线缺少下一步动作"})
    if not development:
        blockers.append({"code": "DEVELOPMENT_MISSING", "message": "尚未建立客户开发主线"})

    recommended = []
    if not decision_maker_count:
        recommended.append({"actionType": "IDENTIFY_DECISION_MAKER", "reason": "补齐客户决策链"})
    if not actions:
        recommended.append({"actionType": "CREATE_CUSTOMER_ACTION", "reason": "建立下一次可验证的客户接触"})
    elif active_actions == 0:
        recommended.append({"actionType": "SCHEDULE_FOLLOW_UP", "reason": "补充下一步跟进动作"})
    if development and not str(development["next_action"] or "").strip():
        recommended.append({"actionType": "DEFINE_NEXT_STEP", "reason": "为当前开发阶段设置下一步"})
    if not recommended:
        recommended.append({"actionType": "ADVANCE_CUSTOMER_STAGE", "reason": "当前关系和行动基础较完整，可推进阶段验证"})

    days = max(7, min(180, round(90 - probability * 0.65)))
    expected_at = (datetime.fromisoformat(timestamp.replace("Z", "+00:00")) + timedelta(days=days)).isoformat()
    evidence = {
        "personCount": len(people),
        "decisionMakerCount": decision_maker_count,
        "actionCount": len(actions),
        "completedActionCount": completed_actions,
        "activeActionCount": active_actions,
        "developmentStage": development["current_stage_code"] if development else None,
        "calculatedAt": timestamp,
    }
    cursor = db.execute(
        """INSERT INTO customer_conversion_predictions
           (customer_id, conversion_probability, expected_conversion_days,
            expected_conversion_at, blockers_json, recommended_actions_json,
            evidence_snapshot_json, model_version, assessed_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, probability, days, expected_at,
         json.dumps(blockers, ensure_ascii=False), json.dumps(recommended, ensure_ascii=False),
         json.dumps(evidence, ensure_ascii=False), MODEL_VERSION, timestamp, timestamp),
    )
    return get_customer_conversion_prediction(db, cursor.lastrowid)
