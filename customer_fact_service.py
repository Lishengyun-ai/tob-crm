from __future__ import annotations

from typing import Any

from customer_fact import CustomerFact
from customer_fact_repository import CustomerFactRepository


class CustomerFactService:
    """CustomerFact 领域服务，只编排事实生命周期操作。"""

    def __init__(self, repository: CustomerFactRepository):
        self.repository = repository

    def createFact(self, customer_id: int, data: dict[str, Any]) -> CustomerFact:
        return self.repository.create(customer_id, data)

    def getCustomerFacts(self, customer_id: int) -> list[CustomerFact]:
        return self.repository.find_by_customer_id(customer_id)

    def expireFact(self, fact_id: int) -> CustomerFact:
        return self.repository.expire(fact_id)

    def verifyFact(self, fact_id: int) -> CustomerFact:
        return self.repository.verify(fact_id)
