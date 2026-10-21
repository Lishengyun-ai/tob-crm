import pathlib
import sqlite3
import tempfile
import unittest

import server


class CustomerDevelopmentAt123Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.DB_DIR = pathlib.Path(self.tmp.name)
        server.DB_PATH = pathlib.Path(self.tmp.name) / "crm.sqlite3"
        server.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_and_metric_formula_are_backward_compatible(self):
        db = server.connect()
        try:
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            self.assertTrue({
                "customer_development_stage_fields",
                "customer_development_people",
                "customer_development_attachments",
                "customer_development_metrics",
            } <= tables)
            development = db.execute(
                "SELECT id FROM customer_developments ORDER BY id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(development)
            development_id = development[0]
            db.execute(
                """INSERT INTO customer_development_stage_fields
                   (customer_development_id, stage_code, field_code, value_json, created_at, updated_at)
                   VALUES (?, 'AT1', 'customer_purchase_total', '100', 'now', 'now')""",
                (development_id,),
            )
            db.execute(
                """INSERT INTO customer_development_stage_fields
                   (customer_development_id, stage_code, field_code, value_json, created_at, updated_at)
                   VALUES (?, 'AT1', 'target_sales_total', '25', 'now', 'now')""",
                (development_id,),
            )
            metrics = server.calculate_customer_development_metrics(db, development_id, now="now")
            values = {row["metric_code"]: row["value"] for row in metrics}
            self.assertEqual(values["customer_purchase_total"], 100)
            self.assertEqual(values["target_sales_total"], 25)
            self.assertEqual(values["estimated_total_market_share"], 0.25)
            self.assertIsNone(values["total_market_share"])
            db.execute(
                "UPDATE customer_development_stage_fields SET value_json = '0' WHERE customer_development_id = ? AND field_code = 'customer_purchase_total'",
                (development_id,),
            )
            metrics = server.calculate_customer_development_metrics(db, development_id, now="now")
            values = {row["metric_code"]: row["value"] for row in metrics}
            self.assertIsNone(values["estimated_total_market_share"])
        finally:
            db.close()

    def test_at2_save_auto_advances_when_any_mapped_field_has_value(self):
        db = server.connect()
        try:
            development = db.execute(
                "SELECT id FROM customer_developments WHERE current_stage_code = 'AT2' ORDER BY id LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(development)
            development_id = development["id"]
            db.execute(
                """INSERT INTO customer_development_stage_fields
                   (customer_development_id, stage_code, field_code, value_json, created_at, updated_at)
                   VALUES (?, 'AT2', 'substrate', ?, 'now', 'now')""",
                (development_id, server.json.dumps("混凝土", ensure_ascii=False)),
            )
            transition = server.auto_advance_customer_development_after_at2_save(db, development_id)
            self.assertTrue(transition["advanced"])
            self.assertEqual(transition["detail"]["current_stage_code"], "AT3")
            records = db.execute(
                "SELECT stage_code, status FROM customer_development_stage_records WHERE customer_development_id = ? ORDER BY id",
                (development_id,),
            ).fetchall()
            self.assertEqual(records[-2]["stage_code"], "AT2")
            self.assertEqual(records[-2]["status"], "completed")
            self.assertEqual(records[-1]["stage_code"], "AT3")
            self.assertEqual(records[-1]["status"], "in_progress")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
