import tempfile
import unittest
from pathlib import Path

import server
from ontology_metadata import (
    create_ontology_attribute,
    create_ontology_domain,
    create_ontology_entity,
    create_ontology_relation,
    create_ontology_rule,
    create_ontology_mapping,
    deactivate_ontology_object,
    ontology_application_links,
    ontology_change_history,
    update_ontology_attribute,
    update_ontology_domain,
    update_ontology_rule,
    update_ontology_mapping,
    validate_ontology_relation,
    parse_semantic_terms,
    validate_semantic_term,
)


class OntologyMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir, self.old_db_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_db_dir, self.old_db_path
        self.temp_dir.cleanup()

    def test_catalog_has_separate_layers_and_evidence_links(self):
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        self.assertTrue(
            {
                "ontology_domains",
                "ontology_entities",
                "ontology_attributes",
                "ontology_relation_definitions",
                "ontology_business_rules",
                "ontology_semantic_mappings",
                "ontology_change_logs",
            }.issubset(tables)
        )

        domains = {
            row["code"]: row
            for row in self.db.execute("SELECT * FROM ontology_domains").fetchall()
        }
        self.assertEqual(domains["customer"]["name_zh"], "客户")
        self.assertEqual(domains["partner"]["development_status"], "待核实")

        customer = self.db.execute(
            "SELECT * FROM ontology_entities WHERE code = 'Customer'"
        ).fetchone()
        self.assertEqual(customer["source_table"], "customers")
        self.assertEqual(customer["development_status"], "已确认")

        attribute = self.db.execute(
            """SELECT * FROM ontology_attributes
               WHERE entity_id = ? AND code = 'name'""",
            (customer["id"],),
        ).fetchone()
        self.assertEqual(attribute["source_table"], "customers")
        self.assertEqual(attribute["source_column"], "name")

        relation = self.db.execute(
            "SELECT * FROM ontology_relation_definitions WHERE code = 'customer_owns_project'"
        ).fetchone()
        self.assertEqual(relation["physical_table"], "projects")
        self.assertEqual(relation["source_column"], "customer_id")
        self.assertEqual(relation["target_column"], "id")

    def test_capabilities_are_explicitly_excluded_from_ontology_statistics(self):
        rules = self.db.execute(
            "SELECT code, layer FROM ontology_business_rules"
        ).fetchall()
        self.assertTrue(rules)
        capability_rules = {row["code"] for row in rules if row["layer"] == "associated_capability"}
        self.assertTrue({"opportunity_stage_engine", "customer_profile_scoring", "relationship_score_engine"}.issubset(capability_rules))
        self.assertIn("opportunity_reporting_required", {row["code"] for row in rules})

        mapping = self.db.execute(
            """SELECT * FROM ontology_semantic_mappings
               WHERE code = 'capability_agent_action'"""
        ).fetchone()
        self.assertEqual(mapping["mapping_type"], "excluded_from_ontology")

        coating_mapping = self.db.execute(
            "SELECT * FROM ontology_semantic_mappings WHERE code='term_coating_opportunity'"
        ).fetchone()
        self.assertEqual(coating_mapping["target_code"], "Opportunity")
        self.assertEqual(coating_mapping["status"], "待核实")
        self.assertTrue(self.db.execute(
            "SELECT 1 FROM ontology_semantic_mappings WHERE code='term_single_supplier' AND status='待核实'"
        ).fetchone())

        entity_codes = {
            row["code"]
            for row in self.db.execute("SELECT code FROM ontology_entities").fetchall()
        }
        self.assertNotIn("Agent", entity_codes)
        self.assertNotIn("Action", entity_codes)

    def test_initialization_is_idempotent_and_does_not_add_business_columns(self):
        business_columns_before = {
            table: [
                row["name"]
                for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            for table in ("customers", "projects", "opportunities")
        }
        counts_before = {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "ontology_domains",
                "ontology_entities",
                "ontology_attributes",
                "ontology_relation_definitions",
                "ontology_business_rules",
                "ontology_semantic_mappings",
                "ontology_change_logs",
            )
        }
        self.db.close()
        server.init_db()
        self.db = server.connect()
        counts_after = {
            table: self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in counts_before
        }
        self.assertEqual(counts_before, counts_after)
        business_columns_after = {
            table: [
                row["name"]
                for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            for table in business_columns_before
        }
        self.assertEqual(business_columns_before, business_columns_after)

    def test_catalog_api_payload_contains_only_metadata_collections(self):
        catalog = server.ontology_catalog(self.db)
        self.assertEqual(
            set(catalog),
            {"domains", "entities", "attributes", "relations", "rules", "mappings", "changeLogs"},
        )
        self.assertGreater(len(catalog["entities"]), 0)
        self.assertNotIn("customers", catalog)

    def test_attribute_flags_and_source_validation(self):
        customer = self.db.execute("SELECT id FROM ontology_entities WHERE code='Customer'").fetchone()
        attr = self.db.execute("SELECT * FROM ontology_attributes WHERE entity_id=? AND code='organization_id'", (customer["id"],)).fetchone()
        self.assertEqual(attr["is_relation_field"], 1)
        self.assertEqual(attr["is_unique"], 0)
        with self.assertRaises(ValueError):
            create_ontology_attribute(self.db, {
                "entity_id": customer["id"], "code": "unknown_field", "name_zh": "未知字段",
                "data_type": "text", "description": "测试未知物理字段", "source_type": "physical_column",
                "source_table": "customers", "source_column": "does_not_exist",
            })

    def test_metadata_crud_and_deactivation_preserve_dependencies(self):
        domain = create_ontology_domain(self.db, {
            "code": "test_domain", "name_zh": "测试领域", "category": "测试",
            "version": "0.1", "development_status": "开发中", "maturity": "草案",
        }, actor="tester")
        entity = create_ontology_entity(self.db, {
            "domain_id": domain["id"], "code": "TestEntity", "name_zh": "测试实体",
            "source_type": "business_table", "source_table": "customers", "source_pk": "id",
            "development_status": "开发中", "maturity": "草案",
        }, actor="tester")
        attr = create_ontology_attribute(self.db, {
            "entity_id": entity["id"], "code": "name", "name_zh": "名称",
            "data_type": "text", "description": "测试名称属性", "source_type": "physical_column",
            "source_table": "customers", "source_column": "name", "is_unique": True,
        }, actor="tester")
        updated = update_ontology_attribute(self.db, attr["id"], {"description": "已编辑业务含义"}, actor="tester")
        self.assertEqual(updated["description"], "已编辑业务含义")
        self.assertEqual(updated["is_unique"], 1)
        self.db.commit()
        result = deactivate_ontology_object(self.db, "entity", entity["id"], actor="tester")
        self.assertEqual(result["status"], "inactive")
        self.assertEqual(next(item["count"] for item in result["dependencies"] if item["type"] == "attributes"), 1)
        self.assertEqual(self.db.execute("SELECT status FROM ontology_attributes WHERE id=?", (attr["id"],)).fetchone()[0], "active")

    def test_priority_relations_have_evidence_and_relation_dimensions(self):
        rows = {
            row["code"]: row
            for row in self.db.execute("SELECT * FROM ontology_relation_definitions").fetchall()
        }
        self.assertIn("customer_has_customer_organization", rows)
        self.assertIn("project_has_lot", rows)
        self.assertIn("project_lot_has_opportunity", rows)
        self.assertEqual(rows["person_contacts_customer"]["cardinality"], "多对多")
        self.assertEqual(rows["person_contacts_opportunity"]["development_status"], "已确认")
        self.assertTrue(rows["project_has_lot"]["constraint_description"])

    def test_relation_crud_validates_physical_columns(self):
        customer = self.db.execute("SELECT id FROM ontology_entities WHERE code='Customer'").fetchone()
        project = self.db.execute("SELECT id FROM ontology_entities WHERE code='Project'").fetchone()
        relation = create_ontology_relation(self.db, {
            "code": "test_customer_project_relation", "name_zh": "测试客户项目关系",
            "source_entity_id": customer["id"], "target_entity_id": project["id"],
            "relation_kind": "foreign_key", "cardinality": "一对多",
            "direction": "Customer → Project", "physical_table": "projects",
            "source_column": "customer_id", "target_column": "id",
            "description": "测试关系", "constraint_description": "项目必须归属客户",
            "development_status": "开发中", "maturity": "草案",
        }, actor="tester")
        self.assertEqual(relation["cardinality"], "一对多")
        self.assertEqual(relation["direction"], "Customer → Project")
        with self.assertRaises(ValueError):
            create_ontology_relation(self.db, {
                "code": "test_invalid_relation", "name_zh": "非法关系",
                "source_entity_id": customer["id"], "target_entity_id": project["id"],
                "relation_kind": "foreign_key", "cardinality": "一对多",
                "direction": "Customer → Project", "physical_table": "projects",
                "source_column": "unknown_column", "target_column": "id",
                "description": "非法物理字段关系",
            })

    def test_relation_extended_fields_and_publish_validation(self):
        customer = self.db.execute("SELECT id FROM ontology_entities WHERE code='Customer'").fetchone()
        project = self.db.execute("SELECT id FROM ontology_entities WHERE code='Project'").fetchone()
        relation = create_ontology_relation(self.db, {
            "code": "test_executable_customer_project", "name_zh": "客户项目可执行关系",
            "source_entity_id": customer["id"], "target_entity_id": project["id"],
            "relation_kind": "foreign_key", "cardinality": "1:N", "direction": "正向",
            "physical_table": "projects", "source_column": "customer_id", "target_column": "id",
            "execution_mode": "executable", "query_path": "/api/projects",
            "synonyms": "客户工程,项目归属", "business_types": ["工程项目"],
            "master_slave_type": "master-detail", "traversal_depth": 2,
            "description": "可执行关系", "development_status": "开发中",
        }, actor="tester")
        self.assertEqual(relation["cardinality"], "一对多")
        self.assertEqual(relation["traversal_depth"], 2)
        self.assertEqual(validate_ontology_relation(self.db, relation["id"])["valid"], True)
        invalid = create_ontology_relation(self.db, {
                "code": "test_bad_executable_relation", "name_zh": "非法可执行关系",
                "source_entity_id": customer["id"], "target_entity_id": project["id"],
                "relation_kind": "semantic", "cardinality": "1:N", "direction": "正向",
                "execution_mode": "executable", "query_path": "/api/raw-sql",
                "description": "不受控路径",
            })
        self.assertFalse(validate_ontology_relation(self.db, invalid["id"])["valid"])

    def test_term_disambiguation_scenarios(self):
        lot = parse_semantic_terms(self.db, "二期一标")
        self.assertEqual(lot["candidates"][0]["target_code"], "ProjectLot")
        object_term = parse_semantic_terms(self.db, "工程报备项目", {"business_type": "工程项目"})
        action_term = parse_semantic_terms(self.db, "发起工程报备")
        self.assertEqual(object_term["candidates"][0]["target_code"], "OpportunityReporting")
        self.assertEqual(action_term["candidates"][0]["target_code"], "OpportunityStageEngine")
        gap = parse_semantic_terms(self.db, "设计院还没突破")
        self.assertEqual(gap["candidates"][0]["target_type"], "relation")
        self.assertFalse(gap["safe_to_execute"])

    def test_rule_and_mapping_crud_validation_and_deactivation(self):
        opportunity = self.db.execute("SELECT id, domain_id FROM ontology_entities WHERE code='Opportunity'").fetchone()
        rule = create_ontology_rule(self.db, {
            "code": "test_opportunity_rule", "name_zh": "测试商机规则", "rule_type": "eligibility",
            "subject_domain_id": opportunity["domain_id"], "subject_entity_id": opportunity["id"],
            "expression_json": {"field": "business_type", "in": ["单供料", "双包"]},
            "action_json": {"result": "待核实"}, "description": "测试商机规则",
            "version": "0.1", "development_status": "待核实", "maturity": "草案",
            "data_source": "test",
        }, actor="tester")
        self.assertEqual(rule["subject_domain_id"], opportunity["domain_id"])
        updated_rule = update_ontology_rule(self.db, rule["id"], {"description": "已更新规则", "status": "inactive"}, actor="tester")
        self.assertEqual(updated_rule["description"], "已更新规则")
        self.assertEqual(updated_rule["status"], "inactive")
        with self.assertRaises(ValueError):
            create_ontology_rule(self.db, {
                "code": "test_invalid_rule", "name_zh": "非法规则", "rule_type": "constraint",
                "subject_entity_id": opportunity["id"], "expression_json": "{bad json",
                "description": "非法 JSON",
            })

        mapping = create_ontology_mapping(self.db, {
            "code": "test_coating_opportunity_mapping", "source_type": "business_term",
            "source_key": "涂料商机", "target_type": "entity", "target_code": "Opportunity",
            "mapping_type": "term_to_entity", "confidence": 90, "status": "待核实",
            "evidence": "设计资料与现有 Opportunity 模型待进一步核对", "version": "0.1",
        }, actor="tester")
        self.assertEqual(mapping["target_code"], "Opportunity")
        self.assertEqual(mapping["development_status"], "待核实")
        updated_mapping = update_ontology_mapping(self.db, mapping["id"], {
            "confidence": 95, "version": "0.2", "development_status": "规划中", "maturity": "设计稿",
        }, actor="tester")
        self.assertEqual(updated_mapping["confidence"], 95)
        self.assertEqual(updated_mapping["version"], "0.2")
        self.assertEqual(updated_mapping["maturity"], "设计稿")
        with self.assertRaises(ValueError):
            create_ontology_mapping(self.db, {
                "code": "test_invalid_mapping", "source_type": "business_term", "source_key": "未知",
                "target_type": "entity", "target_code": "NotAnEntity", "evidence": "未知",
            })
        deactivated = deactivate_ontology_object(self.db, "mapping", mapping["id"], actor="tester")
        self.assertEqual(deactivated["status"], "inactive")

    def test_status_maturity_version_and_history_are_separate(self):
        domain = self.db.execute("SELECT * FROM ontology_domains WHERE code='customer'").fetchone()
        updated = update_ontology_domain(self.db, domain["id"], {
            "version": "0.2", "development_status": "开发中", "maturity": "基础版",
        }, actor="version-tester")
        self.assertEqual(updated["version"], "0.2")
        self.assertEqual(updated["development_status"], "开发中")
        self.assertEqual(updated["maturity"], "基础版")
        with self.assertRaises(ValueError):
            update_ontology_domain(self.db, domain["id"], {"development_status": "已上线"}, actor="version-tester")
        with self.assertRaises(ValueError):
            update_ontology_domain(self.db, domain["id"], {"maturity": "生产完成"}, actor="version-tester")
        history = ontology_change_history(self.db, "domain", "customer")
        self.assertTrue(history)
        latest = history[0]
        self.assertEqual(latest["actor"], "version-tester")
        self.assertEqual(latest["version"], "0.2")
        self.assertIn("变更字段", latest["change_summary"])
        self.assertIn('"version": "0.2"', latest["after_json"])

    def test_deactivation_sets_status_and_reports_dependencies(self):
        entity = self.db.execute("SELECT * FROM ontology_entities WHERE code='Customer'").fetchone()
        result = deactivate_ontology_object(self.db, "entity", entity["id"], actor="dependency-tester")
        self.assertEqual(result["development_status"], "已停用")
        self.assertTrue(result["dependency_check"]["has_active_dependencies"])
        self.assertIn("attributes", result["dependency_check"]["message"])
        latest = ontology_change_history(self.db, "entity", "Customer")[0]
        self.assertEqual(latest["action"], "deactivate")
        self.assertEqual(latest["version"], entity["version"] if "version" in entity.keys() else "")

    def test_application_links_reuse_existing_agent_and_stage_configuration(self):
        opportunity = self.db.execute(
            "SELECT id FROM ontology_domains WHERE code = 'opportunity'"
        ).fetchone()
        links = ontology_application_links(self.db, opportunity["id"])
        self.assertFalse(links["editable"])
        self.assertEqual(links["action_config"]["status"], "未配置")
        self.assertTrue(links["workflows"])
        self.assertTrue(all(item["source"] == "stage_definitions" for item in links["workflows"]))
        self.assertTrue(any(item["status"] == "待核实" for item in links["workflows"]))
        self.assertTrue(any(item["association_status"] == "已配置" for item in links["agents"]))
        # 关联能力只读展示，不会进入本体实体统计或新增关联表。
        tables = {
            row[0]
            for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        self.assertNotIn("ontology_agent_links", tables)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM ontology_entities").fetchone()[0],
            len(__import__("ontology_metadata").ontology_catalog(self.db)["entities"]),
        )

    def test_confirmed_agent_seed_configuration_is_idempotent(self):
        expected = {item[0] for item in server.SEED_AGENTS}
        actual = {row["id"] for row in self.db.execute("SELECT id FROM agents").fetchall()}
        self.assertTrue(expected.issubset(actual))
        before = self.db.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        self.db.commit()
        server.init_db()
        after = self.db.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        self.assertEqual(after, before)

    def test_duplicate_domain_code_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "本体编码已存在"):
            create_ontology_domain(self.db, {
                "code": "customer", "name_zh": "重复客户本体", "category": "业务本体",
            }, actor="duplicate-tester")


if __name__ == "__main__":
    unittest.main()
