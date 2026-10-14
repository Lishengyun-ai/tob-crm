import tempfile
import unittest
from pathlib import Path

import server
from fact_review_service import get_fact_candidate, list_pending_fact_candidates, review_fact_candidate


class FactReviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-13T00:00:00+00:00"
        person = self.db.execute(
            """INSERT INTO persons (name, organization, title, person_type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("王强", "设计院", "工程师", "关键人", now, now),
        )
        self.person_id = person.lastrowid
        candidate = self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
            ("PersonRole", "Person", self.person_id, "负责", "外墙材料选型", "text", "chat", "chat-1", 86, "agent", now),
        )
        self.candidate_id = candidate.lastrowid

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_pending_and_detail_include_review_log(self):
        self.assertEqual(len(list_pending_fact_candidates(self.db)), 1)
        self.assertEqual(get_fact_candidate(self.db, self.candidate_id)["reviewLogs"], [])

    def test_approve_writes_ontology_and_audit_log(self):
        result = review_fact_candidate(self.db, self.candidate_id, "approve", "reviewer-1", now="2026-10-13T01:00:00+00:00")
        self.assertEqual(result["status"], "APPROVED")
        self.assertEqual(result["ontologyResult"]["syncedField"], "persons.role")
        self.assertEqual(self.db.execute("SELECT role FROM persons WHERE id = ?", (self.person_id,)).fetchone()[0], "外墙材料选型")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fact_candidate_review_logs").fetchone()[0], 1)
        self.assertEqual(list_pending_fact_candidates(self.db), [])

    def test_reject_only_changes_candidate_and_keeps_business_object(self):
        result = review_fact_candidate(self.db, self.candidate_id, "reject", "reviewer-2")
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(self.db.execute("SELECT role FROM persons WHERE id = ?", (self.person_id,)).fetchone()[0], None)
        self.assertEqual(result["reviewLogs"][0]["action"], "REJECT")

    def test_modify_requires_change_and_writes_modified_value(self):
        result = review_fact_candidate(
            self.db, self.candidate_id, "modify", "reviewer-3", {"object_value": "设计院外墙材料选型负责人"}
        )
        self.assertEqual(result["status"], "MODIFIED")
        self.assertEqual(result["object_value"], "设计院外墙材料选型负责人")
        self.assertEqual(result["reviewLogs"][0]["action"], "MODIFY")


if __name__ == "__main__":
    unittest.main()
