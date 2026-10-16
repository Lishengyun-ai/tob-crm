import tempfile
import unittest
from pathlib import Path

import server


class UnifiedRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()
        now = "2026-10-16T00:00:00+00:00"
        customer = self.db.execute(
            "INSERT INTO customers (name, customer_type, industry, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            ("统一关系客户", "建设单位", "工程", now, now),
        )
        person = self.db.execute(
            "INSERT INTO persons (name, organization, title, person_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("统一关系人", "客户组织", "采购负责人", "关键人", now, now),
        )
        self.customer_id, self.person_id = customer.lastrowid, person.lastrowid

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_roles_and_unified_person_customer_relationship_are_deduplicated(self):
        self.db.execute(
            "INSERT INTO customer_persons (customer_id, person_id, role, is_primary, created_at) VALUES (?, ?, ?, 1, ?)",
            (self.customer_id, self.person_id, "采购负责人", "2026-10-16T00:00:00+00:00"),
        )
        server.seed_relationship_ontology(self.db, "2026-10-16T00:00:00+00:00")
        role = self.db.execute("SELECT * FROM roles WHERE code = 'person_customer_procurement_owner'").fetchone()
        self.assertIsNotNone(role)
        relations = server.get_relationships(self.db, "Person", self.person_id)
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["role"]["code"], "person_customer_procurement_owner")
        self.assertEqual(relations[0]["source"], "legacy")
        relation_id = relations[0]["id"]
        server.upsert_relationship(
            self.db,
            relations[0]["sourceEntity"]["id"],
            relations[0]["targetEntity"]["id"],
            relations[0]["relationshipType"]["id"],
            {"strengthScore": 88, "source": "manual", "lastInteractionAt": "2026-10-15T12:00:00+00:00"},
            "2026-10-16T00:00:00+00:00",
        )
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM relationships WHERE id = ?", (relation_id,)).fetchone()[0], 1)
        row = self.db.execute("SELECT last_interaction_at, source FROM relationships WHERE id = ?", (relation_id,)).fetchone()
        self.assertEqual(row["last_interaction_at"], "2026-10-15T12:00:00+00:00")
        self.assertEqual(row["source"], "manual")

    def test_relationship_score_engine_keeps_unified_fields(self):
        source = server.ensure_relationship_entity(self.db, "Person", str(self.person_id), now="2026-10-16T00:00:00+00:00")
        target = server.ensure_relationship_entity(self.db, "Customer", str(self.customer_id), now="2026-10-16T00:00:00+00:00")
        rel_type = server.relationship_type_row(self.db, code="person_customer_contact")
        relation = server.upsert_relationship(self.db, source["id"], target["id"], rel_type["id"], {"source": "agent", "lastInteractionAt": "2026-10-15T00:00:00+00:00"}, "2026-10-16T00:00:00+00:00")
        detail = server.calculate_relationship_strength_auto(self.db, relation["id"], "2026-10-16T00:00:00+00:00")
        self.assertEqual(detail["source"], "agent")
        self.assertEqual(detail["last_interaction_at"], "2026-10-15T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
