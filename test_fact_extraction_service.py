import sqlite3
import tempfile
import unittest
from pathlib import Path

import server
from fact_extraction_service import FactExtractionService


class FakeLlm:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    def extract_facts(self, prompt):
        self.prompts.append(prompt)
        return self.result


class FactExtractionServiceTests(unittest.TestCase):
    def test_normalizes_llm_output_to_fact_candidate_shape(self):
        service = FactExtractionService(
            FakeLlm([
                {
                    "fact_type": "PersonRole",
                    "subject": "王强",
                    "subject_id": 7,
                    "predicate": "负责",
                    "object": "外墙材料选型",
                    "confidence": 0.86,
                }
            ]),
            now_provider=lambda: "2026-10-13T00:00:00+00:00",
        )
        candidates = service.extract({"content": "王强负责外墙材料选型", "source_type": "chat", "source_id": "chat-1"})
        self.assertEqual(candidates[0]["subject_type"], "Person")
        self.assertEqual(candidates[0]["confidence"], 86)
        self.assertEqual(candidates[0]["status"], "PENDING")
        self.assertEqual(candidates[0]["object_value"], "外墙材料选型")
        self.assertEqual(set(candidates[0]), {
            "fact_type", "subject_type", "subject_id", "predicate", "object_value",
            "object_type", "source_type", "source_id", "confidence", "status",
            "created_by", "created_time", "review_user", "review_time",
        })

    def test_low_confidence_stays_pending_and_is_detectable(self):
        service = FactExtractionService(
            FakeLlm([{
                "fact_type": "OpportunityStatus", "subject": "华东商机", "subject_id": 3,
                "predicate": "阶段", "object": "需求确认", "confidence": 0.59,
            }])
        )
        candidate = service.extract({"content": "商机仍在需求确认", "source_type": "recording", "source_id": "rec-1"})[0]
        self.assertTrue(service.is_low_confidence(candidate))
        self.assertEqual(candidate["status"], "PENDING")

    def test_queue_only_writes_fact_candidates(self):
        temp_dir = tempfile.TemporaryDirectory()
        old_db_dir, old_db_path = server.DB_DIR, server.DB_PATH
        try:
            server.DB_DIR = Path(temp_dir.name)
            server.DB_PATH = server.DB_DIR / "crm.sqlite3"
            server.init_db()
            db = server.connect()
            project_count_before = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            service = FactExtractionService(FakeLlm([{
                "fact_type": "ProjectInformation", "subject": "华南项目", "subject_id": 9,
                "predicate": "状态", "object": "施工中", "confidence": 0.75,
            }]))
            service.queue(db, {"content": "华南项目施工中", "source_type": "document", "source_id": "doc-1"})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM fact_candidates").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], project_count_before)
        finally:
            if "db" in locals():
                db.close()
            server.DB_DIR, server.DB_PATH = old_db_dir, old_db_path
            temp_dir.cleanup()

    def test_requires_subject_resolution_for_text_only_llm_subject(self):
        service = FactExtractionService(FakeLlm([{
            "fact_type": "CustomerProfile", "subject": "某客户", "predicate": "行业", "object": "地产", "confidence": 0.9,
        }]))
        with self.assertRaisesRegex(ValueError, "cannot resolve subject_id"):
            service.extract({"content": "某客户属于地产行业", "source_type": "chat", "source_id": "chat-2"})


if __name__ == "__main__":
    unittest.main()
