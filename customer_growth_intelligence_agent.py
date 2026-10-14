"""Customer Growth Intelligence Agent：把客户事实、行动和预测转成开发策略。"""

import json
from datetime import datetime, timezone
from typing import Any

from customer_conversion_prediction import get_latest_customer_conversion_prediction
from customer_growth_prediction import get_latest_customer_growth_prediction
from customer_potential_prediction import get_latest_customer_potential_prediction
from customer_value_prediction import get_latest_customer_value_prediction


MODEL_VERSION = "customer-growth-intelligence-v1"
ACTIVE_ACTION_STATUSES = {"pending", "in_progress", "open", "todo", "待处理", "进行中", "未开始"}
DECISION_ROLES = {"决策人", "经济买家", "采购负责人", "采购", "技术负责人", "decision_maker", "economic_buyer"}


def _json(value: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _person_priority(person: Any) -> int:
    role = _text(person["role"]).lower()
    person_type = _text(person["person_type"]).lower()
    if person["is_primary"] or role in {item.lower() for item in DECISION_ROLES} or person_type in {item.lower() for item in DECISION_ROLES}:
        return 1
    if role or person_type:
        return 2
    return 3


def _prediction_snapshot(db: Any, customer_id: int) -> dict[str, Any]:
    return {
        "potential": get_latest_customer_potential_prediction(db, customer_id),
        "conversion": get_latest_customer_conversion_prediction(db, customer_id),
        "value": get_latest_customer_value_prediction(db, customer_id),
        "growth": get_latest_customer_growth_prediction(db, customer_id),
    }


def get_latest_customer_growth_intelligence_report(db: Any, customer_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """SELECT cgi.*, c.name AS customer_name
           FROM customer_growth_intelligence_reports cgi
           JOIN customers c ON c.id = cgi.customer_id
           WHERE cgi.customer_id = ?
           ORDER BY cgi.generated_at DESC, cgi.id DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    return _result(row) if row else None


def get_customer_growth_intelligence_report(db: Any, report_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT cgi.*, c.name AS customer_name
           FROM customer_growth_intelligence_reports cgi
           JOIN customers c ON c.id = cgi.customer_id
           WHERE cgi.id = ?""",
        (report_id,),
    ).fetchone()
    if not row:
        raise LookupError("customer growth intelligence report not found")
    return _result(row)


def _result(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["strategyReport"] = _json(result.pop("strategy_report_json"))
    result["keyPersonBreakthroughAdvice"] = _json(result.pop("key_person_advice_json"))
    result["visitStrategy"] = _json(result.pop("visit_strategy_json"))
    result["nextActions"] = _json(result.pop("next_actions_json"))
    result["predictionSnapshot"] = _json(result.pop("prediction_snapshot_json"))
    result["inputSnapshot"] = _json(result.pop("input_snapshot_json"))
    return result


def _build_person_advice(people: list[Any]) -> list[dict[str, Any]]:
    advice = []
    for person in sorted(people, key=_person_priority)[:5]:
        role = _text(person["role"]) or _text(person["title"]) or _text(person["person_type"]) or "客户联系人"
        if role.lower() in {"决策人", "decision_maker", "经济买家", "economic_buyer"}:
            message = "围绕预算、决策标准和最终批准节点沟通，争取确认明确的决策时间表。"
        elif role.lower() in {"采购负责人", "采购"}:
            message = "优先确认供应商准入、采购流程、商务条款和比价规则，减少后期商务阻力。"
        elif role.lower() in {"技术负责人", "technical"}:
            message = "用场景验证、技术方案和实施风险说明建立信任，并争取其为方案背书。"
        else:
            message = "先确认其在需求、影响力和内部推荐链中的位置，再通过业务价值获得转介绍。"
        advice.append({
            "personId": person["id"],
            "personName": person["name"],
            "role": role,
            "priority": "P1" if _person_priority(person) == 1 else "P2",
            "advice": message,
            "reason": "已关联客户的关键人记录" if person["is_primary"] else "作为客户关系链中的可触达联系人",
        })
    if not advice:
        advice.append({
            "personId": None,
            "personName": None,
            "role": None,
            "priority": "P0",
            "advice": "先建立客户关键人地图，至少识别业务负责人、经济买家和采购负责人。",
            "reason": "当前客户没有可用的 Person 关系记录",
        })
    return advice


def _build_strategy(customer: Any, predictions: dict[str, Any], people: list[Any], actions: list[Any]) -> dict[str, Any]:
    growth = predictions["growth"] or {}
    conversion = predictions["conversion"] or {}
    potential = predictions["potential"] or {}
    value = predictions["value"] or {}
    direction = _text(growth.get("growth_direction")) or "UNKNOWN"
    conversion_probability = int(conversion.get("conversion_probability") or 0)
    growth_score = int(growth.get("growth_score") or 0)
    potential_score = int(potential.get("potential_score") or 0)
    value_score = int(value.get("value_score") or 0)
    decision_makers = [
        person for person in people
        if _text(person["role"]).lower() in {item.lower() for item in DECISION_ROLES}
        or _text(person["person_type"]).lower() in {item.lower() for item in DECISION_ROLES}
    ]
    if direction == "UP" and conversion_probability >= 60:
        priority = "P0"
        summary = "客户增长信号和突破概率较强，应集中资源推进下一阶段验证与成交。"
    elif not decision_makers:
        priority = "P1"
        summary = "客户存在开发空间，但决策链尚未闭合，首要任务是补齐关键人并建立突破路径。"
    elif direction == "DOWN":
        priority = "P2"
        summary = "客户增长信号偏弱，应先验证需求变化、预算窗口和流失风险，再决定投入强度。"
    else:
        priority = "P1"
        summary = "客户具备一定开发基础，建议围绕业务价值和下一步承诺推动关系升温。"
    findings = [
        {"code": "GROWTH", "message": f"增长方向为 {direction}，增长评分为 {growth_score}。"},
        {"code": "CONVERSION", "message": f"突破成功概率为 {conversion_probability}%。"},
        {"code": "POTENTIAL", "message": f"客户开发潜力评分为 {potential_score}。"},
        {"code": "VALUE", "message": f"客户价值评分为 {value_score}，未来收入预测为 {value.get('future_revenue', 0)}。"},
        {"code": "RELATIONSHIP", "message": f"已识别 {len(people)} 位关键人，当前有 {len(actions)} 条行动记录。"},
    ]
    blockers = conversion.get("blockers") or []
    if blockers:
        findings.extend({"code": item.get("code", "BLOCKER"), "message": item.get("message", "")} for item in blockers[:3])
    return {"summary": summary, "priority": priority, "growthDirection": direction, "keyFindings": findings}


def _build_visit_strategy(customer: Any, predictions: dict[str, Any], people_advice: list[dict[str, Any]]) -> dict[str, Any]:
    conversion = predictions["conversion"] or {}
    growth = predictions["growth"] or {}
    value = predictions["value"] or {}
    blockers = conversion.get("blockers") or []
    target_ids = [item["personId"] for item in people_advice if item["personId"] is not None][:3]
    if any(item.get("code") == "DECISION_MAKER_MISSING" for item in blockers) or not target_ids:
        objective = "补齐决策链，确认业务负责人、经济买家和采购负责人。"
    elif _text(growth.get("growth_direction")) == "UP":
        objective = "验证增长机会，确认客户扩大合作范围的业务场景和时间表。"
    else:
        objective = "验证真实需求、预算窗口和客户当前优先级。"
    risk_questions = [item.get("message") for item in blockers if item.get("message")][:3]
    return {
        "objective": objective,
        "targetPersonIds": target_ids,
        "opening": f"围绕 {customer['name']} 当前业务目标，先确认近期变化和最需要解决的问题，再进入方案讨论。",
        "questions": [
            "今年最需要优先解决的业务问题是什么，影响如何衡量？",
            "这项工作的预算、决策人和采购流程分别是什么？",
            "如果本次验证成功，下一步的内部审批和时间节点是什么？",
        ],
        "valueMessage": f"建议用客户价值评分 {value.get('value_score', 0)} 和未来收入空间 {value.get('growth_space', 0)} 作为内部投入与合作优先级的讨论依据。",
        "risksToVerify": risk_questions or ["确认客户是否存在未披露的竞品、预算或内部优先级变化。"],
    }


def _build_next_actions(predictions: dict[str, Any], people: list[Any], actions: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    conversion = predictions["conversion"] or {}
    for item in (conversion.get("recommendedActions") or [])[:3]:
        result.append({
            "actionType": item.get("actionType", "CUSTOMER_FOLLOW_UP"),
            "title": item.get("reason", "执行客户开发跟进"),
            "reason": "来自 Customer Conversion Prediction 的建议",
            "priority": "P1",
            "suggestedDueDays": 7,
        })
    decision_makers = [
        person for person in people
        if _text(person["role"]).lower() in {item.lower() for item in DECISION_ROLES}
        or _text(person["person_type"]).lower() in {item.lower() for item in DECISION_ROLES}
    ]
    if not decision_makers:
        result.append({"actionType": "IDENTIFY_DECISION_MAKER", "title": "识别并建立决策人关系", "reason": "当前预测显示决策链不完整", "priority": "P0", "suggestedDueDays": 5})
    if not any(_text(action["status"]).lower() in ACTIVE_ACTION_STATUSES for action in actions):
        result.append({"actionType": "SCHEDULE_CUSTOMER_VISIT", "title": "安排下一次客户拜访或深度沟通", "reason": "当前没有可执行的进行中行动", "priority": "P1", "suggestedDueDays": 7})
    if not result:
        result.append({"actionType": "ADVANCE_CUSTOMER_STAGE", "title": "推进客户开发阶段", "reason": "已有关键人和行动基础，继续验证下一步承诺", "priority": "P1", "suggestedDueDays": 7})
    unique = []
    seen = set()
    for item in result:
        if item["actionType"] not in seen:
            unique.append(item)
            seen.add(item["actionType"])
    return unique[:5]


def run_customer_growth_intelligence_agent(db: Any, customer_id: int, now: str | None = None) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise LookupError("customer not found")
    people = db.execute(
        """SELECT p.id, p.name, p.organization, p.title, p.person_type, p.status,
                  cp.role, cp.is_primary
           FROM customer_persons cp JOIN persons p ON p.id = cp.person_id
           WHERE cp.customer_id = ? ORDER BY cp.is_primary DESC, p.id""",
        (customer_id,),
    ).fetchall()
    actions = db.execute(
        """SELECT id, title, action_type, status, priority, assignee, due_at, created_at
           FROM actions WHERE customer_id = ? ORDER BY created_at DESC, id DESC""",
        (customer_id,),
    ).fetchall()
    predictions = _prediction_snapshot(db, customer_id)
    people_advice = _build_person_advice(list(people))
    strategy = _build_strategy(customer, predictions, list(people), list(actions))
    visit_strategy = _build_visit_strategy(customer, predictions, people_advice)
    next_actions = _build_next_actions(predictions, list(people), list(actions))
    input_snapshot = {
        "customerId": customer_id,
        "personCount": len(people),
        "actionCount": len(actions),
        "predictionTypes": [key for key, value in predictions.items() if value],
        "generatedAt": timestamp,
    }
    cursor = db.execute(
        """INSERT INTO customer_growth_intelligence_reports
           (customer_id, strategy_report_json, key_person_advice_json,
            visit_strategy_json, next_actions_json, prediction_snapshot_json,
            input_snapshot_json, model_version, generated_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            customer_id,
            json.dumps(strategy, ensure_ascii=False),
            json.dumps(people_advice, ensure_ascii=False),
            json.dumps(visit_strategy, ensure_ascii=False),
            json.dumps(next_actions, ensure_ascii=False),
            json.dumps(predictions, ensure_ascii=False, default=str),
            json.dumps(input_snapshot, ensure_ascii=False),
            MODEL_VERSION,
            timestamp,
            timestamp,
        ),
    )
    return get_customer_growth_intelligence_report(db, cursor.lastrowid)
