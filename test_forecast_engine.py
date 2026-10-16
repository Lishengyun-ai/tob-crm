import sqlite3
import unittest

from forecast_engine import add_feedback, ensure_forecast_schema, replay_forecast, run_forecast


class ForecastEngineTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        for statement in (
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)",
            "CREATE TABLE opportunities (id INTEGER PRIMARY KEY, customer_id INTEGER, customer TEXT, amount REAL, stage TEXT, updated_at TEXT)",
            "CREATE TABLE customer_facts (fact_id INTEGER PRIMARY KEY, customer_id INTEGER, fact_type TEXT, fact_value TEXT, fact_content TEXT, status TEXT, valid_from TEXT)",
            "CREATE TABLE customer_persons (id INTEGER PRIMARY KEY, customer_id INTEGER)",
            "CREATE TABLE actions (id INTEGER PRIMARY KEY, opportunity_id INTEGER, customer_id INTEGER, status TEXT, due_at TEXT, created_at TEXT)",
        ):
            self.db.execute(statement)
        self.db.execute("INSERT INTO customers VALUES (1, '客户A')")
        self.db.execute("INSERT INTO opportunities VALUES (1, 1, '客户A', 100000, '需求确认', '2026-10-16')")
        self.db.commit()
        ensure_forecast_schema(self.db, "2026-10-16T00:00:00+00:00")

    def test_run_snapshot_replay_and_feedback(self):
        forecast = run_forecast(self.db, {
            "domain": "OPPORTUNITY", "subjectType": "Opportunity", "subjectId": 1,
            "targetTypes": ["WIN_PROBABILITY", "FORECAST_REVENUE"],
            "asOfTime": "2026-10-16T00:00:00+00:00",
        }, "2026-10-16T00:00:00+00:00")
        self.assertIn(forecast["status"], {"READY", "PARTIAL"})
        self.assertEqual(len(forecast["features"]), 5)
        self.assertEqual(len(forecast["results"]), 2)
        replay = replay_forecast(self.db, forecast["id"], "2026-10-17T00:00:00+00:00")
        self.assertEqual(replay["mode"], "SIMULATION")
        self.assertEqual(replay["parent_forecast_id"], forecast["id"])
        feedback = add_feedback(self.db, forecast["id"], {"targetType": "WIN_PROBABILITY", "actualValue": 1}, "2026-10-17T00:00:00+00:00")
        self.assertEqual(feedback["forecastId"], forecast["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0], 2)

    def test_customer_growth_uses_low_confidence_for_missing_inputs(self):
        forecast = run_forecast(self.db, {
            "domain": "CUSTOMER_GROWTH", "subjectType": "Customer", "subjectId": 1,
            "targetTypes": ["GROWTH_POTENTIAL"], "asOfTime": "2026-10-16T00:00:00+00:00",
        }, "2026-10-16T00:00:00+00:00")
        self.assertLess(forecast["overall_confidence"], 0.8)
        self.assertEqual(forecast["results"][0]["target_type"], "GROWTH_POTENTIAL")


if __name__ == "__main__":
    unittest.main()
