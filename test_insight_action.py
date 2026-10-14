import sqlite3
import unittest

from insight_action_repository import InsightActionRepository
from insight_action_service import InsightActionService


class InsightActionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """CREATE TABLE insights (id INTEGER PRIMARY KEY, customer_id INTEGER, name TEXT, description TEXT);
            CREATE TABLE actions (id INTEGER PRIMARY KEY, title TEXT, status TEXT);
            CREATE TABLE insight_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id INTEGER NOT NULL,
                action_id INTEGER NOT NULL,
                priority TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_time TEXT NOT NULL,
                UNIQUE(insight_id, action_id)
            );
            INSERT INTO insights VALUES (1, 7, '设计院关系不足', '需要补足设计院关键关系');"""
        )
        self.db.execute("INSERT INTO actions VALUES (10, '创建设计院拜访任务', 'pending')")
        self.service = InsightActionService(InsightActionRepository(self.db))

    def tearDown(self):
        self.db.close()

    def test_list_existing_action_link(self):
        self.db.execute(
            "INSERT INTO insight_actions VALUES (1, 1, 10, 'high', '设计院关系不足', '2026-10-14T00:00:00+00:00')"
        )
        result = self.service.getInsightActions(1)
        self.assertEqual(result[0]["actionId"], 10)
        self.assertEqual(result[0]["title"], "创建设计院拜访任务")

    def test_ai_creates_existing_action_and_relation(self):
        created = []

        def action_creator(**kwargs):
            created.append(kwargs)
            return {"id": 10, "title": kwargs["title"]}

        relation, action = self.service.createActionForInsight(
            1,
            {"priority": "high", "reason": "设计院关系不足"},
            action_creator,
            "2026-10-14T00:00:00+00:00",
        )
        self.assertEqual(relation.actionId, 10)
        self.assertEqual(action["title"], "跟进洞察：设计院关系不足")
        self.assertEqual(created[0]["source_type"], "insight")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
