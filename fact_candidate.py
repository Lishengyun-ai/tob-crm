from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FactCandidateStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


SUBJECT_TYPES = {"Customer", "Person", "Opportunity", "Project"}
SOURCE_TYPES = {"recording", "chat", "document"}
FACT_CANDIDATE_STATUSES = {status.value for status in FactCandidateStatus}


@dataclass(frozen=True)
class FactCandidate:
    """AI 抽取但尚未确认的业务事实候选。"""

    id: int
    fact_type: str
    subject_type: str
    subject_id: int
    predicate: str
    object_value: str
    object_type: str
    source_type: str
    source_id: str
    confidence: int
    status: str
    created_by: str
    created_time: str
    review_user: Optional[str] = None
    review_time: Optional[str] = None


def validate_fact_candidate_values(
    *, subject_type: str, source_type: str, confidence: int, status: str
) -> None:
    """在写入前复用数据库约束，给调用方返回稳定的领域错误。"""
    if subject_type not in SUBJECT_TYPES:
        raise ValueError("subject_type must be one of: Customer, Person, Opportunity, Project")
    if source_type not in SOURCE_TYPES:
        raise ValueError("source_type must be one of: recording, chat, document")
    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100")
    if status not in FACT_CANDIDATE_STATUSES:
        raise ValueError("status must be one of: APPROVED, MODIFIED, PENDING, REJECTED")
