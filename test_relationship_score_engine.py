import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import server


class RelationshipScoreEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_db_dir = server.DB_DIR
        cls.old_db_path = server.DB_PATH
        server.DB_DIR = Path(cls.temp_dir.name)
        server.DB_PATH = server.DB_DIR / "crm.sqlite3"
        server.init_db()

        cls.db = server.connect()
        source = server.ensure_relationship_entity(cls.db, "Person", "test-person", "测试联系人", now="2026-01-01T00:00:00+00:00")
        target = server.ensure_relationship_entity(cls.db, "Opportunity", "test-opportunity", "测试商机", now="2026-01-01T00:00:00+00:00")
        relation_type = server.relationship_type_row(cls.db, code="person_opportunity_decision_maker")
        cls.relationship = server.upsert_relationship(
            cls.db,
            source["id"],
            target["id"],
            relation_type["id"],
            {"firstEstablishedAt": "2025-01-01T00:00:00+00:00"},
            "2026-01-01T00:00:00+00:00",
        )
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        server.DB_DIR = cls.old_db_dir
        server.DB_PATH = cls.old_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.db.execute("DELETE FROM relationship_events WHERE relationship_id = ?", (self.relationship["id"],))
        self.db.execute("DELETE FROM relationship_scores WHERE relationship_id = ?", (self.relationship["id"],))
        self.db.execute(
            """UPDATE relationships SET strength_score = 0, strength_level = '未知关系',
               last_contact_at = NULL, interaction_count = 0,
               first_established_at = '2025-01-01T00:00:00+00:00', last_evaluated_at = NULL
               WHERE id = ?""",
            (self.relationship["id"],),
        )
        self.db.execute(
            """UPDATE relationship_score_configs SET
               interaction_frequency_weight = 0.25, recency_weight = 0.25,
               influence_weight = 0.20, history_weight = 0.15, duration_weight = 0.15
               WHERE code = 'relationship-score-v1'"""
        )
        self.db.commit()

    def test_default_weights_save_all_five_components(self):
        result = server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00"
        )
        latest = result["latestScore"]
        weights = json.loads(latest["weights_json"])
        components = json.loads(latest["components_json"])

        self.assertEqual(set(components), set(server.RELATIONSHIP_SCORE_FACTORS))
        self.assertEqual(latest["duration_score"], 85)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)
        self.assertEqual(latest["calculated_by"], "relationship_score_engine_v1")
        self.assertIn("关系持续时间", latest["reason"])

    def test_event_recalculates_score_without_direct_addition(self):
        before = server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00"
        )["strength_score"]
        result = server.RelationshipService(self.db, "2026-01-01T00:00:00+00:00").record_change(
            self.relationship["id"],
            {
                "eventType": "拜访",
                "eventTime": "2026-01-01T00:00:00+00:00",
                "impactScore": 100,
                "description": "完成关键人拜访",
            },
        )
        event = result["events"][0]

        self.assertGreater(result["strength_score"], before)
        self.assertLess(result["strength_score"], 100)
        self.assertEqual(event["after_score"], result["strength_score"])
        self.assertNotEqual(result["strength_score"], min(100, before + 100))

    def test_custom_weights_are_normalized_and_applied(self):
        self.db.execute(
            """UPDATE relationship_score_configs SET
               interaction_frequency_weight = 0, recency_weight = 0,
               influence_weight = 0, history_weight = 0, duration_weight = 100
               WHERE code = 'relationship-score-v1'"""
        )
        self.db.commit()
        result = server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00"
        )

        self.assertEqual(result["strength_score"], 85)
        self.assertEqual(json.loads(result["latestScore"]["weights_json"]), {"duration": 1.0, "history": 0.0, "influence": 0.0, "interaction_frequency": 0.0, "recency": 0.0})

    def test_backfill_is_idempotent(self):
        server.calculate_relationship_strength_auto(self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00")
        count_before = self.db.execute(
            "SELECT COUNT(*) FROM relationship_scores WHERE relationship_id = ?", (self.relationship["id"],)
        ).fetchone()[0]
        result = server.backfill_relationship_scores(self.db, "2026-01-01T00:00:00+00:00")
        count_after = self.db.execute(
            "SELECT COUNT(*) FROM relationship_scores WHERE relationship_id = ?", (self.relationship["id"],)
        ).fetchone()[0]
        self.assertEqual(count_before, count_after)
        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_batch_recalculation_can_force_new_history(self):
        server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00"
        )
        result = server.recalculate_relationship_scores(
            self.db,
            now="2026-01-02T00:00:00+00:00",
            relationship_ids=[self.relationship["id"]],
            force=True,
        )
        count = self.db.execute(
            "SELECT COUNT(*) FROM relationship_scores WHERE relationship_id = ?",
            (self.relationship["id"],),
        ).fetchone()[0]

        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["calculated"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(count, 2)
        self.assertEqual(result["results"][0]["status"], "calculated")

    def test_batch_recalculation_filters_and_validates_inputs(self):
        result = server.recalculate_relationship_scores(
            self.db,
            now="2026-01-01T00:00:00+00:00",
            relationship_ids=[self.relationship["id"], self.relationship["id"]],
            relationship_type_code="person_opportunity_decision_maker",
            updated_since="2025-12-31T00:00:00+00:00",
            force=False,
        )

        self.assertEqual(result["requested"], 1)
        self.assertEqual(result["calculated"], 1)
        self.assertEqual(
            server.recalculate_relationship_scores(
                self.db,
                relationship_ids=[],
            )["requested"],
            0,
        )
        with self.assertRaises(ValueError):
            server.recalculate_relationship_scores(
                self.db,
                relationship_ids=["invalid"],
            )
        with self.assertRaises(ValueError):
            server.recalculate_relationship_scores(
                self.db,
                updated_since="invalid",
            )

    def test_manual_score_is_preserved_and_auto_recalculation_restores_engine_source(self):
        manual = server.RelationshipService(
            self.db, "2026-01-01T00:00:00+00:00"
        ).calculate_strength(
            self.relationship["id"],
            {
                "mode": "manual",
                "score": 12,
                "durationScore": 20,
                "reason": "人工复核",
            },
        )

        self.assertEqual(manual["strength_score"], 12)
        self.assertEqual(manual["latestScore"]["calculated_by"], "manual")
        self.assertEqual(manual["latestScore"]["duration_score"], 20)

        automatic = server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-02T00:00:00+00:00"
        )
        self.assertEqual(
            automatic["latestScore"]["calculated_by"],
            "relationship_score_engine_v1",
        )
        self.assertEqual(len(automatic["scores"]), 2)
        self.assertEqual(automatic["scores"][1]["calculated_by"], "manual")

    def test_manual_score_cannot_spoof_automatic_source(self):
        with self.assertRaises(ValueError):
            server.save_manual_relationship_score(
                self.db,
                self.relationship["id"],
                {
                    "mode": "manual",
                    "score": 50,
                    "calculatedBy": "relationship_score_engine_v1",
                },
                "2026-01-01T00:00:00+00:00",
            )

    def test_factor_calculators_cover_boundaries_and_missing_values(self):
        now = "2026-01-01T00:00:00+00:00"
        events = [
            {"event_time": "2025-12-31T00:00:00+00:00", "impact_score": 10},
            {"event_time": "2025-10-01T00:00:00+00:00", "impact_score": -10},
            {"event_time": "invalid", "impact_score": 100},
        ]

        self.assertEqual(server.calculate_interaction_frequency_score(events, 0, now), 20)
        self.assertEqual(server.calculate_recency_score(None, events, now), 100)
        self.assertEqual(server.calculate_history_score(events), 30)
        self.assertEqual(
            server.calculate_duration_score("2024-01-03T00:00:00+00:00", now),
            85,
        )
        self.assertEqual(server.calculate_duration_score("invalid", now), 0)

    def test_factor_calculators_use_last_contact_and_legacy_interaction_count(self):
        now = "2026-01-01T00:00:00+00:00"

        self.assertEqual(
            server.calculate_interaction_frequency_score([], 4, now),
            80,
        )
        self.assertEqual(
            server.calculate_recency_score("2025-11-01T00:00:00+00:00", [], now),
            25,
        )

    def test_score_schema_keeps_relationship_base_and_explanation_fields(self):
        relationship_columns = {
            row["name"]
            for row in self.db.execute("PRAGMA table_info(relationships)").fetchall()
        }
        score_columns = {
            row["name"]
            for row in self.db.execute("PRAGMA table_info(relationship_scores)").fetchall()
        }
        config_columns = {
            row["name"]
            for row in self.db.execute("PRAGMA table_info(relationship_score_configs)").fetchall()
        }

        self.assertIn("strength_score", relationship_columns)
        self.assertIn("last_evaluated_at", relationship_columns)
        self.assertTrue({
            "score",
            "interaction_frequency_score",
            "recency_score",
            "influence_score",
            "history_score",
            "duration_score",
            "weights_json",
            "components_json",
            "reason",
            "calculated_by",
            "calculated_at",
        }.issubset(score_columns))
        self.assertTrue({
            "interaction_frequency_weight",
            "recency_weight",
            "influence_weight",
            "history_weight",
            "duration_weight",
        }.issubset(config_columns))

    def test_auto_score_stays_in_range_and_has_complete_explanation(self):
        result = server.calculate_relationship_strength_auto(
            self.db, self.relationship["id"], "2026-01-01T00:00:00+00:00"
        )
        latest = result["latestScore"]
        components = json.loads(latest["components_json"])

        self.assertGreaterEqual(result["strength_score"], 0)
        self.assertLessEqual(result["strength_score"], 100)
        self.assertEqual(set(components), set(server.RELATIONSHIP_SCORE_FACTORS))
        for component in components.values():
            self.assertGreaterEqual(component["score"], 0)
            self.assertLessEqual(component["score"], 100)
            self.assertGreaterEqual(component["weight"], 0)
            self.assertGreaterEqual(component["weightedScore"], 0)

    def test_weight_validation_rejects_invalid_configurations(self):
        invalid_payloads = [
            {"weights": {"interaction_frequency": -1, "recency": 1, "influence": 1, "history": 1, "duration": 1}},
            {"weights": {"interaction_frequency": 0, "recency": 0, "influence": 0, "history": 0, "duration": 0}},
            {"weights": {"interaction_frequency": 1, "recency": 1, "influence": 1, "history": 1}},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    server.normalize_relationship_score_weights(payload)

    def test_level_mapping_covers_score_boundaries(self):
        levels = [
            server.relationship_score_level(0),
            server.relationship_score_level(1),
            server.relationship_score_level(49),
            server.relationship_score_level(50),
            server.relationship_score_level(79),
            server.relationship_score_level(80),
            server.relationship_score_level(100),
        ]
        self.assertEqual(len(levels), 7)
        self.assertEqual(levels[0], "未知关系")
        self.assertEqual(levels[1], "弱关系")
        self.assertEqual(levels[2], "弱关系")
        self.assertEqual(levels[3], "中关系")
        self.assertEqual(levels[4], "中关系")
        self.assertEqual(levels[5], "强关系")
        self.assertEqual(levels[6], "强关系")


if __name__ == "__main__":
    unittest.main()
