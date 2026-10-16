import tempfile
import unittest
from pathlib import Path

import server
from insight_repository import InsightRepository


class InsightActionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-16T00:00:00+00:00"
        customer = self.db.execute("INSERT INTO customers (name, customer_type, industry, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)", ("洞察闭环客户", "建设单位", "工程", now, now))
        self.customer_id = customer.lastrowid

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_insight_fields_and_action_audit_lifecycle(self):
        repo = InsightRepository(self.db)
        insight = repo.create({
            "customerId": self.customer_id, "name": "决策链缺口", "type": "Risk",
            "description": "采购负责人尚未建立", "source": "opportunity-agent",
            "judgment": "商机推进存在关系阻塞", "evidence": ["relationship:12", "event:7"],
            "risk": "预计延迟报价", "recommendation": "安排采购负责人拜访", "confidence": 82,
            "status": "active", "expiresAt": "2026-11-01T00:00:00+00:00",
        }, now="2026-10-16T00:00:00+00:00")
        self.assertEqual(insight.judgment, "商机推进存在关系阻塞")
        self.assertEqual(insight.evidence, ["relationship:12", "event:7"])
        repo.update(insight.id, {"status": "accepted", "actor": "sales"})
        action = server.create_action_record(
            self.db, title="安排采购负责人拜访", customer_id=self.customer_id,
            source_insight_id=insight.id, source_type="insight", source_id=f"insight:{insight.id}",
            action_origin="ai_recommended", approval_status="approved", now="2026-10-16T01:00:00+00:00",
        )
        self.assertEqual(action["actionOrigin"], "ai_recommended")
        self.db.execute("UPDATE actions SET status = 'accepted', accepted_by = 'sales', accepted_at = ? WHERE id = ?", ("2026-10-16T02:00:00+00:00", action["id"]))
        server.record_insight_action_audit(self.db, "accepted", action_id=action["id"], from_status="pending", to_status="accepted", actor="sales", now="2026-10-16T02:00:00+00:00")
        self.db.execute("UPDATE actions SET status = 'completed', completed_at = ?, execution_result = ? WHERE id = ?", ("2026-10-16T03:00:00+00:00", "已完成拜访并补齐采购联系人", action["id"]))
        server.record_insight_action_audit(self.db, "completed", insight_id=insight.id, action_id=action["id"], from_status="accepted", to_status="completed", actor="sales", now="2026-10-16T03:00:00+00:00")
        events = self.db.execute("SELECT event_type FROM insight_action_audits WHERE insight_id = ? OR action_id = ? ORDER BY id", (insight.id, action["id"])).fetchall()
        self.assertEqual([row["event_type"] for row in events], ["recommended", "accepted", "recommended", "accepted", "completed"])


if __name__ == "__main__":
    unittest.main()
