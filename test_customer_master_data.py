import tempfile
import unittest
from pathlib import Path

import server


class CustomerMasterDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-19T00:00:00+00:00"
        self.db.execute(
            """INSERT INTO customers
               (name, customer_type, industry, status, customer_serial_no,
                terminal_customer_code, customer_region, created_at, updated_at)
               VALUES (?, '建设单位', ?, 'active', ?, ?, ?, ?, ?)""",
            ("统一客户主数据", "工程涂料", "C261019001", "SAP-001", "华东", now, now),
        )
        self.db.execute(
            """INSERT INTO customers
               (name, customer_type, industry, status, customer_serial_no,
                created_at, updated_at)
               VALUES (?, '建设单位', ?, 'inactive', ?, ?, ?)""",
            ("停用客户", "工程涂料", "C261019002", now, now),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_query_uses_customer_id_and_supports_search_and_pagination(self):
        result = server.list_customers(self.db, query="C261019001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["customerId"], result[0]["id"])
        self.assertEqual(result[0]["terminal_customer_code"], "SAP-001")

        page = server.list_customers(self.db, query="统一客户主数据", status="active", page=1, page_size=1)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], result[0]["id"])
        self.assertFalse(page["hasNext"])

    def test_serial_and_terminal_code_are_independent(self):
        row = self.db.execute(
            "SELECT customer_serial_no, terminal_customer_code FROM customers WHERE name = ?",
            ("统一客户主数据",),
        ).fetchone()
        self.assertEqual(row["customer_serial_no"], "C261019001")
        self.assertEqual(row["terminal_customer_code"], "SAP-001")

    def test_customer_serial_uses_shanghai_business_date_and_daily_sequence(self):
        self.db.execute(
            "INSERT INTO customers (name, customer_type, industry, status, customer_serial_no, created_at, updated_at) VALUES (?, '建设单位', ?, 'active', ?, ?, ?)",
            ("当日已有客户", "工程涂料", "C261018001", "2026-10-17T16:30:00+00:00", "2026-10-17T16:30:00+00:00"),
        )
        self.db.commit()
        self.assertEqual(server.generate_customer_serial(self.db, "2026-10-17T16:30:00+00:00"), "C261018002")
        self.assertEqual(server.generate_customer_serial(self.db, "2026-10-19T16:30:00+00:00"), "C261020001")


if __name__ == "__main__":
    unittest.main()
