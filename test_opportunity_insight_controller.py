import unittest

from opportunity_insight_controller import OpportunityInsightController


class FakeOpportunityInsightService:
    def getOpportunityInsights(self, opportunity_id):
        return {"opportunities": [], "risks": [], "breakthrough": [], "competition": []}


class OpportunityInsightControllerTests(unittest.TestCase):
    def test_get_route_returns_grouped_shape(self):
        controller = OpportunityInsightController(FakeOpportunityInsightService())
        status, result = controller.handle("GET", "/api/opportunities/10/insights")
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"opportunities", "risks", "breakthrough", "competition"})


if __name__ == "__main__":
    unittest.main()
