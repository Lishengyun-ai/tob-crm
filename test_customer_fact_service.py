import tempfile
import unittest
from pathlib import Path

import server
from customer_fact_repository import CustomerFactRepository
from customer_fact_service import CustomerFactService


class CustomerFactServiceTests(unittest.TestCase):
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
            "INSERT INTO customers (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("Service测试客户", now, now),
        )
        self.customer_id = customer.lastrowid
        self.db.execute("DELETE FROM customer_facts")
        self.service = CustomerFactService(CustomerFactRepository(self.db))

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_fact_lifecycle_delegates_to_repository(self):
        fact = self.service.createFact(
            self.customer_id,
            {
                "factType": "PURCHASE",
                "factName": "采购模式",
                "factValue": "项目采购",
                "sourceType": "CRM",
            },
        )
        self.assertEqual(len(self.service.getCustomerFacts(self.customer_id)), 1)

        verified = self.service.verifyFact(fact.id)
        verification = self.db.execute(
            "SELECT verification_status FROM customer_facts WHERE fact_id = ?",
            (fact.id,),
        ).fetchone()
        self.assertEqual(verification["verification_status"], "VERIFIED")
        self.assertEqual(verified.id, fact.id)

        expired = self.service.expireFact(fact.id)
        self.assertEqual(expired.status, "INACTIVE")
        self.assertEqual(self.service.repository.find_active(self.customer_id), [])


if __name__ == "__main__":
    unittest.main()
