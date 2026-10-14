import unittest

from fact_confidence_service import FactConfidenceService


class FactConfidenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = FactConfidenceService()

    def test_calculates_default_confidence_score_by_source_type(self):
        expected = {
            "AI抽取": 70,
            "人工录入": 80,
            "CRM": 90,
            "ERP": 95,
        }
        for source_type, confidence_score in expected.items():
            self.assertEqual(
                self.service.calculate_confidence(source_type), confidence_score
            )

    def test_supports_existing_camel_case_method(self):
        self.assertEqual(self.service.calculateConfidence("CRM"), 90)

    def test_rejects_unsupported_source_type(self):
        with self.assertRaisesRegex(ValueError, "unsupported source_type"):
            self.service.calculate_confidence("会议记录")


if __name__ == "__main__":
    unittest.main()
