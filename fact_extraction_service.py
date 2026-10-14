from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fact_candidate import (
    SOURCE_TYPES,
    SUBJECT_TYPES,
    validate_fact_candidate_values,
)


SUPPORTED_FACT_TYPES = {
    "CustomerProfile": "Customer",
    "PersonRole": "Person",
    "PersonRelation": "Person",
    "OpportunityStatus": "Opportunity",
    "ProjectInformation": "Project",
    "Competitor": None,
}

LOW_CONFIDENCE_THRESHOLD = 60


class FactExtractionService:
    """将 LLM 输出转换为 FactCandidate，并只写入审核候选表。"""

    def __init__(
        self,
        llm_client: Any,
        subject_resolver: Optional[Callable[[str, str], Optional[int]]] = None,
        now_provider: Optional[Callable[[], str]] = None,
    ):
        self.llm_client = llm_client
        self.subject_resolver = subject_resolver
        self.now_provider = now_provider or self._now

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = str(payload.get(key, "")).strip()
        if not value:
            raise ValueError(f"{key} is required")
        return value

    @staticmethod
    def _parse_llm_result(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, str):
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(text)
        if isinstance(result, dict):
            result = result.get("facts", result.get("items", [result]))
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise ValueError("LLM output must be a JSON array of objects")
        return result

    def _call_llm(self, content: str, source_type: str, source_id: str) -> Any:
        prompt = {
            "task": "extract_business_facts",
            "allowed_fact_types": list(SUPPORTED_FACT_TYPES),
            "content": content,
            "source_type": source_type,
            "source_id": source_id,
            "output_schema": {
                "fact_type": "one of allowed_fact_types",
                "subject_type": "Customer|Person|Opportunity|Project",
                "subject": "subject display name",
                "subject_id": "optional resolved integer id",
                "predicate": "relationship",
                "object": "candidate value",
                "object_type": "text|number|date|boolean|reference",
                "confidence": "number between 0 and 1",
            },
        }
        if callable(self.llm_client):
            return self.llm_client(prompt)
        if hasattr(self.llm_client, "extract_facts"):
            return self.llm_client.extract_facts(prompt)
        if hasattr(self.llm_client, "complete"):
            return self.llm_client.complete(prompt)
        raise TypeError("llm_client must be callable or implement extract_facts/complete")

    @staticmethod
    def _confidence(value: Any) -> int:
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number between 0 and 1") from exc
        if not 0 <= score <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return round(score * 100)

    def _normalize_candidate(
        self, item: dict[str, Any], source_type: str, source_id: str, created_time: str
    ) -> dict[str, Any]:
        fact_type = self._required_text(item, "fact_type")
        if fact_type not in SUPPORTED_FACT_TYPES:
            raise ValueError(f"unsupported fact_type: {fact_type}")
        subject = self._required_text(item, "subject")
        subject_type = str(item.get("subject_type") or SUPPORTED_FACT_TYPES[fact_type] or "").strip()
        if not subject_type:
            raise ValueError("subject_type is required for Competitor facts")
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"unsupported subject_type: {subject_type}")
        subject_id = item.get("subject_id")
        if subject_id is None and self.subject_resolver:
            subject_id = self.subject_resolver(subject_type, subject)
        if subject_id is None:
            raise ValueError(f"cannot resolve subject_id for {subject_type}: {subject}")
        try:
            subject_id = int(subject_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("subject_id must be an integer") from exc
        if subject_id <= 0:
            raise ValueError("subject_id must be greater than 0")
        predicate = self._required_text(item, "predicate")
        object_value = item.get("object")
        if object_value is None or str(object_value).strip() == "":
            raise ValueError("object is required")
        confidence = self._confidence(item.get("confidence"))
        validate_fact_candidate_values(
            subject_type=subject_type,
            source_type=source_type,
            confidence=confidence,
            status="PENDING",
        )
        return {
            "fact_type": fact_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "predicate": predicate,
            "object_value": str(object_value),
            "object_type": str(item.get("object_type") or "text").strip(),
            "source_type": source_type,
            "source_id": source_id,
            "confidence": confidence,
            "status": "PENDING",
            "created_by": "fact-extraction-service",
            "created_time": created_time,
            "review_user": None,
            "review_time": None,
        }

    def extract(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """抽取并返回 FactCandidate 结构，不修改任何数据库对象。"""
        content = self._required_text(payload, "content")
        source_type = self._required_text(payload, "source_type").lower()
        source_id = self._required_text(payload, "source_id")
        if source_type not in SOURCE_TYPES:
            raise ValueError("source_type must be one of: recording, chat, document")
        raw_items = self._parse_llm_result(self._call_llm(content, source_type, source_id))
        created_time = self.now_provider()
        return [self._normalize_candidate(item, source_type, source_id, created_time) for item in raw_items]

    def queue(self, db: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """抽取后写入 fact_candidates；所有候选保持 PENDING，等待审核。"""
        candidates = self.extract(payload)
        for candidate in candidates:
            cursor = db.execute(
                """INSERT INTO fact_candidates
                   (fact_type, subject_type, subject_id, predicate, object_value,
                    object_type, source_type, source_id, confidence, fact_quality_score,
                    fact_quality_level, status,
                    created_by, created_time, review_user, review_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)""",
                tuple(candidate[field] for field in (
                    "fact_type", "subject_type", "subject_id", "predicate", "object_value",
                    "object_type", "source_type", "source_id", "confidence", "status",
                    "created_by", "created_time", "review_user", "review_time",
                )),
            )
            from fact_conflict_service import detect_conflicts_for_fact
            detect_conflicts_for_fact(db, cursor.lastrowid)
            from fact_quality_score import refresh_fact_quality_score
            quality = refresh_fact_quality_score(db, cursor.lastrowid)
            candidate["fact_quality_score"] = quality["fact_quality_score"]
            candidate["fact_quality_level"] = quality["fact_quality_level"]
        db.commit()
        return candidates

    @staticmethod
    def is_low_confidence(candidate: dict[str, Any]) -> bool:
        return int(candidate["confidence"]) < LOW_CONFIDENCE_THRESHOLD
