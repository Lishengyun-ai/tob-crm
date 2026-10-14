import unittest

from insight_action_controller import InsightActionController


class FakeInsightActionService:
    def getInsightActions(self, insight_id):
        return [{"actionId": 10}]

    def createActionForInsight(self, insight_id, payload, action_creator, now):
        class Relation:
            def to_dict(self):
                return {"insightId": insight_id, "actionId": 10}

        return Relation(), {"id": 10, "title": "创建设计院拜访任务"}


class InsightActionControllerTests(unittest.TestCase):
    def test_get_and_post_routes(self):
        controller = InsightActionController(FakeInsightActionService())
        status, result = controller.handle("GET", "/api/insights/1/actions")
        self.assertEqual(status, 200)
        self.assertEqual(result[0]["actionId"], 10)
        status, result = controller.handle(
            "POST", "/api/insights/1/actions", {}, lambda **kwargs: {"id": 10}, "now"
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["action"]["id"], 10)


if __name__ == "__main__":
    unittest.main()
