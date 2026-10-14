import tempfile
import unittest
from pathlib import Path

import server
from fact_quality_score import calculate_fact_quality, quality_level
from fact_review_service import list_pending_fact_candidates


class FactQualityScoreTests(unittest.TestCase):
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

    def add_candidate(self, object_value, confidence=80, source_type="document", status="PENDING"):
        now = "2026-10-13T00:00:00+00:00"
        cursor = self.db.execute(
            """INSERT INTO fact_candidates
               (fact_type, subject_type, subject_id, predicate, object_value, object_type,
                source_type, source_id, confidence, status, created_by, created_time)
               VALUES (?, 'Person', ?, '负责', ?, 'text', ?, ?, ?, ?, 'test', ?)""",
            ("PersonRole", self.person_id, object_value, source_type, object_value, confidence, status, now),
        )
        return cursor.lastrowid

    def test_score_uses_four_weighted_dimensions_and_level(self):
        fact_id = self.add_candidate("外墙材料选型", confidence=80)
        candidate = dict(self.db.execute("SELECT * FROM fact_candidates WHERE id = ?", (fact_id,)).fetchone())
        result = calculate_fact_quality(self.db, candidate)
        self.assertEqual(result["dimensions"], {
            "source_reliability": 90,
            "ai_confidence": 80,
            "historical_consistency": 70,
            "human_confirmation": 0,
        })
        self.assertEqual(result["fact_quality_score"], 65)
        self.assertEqual(result["fact_quality_level"], "C")

    def test_confirmed_history_and_human_review_raise_score(self):
        previous_id = self.add_candidate("设计院负责人", confidence=90, status="APPROVED")
        self.db.execute(
            """INSERT INTO fact_candidate_review_logs
               (fact_candidate_id, action, before_json, after_json, review_user, review_time)
               VALUES (?, 'APPROVE', '{}', '{}', 'reviewer', ?)""",
            (previous_id, "2026-10-12T00:00:00+00:00"),
        )
        current_id = self.add_candidate("设计院负责人", confidence=90)
        candidate = dict(self.db.execute("SELECT * FROM fact_candidates WHERE id = ?", (current_id,)).fetchone())
        result = calculate_fact_quality(self.db, candidate)
        self.assertEqual(result["dimensions"]["historical_consistency"], 100)
        self.assertEqual(result["dimensions"]["human_confirmation"], 25)
        self.assertEqual(result["fact_quality_score"], 79)
        self.assertEqual(result["fact_quality_level"], "B")

    def test_pending_queue_is_sorted_by_quality_score(self):
        low_id = self.add_candidate("低质量", confidence=95, source_type="chat")
        high_id = self.add_candidate("高质量", confidence=95, source_type="document")
        rows = list_pending_fact_candidates(self.db)
        self.assertEqual([row["id"] for row in rows[:2]], [high_id, low_id])
        self.assertGreater(rows[0]["fact_quality_score"], rows[1]["fact_quality_score"])

    def test_grade_boundaries(self):
        self.assertEqual(quality_level(90), "A")
        self.assertEqual(quality_level(89), "B")
        self.assertEqual(quality_level(70), "B")
        self.assertEqual(quality_level(69), "C")


if __name__ == "__main__":
    unittest.main()
