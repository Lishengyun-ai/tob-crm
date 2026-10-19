"""语音、OCR 和视觉抽取的供应商无关适配层及治理持久化。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


OPERATIONS = {"transcribe", "ocr", "vision_extraction"}
RUN_STATUSES = {"PENDING", "RUNNING", "SUCCESS", "FAILED", "RETRYABLE", "REVIEW_REQUIRED"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdapterError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class AdapterRequest:
    operation: str
    source_id: str
    input_type: str
    raw_reference: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30_000
    attempt: int = 1
    max_attempts: int = 3


@dataclass
class AdapterResponse:
    operation: str
    source_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    adapter_name: str = ""
    adapter_version: str = "mock-v1"
    started_at: str = ""
    completed_at: str = ""
    error_code: str | None = None
    error_message: str = ""
    retryable: bool = False
    attempt: int = 1
    timeout_ms: int = 30_000

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["timeoutMs"] = result.pop("timeout_ms")
        result["adapterName"] = result["adapter_name"]
        result["adapterVersion"] = result["adapter_version"]
        result["sourceId"] = result["source_id"]
        return result


class TranscriptionAdapter(Protocol):
    name: str

    def transcribe(self, request: AdapterRequest) -> dict[str, Any]: ...


class OCRAdapter(Protocol):
    name: str

    def extract(self, request: AdapterRequest) -> dict[str, Any]: ...


class VisionExtractionAdapter(Protocol):
    name: str

    def extract(self, request: AdapterRequest) -> dict[str, Any]: ...


class MockTranscriptionAdapter:
    name = "mock-transcription"

    def transcribe(self, request: AdapterRequest) -> dict[str, Any]:
        payload = request.payload
        if payload.get("simulateError"):
            raise AdapterError("MOCK_TRANSCRIPTION_FAILURE", "模拟转写失败", retryable=bool(payload.get("retryable", True)))
        text = str(payload.get("text") or payload.get("mockText") or "").strip()
        if not text:
            raise AdapterError("EMPTY_AUDIO_INPUT", "模拟适配器没有收到可转写文本", retryable=False)
        segments = payload.get("segments") or [{"speaker": "unknown", "startSecond": 0, "endSecond": 0, "text": text}]
        return {"text": text, "language": payload.get("language", "zh-CN"), "segments": segments, "quality": payload.get("quality", 0.9)}


class MockOCRAdapter:
    name = "mock-ocr"

    def extract(self, request: AdapterRequest) -> dict[str, Any]:
        payload = request.payload
        if payload.get("simulateError"):
            raise AdapterError("MOCK_OCR_FAILURE", "模拟 OCR 失败", retryable=bool(payload.get("retryable", True)))
        text = str(payload.get("ocrText") or payload.get("text") or payload.get("notes") or "").strip()
        fields = payload.get("fields") or []
        if not fields:
            for key, value in (("projectName", payload.get("projectName")), ("customerName", payload.get("customerName")), ("address", payload.get("address"))):
                if value:
                    fields.append({"field": key, "value": value, "confidence": payload.get("confidence", 0.72), "evidence": {"sourceType": "image", "sourceId": request.source_id, "quote": str(value)}})
        return {"text": text, "fields": fields, "quality": payload.get("quality", 0.85)}


class MockVisionExtractionAdapter:
    name = "mock-vision-extraction"

    def extract(self, request: AdapterRequest) -> dict[str, Any]:
        payload = request.payload
        if payload.get("simulateError"):
            raise AdapterError("MOCK_VISION_FAILURE", "模拟视觉抽取失败", retryable=bool(payload.get("retryable", True)))
        fields = payload.get("fields") or []
        if not fields:
            for key in ("projectName", "customerName", "address", "observedAt"):
                value = payload.get(key)
                if value:
                    fields.append({"field": key, "value": value, "confidence": payload.get("confidence", 0.72), "evidence": {"sourceType": "image", "sourceId": request.source_id}})
        return {"fields": fields, "matchCandidates": payload.get("matchCandidates", []), "quality": payload.get("quality", 0.8)}


class MediaAdapterService:
    def __init__(self, *, transcription: TranscriptionAdapter | None = None, ocr: OCRAdapter | None = None, vision: VisionExtractionAdapter | None = None):
        self.transcription = transcription or MockTranscriptionAdapter()
        self.ocr = ocr or MockOCRAdapter()
        self.vision = vision or MockVisionExtractionAdapter()

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        if request.operation not in OPERATIONS:
            raise ValueError("operation must be transcribe, ocr, or vision_extraction")
        started = now_iso()
        start_clock = time.monotonic()
        try:
            if request.operation == "transcribe":
                output = self.transcription.transcribe(request)
                adapter_name = self.transcription.name
            elif request.operation == "ocr":
                output = self.ocr.extract(request)
                adapter_name = self.ocr.name
            else:
                output = self.vision.extract(request)
                adapter_name = self.vision.name
            elapsed_ms = int((time.monotonic() - start_clock) * 1000)
            if elapsed_ms > request.timeout_ms:
                raise AdapterError("ADAPTER_TIMEOUT", "适配器处理超过超时时间", retryable=True, details={"elapsedMs": elapsed_ms})
            confidence = float(output.get("confidence", output.get("quality", 0.0)) or 0.0)
            return AdapterResponse(request.operation, request.source_id, "SUCCESS", output, max(0.0, min(1.0, confidence)), adapter_name, attempt=request.attempt, timeout_ms=request.timeout_ms, started_at=started, completed_at=now_iso())
        except AdapterError as exc:
            return AdapterResponse(request.operation, request.source_id, "RETRYABLE" if exc.retryable else "FAILED", {}, 0.0, locals().get("adapter_name", ""), started_at=started, completed_at=now_iso(), error_code=exc.code, error_message=exc.message, retryable=exc.retryable, attempt=request.attempt, timeout_ms=request.timeout_ms)
        except Exception as exc:  # 适配器边界统一错误，避免第三方异常泄漏到业务层
            return AdapterResponse(request.operation, request.source_id, "FAILED", {}, 0.0, locals().get("adapter_name", ""), started_at=started, completed_at=now_iso(), error_code="ADAPTER_UNEXPECTED_ERROR", error_message=str(exc), retryable=False, attempt=request.attempt, timeout_ms=request.timeout_ms)

    def execute_with_retry(self, request: AdapterRequest) -> AdapterResponse:
        response = self.execute(request)
        while response.status == "RETRYABLE" and request.attempt < request.max_attempts:
            request = AdapterRequest(**{**asdict(request), "attempt": request.attempt + 1})
            response = self.execute(request)
        return response


def ensure_media_adapter_schema(db: Any) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS voice_recordings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_name TEXT NOT NULL,
      file_path TEXT NOT NULL,
      mime_type TEXT NOT NULL DEFAULT 'audio/*',
      file_size INTEGER NOT NULL DEFAULT 0,
      sha256 TEXT NOT NULL,
      customer_id INTEGER,
      opportunity_id INTEGER,
      status TEXT NOT NULL DEFAULT 'uploaded',
      transcript_json TEXT NOT NULL DEFAULT '{}',
      error_code TEXT NOT NULL DEFAULT '',
      error_message TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
      FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS media_adapter_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      operation TEXT NOT NULL,
      input_type TEXT NOT NULL,
      source_id TEXT NOT NULL,
      raw_file_path TEXT,
      request_json TEXT NOT NULL DEFAULT '{}',
      response_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'PENDING',
      confidence REAL NOT NULL DEFAULT 0,
      timeout_ms INTEGER NOT NULL DEFAULT 30000,
      attempt INTEGER NOT NULL DEFAULT 1,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      error_code TEXT NOT NULL DEFAULT '',
      error_message TEXT NOT NULL DEFAULT '',
      retry_of INTEGER,
      created_at TEXT NOT NULL,
      completed_at TEXT,
      FOREIGN KEY(retry_of) REFERENCES media_adapter_runs(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS media_candidate_drafts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id INTEGER NOT NULL,
      draft_type TEXT NOT NULL,
      source_id TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      confidence REAL NOT NULL DEFAULT 0,
      review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
      review_user TEXT,
      reviewed_at TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(run_id) REFERENCES media_adapter_runs(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS media_audit_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id INTEGER,
      event_type TEXT NOT NULL,
      actor TEXT NOT NULL DEFAULT 'system',
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      FOREIGN KEY(run_id) REFERENCES media_adapter_runs(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_media_runs_source ON media_adapter_runs(input_type, source_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_media_runs_status ON media_adapter_runs(status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_media_drafts_status ON media_candidate_drafts(review_status, created_at DESC);
    """)
    for table in ("project_evidence", "discovery_runs"):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if columns and "adapter_run_id" not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN adapter_run_id INTEGER")


def save_raw_file(root: Path, raw: bytes, file_name: str) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    safe_name = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in str(file_name or "evidence.bin"))
    evidence_dir = root / "data" / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    path = evidence_dir / f"{digest[:16]}_{safe_name}"
    if not path.exists():
        path.write_bytes(raw)
    return str(path.relative_to(root)), digest


def persist_adapter_run(db: Any, request: AdapterRequest, response: AdapterResponse, *, raw_file_path: str | None = None, retry_of: int | None = None, now: str | None = None) -> int:
    timestamp = now or now_iso()
    cur = db.execute("""INSERT INTO media_adapter_runs
      (operation, input_type, source_id, raw_file_path, request_json, response_json, status, confidence, timeout_ms, attempt, max_attempts, error_code, error_message, retry_of, created_at, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (request.operation, request.input_type, request.source_id, raw_file_path, json.dumps({**asdict(request), "payload": {k: v for k, v in request.payload.items() if k not in {"contentBase64", "rawBytes"}}}, ensure_ascii=False), json.dumps(response.to_dict(), ensure_ascii=False), response.status, response.confidence, request.timeout_ms, request.attempt, request.max_attempts, response.error_code or "", response.error_message, retry_of, timestamp, response.completed_at or timestamp))
    event = "adapter_succeeded" if response.status == "SUCCESS" else "adapter_failed" if response.status == "FAILED" else "adapter_retryable_failure"
    db.execute("INSERT INTO media_audit_logs (run_id, event_type, actor, payload_json, created_at) VALUES (?, ?, 'system', ?, ?)", (cur.lastrowid, event, json.dumps({"operation": request.operation, "attempt": request.attempt, "errorCode": response.error_code}, ensure_ascii=False), timestamp))
    return cur.lastrowid


def create_candidate_draft(db: Any, run_id: int, draft_type: str, source_id: str, payload: dict[str, Any], confidence: float, now: str | None = None) -> int:
    cur = db.execute("INSERT INTO media_candidate_drafts (run_id, draft_type, source_id, payload_json, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?)", (run_id, draft_type, source_id, json.dumps(payload, ensure_ascii=False), confidence, now or now_iso()))
    db.execute("INSERT INTO media_audit_logs (run_id, event_type, actor, payload_json, created_at) VALUES (?, 'candidate_created', 'system', ?, ?)", (run_id, json.dumps({"draftType": draft_type, "confidence": confidence}, ensure_ascii=False), now or now_iso()))
    return cur.lastrowid


def queue_fact_candidates(db: Any, facts: list[dict[str, Any]], *, source_type: str, source_id: str, now: str | None = None) -> list[int]:
    """将有明确主体的识别结果放入 FactCandidate，绝不直接写正式事实。"""
    timestamp = now or now_iso()
    ids: list[int] = []
    allowed = {"CustomerProfile": "Customer", "ProjectInformation": "Project", "OpportunityStatus": "Opportunity", "PersonRole": "Person", "PersonRelation": "Person", "Competitor": None}
    for item in facts or []:
        subject_type = str(item.get("subjectType") or item.get("subject_type") or "").strip()
        subject_id = item.get("subjectId", item.get("subject_id"))
        fact_type = str(item.get("factType") or item.get("fact_type") or "").strip()
        predicate = str(item.get("predicate") or item.get("field") or "").strip()
        value = item.get("objectValue", item.get("object_value", item.get("value")))
        if not subject_type or subject_id is None or not fact_type or not predicate or value in (None, ""):
            continue
        if fact_type not in allowed or (allowed[fact_type] and allowed[fact_type] != subject_type):
            continue
        try:
            subject_id = int(subject_id)
            confidence = round(float(item.get("confidence", 0.0)) * 100) if float(item.get("confidence", 0.0)) <= 1 else int(item.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= confidence <= 100:
            continue
        table = {"Customer": "customers", "Person": "persons", "Opportunity": "opportunities", "Project": "projects"}.get(subject_type)
        if not table or not db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (subject_id,)).fetchone():
            continue
        cur = db.execute("""INSERT INTO fact_candidates
          (fact_type, subject_type, subject_id, predicate, object_value, object_type, source_type, source_id, confidence, status, created_by, created_time)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 'media-adapter', ?)""", (fact_type, subject_type, subject_id, predicate, str(value), str(item.get("objectType") or item.get("object_type") or "text"), source_type, source_id, confidence, timestamp))
        ids.append(cur.lastrowid)
        try:
            from fact_conflict_service import detect_conflicts_for_fact
            detect_conflicts_for_fact(db, cur.lastrowid)
            from fact_quality_score import refresh_fact_quality_score
            refresh_fact_quality_score(db, cur.lastrowid)
        except Exception:
            pass
    return ids
