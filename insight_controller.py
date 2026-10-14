from __future__ import annotations

import re
from typing import Any

from insight import Insight
from insight_service import InsightService


class InsightController:
    """Insight CRUD API Controller。"""

    def __init__(self, service: InsightService):
        self.service = service

    @staticmethod
    def _serialize(insight: Insight) -> dict[str, Any]:
        return insight.to_dict()

    def handle(
        self, method: str, path: str, payload: dict[str, Any] | None = None,
        query: dict[str, list[str]] | None = None,
    ) -> tuple[int, Any]:
        method = method.upper()
        payload = payload or {}
        query = query or {}
        if path == "/api/insights" and method == "GET":
            customer_id = query.get("customerId", [None])[0]
            if customer_id is not None:
                try:
                    customer_id = int(customer_id)
                except ValueError as exc:
                    raise ValueError("customerId must be an integer") from exc
            return 200, [self._serialize(item) for item in self.service.listInsights(
                query.get("type", [None])[0], query.get("source", [None])[0], customer_id
            )]
        match = re.fullmatch(r"/api/customers/(\d+)/insights", path)
        if match and method == "GET":
            return 200, [self._serialize(item) for item in self.service.listInsights(
                customer_id=int(match.group(1))
            )]
        if path == "/api/insights" and method == "POST":
            return 201, self._serialize(self.service.createInsight(payload))

        match = re.fullmatch(r"/api/insights/(\d+)", path)
        if match:
            insight_id = int(match.group(1))
            if method == "GET":
                insight = self.service.getInsight(insight_id)
                if insight is None:
                    raise LookupError("insight not found")
                return 200, self._serialize(insight)
            if method == "PUT":
                return 200, self._serialize(self.service.updateInsight(insight_id, payload))
            if method == "DELETE":
                self.service.deleteInsight(insight_id)
                return 200, {"status": "deleted", "id": insight_id}
        raise LookupError("insight route not found")
