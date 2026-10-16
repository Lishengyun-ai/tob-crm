import tempfile
import unittest
from pathlib import Path

import server
from opportunity_intelligence_agent import list_risks, run_opportunity_intelligence


class OpportunityIntelligenceAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        self.opportunity_id = self.db.execute("SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()[0]

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_query_is_structured_and_does_not_write_action_without_confirmation(self):
        result = run_opportunity_intelligence(self.db, {
            "message": "哪些商机最可能赢？",
            "scope": {"opportunityIds": [self.opportunity_id]},
            "maxResults": 1,
        }, now="2026-10-16T00:00:00+00:00", action_creator=lambda **kwargs: server.create_action_record(self.db, **kwargs))
        self.assertEqual(result["intent"], "RANK_WIN_PROBABILITY")
        self.assertEqual(result["scope"]["opportunityCount"], 1)
        self.assertTrue(result["results"][0]["forecastId"])
        self.assertIn("winProbability", result["results"][0])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM actions WHERE source_agent_id = 'opportunity-intelligence'").fetchone()[0], 0)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM agent_runs WHERE agent_id = 'opportunity-intelligence'").fetchone()[0], 0)

    def test_confirmed_approved_recommendation_creates_action_and_risk_is_queryable(self):
        self.db.execute("UPDATE opportunities SET next_action = '' WHERE id = ?", (self.opportunity_id,))
        result = run_opportunity_intelligence(self.db, {
            "message": "下一步应该做什么？",
            "scope": {"opportunityIds": [self.opportunity_id]},
            "maxResults": 1,
            "confirmActions": True,
            "approvalStatus": "APPROVED",
            "actor": "test-user",
        }, now="2026-10-16T00:00:00+00:00", action_creator=lambda **kwargs: server.create_action_record(self.db, **kwargs))
        self.assertEqual(result["intent"], "RECOMMEND_NEXT_ACTION")
        self.assertTrue(result["recommendedActions"])
        self.assertGreaterEqual(self.db.execute("SELECT COUNT(*) FROM actions WHERE source_agent_id = 'opportunity-intelligence'").fetchone()[0], 1)
        risks = list_risks(self.db, self.opportunity_id)
        self.assertTrue(risks)
        self.assertTrue(all("riskId" in risk for risk in risks))


if __name__ == "__main__":
    unittest.main()
