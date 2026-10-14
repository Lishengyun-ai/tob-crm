import tempfile
import unittest
from pathlib import Path

import server
from fact_approval_ontology_sync import list_sync_logs, retry_ontology_sync
from fact_review_service import review_fact_candidate


class FactApprovalOntologySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        self.now = "2026-10-13T00:00:00+00:00"
        self.customer_id = self.db.execute(
            "SELECT id FROM customers ORDER BY id LIMIT 1"
        ).fetchone()[0]
        person = self.db.execute(
            """INSERT INTO persons (name, organization, title, person_type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("王强", "设计院", "工程师", "关键人", self.now, self.now),
        )
        self.person_id = person.lastrowid
        self.opportunity_id = self.db.execute("SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()[0]
        self.project_id = self.db.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()[0]

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def add_candidate(self, fact_type, subject_type, subject_id, predicate, value):
        cursor = self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES (?, ?, ?, ?, ?, 'text', 'chat', ?, 90, 'PENDING', 'agent', ?)""",
            (fact_type, subject_type, subject_id, predicate, value, f"sync-{fact_type}-{subject_id}", self.now),
        )
        self.db.commit()
        return cursor.lastrowid

    def test_approved_facts_sync_to_all_supported_ontology_objects(self):
        cases = [
            ("CustomerProfile", "Customer", self.customer_id, "customer_level", "重点客户", "customers.customer_level"),
            ("PersonRole", "Person", self.person_id, "role", "决策影响人", "persons.role"),
            ("OpportunityStatus", "Opportunity", self.opportunity_id, "stage", "需求确认", "opportunities.stage"),
            ("ProjectInformation", "Project", self.project_id, "status", "施工中", "projects.status"),
        ]
        for fact_type, subject_type, subject_id, predicate, value, target_field in cases:
            with self.subTest(fact_type=fact_type):
                candidate_id = self.add_candidate(fact_type, subject_type, subject_id, predicate, value)
                result = review_fact_candidate(self.db, candidate_id, "approve", "reviewer", now=self.now)
                self.assertTrue(result["ontologyResult"]["success"])
                self.assertEqual(result["ontologyResult"]["syncedField"], target_field)
                self.assertEqual(list_sync_logs(self.db, candidate_id)[0]["status"], "SUCCESS")

    def test_failed_sync_is_audited_and_can_be_retried(self):
        candidate_id = self.add_candidate("PersonRole", "Person", 999999, "role", "决策影响人")
        self.db.execute("UPDATE fact_candidates SET status = 'APPROVED' WHERE id = ?", (candidate_id,))
        self.db.commit()
        result = retry_ontology_sync(self.db, candidate_id, self.now)
        self.assertFalse(result["success"])
        self.assertEqual(list_sync_logs(self.db, candidate_id)[0]["status"], "FAILED")
        self.assertIn("object not found", result["error"])


if __name__ == "__main__":
    unittest.main()
