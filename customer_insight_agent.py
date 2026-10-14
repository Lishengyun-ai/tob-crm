from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from insight import Insight
from insight_repository import InsightRepository
from insight_score_repository import InsightScoreRepository


class CustomerInsightAgent:
    """基于 CRM 本体数据生成结构化 Insight，再组装客户洞察报告。"""

    SOURCE = "Customer Insight Agent"

    def __init__(self, db: Any):
        self.db = db
        self.insights = InsightRepository(db)
        self.scores = InsightScoreRepository(db)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_context(self, customer_id: int) -> dict[str, Any]:
        customer = self.db.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not customer:
            raise LookupError("customer not found")
        opportunities = self.db.execute(
            """SELECT * FROM opportunities
               WHERE customer_id = ? OR (customer_id IS NULL AND customer = ?)
               ORDER BY updated_at DESC, id DESC""",
            (customer_id, customer["name"]),
        ).fetchall()
        activities = self.db.execute(
            """SELECT be.*, o.name AS opportunity_name
               FROM business_events be
               JOIN opportunities o ON o.id = be.opportunity_id
               WHERE o.customer_id = ? OR (o.customer_id IS NULL AND o.customer = ?)
               ORDER BY be.created_at DESC, be.id DESC""",
            (customer_id, customer["name"]),
        ).fetchall()
        persons = self.db.execute(
            """SELECT p.*, cp.role, cp.is_primary
               FROM customer_persons cp
               JOIN persons p ON p.id = cp.person_id
               WHERE cp.customer_id = ?
               ORDER BY cp.is_primary DESC, p.id""",
            (customer_id,),
        ).fetchall()
        competition = self.db.execute(
            """SELECT * FROM customer_facts
               WHERE customer_id = ? AND fact_type = 'COMPETITOR'
                 AND status = 'ACTIVE'
               ORDER BY created_time DESC, fact_id DESC""",
            (customer_id,),
        ).fetchall()
        return {
            "customer": dict(customer),
            "opportunities": [dict(row) for row in opportunities],
            "activities": [dict(row) for row in activities],
            "persons": [dict(row) for row in persons],
            "competition": [dict(row) for row in competition],
        }

    def _create(self, customer_id: int, name: str, insight_type: str, description: str, now: str) -> Insight:
        return self.insights.create(
            {
                "customerId": customer_id,
                "name": name,
                "type": insight_type,
                "description": description,
                "source": self.SOURCE,
            },
            now=now,
        )

    def _generate_insights(self, context: dict[str, Any], now: str) -> list[Insight]:
        customer = context["customer"]
        customer_id = customer["id"]
        opportunities = context["opportunities"]
        activities = context["activities"]
        persons = context["persons"]
        competition = context["competition"]
        generated: list[Insight] = []

        if opportunities:
            for opportunity in opportunities:
                amount = int(opportunity.get("amount") or 0)
                generated.append(self._create(
                    customer_id,
                    f"商机机会：{opportunity['name']}",
                    "Opportunity",
                    f"{opportunity['name']}处于{opportunity.get('stage', '未知阶段')}，商机金额为{amount}，可结合{len(activities)}条客户活动继续推进。",
                    now,
                ))
        else:
            generated.append(self._create(
                customer_id, "客户暂无在途商机", "Opportunity",
                "当前客户没有已关联的在途商机，存在从客户需求和项目储备中识别新机会的空间。", now,
            ))

        risks = [row["risk"] for row in opportunities if str(row.get("risk", "")).strip()]
        if risks:
            generated.append(self._create(
                customer_id, "商机风险信号", "Risk",
                f"当前商机存在{len(risks)}项风险描述：{'；'.join(str(item) for item in risks[:3])}。", now,
            ))
        if not persons:
            generated.append(self._create(
                customer_id, "关键人覆盖不足", "Risk",
                "客户尚未建立关键人关系记录，决策链和影响人信息不足。", now,
            ))
        if not activities:
            generated.append(self._create(
                customer_id, "近期客户活动不足", "Risk",
                "当前客户没有可识别的业务活动记录，洞察时效性和推进连续性不足。", now,
            ))

        if persons:
            roles = sorted({str(person.get("role") or "联系人") for person in persons})
            generated.append(self._create(
                customer_id, "关键人关系突破", "Breakthrough",
                f"已识别{len(persons)}位客户关键人，覆盖角色：{'、'.join(roles[:5])}，可围绕高影响力角色设计下一次拜访。", now,
            ))
        else:
            generated.append(self._create(
                customer_id, "补齐关键人关系", "Breakthrough",
                "优先识别客户决策人、采购负责人和技术负责人，建立进入客户决策链的突破路径。", now,
            ))

        if competition:
            competitor_names = [str(row.get("fact_value") or row.get("fact_name")) for row in competition]
            generated.append(self._create(
                customer_id, "竞品情况", "Competition",
                f"已记录{len(competition)}条竞争事实，涉及：{'、'.join(competitor_names[:5])}。需要在方案和价值证明中回应竞争差异。", now,
            ))
        else:
            generated.append(self._create(
                customer_id, "竞争信息待补充", "Competition",
                "当前客户没有已确认的竞争事实，建议在下一次拜访中补充竞品、价格和供应商准入信息。", now,
            ))

        next_actions = [str(row["next_action"]).strip() for row in opportunities if str(row.get("next_action", "")).strip()]
        next_step = next_actions[0] if next_actions else "确认客户决策链并安排下一次客户沟通"
        generated.append(self._create(
            customer_id, "下一步建议", "Recommendation",
            f"建议优先执行：{next_step}。行动应结合当前关键人、活动和竞争信息持续回写 CRM。", now,
        ))
        return generated

    @staticmethod
    def _report(
        insights: list[Insight], scores: dict[int, dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        sections = {
            "opportunities": [],
            "risks": [],
            "breakthrough": [],
            "competition": [],
            "recommendations": [],
        }
        key_by_type = {
            "Opportunity": "opportunities",
            "Risk": "risks",
            "Breakthrough": "breakthrough",
            "Competition": "competition",
            "Recommendation": "recommendations",
        }
        for insight in insights:
            sections[key_by_type[insight.type]].append({
                **insight.to_dict(),
                "score": scores[insight.id],
            })
        for items in sections.values():
            items.sort(key=lambda item: item["score"]["score"], reverse=True)
        return sections

    def run(self, customer_id: int, now: str | None = None) -> dict[str, Any]:
        timestamp = now or self._now()
        context = self._load_context(customer_id)
        insights = self._generate_insights(context, timestamp)
        score_results = [self.scores.score(insight.id, timestamp) for insight in insights]
        score_map = {score.insightId: score.to_dict() for score in score_results}
        return {
            "customer": context["customer"],
            "contextSummary": {
                "opportunityCount": len(context["opportunities"]),
                "activityCount": len(context["activities"]),
                "personCount": len(context["persons"]),
                "competitionCount": len(context["competition"]),
            },
            "insights": [{**insight.to_dict(), "score": score_map[insight.id]} for insight in insights],
            "scores": list(score_map.values()),
            "report": self._report(insights, score_map),
        }
