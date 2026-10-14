from __future__ import annotations

import re
from typing import Any, Callable

from insight_action_service import InsightActionService


class InsightActionController:
    """Insight Action API Controller。"""

    def __init__(self, service: InsightActionService):
        self.service = service

    def handle(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        action_creator: Callable[..., dict[str, Any] | None] | None = None,
        now: str | None = None,
    ) -> tuple[int, Any]:
        match = re.fullmatch(r"/api/insights/(\d+)/actions", path)
        if not match:
            raise LookupError("insight action route not found")
        insight_id = int(match.group(1))
        if method.upper() == "GET":
            return 200, self.service.getInsightActions(insight_id)
        if method.upper() == "POST":
            if action_creator is None:
                raise RuntimeError("action creator is required")
            relation, action = self.service.createActionForInsight(
                insight_id, payload or {}, action_creator, now
            )
            return 201, {"insightAction": relation.to_dict(), "action": action}
        raise LookupError("insight action route not found")
