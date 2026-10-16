"""Opportunity Intelligence Agent 编排层。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from forecast_engine import ensure_forecast_schema, run_forecast


AGENT_CODE = "opportunity-intelligence"


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def ensure_opportunity_intelligence_schema(db: Any, now: str | None = None) -> None:
    timestamp = _now(now)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS opportunity_intelligence_risks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      opportunity_id INTEGER NOT NULL,
      risk_type TEXT NOT NULL,
      severity TEXT NOT NULL DEFAULT 'MEDIUM',
      probability REAL NOT NULL DEFAULT 0,
      impact_score REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'OPEN',
      reason TEXT NOT NULL DEFAULT '',
      evidence_json TEXT NOT NULL DEFAULT '[]',
      recommended_action TEXT NOT NULL DEFAULT '',
      owner_person_id INTEGER,
      detected_at TEXT NOT NULL,
      last_observed_at TEXT NOT NULL,
      due_at TEXT,
      resolution_note TEXT NOT NULL DEFAULT '',
      UNIQUE(opportunity_id, risk_type),
      FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS opportunity_agent_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_run_id INTEGER,
      opportunity_id INTEGER,
      agent_code TEXT NOT NULL,
      intent TEXT NOT NULL,
      input_context_hash TEXT NOT NULL,
      scope_json TEXT NOT NULL DEFAULT '{}',
      forecast_ids_json TEXT NOT NULL DEFAULT '[]',
      risk_ids_json TEXT NOT NULL DEFAULT '[]',
      action_ids_json TEXT NOT NULL DEFAULT '[]',
      approval_required INTEGER NOT NULL DEFAULT 0,
      approval_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
      result_status TEXT NOT NULL DEFAULT 'SUCCESS',
      result_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      completed_at TEXT,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL,
      FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_opportunity_intelligence_risks_score ON opportunity_intelligence_risks(status, severity, probability DESC, impact_score DESC);
    CREATE INDEX IF NOT EXISTS idx_opportunity_intelligence_risks_opp ON opportunity_intelligence_risks(opportunity_id, status);
    CREATE INDEX IF NOT EXISTS idx_opportunity_agent_runs_opp ON opportunity_agent_runs(opportunity_id, created_at DESC);
    """)
    db.execute("INSERT OR IGNORE INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (AGENT_CODE, "Opportunity Intelligence Agent", "商机诊断", "统一编排商机预测、风险和下一步行动。", timestamp, timestamp))


def _intent(message: str) -> str:
    text = str(message or "").lower()
    if any(word in text for word in ("风险", "危险", "最容易输", "risk")):
        return "RANK_RISK"
    if any(word in text for word in ("下一步", "行动", "怎么推进", "next best", "action")):
        return "RECOMMEND_NEXT_ACTION"
    if any(word in text for word in ("为什么", "原因", "解释", "概率")):
        return "ANALYZE_WIN_PROBABILITY"
    if any(word in text for word in ("成交", "什么时候", "close", "收入", "金额")):
        return "QUERY_FORECAST"
    return "RANK_WIN_PROBABILITY"


def _status_open(value: Any) -> bool:
    return str(value or "").lower() not in {"赢单", "输单", "won", "lost", "closed_won", "closed_lost"}


def _scope_opportunities(db: Any, payload: dict[str, Any]) -> list[Any]:
    scope = payload.get("scope") or {}
    clauses = ["1 = 1"]
    values: list[Any] = []
    requested = scope.get("opportunityIds") or payload.get("opportunityIds")
    if requested:
        ids = []
        for value in requested:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if not ids:
            return []
        clauses.append("id IN (%s)" % ",".join("?" for _ in ids))
        values.extend(ids)
    if scope.get("customerId") is not None:
        clauses.append("customer_id = ?")
        values.append(int(scope["customerId"]))
    if scope.get("projectId") is not None:
        clauses.append("project_id = ?")
        values.append(int(scope["projectId"]))
    if scope.get("owner") or scope.get("ownerName"):
        clauses.append("owner = ?")
        values.append(scope.get("owner") or scope.get("ownerName"))
    rows = db.execute(f"SELECT * FROM opportunities WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, id DESC", tuple(values)).fetchall()
    authorized = scope.get("authorizedOpportunityIds") or payload.get("authorizedOpportunityIds") or payload.get("userOpportunityIds")
    authorized_ids = None
    if authorized is not None:
        authorized_ids = {int(value) for value in authorized if str(value).isdigit()}
    return [row for row in rows if _status_open(row["stage"]) and (authorized_ids is None or row["id"] in authorized_ids)]


def _risk_candidates(db: Any, opportunity: Any, forecast: dict[str, Any], now: str) -> list[dict[str, Any]]:
    oid = opportunity["id"]
    actions = db.execute("SELECT id, title, status, due_at, created_at FROM actions WHERE opportunity_id = ? ORDER BY created_at DESC", (oid,)).fetchall()
    risks: list[dict[str, Any]] = []
    overdue = [a for a in actions if a["due_at"] and str(a["due_at"]) < now[:10] and str(a["status"] or "").lower() not in {"completed", "cancelled", "已完成", "已取消"}]
    if not actions:
        risks.append({"riskType": "STALE_ACTIVITY", "severity": "HIGH", "probability": 0.75, "impactScore": 0.75, "reason": "商机没有已记录的销售动作，无法证明近期推进活动。", "recommendedAction": "确认客户下一次会议、参与人和输出物。", "evidence": ["opportunity.actions"]})
    elif overdue:
        risks.append({"riskType": "STALE_ACTIVITY", "severity": "HIGH", "probability": min(0.95, 0.55 + len(overdue) * 0.1), "impactScore": 0.7, "reason": f"有 {len(overdue)} 个销售动作已逾期且未完成，可能推迟成交。", "recommendedAction": "先关闭或重新确认逾期动作的客户承诺日期。", "evidence": [f"action:{a['id']}" for a in overdue]})
    if not str(opportunity["next_action"] or "").strip():
        risks.append({"riskType": "NEXT_STEP_MISSING", "severity": "HIGH", "probability": 0.68, "impactScore": 0.65, "reason": "商机没有明确的下一步动作，阶段推进缺少可验证承诺。", "recommendedAction": "与客户确认下一步日期、参与人和交付物。", "evidence": ["opportunity.next_action"]})
    if not str(opportunity["risk"] or "").strip() and str(opportunity["stage"] or "") in {"初步接触", "需求确认"}:
        risks.append({"riskType": "DECISION_MAKER_GAP", "severity": "MEDIUM", "probability": 0.52, "impactScore": 0.6, "reason": "当前处于早期阶段且尚未记录明确风险或决策链信息。", "recommendedAction": "补齐预算负责人和最终决策人关系。", "evidence": ["opportunity.stage"]})
    if forecast.get("overallConfidence", forecast.get("overall_confidence", 0)) < 0.5:
        risks.append({"riskType": "DATA_QUALITY", "severity": "MEDIUM", "probability": 0.8, "impactScore": 0.5, "reason": "预测输入数据完整度或新鲜度不足，当前结论需要人工复核。", "recommendedAction": "补齐金额、阶段、项目和关键人事实后重新预测。", "evidence": ["forecast.overall_confidence"]})
    return risks


def _persist_risks(db: Any, opportunity_id: int, candidates: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    output = []
    for risk in candidates:
        existing = db.execute("SELECT id, status FROM opportunity_intelligence_risks WHERE opportunity_id = ? AND risk_type = ?", (opportunity_id, risk["riskType"])).fetchone()
        if existing and existing["status"] in {"RESOLVED", "FALSE_POSITIVE", "ACCEPTED"}:
            continue
        if existing:
            db.execute("""UPDATE opportunity_intelligence_risks
              SET severity = ?, probability = ?, impact_score = ?, reason = ?, evidence_json = ?, recommended_action = ?, last_observed_at = ?
              WHERE id = ?""", (risk["severity"], risk["probability"], risk["impactScore"], risk["reason"], json.dumps(risk["evidence"], ensure_ascii=False), risk["recommendedAction"], now, existing["id"]))
            risk_id = existing["id"]
        else:
            cur = db.execute("""INSERT INTO opportunity_intelligence_risks
              (opportunity_id, risk_type, severity, probability, impact_score, status, reason, evidence_json, recommended_action, detected_at, last_observed_at)
              VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)""", (opportunity_id, risk["riskType"], risk["severity"], risk["probability"], risk["impactScore"], risk["reason"], json.dumps(risk["evidence"], ensure_ascii=False), risk["recommendedAction"], now, now))
            risk_id = cur.lastrowid
        output.append({**risk, "riskId": risk_id, "opportunityId": opportunity_id, "status": "OPEN"})
    return output


def _recommendations(opportunity: Any, risks: list[dict[str, Any]], forecast: dict[str, Any], now: str) -> list[dict[str, Any]]:
    actions = []
    for risk in sorted(risks, key=lambda item: (item["severity"] != "CRITICAL", item["severity"] != "HIGH", -item["probability"]))[:3]:
        due = (datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(days=7)).date().isoformat()
        actions.append({"title": risk["recommendedAction"], "actionType": "opportunity_risk_mitigation", "priority": "high" if risk["severity"] in {"HIGH", "CRITICAL"} else "medium", "reason": risk["reason"], "riskId": risk["riskId"], "evidenceIds": risk["evidence"], "expectedImpact": "改善赢单概率或降低成交延期风险", "opportunityId": opportunity["id"], "assignee": opportunity["owner"], "dueAt": due, "approvalRequired": True})
    if not actions and forecast.get("results"):
        actions.append({"title": "确认下一次客户推进会议", "actionType": "next_step_confirmation", "priority": "medium", "reason": "当前未检测到开放风险，但需要保留可验证的下一步承诺。", "riskId": None, "evidenceIds": [], "expectedImpact": "保持商机推进节奏", "opportunityId": opportunity["id"], "assignee": opportunity["owner"], "dueAt": (datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(days=7)).date().isoformat(), "approvalRequired": False})
    return actions


def run_opportunity_intelligence(db: Any, payload: dict[str, Any], now: str | None = None, action_creator: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    timestamp = _now(now)
    ensure_forecast_schema(db, timestamp)
    ensure_opportunity_intelligence_schema(db, timestamp)
    message = str(payload.get("message", "")).strip()
    intent = _intent(message)
    rows = _scope_opportunities(db, payload)
    if not rows:
        raise LookupError("no opportunities in authorized scope")
    as_of = str(payload.get("asOfTime") or timestamp)
    max_results = max(1, min(50, int(payload.get("maxResults", 5) or 5)))
    forecast_ids: list[int] = []
    risk_ids: list[int] = []
    action_ids: list[int] = []
    result_rows = []
    all_risks = []
    for opportunity in rows:
        forecast = run_forecast(db, {"domain": "OPPORTUNITY", "subjectType": "Opportunity", "subjectId": opportunity["id"], "targetTypes": ["WIN_PROBABILITY", "CLOSE_DATE", "FORECAST_REVENUE", "RISK_LEVEL"], "asOfTime": as_of, "mode": "PUBLISHED", "modelVersionId": payload.get("modelVersionId")}, timestamp)
        forecast_ids.append(forecast["id"])
        results = {r["target_type"]: r for r in forecast["results"]}
        risks = _persist_risks(db, opportunity["id"], _risk_candidates(db, opportunity, forecast, timestamp), timestamp)
        risk_ids.extend([r["riskId"] for r in risks])
        all_risks.extend(risks)
        recommendations = _recommendations(opportunity, risks, forecast, timestamp)
        win = results.get("WIN_PROBABILITY", {}).get("value", 0)
        close = results.get("CLOSE_DATE", {}).get("value")
        revenue = results.get("FORECAST_REVENUE", {}).get("value", 0)
        result_rows.append({"opportunityId": opportunity["id"], "name": opportunity["name"], "customerName": opportunity["customer"], "winProbability": win, "expectedCloseDate": close, "forecastRevenue": revenue, "currency": "CNY", "riskLevel": "CRITICAL" if any(r["severity"] == "CRITICAL" for r in risks) else "HIGH" if any(r["severity"] == "HIGH" for r in risks) else "MEDIUM" if risks else "LOW", "confidence": forecast["overallConfidence"], "forecastId": forecast["id"], "topFactors": [e["factor_code"] for e in forecast["explanations"][:3]], "evidenceIds": [f["feature_code"] for f in forecast["features"] if not f["missing"]][:5], "risks": risks, "recommendedActions": recommendations, "asOfTime": as_of, "dataCompleteness": forecast["dataCompleteness"]})
    if intent == "RANK_RISK":
        result_rows.sort(key=lambda r: ({"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}[r["riskLevel"]], -len(r["risks"]), -r["confidence"]), reverse=True)
    else:
        result_rows.sort(key=lambda r: (r["winProbability"] * r["confidence"]), reverse=True)
    result_rows = result_rows[:max_results]
    confirm = bool(payload.get("confirmActions"))
    require_approval = bool(payload.get("requireApproval", True))
    if confirm and action_creator:
        for result in result_rows:
            for recommendation in result["recommendedActions"]:
                if recommendation["approvalRequired"] and str(payload.get("approvalStatus", "PENDING")).upper() != "APPROVED":
                    continue
                action = action_creator(title=recommendation["title"], description=recommendation["reason"], action_type=recommendation["actionType"], status="pending", priority=recommendation["priority"], assignee=recommendation["assignee"], due_at=recommendation["dueAt"], opportunity_id=recommendation["opportunityId"], source_type="opportunity_intelligence", source_id=str(recommendation.get("riskId") or result["forecastId"]), source_agent_id=AGENT_CODE, action_origin="ai_recommended", approval_status="approved" if not recommendation["approvalRequired"] else "approved", created_by=payload.get("actor", "user"), now=timestamp)
                action_ids.append(action["id"])
    context_hash = hashlib.sha256(json.dumps({"message": message, "scope": payload.get("scope", {}), "asOfTime": as_of}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result_status = "SUCCESS" if result_rows else "PARTIAL"
    agent_cur = db.execute("INSERT INTO agent_runs (agent_id, opportunity_id, input_json, result, status, created_at) VALUES (?, ?, ?, ?, ?, ?)", (AGENT_CODE, result_rows[0]["opportunityId"] if len(result_rows) == 1 else None, json.dumps(payload, ensure_ascii=False), json.dumps(result_rows, ensure_ascii=False), "completed", timestamp))
    if action_ids:
        db.execute("UPDATE actions SET source_agent_run_id = ? WHERE id IN (%s)" % ",".join("?" for _ in action_ids), (agent_cur.lastrowid, *action_ids))
    run_cur = db.execute("""INSERT INTO opportunity_agent_runs
      (agent_run_id, opportunity_id, agent_code, intent, input_context_hash, scope_json, forecast_ids_json, risk_ids_json, action_ids_json, approval_required, approval_status, result_status, result_json, created_at, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (agent_cur.lastrowid, result_rows[0]["opportunityId"] if len(result_rows) == 1 else None, AGENT_CODE, intent, context_hash, json.dumps(payload.get("scope", {}), ensure_ascii=False), json.dumps(forecast_ids), json.dumps(risk_ids), json.dumps(action_ids), int(require_approval), "APPROVED" if action_ids else "PENDING" if require_approval else "NOT_REQUIRED", result_status, json.dumps(result_rows, ensure_ascii=False), timestamp, timestamp))
    for result in result_rows:
        db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (result["opportunityId"], "opportunity_intelligence_agent_run", f"Opportunity Intelligence Agent 已运行：{intent}", timestamp))
    answer = "当前最可能赢的商机已按赢单概率排序。" if intent != "RANK_RISK" else "当前风险最高的商机已按风险等级和置信度排序。"
    if intent == "RECOMMEND_NEXT_ACTION":
        answer = "已根据开放风险和阶段缺口生成下一步行动建议；未经确认或审批不会写入 Action。"
    return {"runId": agent_cur.lastrowid, "agentRunId": run_cur.lastrowid, "intent": intent, "answer": answer, "scope": {"description": "当前用户授权范围内的开放商机", "opportunityCount": len(rows)}, "results": result_rows, "dataQuality": {"status": "PARTIAL" if any(r["dataCompleteness"] < 0.7 for r in result_rows) else "READY", "staleOpportunityCount": sum(1 for r in result_rows if r["dataCompleteness"] < 0.5), "missingDataNotice": "部分商机存在缺失或低质量输入，置信度已下调。" if any(r["dataCompleteness"] < 0.7 for r in result_rows) else ""}, "citations": [{"type": "FORECAST", "id": r["forecastId"], "asOfTime": r["asOfTime"]} for r in result_rows], "recommendedActions": [a for r in result_rows for a in r["recommendedActions"]], "actionIds": action_ids, "approvalRequired": require_approval and bool([a for r in result_rows for a in r["recommendedActions"]]), "createdAt": timestamp}


def list_risks(db: Any, opportunity_id: int) -> list[dict[str, Any]]:
    output = []
    for row in db.execute("SELECT * FROM opportunity_intelligence_risks WHERE opportunity_id = ? ORDER BY CASE severity WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END DESC, probability DESC", (opportunity_id,)).fetchall():
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
        return_item = {**item, "riskId": item["id"], "riskType": item["risk_type"], "opportunityId": item["opportunity_id"], "impactScore": item["impact_score"], "recommendedAction": item["recommended_action"]}
        output.append(return_item)
    return output


def update_risk_status(db: Any, risk_id: int, status: str, note: str = "", now: str | None = None) -> dict[str, Any]:
    normalized = str(status or "").upper()
    if normalized not in {"OPEN", "ACKNOWLEDGED", "MITIGATING", "RESOLVED", "ACCEPTED", "FALSE_POSITIVE"}:
        raise ValueError("invalid risk status")
    timestamp = _now(now)
    row = db.execute("SELECT * FROM opportunity_intelligence_risks WHERE id = ?", (risk_id,)).fetchone()
    if not row:
        raise LookupError("risk not found")
    db.execute("UPDATE opportunity_intelligence_risks SET status = ?, resolution_note = ?, last_observed_at = ? WHERE id = ?", (normalized, str(note or ""), timestamp, risk_id))
    return {**dict(row), "riskId": risk_id, "status": normalized, "resolutionNote": note, "updatedAt": timestamp}
