import tempfile
import unittest
from pathlib import Path

import server
from customer_fact import CustomerFactRepository


class CustomerFactRepositoryTests(unittest.TestCase):
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
            """INSERT INTO customers (name, customer_type, industry, status, created_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            ("CustomerFact测试客户", "建设单位", "工程涂料", now, now),
        )
        self.customer_id = customer.lastrowid
        self.repository = CustomerFactRepository(self.db)

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_create_list_update_and_delete_customer_fact(self):
        fact = self.repository.create(
            self.customer_id,
            {
                "factType": "PURCHASE",
                "factName": "采购决策周期",
                "factContent": "年度预算审批后集中采购",
                "factValue": "90",
                "unit": "天",
                "sourceType": "interview",
                "sourceId": "visit-001",
                "confidenceScore": 85,
                "verificationStatus": "VERIFIED",
                "validFrom": "2026-01-01",
                "status": "ACTIVE",
                "createdBy": "测试用户",
            },
            now="2026-10-13T01:00:00+00:00",
        )
        self.assertEqual(fact.customer_id, self.customer_id)
        self.assertEqual(fact.fact_type, "PURCHASE")
        self.assertEqual(fact.confidence_score, 85)

        facts = self.repository.list_for_customer(self.customer_id, fact_type="PURCHASE")
        self.assertEqual([item.fact_id for item in facts], [fact.fact_id])

        updated = self.repository.update(
            fact.fact_id,
            {"factValue": "75", "confidenceScore": 92, "verificationStatus": "VERIFIED"},
            now="2026-10-13T02:00:00+00:00",
        )
        self.assertEqual(updated.fact_value, "75")
        self.assertEqual(updated.confidence_score, 92)
        self.assertEqual(updated.updated_time, "2026-10-13T02:00:00+00:00")

        self.repository.delete(fact.fact_id)
        self.assertIsNone(self.repository.get(fact.fact_id))

    def test_rejects_invalid_fact_type_and_confidence_score(self):
        with self.assertRaisesRegex(ValueError, "factType must be one of"):
            self.repository.create(self.customer_id, {"factType": "UNKNOWN", "factName": "无效事实"})
        with self.assertRaisesRegex(ValueError, "confidenceScore must be between 0 and 100"):
            self.repository.create(
                self.customer_id,
                {"factType": "STRATEGY", "factName": "年度策略", "confidenceScore": 101},
            )

    def test_customer_fact_has_customer_foreign_key(self):
        with self.assertRaisesRegex(LookupError, "customer not found"):
            self.repository.create(999999, {"factType": "CUSTOMER_BASIC", "factName": "客户类型"})


if __name__ == "__main__":
    unittest.main()
