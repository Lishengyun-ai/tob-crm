import sqlite3
import unittest
from governance import ensure_governance_schema, authorize_operation, create_approval_request, decide_approval, run_quality_check

class GovernanceTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE relationship_entities(id INTEGER PRIMARY KEY, entity_type TEXT);
        CREATE TABLE roles(id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE relationships(id INTEGER PRIMARY KEY, source_entity_id INTEGER, target_entity_id INTEGER, role_id INTEGER);
        CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT, customer_id INTEGER);
        CREATE TABLE project_lots(id INTEGER PRIMARY KEY, phase_id INTEGER, lot_name TEXT);
        CREATE TABLE opportunities(id INTEGER PRIMARY KEY, name TEXT, customer TEXT, stage TEXT, amount INTEGER, created_at TEXT);
        CREATE TABLE stage_definitions(code TEXT, name TEXT, required_fields_json TEXT);
        CREATE TABLE fact_conflicts(id INTEGER PRIMARY KEY, fact_id_1 INTEGER, fact_id_2 INTEGER, resolution_status TEXT);
        """); ensure_governance_schema(self.db)

    def test_scope_and_high_risk_policy(self):
        self.assertFalse(authorize_operation(self.db, {"userId":"u", "allowedOpportunityIds":[1]}, "read_only", "Opportunity", 2).allowed)
        d = authorize_operation(self.db, "u", "formal_write", "Opportunity", None, {"amount": 100})
        self.assertTrue(d.allowed); self.assertTrue(d.requiresApproval)

    def test_approval_requires_separation_and_audits(self):
        rid = create_approval_request(self.db, "seller", "opportunity_create", "Opportunity", None, {"amount": 1})
        with self.assertRaises(PermissionError): decide_approval(self.db, {"userId":"seller", "canApprove":True}, rid, True)
        item = decide_approval(self.db, {"userId":"manager", "roles":["approver"], "canApprove":True}, rid, True)
        self.assertEqual(item["status"], "APPROVED")
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM governance_audit_logs").fetchone()[0], 1)

    def test_quality_detects_orphan_duplicate_and_conflict(self):
        self.db.execute("INSERT INTO relationships VALUES (1, 999, 998, 77)")
        self.db.execute("INSERT INTO projects VALUES (1, '项目A', 1)"); self.db.execute("INSERT INTO projects VALUES (2, '项目A', 1)")
        self.db.execute("INSERT INTO fact_conflicts VALUES (1, 1, 2, 'OPEN')")
        result = run_quality_check(self.db, "manager")
        types = {x["issue_type"] for x in result["issues"]}
        self.assertIn("orphan_relationship", types); self.assertIn("duplicate_project", types); self.assertIn("conflicting_fact", types)

if __name__ == "__main__": unittest.main()
