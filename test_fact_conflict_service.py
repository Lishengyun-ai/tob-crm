import tempfile
import unittest
from pathlib import Path

import server
from fact_conflict_service import detect_conflicts_for_fact, list_fact_conflicts
from fact_extraction_service import FactExtractionService
from fact_review_service import review_fact_candidate


class FactConflictServiceTests(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def add_candidate(self, value, status="PENDING"):
        cursor = self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES ('PersonRole', 'Person', ?, '负责', ?, 'text', 'chat', ?, 80, ?, 'agent', ?)""",
            (self.person_id, value, f"chat-{value}", status, "2026-10-13T00:00:00+00:00"),
        )
        self.db.commit()
        return cursor.lastrowid

    def test_same_subject_predicate_and_different_object_creates_conflict(self):
        first = self.add_candidate("外墙材料选型")
        second = self.add_candidate("内墙材料选型")
        conflicts = detect_conflicts_for_fact(self.db, second)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["fact_id_1"], min(first, second))
        self.assertEqual(conflicts[0]["resolution_status"], "OPEN")

    def test_extraction_queue_detects_conflict_automatically(self):
        person_id = self.person_id
        class FakeLlm:
            def extract_facts(self, prompt):
                return [
                    {"fact_type": "PersonRole", "subject": "王强", "subject_id": person_id,
                     "predicate": "负责", "object": "外墙材料选型", "confidence": 0.8},
                    {"fact_type": "PersonRole", "subject": "王强", "subject_id": person_id,
                     "predicate": "负责", "object": "内墙材料选型", "confidence": 0.7},
                ]

        FactExtractionService(FakeLlm()).queue(
            self.db, {"content": "王强负责材料选型", "source_type": "chat", "source_id": "chat-auto-1"}
        )
        self.assertEqual(len(list_fact_conflicts(self.db, open_only=True)), 1)

    def test_open_conflict_blocks_approval_and_does_not_overwrite_person(self):
        first = self.add_candidate("外墙材料选型")
        second = self.add_candidate("内墙材料选型")
        detect_conflicts_for_fact(self.db, second)
        result = review_fact_candidate(self.db, second, "approve", "reviewer-1")
        self.assertFalse(result["ontologyResult"]["success"])
        self.assertIn("conflict must be resolved", result["ontologyResult"]["error"])
        self.assertEqual(self.db.execute("SELECT role FROM persons WHERE id = ?", (self.person_id,)).fetchone()[0], None)
        self.assertEqual(self.db.execute("SELECT status FROM fact_candidates WHERE id = ?", (second,)).fetchone()[0], "PENDING")

    def test_rejecting_candidate_resolves_its_conflict(self):
        first = self.add_candidate("外墙材料选型")
        second = self.add_candidate("内墙材料选型")
        detect_conflicts_for_fact(self.db, second)
        review_fact_candidate(self.db, second, "reject", "reviewer-2")
        conflicts = list_fact_conflicts(self.db, first)
        self.assertEqual(conflicts[0]["resolution_status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
