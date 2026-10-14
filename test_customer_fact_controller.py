import unittest

from customer_fact import CustomerFact
from customer_fact_controller import CustomerFactController


class FakeCustomerFactService:
    def __init__(self):
        self.calls = []
        self.fact = CustomerFact(
            id=1,
            customerId=7,
            factType="PURCHASE",
            factName="采购模式",
            factContent="",
            factValue="项目采购",
            confidenceScore=80,
            sourceType="CRM",
            sourceId="source-1",
            status="ACTIVE",
            validFrom=None,
            validTo=None,
        )

    def getCustomerFacts(self, customer_id):
        self.calls.append(("getCustomerFacts", customer_id))
        return [self.fact]

    def createFact(self, customer_id, payload):
        self.calls.append(("createFact", customer_id, payload))
        return self.fact

    def verifyFact(self, fact_id):
        self.calls.append(("verifyFact", fact_id))
        return self.fact

    def expireFact(self, fact_id):
        self.calls.append(("expireFact", fact_id))
        return self.fact


class CustomerFactControllerTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeCustomerFactService()
        self.controller = CustomerFactController(self.service)

    def test_routes_delegate_to_service(self):
        status, result = self.controller.handle("GET", "/api/customers/7/facts")
        self.assertEqual(status, 200)
        self.assertEqual(result[0]["id"], 1)

        status, _ = self.controller.handle("POST", "/api/customers/7/facts", {"factType": "PURCHASE"})
        self.assertEqual(status, 201)
        status, _ = self.controller.handle("PUT", "/api/facts/1/verify")
        self.assertEqual(status, 200)
        status, _ = self.controller.handle("DELETE", "/api/facts/1")
        self.assertEqual(status, 200)
        self.assertEqual(
            [call[0] for call in self.service.calls],
            ["getCustomerFacts", "createFact", "verifyFact", "expireFact"],
        )

    def test_unknown_route_is_rejected(self):
        with self.assertRaisesRegex(LookupError, "route not found"):
            self.controller.handle("GET", "/api/facts/1")


if __name__ == "__main__":
    unittest.main()
