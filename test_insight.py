import sqlite3
import unittest

from insight import Insight, InsightType
from insight_repository import InsightRepository


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                created_time TEXT NOT NULL
            )"""
        )
        self.db.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        self.db.execute("INSERT INTO customers (id, name) VALUES (7, '测试客户')")
        self.repository = InsightRepository(self.db)

    def tearDown(self):
        self.db.close()

    def test_create_update_list_and_delete(self):
        insight = self.repository.create(
            {"customerId": 7, "name": "预算窗口", "type": InsightType.OPPORTUNITY.value,
             "description": "客户已释放预算信号", "source": "Customer Insight Agent"},
            now="2026-10-14T00:00:00+00:00",
        )
        self.assertIsInstance(insight, Insight)
        self.assertEqual(insight.created_time, "2026-10-14T00:00:00+00:00")
        self.assertEqual(len(self.repository.list(InsightType.OPPORTUNITY.value)), 1)

        updated = self.repository.update(insight.id, {"name": "确认预算窗口", "description": "需要在下次拜访确认"})
        self.assertEqual(updated.name, "确认预算窗口")
        self.repository.delete(insight.id)
        self.assertIsNone(self.repository.get(insight.id))

    def test_invalid_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "type must be one of"):
            self.repository.create({"customerId": 7, "name": "测试", "type": "Unknown", "description": "说明", "source": "测试"})

    def test_customer_relationship_is_required(self):
        with self.assertRaisesRegex(ValueError, "customerId must be an integer"):
            self.repository.create({"name": "测试", "type": "Risk", "description": "说明", "source": "测试"})


if __name__ == "__main__":
    unittest.main()
