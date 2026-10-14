import sqlite3
import unittest

from customer_insight_agent import CustomerInsightAgent


class CustomerInsightAgentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, created_at TEXT, updated_at TEXT);
            CREATE TABLE opportunities (
                id INTEGER PRIMARY KEY, name TEXT, customer TEXT, customer_id INTEGER,
                stage TEXT, amount INTEGER, risk TEXT, next_action TEXT, updated_at TEXT
            );
            CREATE TABLE business_events (
                id INTEGER PRIMARY KEY, opportunity_id INTEGER, event_type TEXT,
                message TEXT, created_at TEXT
            );
            CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, organization TEXT, title TEXT);
            CREATE TABLE customer_persons (
                customer_id INTEGER, person_id INTEGER, role TEXT, is_primary INTEGER
            );
            CREATE TABLE customer_facts (
                fact_id INTEGER PRIMARY KEY, customer_id INTEGER, fact_type TEXT,
                fact_name TEXT, fact_value TEXT, status TEXT, created_time TEXT
            );
            CREATE TABLE insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, name TEXT,
                type TEXT, description TEXT, source TEXT, created_time TEXT
            );
            CREATE TABLE insight_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT, insight_id INTEGER UNIQUE,
                confidence INTEGER, business_value INTEGER, urgency INTEGER,
                actionability INTEGER, score INTEGER, created_time TEXT
            );
            INSERT INTO customers VALUES (1, '测试客户', 'now', 'now');
            INSERT INTO opportunities VALUES (10, '重点项目', '测试客户', 1, '需求确认', 1000000, '决策链不完整', '识别经济买家', '2026-10-14');
            INSERT INTO business_events VALUES (1, 10, 'meeting', '完成客户访谈', '2026-10-14');
            INSERT INTO persons VALUES (20, '张设计', '测试设计院', '设计负责人');
            INSERT INTO customer_persons VALUES (1, 20, '设计负责人', 1);
            INSERT INTO customer_facts VALUES (30, 1, 'COMPETITOR', '竞品', '竞品A', 'ACTIVE', '2026-10-14');"""
        )

    def tearDown(self):
        self.db.close()

    def test_generates_structured_insights_then_report(self):
        result = CustomerInsightAgent(self.db).run(1, "2026-10-14T00:00:00+00:00")
        self.assertEqual(result["contextSummary"], {
            "opportunityCount": 1,
            "activityCount": 1,
            "personCount": 1,
            "competitionCount": 1,
        })
        self.assertGreaterEqual(len(result["insights"]), 5)
        self.assertEqual(set(result["report"]), {
            "opportunities", "risks", "breakthrough", "competition", "recommendations"
        })
        self.assertEqual(
            {item["id"] for item in result["report"]["opportunities"]},
            {item["id"] for item in result["insights"] if item["type"] == "Opportunity"},
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM insights").fetchone()[0],
            len(result["insights"]),
        )

    def test_missing_customer_is_rejected(self):
        with self.assertRaisesRegex(LookupError, "customer not found"):
            CustomerInsightAgent(self.db).run(999)


if __name__ == "__main__":
    unittest.main()
