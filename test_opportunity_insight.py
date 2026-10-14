import sqlite3
import unittest

from opportunity_insight_repository import OpportunityInsightRepository


class OpportunityInsightRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE opportunities (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE insights (
                id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, name TEXT NOT NULL,
                type TEXT NOT NULL, description TEXT NOT NULL, source TEXT NOT NULL,
                created_time TEXT NOT NULL
            );
            CREATE TABLE opportunity_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER NOT NULL,
                insight_id INTEGER NOT NULL,
                created_time TEXT NOT NULL,
                UNIQUE(opportunity_id, insight_id)
            );
            INSERT INTO opportunities VALUES (10, '测试商机');
            INSERT INTO insights VALUES
                (1, 7, '机会', 'Opportunity', '扩展机会', 'Agent', '2026-10-14T00:00:00+00:00'),
                (2, 7, '风险', 'Risk', '预算风险', 'Agent', '2026-10-14T00:00:01+00:00'),
                (3, 7, '突破点', 'Breakthrough', '关键人突破', 'Agent', '2026-10-14T00:00:02+00:00'),
                (4, 7, '竞争', 'Competition', '竞品价格优势', 'Agent', '2026-10-14T00:00:03+00:00');"""
        )
        self.repository = OpportunityInsightRepository(self.db)

    def tearDown(self):
        self.db.close()

    def test_grouped_insights(self):
        for insight_id in range(1, 5):
            self.repository.create(10, insight_id, "2026-10-14T00:01:00+00:00")
        result = self.repository.grouped_insights_for_opportunity(10)
        self.assertEqual(set(result), {"opportunities", "risks", "breakthrough", "competition"})
        self.assertEqual(len(result["opportunities"]), 1)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["breakthrough"]), 1)
        self.assertEqual(len(result["competition"]), 1)

    def test_duplicate_relation_is_rejected(self):
        self.repository.create(10, 1)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.repository.create(10, 1)

    def test_missing_opportunity_is_rejected(self):
        with self.assertRaisesRegex(LookupError, "opportunity not found"):
            self.repository.grouped_insights_for_opportunity(999)


if __name__ == "__main__":
    unittest.main()
