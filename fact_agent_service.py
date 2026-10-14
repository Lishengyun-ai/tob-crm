"""CRM Agent 读取 Fact Candidate 的统一上下文服务。"""

from __future__ import annotations

from typing import Any, Optional


CONFIRMED_STATUSES = ("APPROVED", "MODIFIED")
PENDING_STATUS = "PENDING"

AGENT_ROLES = {
    "customer-insight": "customer",
    "customer-insight-agent": "customer",
    "opportunity-analysis": "opportunity",
    "opportunity-progress": "opportunity",
    "visit-assistant": "visit",
    "visit-script": "visit",
}


def _customer_id_for_opportunity(db: Any, opportunity_id: Optional[int]) -> Optional[int]:
    if not opportunity_id:
        return None
    row = db.execute("SELECT customer_id FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _query_facts(
    db: Any,
    role: str,
    customer_id: Optional[int],
    opportunity_id: Optional[int],
    limit: int,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if role == "customer":
        if customer_id is None:
            return []
        conditions.append("subject_type = 'Customer' AND subject_id = ?")
        params.append(customer_id)
        statuses = CONFIRMED_STATUSES
    elif role == "opportunity":
        if opportunity_id is None:
            return []
        conditions.append("subject_type = 'Opportunity' AND subject_id = ?")
        params.append(opportunity_id)
        statuses = CONFIRMED_STATUSES
    else:
        scope = []
        if customer_id is not None:
            scope.append("(subject_type = 'Customer' AND subject_id = ?)")
            params.append(customer_id)
        if opportunity_id is not None:
            scope.append("(subject_type = 'Opportunity' AND subject_id = ?)")
            params.append(opportunity_id)
        if not scope:
            return []
        conditions.append("(" + " OR ".join(scope) + ")")
        statuses = (PENDING_STATUS,)
    placeholders = ", ".join("?" for _ in statuses)
    conditions.append(f"status IN ({placeholders})")
    params.extend(statuses)
    params.append(max(1, min(int(limit), 100)))
    rows = db.execute(
        f"""SELECT * FROM fact_candidates
            WHERE {' AND '.join(conditions)}
            ORDER BY created_time DESC, id DESC
            LIMIT ?""",
        params,
    ).fetchall()
    return [_format_fact(dict(row)) for row in rows]


def _format_fact(fact: dict[str, Any]) -> dict[str, Any]:
    confirmed = fact["status"] in CONFIRMED_STATUSES
    fact["display_mark"] = "[已确认事实]" if confirmed else "[AI推测]"
    fact["is_business_basis"] = confirmed
    fact["is_suggestion_only"] = not confirmed
    fact["display_text"] = (
        f"{fact['display_mark']} {fact['predicate']}：{fact['object_value']}"
    )
    return fact


def get_agent_fact_context(
    db: Any,
    agent_id: str,
    *,
    customer_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    limit: int = 20,
) -> dict[str, Any]:
    """按 Agent 角色返回事实依据与提示，不返回 REJECTED 候选。"""
    role = AGENT_ROLES.get(str(agent_id).strip(), "")
    if not role:
        raise ValueError("agent does not support Fact Candidate context")
    if opportunity_id and customer_id is None:
        customer_id = _customer_id_for_opportunity(db, opportunity_id)
    facts = _query_facts(db, role, customer_id, opportunity_id, limit)
    confirmed = [fact for fact in facts if fact["is_business_basis"]]
    suggestions = [fact for fact in facts if fact["is_suggestion_only"]]
    return {
        "agentId": agent_id,
        "scope": {"customerId": customer_id, "opportunityId": opportunity_id},
        "facts": facts,
        "confirmedFacts": confirmed,
        "suggestions": suggestions,
        "businessBasis": [fact["display_text"] for fact in confirmed],
        "提示": [fact["display_text"] for fact in suggestions],
    }


__all__ = ["get_agent_fact_context"]
