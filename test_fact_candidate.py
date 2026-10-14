import sqlite3
import tempfile
import unittest
from pathlib import Path

import server


class FactCandidateSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_creates_fact_candidate_table_without_changing_business_tables(self):
        table_names = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        self.assertIn("fact_candidates", table_names)
        self.assertIn("customers", table_names)
        columns = [row[1] for row in self.db.execute("PRAGMA table_info(fact_candidates)")]
        self.assertEqual(
            columns,
            [
                "id", "fact_type", "subject_type", "subject_id", "predicate",
                "object_value", "object_type", "source_type", "source_id",
                "confidence", "fact_quality_score", "fact_quality_level", "status", "created_by", "created_time",
                "review_user", "review_time",
            ],
        )

    def test_accepts_all_subject_types_and_review_statuses(self):
        for index, subject_type in enumerate(("Customer", "Person", "Opportunity", "Project"), 1):
            self.db.execute(
                """INSERT INTO fact_candidates
                   (fact_type, subject_type, subject_id, predicate, object_value,
                    object_type, source_type, source_id, confidence, status,
                    created_by, created_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "PROJECT", subject_type, index, "hasFact", "候选值", "text",
                    "document", f"doc-{index}", 80, "PENDING", "agent", "2026-10-13T00:00:00Z",
                ),
            )
        self.db.commit()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fact_candidates").fetchone()[0], 4)

    def test_rejects_invalid_status_subject_source_and_confidence(self):
        base = (
            "PROJECT", "Customer", 1, "hasFact", "候选值", "text",
            "document", "doc-1", 80, "PENDING", "agent", "2026-10-13T00:00:00Z",
        )
        for field, value in (("subject_type", "Account"), ("source_type", "email"), ("status", "DONE")):
            with self.subTest(field=field):
                values = list(base)
                values[{"subject_type": 1, "source_type": 6, "status": 9}[field]] = value
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(
                        """INSERT INTO fact_candidates
                           (fact_type, subject_type, subject_id, predicate, object_value,
                            object_type, source_type, source_id, confidence, status,
                            created_by, created_time)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        values,
                    )
        values = list(base)
        values[8] = 101
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """INSERT INTO fact_candidates
                   (fact_type, subject_type, subject_id, predicate, object_value,
                    object_type, source_type, source_id, confidence, status,
                    created_by, created_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )


if __name__ == "__main__":
    unittest.main()
