import json
import tempfile
import unittest
from pathlib import Path

import server
from semantic_management import (
    create_package,
    create_resource,
    create_version,
    ensure_semantic_management_schema,
    list_resources,
    publish_version,
    update_resource,
    validate_resource,
    publish_resource,
    preview_process,
    check_process_completion,
    calculate_metric,
    create_mapping,
    validate_mapping,
    evaluate_rule_ast,
    evaluate_business_rules,
    preview_semantic_import, confirm_semantic_import, build_semantic_index,
    search_semantic_index, get_semantic_call_stats,
)


class SemanticManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.tmp.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()

    def tearDown(self):
        self.db.close()
        server.DB_DIR, server.DB_PATH = self.old_dir, self.old_path
        self.tmp.cleanup()

    def test_domain_seed_and_resource_types_are_initialized(self):
        rows = self.db.execute("SELECT code FROM semantic_domains ORDER BY code").fetchall()
        self.assertEqual([row[0] for row in rows], ["CRM_COMMON", "NIPPON_ENTERPRISE", "TUB_PAINT"])
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"semantic_packages", "semantic_package_versions", "semantic_resources", "semantic_release_records"}.issubset(tables))

    def test_resource_crud_search_reference_validation_and_publish(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        package = create_package(self.db, {"domainId": domain_id, "code": "crm-common-core", "name": "CRM 通用核心"}, "tester")
        resource = create_resource(self.db, {
            "domainId": domain_id, "packageId": package["id"], "resourceType": "rule",
            "code": "opportunity-stage-gate", "nameZh": "商机阶段准入",
            "payload": {"references": [{"type": "entity", "code": "Opportunity"}], "expression": {"op": "eq", "field": "opportunity.stage", "value": "商机跟踪"}, "action": {"type": "return_warning"}},
        }, "tester")
        self.assertTrue(validate_resource(self.db, resource["id"])["valid"])
        self.assertEqual(len(list_resources(self.db, resource_type="rule", search="阶段")), 1)
        version = create_version(self.db, package["id"], {"version": "1.0.0", "resourceIds": [resource["id"]]}, "tester")
        published = publish_version(self.db, version["id"], {"userId": "publisher", "roles": ["admin"], "canWrite": True})
        self.assertEqual(published["status"], "published")
        with self.assertRaises(ValueError):
            update_resource(self.db, resource["id"], {"description": "不可覆盖"}, "tester")

    def test_dsl_rejects_eval_sql_and_unknown_operator(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        for payload in (
            {"expression": {"eval": "1+1"}},
            {"expression": {"type": "sql", "value": "select 1"}},
            {"expression": {"op": "raw_sql", "value": "select 1"}},
        ):
            with self.assertRaises(ValueError):
                create_resource(self.db, {"domainId": domain_id, "resourceType": "rule", "code": "unsafe-rule", "nameZh": "非法规则", "payload": payload}, "tester")
        with self.assertRaises(ValueError):
            evaluate_rule_ast({"op": "eq", "field": "opportunity.owner_password", "value": "x"}, {})

    def test_business_rules_evaluate_without_dynamic_code(self):
        rows = evaluate_business_rules(self.db, {"stage": "OPP_REPORTED", "required": {"projectName": "项目", "customer": "客户", "source": "来源"}}, ["opportunity_reporting_required"])
        self.assertTrue(rows[0]["matched"])
        rows = evaluate_business_rules(self.db, {"stage": "OPP_REPORTED", "required": {"projectName": "项目"}}, ["opportunity_reporting_required"])
        self.assertFalse(rows[0]["matched"])

    def test_entity_mapping_validates_real_ontology_and_never_marks_failed_runtime_usable(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        entity = create_resource(self.db, {"domainId": domain_id, "resourceType": "entity", "code": "customer-semantic", "nameZh": "客户语义实体", "payload": {"references": []}}, "tester")
        mapping = create_mapping(self.db, {"semanticResourceId": entity["id"], "targetType": "ontology_entity", "targetRef": "Customer", "attributeMapping": {"name": "name"}, "permission": {"scope": "current_user"}, "filter": {}}, "tester")
        self.assertEqual(mapping["validation_status"], "passed")
        self.assertFalse(mapping["runtimeUsable"])
        self.db.execute("UPDATE semantic_object_mappings SET target_ref='MissingEntity' WHERE id=?", (mapping["id"],))
        failed = validate_mapping(self.db, mapping["id"])
        self.assertEqual(failed["validation_status"], "failed")
        self.assertFalse(failed["runtimeUsable"])
        self.assertTrue(failed["validation_errors"])

    def test_action_event_config_and_safe_task_deduplication(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        action = create_resource(self.db, {"domainId": domain_id, "resourceType": "action", "code": "create-follow-up-task", "nameZh": "创建跟进任务", "payload": {"service": "/api/actions", "trigger_words": ["安排跟进"], "parameters_schema": {"required": ["title", "opportunity_id"]}, "output_schema": {"type": "object"}, "requires_confirmation": False, "idempotency": "dedupe_key"}}, "tester")
        self.assertTrue(validate_resource(self.db, action["id"])["valid"])
        self.assertEqual(publish_resource(self.db, action["id"], "tester")["status"], "published")
        event = create_resource(self.db, {"domainId": domain_id, "resourceType": "event", "code": "opportunity-created", "nameZh": "商机已创建", "payload": {"source": "business_events", "payload_schema": {"type": "object"}, "mode": "sync", "retry": {"max": 2}}}, "tester")
        self.assertTrue(validate_resource(self.db, event["id"])["valid"])
        with self.assertRaises(ValueError):
            create_resource(self.db, {"domainId": domain_id, "resourceType": "action", "code": "unsafe-action", "nameZh": "非法动作", "payload": {"service": "/api/raw-write"}}, "tester")
        opportunity_id = self.db.execute("SELECT id FROM opportunities LIMIT 1").fetchone()[0]
        first = server.create_action_record(self.db, title="安排跟进", opportunity_id=opportunity_id, dedupe_key="task7-demo", created_by="tester")
        second = server.create_action_record(self.db, title="安排跟进", opportunity_id=opportunity_id, dedupe_key="task7-demo", created_by="tester")
        self.assertEqual(first["id"], second["id"])

    def test_process_sop_validation_preview_and_completion(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='TUB_PAINT'").fetchone()[0]
        steps = [
            {"id": "read-people", "name": "读取商机关联人员", "goal": "获取人员", "description": "读取现有人员关系", "completion": "人员列表已读取", "evidence_refs": ["opportunity.people"], "next": ["classify"]},
            {"id": "classify", "name": "识别决策角色", "goal": "识别角色和态度", "description": "分析影响力和支持态度", "completion": "角色已标记", "evidence_refs": ["person.role"], "next": ["coverage"]},
            {"id": "coverage", "name": "检查关键角色覆盖", "goal": "发现缺口", "description": "检查关键角色是否覆盖", "completion": "覆盖结果已记录", "evidence_refs": ["coverage.result"], "next": []},
        ]
        process = create_resource(self.db, {"domainId": domain_id, "resourceType": "process", "code": "decision-chain-coverage-sop", "nameZh": "决策链覆盖推进 SOP", "payload": {"mode": "recommendation", "steps": steps, "completion": {"required_steps": ["read-people", "classify", "coverage"]}, "references": []}}, "tester")
        self.assertEqual(preview_process(self.db, process["id"])["steps"][0]["id"], "read-people")
        self.assertFalse(check_process_completion(json.loads(self.db.execute("SELECT payload_json FROM semantic_resources WHERE id=?", (process["id"],)).fetchone()[0]), [{"step_id": "read-people", "status": "completed"}])["complete"])
        with self.assertRaises(ValueError):
            create_resource(self.db, {"domainId": domain_id, "resourceType": "process", "code": "bad-sop", "nameZh": "循环 SOP", "payload": {"steps": [{"id": "a", "name": "A", "goal": "", "description": "", "completion": "", "evidence_refs": [], "next": ["a"]}]}}, "tester")

    def test_metric_dimension_target_safe_calculation(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        metric = create_resource(self.db, {"domainId": domain_id, "resourceType": "metric", "code": "weighted_opportunity_amount", "nameZh": "加权商机金额", "payload": {"formula": {"op": "sum", "field": "amount"}, "min_sample": 1, "zero_denominator": "N/A", "unit": "CNY", "source_mapping": "opportunities.amount"}}, "tester")
        result = calculate_metric(self.db, metric["id"])
        self.assertIn(result["display"], ("样本不足", "待映射")) if result["sampleSize"] == 0 else self.assertIsNotNone(result["value"])
        dimension = create_resource(self.db, {"domainId": domain_id, "resourceType": "dimension", "code": "sales_region", "nameZh": "销售大区", "payload": {"source_entity": "Opportunity", "source_attribute": "business_type", "data_type": "enum", "metrics": ["weighted_opportunity_amount"]}}, "tester")
        self.assertTrue(validate_resource(self.db, dimension["id"])["valid"])
        with self.assertRaises(ValueError):
            create_resource(self.db, {"domainId": domain_id, "resourceType": "target", "code": "bad-target", "nameZh": "错误目标", "payload": {"metric_code": "weighted_opportunity_amount", "target_value": 10, "warning_threshold": 20, "critical_threshold": 30, "direction": "higher_better"}}, "tester")

    def test_analysis_attribution_strategy_evidence_boundaries(self):
        domain_id = self.db.execute("SELECT id FROM semantic_domains WHERE code='TUB_PAINT'").fetchone()[0]
        model = create_resource(self.db, {"domainId": domain_id, "resourceType": "analysis_model", "code": "customer-growth-model", "nameZh": "客户增长分析模型", "payload": {"input_features": ["relationship_coverage"], "output_schema": {"type": "object", "properties": {"confidence": {"type": "number"}}}, "method": "agent", "invocation": "agent", "confidence_threshold": 0.75}}, "tester")
        self.assertTrue(validate_resource(self.db, model["id"])["valid"])
        with self.assertRaises(ValueError):
            create_resource(self.db, {"domainId": domain_id, "resourceType": "attribution_model", "code": "bad-attribution", "nameZh": "无证据归因", "payload": {"target_metric": "weighted_opportunity_amount", "factors": [{"name": "预算", "relation_type": "correlation", "weight": 0.8}]}}, "tester")
        strategy = create_resource(self.db, {"domainId": domain_id, "resourceType": "strategy", "code": "design-institute-breakthrough", "nameZh": "设计院关系突破策略", "payload": {"rationale": "已认识工程负责人但设计院关系未突破", "evidence": ["person.role", "relationship_gap"], "recommended_steps": ["识别设计院关键人", "安排拜访"], "risk_boundary": "不得把推测当作已建立关系", "requires_confirmation": True, "references": []}}, "tester")
        self.assertTrue(validate_resource(self.db, strategy["id"])["valid"])

    def test_import_preview_conflict_and_draft_confirm(self):
        domain = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        published = create_resource(self.db, {"domainId": domain, "resourceType": "entity", "code": "import_conflict", "nameZh": "已发布实体"}, "tester")
        self.db.execute("UPDATE semantic_resources SET status='published' WHERE id=?", (published["id"],))
        preview = preview_semantic_import(self.db, json.dumps([{"resourceType": "entity", "code": "import_conflict", "nameZh": "覆盖", "domainCode": "CRM_COMMON"}, {"resourceType": "entity", "code": "import_new", "nameZh": "新实体", "domainCode": "CRM_COMMON"}]), "sample.json")
        self.assertEqual(preview["stats"]["conflicts"], 1)
        self.assertEqual(preview["stats"]["valid"], 1)
        with self.assertRaises(ValueError): confirm_semantic_import(self.db, preview, "tester")

    def test_index_published_only_and_agent_run_stats(self):
        domain = self.db.execute("SELECT id FROM semantic_domains WHERE code='CRM_COMMON'").fetchone()[0]
        draft = create_resource(self.db, {"domainId": domain, "resourceType": "entity", "code": "draft_only", "nameZh": "草稿"}, "tester")
        published = create_resource(self.db, {"domainId": domain, "resourceType": "entity", "code": "published_only", "nameZh": "已发布"}, "tester")
        self.db.execute("UPDATE semantic_resources SET status='published' WHERE id=?", (published["id"],))
        cur = self.db.execute("INSERT INTO semantic_search_indexes(updated_at) VALUES(?)", ("now",))
        result = build_semantic_index(self.db, cur.lastrowid)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([x["code"] for x in search_semantic_index(self.db, cur.lastrowid, "已发布")], ["published_only"])
        agent_id = self.db.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        self.db.execute("INSERT INTO agent_runs(agent_id,input_json,status,created_at) VALUES(?,?,?,?)", (agent_id, json.dumps({"semanticResourceId": published["id"], "semanticVersion": "0.1.0", "latencyMs": 12}), "completed", "2026-01-01T00:00:00Z"))
        stats = get_semantic_call_stats(self.db, agent_id=agent_id)
        self.assertEqual(stats[0]["callCount"], 1)


if __name__ == "__main__":
    unittest.main()
