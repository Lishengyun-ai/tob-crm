import unittest

from insight_score import InsightScore
from insight_score_controller import InsightScoreController


class FakeInsightScoreService:
    def scoreInsight(self, insight_id, now=None):
        return InsightScore(1, insight_id, 90, 85, 90, 82, 87, now or "now")

    def getInsightScore(self, insight_id):
        return self.scoreInsight(insight_id)

    def listScores(self, minimum_score=None):
        return [self.scoreInsight(1)]


class InsightScoreControllerTests(unittest.TestCase):
    def test_score_routes(self):
        controller = InsightScoreController(FakeInsightScoreService())
        status, result = controller.handle("POST", "/api/insights/1/score", "now")
        self.assertEqual(status, 201)
        self.assertEqual(result["score"], 87)
        self.assertEqual(controller.handle("GET", "/api/insight-scores")[1][0]["insightId"], 1)


if __name__ == "__main__":
    unittest.main()
