import tempfile
import json
import unittest
from pathlib import Path

import server


class At2SemanticRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.DB_DIR = Path(self.tmp.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        self.customer = self.db.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()["id"]
        self.project = self.db.execute("SELECT id FROM projects WHERE customer_id=? ORDER BY id LIMIT 1", (self.customer,)).fetchone()["id"]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add_person_role(self, role):
        now = "2026-10-18T00:00:00+00:00"
        cur = self.db.execute("INSERT INTO persons(name,created_at,updated_at) VALUES(?,?,?)", (role, now, now))
        pid = cur.lastrowid
        self.db.execute("INSERT INTO customer_persons(customer_id,person_id,role,created_at) VALUES(?,?,?,?)", (self.customer, pid, role, now))

    def test_missing_roles_generates_actions(self):
        result = server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", [])
        self.assertEqual(result["status"], "action_required")
        self.assertEqual(set(result["missingRoles"]), {"design_institute", "budget_approver", "technical_spec_influencer"})
        self.assertEqual(len(result["actions"]), 3)
        self.assertEqual(result["actions"][0]["action_origin"], "semantic_rule")

    def test_missing_technical_role(self):
        self.add_person_role("设计院影响人")
        self.add_person_role("预算审批人")
        result = server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", ["访谈证据"])
        self.assertEqual(result["missingRoles"], ["technical_spec_influencer"])
        raw = result["actions"][0].get("result_json") or result["actions"][0].get("resultJson") or "{}"
        metadata = json.loads(raw) if isinstance(raw, str) else raw
        self.assertEqual(metadata.get("ruleAsset", {}).get("code"), "at2_relationship_coverage")

    def test_complete_relationship(self):
        for role in ("设计院影响人", "预算审批人", "技术规格影响人"):
            self.add_person_role(role)
        result = server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", [])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["actions"], [])

    def test_unpublished_asset_fails(self):
        self.db.execute("UPDATE semantic_resources SET status='draft' WHERE code='at2_relationship_coverage'")
        with self.assertRaises(ValueError):
            server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", [])

    def test_requested_version_and_invalid_reference_fail(self):
        with self.assertRaises(ValueError):
            server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", [], {"rule": "9.9.9"})
        rule_id = self.db.execute("SELECT id FROM semantic_resources WHERE code='at2_relationship_coverage'").fetchone()["id"]
        ref = self.db.execute("SELECT id FROM semantic_asset_references WHERE source_asset_id=? LIMIT 1", (rule_id,)).fetchone()
        self.db.execute("UPDATE semantic_asset_references SET status='inactive' WHERE id=?", (ref["id"],))
        with self.assertRaises(ValueError):
            server.run_at2_semantic_chain(self.db, self.customer, self.project, "tester", [])


if __name__ == "__main__":
    unittest.main()
