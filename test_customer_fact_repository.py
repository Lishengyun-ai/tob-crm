import tempfile
import unittest
from pathlib import Path

import server
from customer_fact_repository import CustomerFactRepository


class CustomerFactRepositoryQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-13T00:00:00+00:00"
        customer = self.db.execute(
            """INSERT INTO customers (name, created_at, updated_at)
               VALUES (?, ?, ?)""",
            ("Repository测试客户", now, now),
        )
        self.customer_id = customer.lastrowid
        self.other_customer_id = self.db.execute(
            """INSERT INTO customers (name, created_at, updated_at)
               VALUES (?, ?, ?)""",
            ("Repository其他客户", now, now),
        ).lastrowid
        self.db.execute("DELETE FROM customer_facts")
        for customer_id, fact_type, status, updated_time in [
            (self.customer_id, "PURCHASE", "ACTIVE", "2026-10-13T03:00:00+00:00"),
            (self.customer_id, "PROJECT", "INACTIVE", "2026-10-13T02:00:00+00:00"),
            (self.other_customer_id, "PURCHASE", "ACTIVE", "2026-10-13T01:00:00+00:00"),
        ]:
            self.db.execute(
                """INSERT INTO customer_facts
                   (customer_id, fact_type, fact_name, fact_content, fact_value,
                    source_type, source_id, status, created_time, updated_time)
                   VALUES (?, ?, ?, '', '', 'manual', '', ?, ?, ?)""",
                (customer_id, fact_type, fact_type, status, now, updated_time),
            )
        self.repository = CustomerFactRepository(self.db)

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_find_by_customer_id(self):
        facts = self.repository.find_by_customer_id(self.customer_id)
        self.assertEqual(len(facts), 2)
        self.assertTrue(all(fact.customerId == self.customer_id for fact in facts))

    def test_find_by_fact_type(self):
        facts = self.repository.find_by_fact_type("PURCHASE")
        self.assertEqual(len(facts), 2)
        self.assertTrue(all(fact.factType == "PURCHASE" for fact in facts))

    def test_find_active_can_filter_by_customer(self):
        self.assertEqual(len(self.repository.find_active()), 2)
        facts = self.repository.find_active(self.customer_id)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].status, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
