"""AI CRM 权限、审批、审计与数据质量治理（标准库实现）。"""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

OPERATIONS = ("read_only", "recommendation", "draft_write", "formal_write", "approval")
HIGH_RISK_FIELDS = {"amount", "price", "discount", "contractTerms", "externalCommitment", "customer_id", "stage"}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _actor(actor):
    if isinstance(actor, str):
        return {"userId": actor, "roles": ["sales"], "canWrite": True, "canApprove": False,
                "allowedOpportunityIds": None, "allowedCustomerIds": None}
    actor = actor or {}
    return {"userId": actor.get("userId") or actor.get("id") or actor.get("name") or "system",
            "roles": actor.get("roles") or ["sales"],
            "canWrite": bool(actor.get("canWrite", True)),
            "canApprove": bool(actor.get("canApprove", False)),
            "allowedOpportunityIds": actor.get("allowedOpportunityIds"),
            "allowedCustomerIds": actor.get("allowedCustomerIds")}

@dataclass
class GovernanceDecision:
    allowed: bool
    requiresApproval: bool = False
    reason: str = ""
    scope: str = "user"
    riskLevel: str = "low"
    actor: str = "system"

def authorize_operation(db, actor, operation, subject_type=None, subject_id=None, payload=None):
    a = _actor(actor); payload = payload or {}
    if operation not in OPERATIONS:
        return GovernanceDecision(False, reason="unknown operation", actor=a["userId"])
    ids_key = "allowed" + (subject_type or "").capitalize() + "Ids"
    allowed_ids = a.get(ids_key)
    if allowed_ids is not None and subject_id is not None and int(subject_id) not in {int(x) for x in allowed_ids}:
        return GovernanceDecision(False, reason="超出当前用户数据范围", scope="user", actor=a["userId"])
    if operation in ("read_only", "recommendation"):
        return GovernanceDecision(True, reason="当前用户范围内允许", actor=a["userId"])
    if operation == "approval" and not (a["canApprove"] or "approver" in a["roles"] or "admin" in a["roles"]):
        return GovernanceDecision(False, reason="当前用户没有审批权限", actor=a["userId"])
    if operation in ("draft_write", "formal_write") and not a["canWrite"] and "admin" not in a["roles"]:
        return GovernanceDecision(False, reason="当前用户没有写入权限", actor=a["userId"])
    keys = set(payload)
    high = bool(keys & HIGH_RISK_FIELDS) or bool(payload.get("approvalRequired"))
    return GovernanceDecision(True, requiresApproval=(operation == "formal_write" and high),
                              riskLevel="high" if high else "low", actor=a["userId"],
                              reason="高风险字段需审批" if high else "当前用户范围内允许")

def ensure_governance_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS governance_audit_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL, actor_roles_json TEXT NOT NULL DEFAULT '[]',
      operation TEXT NOT NULL, decision TEXT NOT NULL, target_type TEXT NOT NULL DEFAULT '', target_id INTEGER,
      risk_level TEXT NOT NULL DEFAULT 'low', before_json TEXT NOT NULL DEFAULT '{}', after_json TEXT NOT NULL DEFAULT '{}',
      metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_governance_audit_target ON governance_audit_logs(target_type, target_id, created_at);
    CREATE TABLE IF NOT EXISTS approval_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_type TEXT NOT NULL, target_type TEXT NOT NULL, target_id INTEGER,
      requested_by TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', risk_level TEXT NOT NULL DEFAULT 'high',
      payload_json TEXT NOT NULL DEFAULT '{}', reason TEXT NOT NULL DEFAULT '', approved_by TEXT, approved_at TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status, created_at);
    CREATE TABLE IF NOT EXISTS data_quality_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, requested_by TEXT NOT NULL, scope_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'completed', issue_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, completed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS data_quality_issues (
      id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, issue_type TEXT NOT NULL, severity TEXT NOT NULL,
      entity_type TEXT NOT NULL DEFAULT '', entity_id INTEGER, message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'OPEN', created_at TEXT NOT NULL, resolved_at TEXT, resolved_by TEXT,
      FOREIGN KEY(run_id) REFERENCES data_quality_runs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_quality_issues_status ON data_quality_issues(status, severity);
    """)

def record_audit(db, actor, operation, decision, target_type="", target_id=None, before=None, after=None, metadata=None):
    a = _actor(actor)
    db.execute("INSERT INTO governance_audit_logs (actor_id, actor_roles_json, operation, decision, target_type, target_id, risk_level, before_json, after_json, metadata_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (a["userId"], json.dumps(a["roles"], ensure_ascii=False), operation, decision, target_type, target_id,
                "high" if decision in ("approval_required", "approved", "rejected") else "low",
                json.dumps(before or {}, ensure_ascii=False), json.dumps(after or {}, ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False), now_iso()))

def create_approval_request(db, actor, request_type, target_type, target_id, payload, reason=""):
    a = _actor(actor); t = now_iso()
    cur = db.execute("INSERT INTO approval_requests (request_type,target_type,target_id,requested_by,status,risk_level,payload_json,reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (request_type, target_type, target_id, a["userId"], "PENDING", "high", json.dumps(payload or {}, ensure_ascii=False), reason, t, t))
    record_audit(db, actor, "formal_write", "approval_required", target_type, target_id, after=payload, metadata={"approvalRequestId": cur.lastrowid})
    return cur.lastrowid

def decide_approval(db, actor, request_id, approved, reason=""):
    row = db.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
    if not row: raise LookupError("approval request not found")
    decision = authorize_operation(db, actor, "approval", row["target_type"], row["target_id"])
    if not decision.allowed: raise PermissionError(decision.reason)
    a = _actor(actor)
    if row["requested_by"] == a["userId"]: raise PermissionError("申请人不能审批自己的请求")
    status = "APPROVED" if approved else "REJECTED"; t = now_iso()
    db.execute("UPDATE approval_requests SET status=?, approved_by=?, approved_at=?, updated_at=? WHERE id=?", (status, a["userId"], t, t, request_id))
    record_audit(db, actor, "approval", status.lower(), row["target_type"], row["target_id"], metadata={"approvalRequestId": request_id, "reason": reason})
    return dict(db.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone())

def _issue(db, run_id, typ, severity, entity_type, entity_id, message, details=None):
    db.execute("INSERT INTO data_quality_issues (run_id,issue_type,severity,entity_type,entity_id,message,details_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
               (run_id, typ, severity, entity_type, entity_id, message, json.dumps(details or {}, ensure_ascii=False), now_iso()))

def run_quality_check(db, actor="system", scope=None):
    a = _actor(actor); t = now_iso(); cur = db.execute("INSERT INTO data_quality_runs (requested_by,scope_json,created_at) VALUES (?,?,?)", (a["userId"], json.dumps(scope or {}, ensure_ascii=False), t)); run_id = cur.lastrowid
    # 孤儿关系：关系实体或角色不存在
    for r in db.execute("SELECT id,source_entity_id,target_entity_id,role_id FROM relationships").fetchall():
        bad = []
        for col in ("source_entity_id", "target_entity_id"):
            if not db.execute("SELECT 1 FROM relationship_entities WHERE id=?", (r[col],)).fetchone(): bad.append(col)
        if r["role_id"] is not None and not db.execute("SELECT 1 FROM roles WHERE id=? AND status='active'", (r["role_id"],)).fetchone(): bad.append("role_id")
        if bad: _issue(db, run_id, "orphan_relationship", "high", "relationship", r["id"], "关系引用不存在的实体或角色", {"fields": bad})
    for r in db.execute("SELECT name, customer_id, COUNT(*) n FROM projects GROUP BY name, customer_id HAVING n > 1").fetchall(): _issue(db, run_id, "duplicate_project", "medium", "project", None, "项目名称与客户重复", dict(r))
    for r in db.execute("SELECT phase_id, lot_name, COUNT(*) n FROM project_lots GROUP BY phase_id, lot_name HAVING n > 1").fetchall(): _issue(db, run_id, "duplicate_lot", "medium", "project_lot", None, "标段名称重复", dict(r))
    for o in db.execute("SELECT * FROM opportunities").fetchall():
        definition = db.execute("SELECT required_fields_json FROM stage_definitions WHERE name=? OR code=? LIMIT 1", (o["stage"], o["stage"])).fetchone()
        if definition:
            try: required = json.loads(definition["required_fields_json"] or "[]")
            except Exception: required = []
            missing = [x.get("key") for x in required if x.get("key") in ("projectName", "customer", "source") and not str(o["name"] if x.get("key")=="projectName" else o["customer"]).strip()]
            if missing: _issue(db, run_id, "missing_stage_condition", "high", "opportunity", o["id"], "商机缺少阶段必填条件", {"missing": missing})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forecasts'").fetchone():
        for f in db.execute("SELECT id, subject_type, subject_id FROM forecasts WHERE created_at < ? AND status NOT IN ('STALE','FAILED')", (cutoff,)).fetchall(): _issue(db, run_id, "stale_forecast", "medium", f["subject_type"], f["subject_id"], "预测超过 30 天未刷新", {"forecastId": f["id"]})
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_conflicts'").fetchone():
        for f in db.execute("SELECT id,fact_id_1,fact_id_2 FROM fact_conflicts WHERE resolution_status='OPEN'").fetchall(): _issue(db, run_id, "conflicting_fact", "high", "fact_conflict", f["id"], "存在未解决的冲突事实", dict(f))
    count = db.execute("SELECT COUNT(*) FROM data_quality_issues WHERE run_id=?", (run_id,)).fetchone()[0]
    db.execute("UPDATE data_quality_runs SET issue_count=?,completed_at=? WHERE id=?", (count, now_iso(), run_id)); record_audit(db, actor, "read_only", "completed", "data_quality_run", run_id, metadata={"issueCount": count})
    return get_quality_run(db, run_id)

def get_quality_run(db, run_id):
    row = db.execute("SELECT * FROM data_quality_runs WHERE id=?", (run_id,)).fetchone()
    if not row: raise LookupError("quality run not found")
    result = dict(row); result["scope"] = json.loads(result.pop("scope_json") or "{}"); result["issues"] = list_quality_issues(db, run_id); return result

def list_quality_issues(db, run_id=None, status=None):
    where=[]; args=[]
    if run_id is not None: where.append("run_id=?"); args.append(run_id)
    if status: where.append("status=?"); args.append(status)
    sql="SELECT * FROM data_quality_issues" + (" WHERE "+" AND ".join(where) if where else "") + " ORDER BY severity DESC,id DESC"
    out=[]
    for r in db.execute(sql,args).fetchall():
        x=dict(r); x["details"]=json.loads(x.pop("details_json") or "{}"); out.append(x)
    return out

