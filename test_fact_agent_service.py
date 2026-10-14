import tempfile
import unittest
from pathlib import Path

import server
from fact_agent_service import get_agent_fact_context


class FactAgentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-13T00:00:00+00:00"
        self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES ('CustomerProfile', 'Customer', 1, '等级', '重点客户', 'text',
                       'document', 'doc-1', 90, 'APPROVED', 'test', ?)""",
            (now,),
        )
        self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES ('CustomerProfile', 'Customer', 1, '行业', '地产', 'text',
                       'chat', 'chat-1', 55, 'PENDING', 'test', ?)""",
            (now,),
        )
        self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES ('CustomerProfile', 'Customer', 1, '规模', '大型', 'text',
                       'chat', 'chat-2', 80, 'REJECTED', 'test', ?)""",
            (now,),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_customer_insight_exposes_confirmed_facts_as_business_basis(self):
        result = get_agent_fact_context(self.db, "customer-insight", customer_id=1)
        self.assertEqual(len(result["confirmedFacts"]), 1)
        self.assertEqual(result["confirmedFacts"][0]["display_mark"], "[已确认事实]")
        self.assertTrue(result["confirmedFacts"][0]["is_business_basis"])
        self.assertEqual(result["suggestions"], [])

    def test_visit_assistant_exposes_pending_facts_as_suggestions_only(self):
        result = get_agent_fact_context(self.db, "visit-script", customer_id=1)
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertEqual(result["suggestions"][0]["display_mark"], "[AI推测]")
        self.assertTrue(result["suggestions"][0]["is_suggestion_only"])
        self.assertEqual(result["businessBasis"], [])

    def test_rejected_facts_are_never_exposed(self):
        result = get_agent_fact_context(self.db, "customer-insight", customer_id=1)
        self.assertNotIn("大型", [item["object_value"] for item in result["facts"]])

    def test_unsupported_agent_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not support"):
            get_agent_fact_context(self.db, "competition", customer_id=1)


if __name__ == "__main__":
    unittest.main()
