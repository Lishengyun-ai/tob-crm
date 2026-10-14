import sqlite3
import unittest

from insight_score_repository import InsightScoreRepository


class InsightScoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """CREATE TABLE insights (
                id INTEGER PRIMARY KEY, type TEXT, source TEXT, description TEXT
            );
            CREATE TABLE insight_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id INTEGER UNIQUE NOT NULL,
                confidence INTEGER NOT NULL,
                business_value INTEGER NOT NULL,
                urgency INTEGER NOT NULL,
                actionability INTEGER NOT NULL,
                score INTEGER NOT NULL,
                created_time TEXT NOT NULL
            );
            INSERT INTO insights VALUES
                (1, 'Risk', 'Customer Insight Agent', '决策链不完整，预算审批节点尚未确认');"""
        )
        self.repository = InsightScoreRepository(self.db)

    def tearDown(self):
        self.db.close()

    def test_weighted_score_is_between_zero_and_hundred(self):
        score = self.repository.score(1, "2026-10-14T00:00:00+00:00")
        self.assertEqual(score.confidence, 90)
        self.assertEqual(score.businessValue, 85)
        self.assertEqual(score.urgency, 90)
        self.assertEqual(score.actionability, 82)
        self.assertEqual(score.score, 87)
        self.assertTrue(0 <= score.score <= 100)

    def test_rescoring_updates_the_same_record(self):
        first = self.repository.score(1)
        second = self.repository.score(1)
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.repository.list()[0].insightId, 1)


if __name__ == "__main__":
    unittest.main()
