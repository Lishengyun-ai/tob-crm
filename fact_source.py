from dataclasses import dataclass
from enum import Enum


class FactSourceType(str, Enum):
    CRM = "CRM"
    ERP = "ERP"
    YUNZHU = "云筑"
    MANUAL_ENTRY = "人工录入"
    AI_EXTRACTION = "AI抽取"
    MEETING_RECORD = "会议记录"


@dataclass(frozen=True)
class FactSource:
    """客户事实来源 Entity。"""

    id: int
    source_type: str
    source_name: str
    source_system: str
    source_record_id: str
    extract_method: str
    created_time: str
