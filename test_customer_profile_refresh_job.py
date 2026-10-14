import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class CustomerProfileRefreshJobTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-14T00:00:00+00:00"
        customer = self.db.execute(
            """INSERT INTO customers
               (name, customer_type, industry, status, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            ("刷新任务测试客户", "建设单位", "工程涂料", now, now),
        )
        profile = self.db.execute(
            """INSERT INTO customer_profiles
               (customer_id, profile_type, version_no, scope_type, status,
                completeness_score, created_at, updated_at)
               VALUES (?, 'baseline', 1, 'customer', 'active', ?, ?, ?)""",
            (customer.lastrowid, 42, now, now),
        )
        self.profile_id = profile.lastrowid
        self.db.commit()

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_create_job_returns_job_id_and_persists_request(self):
        job = server.create_customer_profile_refresh_job(
            self.db,
            self.profile_id,
            ["CRM", "PROJECT"],
            "preview",
            now="2026-10-14T01:00:00+00:00",
        )

        self.assertIsInstance(job["jobId"], int)
        self.assertEqual(job["status"], "queued")
        row = self.db.execute(
            "SELECT * FROM customer_profile_refresh_jobs WHERE id = ?",
            (job["jobId"],),
        ).fetchone()
        self.assertEqual(row["customer_profile_id"], self.profile_id)
        self.assertEqual(row["sources"], '["CRM", "PROJECT"]')
        self.assertEqual(row["mode"], "preview")
        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["start_time"])
        self.assertIsNone(row["end_time"])

    def test_job_completes_without_running_in_request_transaction(self):
        job = server.create_customer_profile_refresh_job(
            self.db, self.profile_id, ["ALL"], "formal"
        )

        with patch.object(server, "refresh_customer_profile", return_value={"profileId": self.profile_id}):
            server.run_customer_profile_refresh_job(job["jobId"])

        row = self.db.execute(
            "SELECT status, start_time, end_time, error_message FROM customer_profile_refresh_jobs WHERE id = ?",
            (job["jobId"],),
        ).fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertIsNotNone(row["start_time"])
        self.assertIsNotNone(row["end_time"])
        self.assertEqual(row["error_message"], "")

    def test_job_status_returns_polling_fields(self):
        job = server.create_customer_profile_refresh_job(
            self.db, self.profile_id, ["PROJECT"], "formal"
        )

        queued = server.get_customer_profile_refresh_job_status(self.db, job["jobId"])
        self.assertEqual(queued, {
            "status": "queued",
            "progress": 0,
            "message": "等待刷新任务执行",
            "error_message": "",
        })

        self.db.execute(
            "UPDATE customer_profile_refresh_jobs SET status = 'running', error_message = '' WHERE id = ?",
            (job["jobId"],),
        )
        self.db.commit()
        running = server.get_customer_profile_refresh_job_status(self.db, job["jobId"])
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["progress"], 50)
        self.assertEqual(running["error_message"], "")

        self.db.execute(
            "UPDATE customer_profile_refresh_jobs SET status = 'failed', error_message = '刷新失败' WHERE id = ?",
            (job["jobId"],),
        )
        self.db.commit()
        failed = server.get_customer_profile_refresh_job_status(self.db, job["jobId"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["progress"], 100)
        self.assertEqual(failed["error_message"], "刷新失败")

    def test_failed_job_rolls_back_profile_changes(self):
        job = server.create_customer_profile_refresh_job(
            self.db, self.profile_id, ["MANUAL_FACT"], "formal"
        )

        def fail_after_mutation(db, profile_id, **kwargs):
            db.execute(
                "UPDATE customer_profiles SET completeness_score = 99 WHERE id = ?",
                (profile_id,),
            )
            raise RuntimeError("simulated refresh failure")

        with patch.object(server, "refresh_customer_profile", side_effect=fail_after_mutation):
            server.run_customer_profile_refresh_job(job["jobId"])

        profile = self.db.execute(
            "SELECT completeness_score FROM customer_profiles WHERE id = ?",
            (self.profile_id,),
        ).fetchone()
        job_row = self.db.execute(
            "SELECT status, end_time, error_message FROM customer_profile_refresh_jobs WHERE id = ?",
            (job["jobId"],),
        ).fetchone()
        self.assertEqual(profile["completeness_score"], 42)
        self.assertEqual(job_row["status"], "failed")
        self.assertIsNotNone(job_row["end_time"])
        self.assertIn("simulated refresh failure", job_row["error_message"])

    def test_failed_job_preserves_existing_facts_scores_and_summary(self):
        now = "2026-10-14T03:00:00+00:00"
        fact = server.upsert_customer_profile_fact(
            self.db,
            self.profile_id,
            {"factCode": "business_model", "value": "旧事实", "confidence": 88},
            now=now,
        )
        self.db.execute(
            """INSERT INTO customer_profile_scores
               (profile_id, score_type, score, level, reason, assessed_at, created_at)
               VALUES (?, 'customer_value', 72, 'B', '旧评分', ?, ?)""",
            (self.profile_id, now, now),
        )
        self.db.execute(
            """INSERT INTO customer_profile_summaries
               (profile_id, summary_type, title, content, status, created_at, updated_at)
               VALUES (?, 'executive_summary', '旧摘要', '旧摘要内容', 'published', ?, ?)""",
            (self.profile_id, now, now),
        )
        self.db.commit()
        job = server.create_customer_profile_refresh_job(
            self.db, self.profile_id, ["ALL"], "formal"
        )

        def fail_after_mutating_derived_data(db, profile_id, **kwargs):
            db.execute(
                "UPDATE customer_profile_facts SET value_json = ? WHERE id = ?",
                ('"新事实"', fact["id"]),
            )
            db.execute(
                "UPDATE customer_profile_scores SET score = 99 WHERE profile_id = ?",
                (profile_id,),
            )
            db.execute(
                "UPDATE customer_profile_summaries SET content = '新摘要内容' WHERE profile_id = ?",
                (profile_id,),
            )
            raise RuntimeError("derived data failure")

        with patch.object(server, "refresh_customer_profile", side_effect=fail_after_mutating_derived_data):
            server.run_customer_profile_refresh_job(job["jobId"])

        fact_row = self.db.execute(
            "SELECT value_json FROM customer_profile_facts WHERE id = ?",
            (fact["id"],),
        ).fetchone()
        score_row = self.db.execute(
            "SELECT score FROM customer_profile_scores WHERE profile_id = ?",
            (self.profile_id,),
        ).fetchone()
        summary_row = self.db.execute(
            "SELECT content FROM customer_profile_summaries WHERE profile_id = ?",
            (self.profile_id,),
        ).fetchone()
        job_row = self.db.execute(
            "SELECT status, error_message FROM customer_profile_refresh_jobs WHERE id = ?",
            (job["jobId"],),
        ).fetchone()
        self.assertEqual(fact_row["value_json"], '"旧事实"')
        self.assertEqual(score_row["score"], 72)
        self.assertEqual(summary_row["content"], "旧摘要内容")
        self.assertEqual(job_row["status"], "failed")
        self.assertIn("derived data failure", job_row["error_message"])

    def test_preview_returns_diff_and_keeps_profile_tables_unchanged(self):
        before_facts = self.db.execute(
            "SELECT COUNT(*) FROM customer_profile_facts WHERE profile_id = ?",
            (self.profile_id,),
        ).fetchone()[0]
        before_scores = self.db.execute(
            "SELECT COUNT(*) FROM customer_profile_scores WHERE profile_id = ?",
            (self.profile_id,),
        ).fetchone()[0]
        before_summaries = self.db.execute(
            "SELECT COUNT(*) FROM customer_profile_summaries WHERE profile_id = ?",
            (self.profile_id,),
        ).fetchone()[0]

        result = server.refresh_customer_profile(
            self.db,
            self.profile_id,
            source_types=["project"],
            dry_run=True,
            now="2026-10-14T02:00:00+00:00",
        )

        self.assertTrue(result["dryRun"])
        self.assertEqual(result["mode"], "preview")
        self.assertIn("newFacts", result)
        self.assertIn("deletedFacts", result)
        self.assertIn("scoreChanges", result)
        self.assertIn("summaryChange", result)
        self.assertIn("pendingCandidateCount", result)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_facts WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            before_facts,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_scores WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            before_scores,
        )
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM customer_profile_summaries WHERE profile_id = ?",
                (self.profile_id,),
            ).fetchone()[0],
            before_summaries,
        )


if __name__ == "__main__":
    unittest.main()
