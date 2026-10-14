import tempfile
import unittest
from pathlib import Path

import server


class RelationshipScoreModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_db_dir = server.DB_DIR
        self.old_db_path = server.DB_PATH
        server.DB_DIR = Path(self.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()
        self.db = server.connect()

    def add_rules_for_version(self, version_id):
        for index, dimension in enumerate(
            server.list_relationship_score_dimensions(self.db, version_id)
        ):
            server.create_relationship_score_rule(
                self.db,
                dimension["dimension_id"],
                {
                    "rule_id": f"{version_id}-rule-{index}",
                    "dimension_id": dimension["dimension_id"],
                    "rule_type": "RANGE",
                    "condition": {
                        "field": "interaction_count",
                        "operator": ">=",
                        "value": index,
                    },
                    "score": 100,
                },
            )

    def tearDown(self):
        self.db.close()
        server.DB_DIR = self.old_db_dir
        server.DB_PATH = self.old_db_path
        self.temp_dir.cleanup()

    def test_create_list_and_get_model(self):
        model = server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v2",
                "model_name": "关系评分模型 V2",
                "description": "测试中的主模型",
                "status": "TESTING",
                "created_by": "Lisa",
            },
            now="2026-10-12T00:00:00+00:00",
        )
        self.db.commit()

        self.assertEqual(model["model_id"], "relationship-score-v2")
        self.assertEqual(model["status"], "TESTING")
        self.assertEqual(model["created_by"], "Lisa")
        self.assertEqual(
            server.get_relationship_score_model(self.db, "relationship-score-v2"),
            model,
        )
        self.assertEqual(
            server.list_relationship_score_models(self.db, "testing"),
            [model],
        )

    def test_update_model_keeps_business_id_and_updates_time(self):
        server.create_relationship_score_model(
            self.db,
            {
                "modelId": "relationship-score-v1",
                "modelName": "关系评分模型 V1",
                "createdBy": "system",
            },
            now="2026-10-12T00:00:00+00:00",
        )
        updated = server.update_relationship_score_model(
            self.db,
            "relationship-score-v1",
            {
                "modelName": "关系评分模型 V1（测试）",
                "status": "PUBLISHED",
                "description": "已完成主模型配置",
            },
            now="2026-10-12T01:00:00+00:00",
        )

        self.assertEqual(updated["model_id"], "relationship-score-v1")
        self.assertEqual(updated["model_name"], "关系评分模型 V1（测试）")
        self.assertEqual(updated["status"], "PUBLISHED")
        self.assertEqual(updated["updated_time"], "2026-10-12T01:00:00+00:00")
        with self.assertRaises(ValueError):
            server.update_relationship_score_model(
                self.db,
                "relationship-score-v1",
                {"model_id": "another-model"},
            )

    def test_validation_and_duplicate_model_id(self):
        with self.assertRaisesRegex(ValueError, "model_name is required"):
            server.create_relationship_score_model(
                self.db,
                {"model_id": "invalid", "created_by": "Lisa"},
            )
        with self.assertRaisesRegex(ValueError, "status must be one of"):
            server.create_relationship_score_model(
                self.db,
                {
                    "model_id": "invalid",
                    "model_name": "无效状态模型",
                    "created_by": "Lisa",
                    "status": "ARCHIVED",
                },
            )

        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "duplicate",
                "model_name": "重复模型",
                "created_by": "Lisa",
            },
        )
        with self.assertRaisesRegex(ValueError, "model_id already exists"):
            server.create_relationship_score_model(
                self.db,
                {
                    "model_id": "duplicate",
                    "model_name": "重复模型 2",
                    "created_by": "Lisa",
                },
            )

    def test_detail_does_not_include_versions_dimensions_or_rules(self):
        model = server.create_relationship_score_model(
            self.db,
            {
                "model_id": "main-only",
                "model_name": "仅主对象",
                "created_by": "Lisa",
            },
        )
        self.assertEqual(set(model), {
            "model_id",
            "model_name",
            "description",
            "status",
            "created_by",
            "created_time",
            "updated_time",
        })

    def test_create_and_list_versions_under_a_model(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
            },
            now="2026-10-12T00:00:00+00:00",
        )

        self.assertEqual(version["status"], "DRAFT")
        self.assertIsNone(version["published_time"])
        self.assertEqual(
            server.list_relationship_score_model_versions(
                self.db, "relationship-score-v1"
            ),
            [version],
        )

    def test_version_no_is_unique_per_model_and_parent_is_required(self):
        with self.assertRaisesRegex(LookupError, "relationship score model not found"):
            server.create_relationship_score_model_version(
                self.db,
                "missing-model",
                {
                    "version_id": "missing-version",
                    "model_id": "missing-model",
                    "version_no": "1.0.0",
                    "created_by": "Lisa",
                },
            )

        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
            },
        )
        with self.assertRaisesRegex(ValueError, "version_id or version_no already exists"):
            server.create_relationship_score_model_version(
                self.db,
                "relationship-score-v1",
                {
                    "version_id": "relationship-score-v1-002",
                    "model_id": "relationship-score-v1",
                    "version_no": "1.0.0",
                    "created_by": "Lisa",
                },
            )
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v2",
                "model_name": "关系评分模型 V2",
                "created_by": "Lisa",
            },
        )
        other_model_version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v2",
            {
                "version_id": "relationship-score-v2-001",
                "model_id": "relationship-score-v2",
                "version_no": "1.0.0",
                "created_by": "Lisa",
            },
        )
        self.assertEqual(other_model_version["version_no"], "1.0.0")

    def test_published_version_cannot_be_updated_and_new_publish_disables_old(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        first = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        self.add_rules_for_version(first["version_id"])
        first_published = server.publish_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            first["version_id"],
            now="2026-10-12T01:00:00+00:00",
        )
        self.assertEqual(first_published["status"], "PUBLISHED")
        self.assertEqual(
            first_published["published_time"], "2026-10-12T01:00:00+00:00"
        )
        with self.assertRaisesRegex(ValueError, "published versions cannot be modified"):
            server.update_relationship_score_model_version(
                self.db,
                "relationship-score-v1",
                first["version_id"],
                {"version_no": "1.0.1"},
            )

        second = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-002",
                "model_id": "relationship-score-v1",
                "version_no": "2.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        self.add_rules_for_version(second["version_id"])
        second_published = server.publish_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            second["version_id"],
            now="2026-10-12T02:00:00+00:00",
        )

        self.assertEqual(second_published["status"], "PUBLISHED")
        old = server.get_relationship_score_model_version(
            self.db, "relationship-score-v1", first["version_id"]
        )
        self.assertEqual(old["status"], "DISABLED")
        self.assertIsNotNone(old["published_time"])
        self.assertEqual(
            len(
                server.list_relationship_score_model_versions(
                    self.db, "relationship-score-v1", "PUBLISHED"
                )
            ),
            1,
        )

    def test_edit_draft_version_and_publish_status_cannot_be_bypassed(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        self.add_rules_for_version(version["version_id"])
        updated = server.update_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            version["version_id"],
            {"status": "TESTING", "version_no": "1.0.1"},
        )
        self.assertEqual(updated["status"], "TESTING")
        self.assertEqual(updated["version_no"], "1.0.1")

        with self.assertRaisesRegex(ValueError, "published through the publish API"):
            server.update_relationship_score_model_version(
                self.db,
                "relationship-score-v1",
                version["version_id"],
                {"status": "PUBLISHED"},
            )

    def test_new_version_has_five_default_dimensions(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        dimensions = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )

        self.assertEqual(len(dimensions), 5)
        self.assertEqual(
            [item["dimension_code"] for item in dimensions],
            [
                "duration",
                "history",
                "influence",
                "interaction_frequency",
                "recency",
            ],
        )
        self.assertTrue(all(item["enabled"] for item in dimensions))

    def test_dimension_crud_and_enable_disable(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        dimension = server.create_relationship_score_dimension(
            self.db,
            version["version_id"],
            {
                "dimension_id": "relationship-score-v1-custom",
                "version_id": version["version_id"],
                "dimension_code": "custom",
                "dimension_name": "自定义维度",
                "weight": 0.10,
                "enabled": True,
                "description": "自定义测试维度",
            },
        )
        self.assertEqual(dimension["dimension_name"], "自定义维度")

        updated = server.update_relationship_score_dimension(
            self.db,
            version["version_id"],
            dimension["dimension_id"],
            {"enabled": False, "weight": 0.2},
        )
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["weight"], 0.2)
        self.assertEqual(
            server.get_relationship_score_dimension(
                self.db, version["version_id"], dimension["dimension_id"]
            ),
            updated,
        )

        deleted = server.delete_relationship_score_dimension(
            self.db, version["version_id"], dimension["dimension_id"]
        )
        self.assertEqual(deleted["status"], "deleted")
        self.assertIsNone(
            server.get_relationship_score_dimension(
                self.db, version["version_id"], dimension["dimension_id"]
            )
        )

    def test_dimension_must_belong_to_version_and_codes_are_unique(self):
        with self.assertRaisesRegex(LookupError, "version not found"):
            server.list_relationship_score_dimensions(self.db, "missing-version")

        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
            },
        )
        with self.assertRaisesRegex(ValueError, "dimension_id or dimension_code already exists"):
            server.create_relationship_score_dimension(
                self.db,
                version["version_id"],
                {
                    "dimension_id": "another-id",
                    "version_id": version["version_id"],
                    "dimension_code": "interaction_frequency",
                    "dimension_name": "重复编码",
                    "weight": 0.1,
                    "created_by": "Lisa",
                },
            )

    def test_published_version_dimensions_are_immutable(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        self.add_rules_for_version(version["version_id"])
        server.publish_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            version["version_id"],
        )
        default_dimension = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )[0]
        with self.assertRaisesRegex(ValueError, "published versions cannot modify dimensions"):
            server.update_relationship_score_dimension(
                self.db,
                version["version_id"],
                default_dimension["dimension_id"],
                {"enabled": False},
            )
        with self.assertRaisesRegex(ValueError, "published versions cannot modify dimensions"):
            server.delete_relationship_score_dimension(
                self.db,
                version["version_id"],
                default_dimension["dimension_id"],
            )

    def test_rule_types_validate_and_rule_parser_evaluates_examples(self):
        rule_range = {
            "rule_type": "RANGE",
            "condition": {
                "field": "interaction_count",
                "operator": ">=",
                "value": 5,
            },
        }
        self.assertTrue(
            server.evaluate_relationship_score_rule(
                rule_range, {"interaction_count": 5}
            )
        )
        self.assertFalse(
            server.evaluate_relationship_score_rule(
                rule_range, {"interaction_count": 4}
            )
        )

        rule_time = {
            "rule_type": "TIME",
            "condition": {"field": "last_contact_at", "withinDays": 7},
        }
        self.assertTrue(
            server.evaluate_relationship_score_rule(
                rule_time,
                {"last_contact_at": "2026-10-10T00:00:00+00:00"},
                now="2026-10-12T00:00:00+00:00",
            )
        )
        rule_enum = {
            "rule_type": "ENUM",
            "condition": {"field": "role", "operator": "=", "value": "decision_maker"},
        }
        self.assertTrue(
            server.evaluate_relationship_score_rule(
                rule_enum, {"role": "decision_maker"}
            )
        )
        with self.assertRaisesRegex(ValueError, "TIME condition.withinDays"):
            server.evaluate_relationship_score_rule(
                {"rule_type": "TIME", "condition": {"field": "last_contact_at"}},
                {},
            )

    def test_rule_crud_sort_enable_disable_and_version_isolation(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        dimension = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )[0]
        first = server.create_relationship_score_rule(
            self.db,
            dimension["dimension_id"],
            {
                "rule_id": "rule-1",
                "dimension_id": dimension["dimension_id"],
                "rule_type": "RANGE",
                "condition": {
                    "field": "interaction_count",
                    "operator": ">=",
                    "value": 5,
                },
                "score": 80,
                "priority": 1,
            },
        )
        second = server.create_relationship_score_rule(
            self.db,
            dimension["dimension_id"],
            {
                "rule_id": "rule-2",
                "dimension_id": dimension["dimension_id"],
                "rule_type": "TIME",
                "condition": {"field": "last_contact_at", "withinDays": 7},
                "score": 90,
                "priority": 2,
            },
        )
        self.assertEqual(first["score"], 80)
        updated = server.update_relationship_score_rule(
            self.db,
            dimension["dimension_id"],
            first["rule_id"],
            {"enabled": False, "score": 85},
        )
        self.assertFalse(updated["enabled"])
        ordered = server.reorder_relationship_score_rules(
            self.db,
            dimension["dimension_id"],
            [second["rule_id"], first["rule_id"]],
        )
        self.assertEqual([item["rule_id"] for item in ordered], ["rule-2", "rule-1"])
        deleted = server.delete_relationship_score_rule(
            self.db, dimension["dimension_id"], first["rule_id"]
        )
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(
            len(server.list_relationship_score_rules(self.db, dimension["dimension_id"])),
            1,
        )

        other_version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-002",
                "model_id": "relationship-score-v1",
                "version_no": "2.0.0",
                "created_by": "Lisa",
            },
        )
        other_dimension = server.list_relationship_score_dimensions(
            self.db, other_version["version_id"]
        )[0]
        other_rule = server.create_relationship_score_rule(
            self.db,
            other_dimension["dimension_id"],
            {
                "rule_id": "rule-2",
                "dimension_id": other_dimension["dimension_id"],
                "rule_type": "ENUM",
                "condition": {"field": "role", "value": "decision_maker"},
                "score": 100,
            },
        )
        self.assertEqual(other_rule["rule_id"], "rule-2")

    def test_published_version_rules_are_immutable(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "relationship-score-v1",
                "model_name": "关系评分模型 V1",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "relationship-score-v1",
            {
                "version_id": "relationship-score-v1-001",
                "model_id": "relationship-score-v1",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        self.add_rules_for_version(version["version_id"])
        dimension = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )[0]
        server.create_relationship_score_rule(
            self.db,
            dimension["dimension_id"],
            {
                "rule_id": "published-rule",
                "dimension_id": dimension["dimension_id"],
                "rule_type": "ENUM",
                "condition": {"field": "role", "value": "decision_maker"},
                "score": 100,
            },
        )
        server.publish_relationship_score_model_version(
            self.db, "relationship-score-v1", version["version_id"]
        )
        with self.assertRaisesRegex(ValueError, "published versions cannot modify rules"):
            server.update_relationship_score_rule(
                self.db,
                dimension["dimension_id"],
                "published-rule",
                {"enabled": False},
            )
        with self.assertRaisesRegex(ValueError, "published versions cannot modify rules"):
            server.reorder_relationship_score_rules(
                self.db, dimension["dimension_id"], ["published-rule"]
            )

    def test_publish_validation_reports_missing_dimensions_weights_rules_and_status(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "validation-model",
                "model_name": "校验模型",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "validation-model",
            {
                "version_id": "validation-version",
                "model_id": "validation-model",
                "version_no": "1.0.0",
                "created_by": "Lisa",
            },
        )
        dimension = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )[0]
        server.update_relationship_score_dimension(
            self.db,
            version["version_id"],
            dimension["dimension_id"],
            {"weight": 0.3},
        )
        validation = server.validate_relationship_score_model_version(
            self.db, "validation-model", version["version_id"]
        )
        codes = {item["code"] for item in validation["errors"]}
        self.assertFalse(validation["valid"])
        self.assertIn("INVALID_STATUS", codes)
        self.assertIn("INVALID_WEIGHT_SUM", codes)
        self.assertIn("NO_ENABLED_RULE", codes)

        with self.assertRaisesRegex(ValueError, "PUBLISH_VALIDATION_FAILED|INVALID_STATUS"):
            server.publish_relationship_score_model_version(
                self.db, "validation-model", version["version_id"]
            )

    def test_publish_validation_rejects_conflicting_rules_and_accepts_valid_testing_version(self):
        server.create_relationship_score_model(
            self.db,
            {
                "model_id": "validation-model",
                "model_name": "校验模型",
                "created_by": "Lisa",
            },
        )
        version = server.create_relationship_score_model_version(
            self.db,
            "validation-model",
            {
                "version_id": "validation-version",
                "model_id": "validation-model",
                "version_no": "1.0.0",
                "created_by": "Lisa",
                "status": "TESTING",
            },
        )
        dimensions = server.list_relationship_score_dimensions(
            self.db, version["version_id"]
        )
        for dimension in dimensions:
            server.update_relationship_score_dimension(
                self.db,
                version["version_id"],
                dimension["dimension_id"],
                {"weight": dimension["weight"]},
            )
        first_dimension = dimensions[0]
        for index, dimension in enumerate(dimensions):
            server.create_relationship_score_rule(
                self.db,
                dimension["dimension_id"],
                {
                    "rule_id": f"validation-rule-{index}",
                    "dimension_id": dimension["dimension_id"],
                    "rule_type": "RANGE",
                    "condition": {
                        "field": "interaction_count",
                        "operator": ">=",
                        "value": 5,
                    },
                    "score": 50,
                },
            )
        server.create_relationship_score_rule(
            self.db,
            first_dimension["dimension_id"],
            {
                "rule_id": "validation-conflict",
                "dimension_id": first_dimension["dimension_id"],
                "rule_type": "RANGE",
                "condition": {
                    "field": "interaction_count",
                    "operator": ">=",
                    "value": 10,
                },
                "score": 80,
            },
        )
        validation = server.validate_relationship_score_model_version(
            self.db, "validation-model", version["version_id"]
        )
        self.assertFalse(validation["valid"])
        self.assertIn(
            "CONFLICTING_RULES",
            {item["code"] for item in validation["errors"]},
        )

        server.delete_relationship_score_rule(
            self.db, first_dimension["dimension_id"], "validation-conflict"
        )
        valid = server.validate_relationship_score_model_version(
            self.db, "validation-model", version["version_id"]
        )
        self.assertTrue(valid["valid"])
        published = server.publish_relationship_score_model_version(
            self.db,
            "validation-model",
            version["version_id"],
            now="2026-10-12T03:00:00+00:00",
        )
        self.assertEqual(published["status"], "PUBLISHED")
        self.assertEqual(
            server.get_relationship_score_config(self.db)["versionId"],
            version["version_id"],
        )


if __name__ == "__main__":
    unittest.main()
