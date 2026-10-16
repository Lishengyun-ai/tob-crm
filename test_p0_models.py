import tempfile
import unittest
from pathlib import Path

import server


class P0ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        self.now = "2026-10-15T00:00:00+00:00"

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_p0_tables_and_legacy_mappings_are_initialized(self):
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        self.assertTrue({"organizations", "project_phases", "project_lots"}.issubset(tables))
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM organizations").fetchone()[0], 0)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM project_phases").fetchone()[0], 0)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM project_lots").fetchone()[0], 0)
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM opportunities WHERE project_section_id IS NOT NULL AND project_lot_id IS NULL"
            ).fetchone()[0],
            0,
        )

    def test_customer_development_opportunity_can_exist_without_project_opportunity(self):
        customer_id = self.db.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()[0]
        cur = self.db.execute(
            """INSERT INTO customer_development_opportunities
               (customer_id, target, opportunity_type, stage, owner, probability,
                status, summary, next_action, relation_type, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                customer_id,
                "集团级集采突破",
                "集采突破",
                "关系建立",
                "李盛云",
                0.65,
                "active",
                "建立集团采购关系",
                "确认区域采购负责人",
                "客户级开发机会",
                "P0 模型测试",
                self.now,
                self.now,
            ),
        )
        row = self.db.execute(
            "SELECT * FROM customer_development_opportunities WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        self.assertIsNone(row["opportunity_id"])
        self.assertEqual(row["customer_id"], customer_id)
        self.assertEqual(row["target"], "集团级集采突破")

    def test_project_lot_is_scoped_to_phase_and_project(self):
        phase = self.db.execute(
            "SELECT id, project_id FROM project_phases ORDER BY id LIMIT 1"
        ).fetchone()
        lot = self.db.execute(
            "SELECT phase_id, legacy_section_id FROM project_lots WHERE phase_id = ?",
            (phase["id"],),
        ).fetchone()
        self.assertIsNotNone(lot)
        section_project = self.db.execute(
            "SELECT project_id FROM project_sections WHERE id = ?",
            (lot["legacy_section_id"],),
        ).fetchone()
        self.assertEqual(section_project["project_id"], phase["project_id"])

    def test_init_is_idempotent(self):
        before = {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("organizations", "project_phases", "project_lots")
        }
        self.db.close()
        server.init_db()
        self.db = server.connect()
        after = {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
