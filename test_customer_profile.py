import tempfile
import unittest
from pathlib import Path

import server


class CustomerProfileClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-12T00:00:00+00:00"
        customer = self.db.execute(
            """INSERT INTO customers
               (name, customer_type, industry, status, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            ("闭环测试客户", "建设单位", "工程涂料", now, now),
        )
        self.customer_id = customer.lastrowid
        profile = self.db.execute(
            """INSERT INTO customer_profiles
               (customer_id, profile_type, version_no, scope_type, status, created_at, updated_at)
               VALUES (?, 'baseline', 1, 'customer', 'active', ?, ?)""",
            (self.customer_id, now, now),
        )
        self.profile_id = profile.lastrowid

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_fact_upsert_and_delete_are_traceable(self):
        fact = server.upsert_customer_profile_fact(
            self.db,
            self.profile_id,
            {
                "factCode": "business_model",
                "value": "工程项目型客户",
                "confidence": 90,
                "sourceType": "manual",
                "sourceId": "test-input",
            },
            now="2026-10-12T00:00:00+00:00",
        )
        self.assertEqual(fact["value"], "工程项目型客户")
        self.assertEqual(fact["source_id"], "test-input")

        updated = server.upsert_customer_profile_fact(
            self.db,
            self.profile_id,
            {
                "factCode": "business_model",
                "value": "集团工程客户",
                "confidence": 95,
            },
            now="2026-10-12T01:00:00+00:00",
        )
        self.assertEqual(updated["value"], "集团工程客户")
        self.assertEqual(updated["confidence"], 95)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_facts WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            1,
        )
        result = server.delete_customer_profile_fact(
            self.db,
            self.profile_id,
            updated["id"],
            now="2026-10-12T02:00:00+00:00",
        )
        self.assertEqual(result["status"], "deleted")
        self.assertIsNone(
            self.db.execute(
                "SELECT id FROM customer_profile_facts WHERE id = ?",
                (updated["id"],),
            ).fetchone()
        )

    def test_profile_projection_and_quality_payload(self):
        now = "2026-10-12T00:00:00+00:00"
        self.db.execute(
            "UPDATE customer_profiles SET confidence_score = 40, expires_at = ?, value_score = 88, growth_potential = 71, customer_level = 'A' WHERE id = ?",
            ("2026-10-01T00:00:00+00:00", self.profile_id),
        )
        server.upsert_customer_profile_fact(
            self.db, self.profile_id,
            {"factCode": "construction_area", "value": 120000, "valueType": "number", "confidence": 45}, now,
        )
        profile = server.get_customer_profile(self.db, self.profile_id)
        self.assertEqual(profile["value_score"], 88)
        self.assertEqual(profile["growth_potential"], 71)
        self.assertEqual(profile["customer_level"], "A")
        warning_codes = {item["code"] for item in profile["qualityWarnings"]}
        self.assertIn("LOW_CONFIDENCE", warning_codes)
        self.assertIn("EXPIRED", warning_codes)
        self.assertIn("predictions", profile)

    def test_refresh_runs_extraction_scoring_and_summary(self):
        server.upsert_customer_profile_fact(
            self.db,
            self.profile_id,
            {
                "factCode": "business_model",
                "value": "工程项目型客户",
                "confidence": 90,
            },
        )
        result = server.refresh_customer_profile(
            self.db,
            self.profile_id,
            source_types=["project"],
            now="2026-10-12T03:00:00+00:00",
        )

        self.assertFalse(result["dryRun"])
        self.assertEqual(result["profileId"], self.profile_id)
        self.assertEqual(result["extraction"]["status"], "completed")
        self.assertTrue(result["scores"])
        self.assertIsNotNone(result["summary"])
        self.assertEqual(result["profile"]["id"], self.profile_id)
        self.assertTrue(result["profile"]["summaries"])
        self.assertTrue(
            any(item["status"] == "published" for item in result["profile"]["summaries"])
        )

    def test_refresh_dry_run_does_not_create_scores_or_summary(self):
        result = server.refresh_customer_profile(
            self.db,
            self.profile_id,
            source_types=["project"],
            dry_run=True,
            now="2026-10-12T04:00:00+00:00",
        )

        self.assertTrue(result["dryRun"])
        self.assertEqual(result["scores"], [])
        self.assertIsNone(result["summary"])
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_scores WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_summaries WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            0,
        )

    def test_refresh_stales_previous_summary_before_creating_new_one(self):
        first = server.refresh_customer_profile(
            self.db,
            self.profile_id,
            source_types=["project"],
            now="2026-10-12T05:00:00+00:00",
        )
        second = server.refresh_customer_profile(
            self.db,
            self.profile_id,
            source_types=["project"],
            now="2026-10-12T06:00:00+00:00",
        )
        self.assertIsNotNone(first["summary"])
        self.assertIsNotNone(second["summary"])
        statuses = [
            row["status"]
            for row in self.db.execute(
                "SELECT status FROM customer_profile_summaries WHERE profile_id = ? ORDER BY id",
                (self.profile_id,),
            ).fetchall()
        ]
        self.assertEqual(statuses, ["stale", "published"])

    def _create_review_candidate(self):
        now = "2026-10-12T07:00:00+00:00"
        run = self.db.execute(
            """INSERT INTO customer_fact_extraction_runs
               (customer_id, profile_id, trigger_type, source_types_json,
                rule_version, status, dry_run, started_at, created_at)
               VALUES (?, ?, 'manual', '["project"]', 'customer-fact-extraction-v1',
                       'completed', 0, ?, ?)""",
            (self.customer_id, self.profile_id, now, now),
        )
        candidate = self.db.execute(
            """INSERT INTO customer_fact_extraction_candidates
               (run_id, customer_id, profile_id, fact_code, fact_name, category,
                value_type, value_json, confidence, rule_code, source_object_type,
                source_object_id, source_text, observed_at, status, created_at)
               VALUES (?, ?, ?, 'business_model', '业务模式', 'business_model',
                       'text', ?, 65, 'test.rule', 'project', 'project-1',
                       '客户存在工程项目', ?, 'needs_review', ?)""",
            (
                run.lastrowid,
                self.customer_id,
                self.profile_id,
                '"工程项目型客户"',
                now,
                now,
            ),
        )
        self.db.commit()
        return run.lastrowid, candidate.lastrowid

    def test_candidate_review_accept_writes_fact_and_updates_run(self):
        run_id, candidate_id = self._create_review_candidate()
        result = server.review_customer_fact_extraction_candidate(
            self.db,
            candidate_id,
            "accept",
            {"value": "集团工程客户", "factName": "业务模式"},
            now="2026-10-12T08:00:00+00:00",
        )

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["review_count"], 0)
        fact = self.db.execute(
            """SELECT * FROM customer_profile_facts
               WHERE profile_id = ? AND fact_code = 'business_model'""",
            (self.profile_id,),
        ).fetchone()
        self.assertEqual(server._json_value(fact["value_json"], None), "集团工程客户")
        candidate = self.db.execute(
            "SELECT status, applied_fact_id, reviewed_at FROM customer_fact_extraction_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        self.assertEqual(candidate["status"], "accepted")
        self.assertEqual(candidate["applied_fact_id"], fact["id"])
        self.assertEqual(candidate["reviewed_at"], "2026-10-12T08:00:00+00:00")
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_summaries WHERE profile_id = ? AND status = 'stale'",
                (self.profile_id,),
            ).fetchone()[0],
            0,
        )

    def test_candidate_review_reject_only_changes_candidate_status(self):
        run_id, candidate_id = self._create_review_candidate()
        result = server.review_customer_fact_extraction_candidate(
            self.db,
            candidate_id,
            "reject",
            now="2026-10-12T09:00:00+00:00",
        )
        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["review_count"], 0)
        candidate = self.db.execute(
            "SELECT status, applied_fact_id FROM customer_fact_extraction_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        self.assertEqual(candidate["status"], "rejected")
        self.assertIsNone(candidate["applied_fact_id"])
        self.assertIsNone(
            self.db.execute(
                "SELECT id FROM customer_profile_facts WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()
        )

    def test_candidate_review_rejects_invalid_or_non_reviewable_candidates(self):
        run_id, candidate_id = self._create_review_candidate()
        with self.assertRaisesRegex(ValueError, "decision must be accept or reject"):
            server.review_customer_fact_extraction_candidate(
                self.db, candidate_id, "pending"
            )
        self.db.execute(
            "UPDATE customer_fact_extraction_candidates SET status = 'supporting' WHERE id = ?",
            (candidate_id,),
        )
        with self.assertRaisesRegex(ValueError, "supporting candidates cannot be reviewed"):
            server.review_customer_fact_extraction_candidate(
                self.db, candidate_id, "accept"
            )


if __name__ == "__main__":
    unittest.main()
