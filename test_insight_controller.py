import unittest

from insight import Insight
from insight_controller import InsightController


class FakeInsightService:
    def __init__(self):
        self.insight = Insight(1, 7, "预算窗口", "Opportunity", "客户已释放预算信号", "Agent", "2026-10-14T00:00:00+00:00")

    def listInsights(self, insight_type=None, source=None, customer_id=None):
        return [self.insight]

    def getInsight(self, insight_id):
        return self.insight if insight_id == 1 else None

    def createInsight(self, payload):
        return self.insight

    def updateInsight(self, insight_id, payload):
        return self.insight

    def deleteInsight(self, insight_id):
        return None


class InsightControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = InsightController(FakeInsightService())

    def test_crud_routes(self):
        self.assertEqual(self.controller.handle("GET", "/api/insights")[0], 200)
        self.assertEqual(self.controller.handle("GET", "/api/customers/7/insights")[0], 200)
        self.assertEqual(self.controller.handle("GET", "/api/insights/1")[1]["id"], 1)
        self.assertEqual(self.controller.handle("POST", "/api/insights", {})[0], 201)
        self.assertEqual(self.controller.handle("PUT", "/api/insights/1", {})[0], 200)
        self.assertEqual(self.controller.handle("DELETE", "/api/insights/1")[1]["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
