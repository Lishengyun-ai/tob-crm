from __future__ import annotations

import re
from typing import Any

from opportunity_insight_service import OpportunityInsightService


class OpportunityInsightController:
    """商机洞察查询 API Controller。"""

    def __init__(self, service: OpportunityInsightService):
        self.service = service

    def handle(self, method: str, path: str) -> tuple[int, Any]:
        match = re.fullmatch(r"/api/opportunities/(\d+)/insights", path)
        if match and method.upper() == "GET":
            return 200, self.service.getOpportunityInsights(int(match.group(1)))
        raise LookupError("opportunity insight route not found")
