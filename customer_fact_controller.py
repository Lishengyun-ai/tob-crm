from __future__ import annotations

import re
from typing import Any

from customer_fact import CustomerFact
from customer_fact_service import CustomerFactService


class CustomerFactController:
    """CustomerFact API Controller，不直接访问数据库。"""

    ROUTES = {
        "GET": "/api/customers/{id}/facts",
        "POST": "/api/customers/{id}/facts",
        "PUT": "/api/facts/{id}/verify",
        "DELETE": "/api/facts/{id}",
    }

    def __init__(self, service: CustomerFactService):
        self.service = service

    @staticmethod
    def _serialize(fact: CustomerFact) -> dict[str, Any]:
        return fact.to_dict()

    def get_customer_facts(self, customer_id: int) -> list[dict[str, Any]]:
        return [self._serialize(fact) for fact in self.service.getCustomerFacts(customer_id)]

    def create_customer_fact(self, customer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._serialize(self.service.createFact(customer_id, payload))

    def verify_fact(self, fact_id: int) -> dict[str, Any]:
        return self._serialize(self.service.verifyFact(fact_id))

    def expire_fact(self, fact_id: int) -> dict[str, Any]:
        return self._serialize(self.service.expireFact(fact_id))

    def handle(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
        """将指定 API 路径分发到对应 Controller 动作。"""
        method = method.upper()
        payload = payload or {}
        match = re.fullmatch(r"/api/customers/(\d+)/facts", path)
        if match and method == "GET":
            return 200, self.get_customer_facts(int(match.group(1)))
        if match and method == "POST":
            return 201, self.create_customer_fact(int(match.group(1)), payload)

        match = re.fullmatch(r"/api/facts/(\d+)/verify", path)
        if match and method == "PUT":
            return 200, self.verify_fact(int(match.group(1)))

        match = re.fullmatch(r"/api/facts/(\d+)", path)
        if match and method == "DELETE":
            return 200, self.expire_fact(int(match.group(1)))

        raise LookupError("customer fact route not found")
