class FactConfidenceService:
    """根据事实来源计算 confidence_score。"""

    CONFIDENCE_SCORES = {
        "AI抽取": 70,
        "人工录入": 80,
        "CRM": 90,
        "ERP": 95,
    }

    def calculate_confidence(self, source_type: str) -> int:
        source_type = str(source_type).strip()
        if source_type not in self.CONFIDENCE_SCORES:
            raise ValueError(f"unsupported source_type: {source_type}")
        return self.CONFIDENCE_SCORES[source_type]

    def calculateConfidence(self, source_type: str) -> int:
        return self.calculate_confidence(source_type)
