import json
import os
import sqlite3
import base64
import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB_DIR = ROOT / "data"
DB_PATH = DB_DIR / "crm.sqlite3"
OUTPUTS = ROOT / "outputs"

SEED_OPPORTUNITIES = [
    ("华东区域数字化营销项目", "华东建材集团", "方案与报价", "1280000", "制造业", "李盛云", "客户已确认营销自动化与渠道协同需求，等待最终方案评审。", "预算审批节点尚未确认", "准备方案评审会议", "交易数据,CRM通用"),
    ("星河零售会员运营平台", "星河商业集团", "需求确认", "860000", "零售行业", "王敏", "已完成业务访谈，客户关注会员分层、复购预测与活动归因。", "关键用户尚未全部参与", "补充客户成功案例", "客户洞察,行业语义"),
    ("南方能源供应链协同", "南方能源", "初步接触", "2400000", "CRM通用", "赵一", "来自伙伴推荐的集团级线索，正在确认采购范围与决策链。", "决策链不完整", "识别经济买家", "伙伴引荐,集团客户"),
    ("远景科技售后服务升级", "远景科技", "商务谈判", "620000", "高科技", "陈晨", "技术方案和报价已通过，正在确认合同条款与交付周期。", "交付资源需要锁定", "发起合同审批", "服务管理,项目型"),
    ("海岳地产客户经营平台", "海岳地产", "赢单", "1050000", "地产行业", "李盛云", "合同已签署，进入首期交付准备阶段。", "", "创建项目与交付计划", "赢单,交付准备"),
]

SEED_AGENTS = [
    ("customer-insight", "客户洞察 Agent", "客户开发", "从客户、商机、关系和经营指标生成画像、评分、机会与风险洞察。", "客户画像生成,客户评分计算,机会识别,风险扫描", "客户画像,涂料客户增长潜力模型,采购金额增长归因"),
    ("development-strategy", "客户开发策略 Agent", "客户开发", "结合客户 AT 阶段和涂料行业策略，生成突破路径、关键人策略与 30/60/90 天计划。", "开发目标拆解,工程入口识别,设计突破,方案植入,样板验证,关键人地图,30/60/90行动计划", "客户出货目标达成阈值,高潜工程客户增购策略,工程涂料项目推进 SOP"),
    ("visit-script", "拜访话术 Agent", "销售执行", "根据客户角色、当前 AT 阶段和商机风险，生成开场、提问与价值表达。", "开场话术,需求提问,价值表达,异议回应", "客户画像,涂料行业术语,商机关系图谱"),
    ("solution", "方案 Agent", "销售执行", "基于基材、应用场景、产品体系和客户目标推荐涂料解决方案与案例。", "场景分析,产品体系匹配,解决方案推荐,案例匹配,用量测算", "涂料产品,涂布率,工程涂料项目推进 SOP"),
    ("presentation", "PPT Agent", "销售执行", "将客户画像、方案、价值测算和竞争信息组织成客户交流材料与汇报大纲。", "客户交流材料,汇报方案,价值测算,一页纸摘要", "客户画像,采购金额,高潜工程客户增购策略"),
    ("competition", "竞争策略 Agent", "销售执行", "识别竞品、价格、关系和供应商准入风险，给出涂料商机突破打法。", "竞品分析,竞争位势,价格策略,突破打法", "商机关系图谱,涂料报价审批规则,采购金额增长归因"),
    ("opportunity-progress", "商机推进 Agent", "商机诊断", "识别商机所处 AT 阶段、缺失条件和下一步动作，推动商机形成可验证的业务事件。", "AT阶段判断,阶段准入校验,下一步动作,风险提示,业务事件记录", "推进涂料商机,样板验证完成,工程涂料项目推进 SOP"),
    ("win-loss-review", "赢单/输单复盘 Agent", "商机诊断", "复盘赢单、输单和样板验证结果，将经验沉淀为可复用的策略与知识。", "赢单复盘,输单归因,最佳实践提炼,知识库沉淀", "采购金额增长归因,商机关系图谱,高潜工程客户增购策略"),
]

STAGE_DEFINITIONS = [
    {
        "code": "OPP_REPORTED",
        "name": "商机报备",
        "sequence": 1,
        "required": [
            {"key": "projectName", "label": "项目名称"},
            {"key": "customer", "label": "客户名称"},
            {"key": "source", "label": "商机来源"},
        ],
        "next": "OPP_CONFIRMED",
        "agent": "opportunity-discovery",
    },
    {
        "code": "OPP_CONFIRMED",
        "name": "商机确认",
        "sequence": 2,
        "required": [
            {"key": "duplicateStatus", "label": "查重状态"},
            {"key": "projectType", "label": "项目类型"},
        ],
        "next": "OPP_TRACKING",
        "agent": "opportunity-progress",
    },
    {
        "code": "OPP_TRACKING",
        "name": "商机跟踪",
        "sequence": 3,
        "required": [
            {"key": "need", "label": "客户需求"},
            {"key": "decisionChain", "label": "决策链"},
            {"key": "competitor", "label": "竞品信息"},
        ],
        "next": "OPP_PRE_BID",
        "agent": "opportunity-progress",
    },
    {
        "code": "OPP_PRE_BID",
        "name": "标前引导",
        "sequence": 4,
        "required": [
            {"key": "solution", "label": "产品方案"},
            {"key": "priceCost", "label": "价格与成本分析"},
            {"key": "sampleStatus", "label": "打样或现场样板"},
        ],
        "next": "OPP_TENDERING",
        "agent": "solution",
    },
    {
        "code": "OPP_TENDERING",
        "name": "招投标",
        "sequence": 5,
        "required": [
            {"key": "bidPlan", "label": "投标资料"},
            {"key": "commercialPlan", "label": "商务谈判准备"},
            {"key": "termRisk", "label": "标书条款评估"},
        ],
        "next": "OPP_SIGNED",
        "agent": "competition",
    },
    {
        "code": "OPP_SIGNED",
        "name": "签约",
        "sequence": 6,
        "required": [
            {"key": "awardNotice", "label": "中标通知书"},
            {"key": "contractNo", "label": "合同编号"},
            {"key": "contractAmount", "label": "合同金额"},
        ],
        "next": None,
        "agent": "opportunity-progress",
    },
]

LEGACY_STAGE_MAP = {
    "初步接触": "商机报备",
    "需求确认": "商机确认",
    "方案与报价": "标前引导",
    "商务谈判": "招投标",
    "赢单": "签约",
}

def connect():
    DB_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          customer TEXT NOT NULL,
          customer_id INTEGER,
          project_id INTEGER,
          project_section_id INTEGER,
          stage TEXT NOT NULL,
          amount INTEGER NOT NULL DEFAULT 0,
          business_type TEXT NOT NULL,
          owner TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          risk TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          source_category TEXT NOT NULL DEFAULT '内部信息',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_fields (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          field_name TEXT NOT NULL,
          field_type TEXT NOT NULL,
          field_value TEXT NOT NULL,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS business_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          message TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          category TEXT NOT NULL,
          asset_type TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          badges TEXT NOT NULL DEFAULT '',
          fields_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agents (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          scene TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '已启用',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_skills (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT NOT NULL,
          name TEXT NOT NULL,
          skill_type TEXT NOT NULL DEFAULT 'Skill',
          description TEXT NOT NULL DEFAULT '',
          linked_assets TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT NOT NULL,
          opportunity_id INTEGER,
          input_json TEXT NOT NULL DEFAULT '{}',
          result TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'completed',
          created_at TEXT NOT NULL,
          FOREIGN KEY(agent_id) REFERENCES agents(id),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          customer_type TEXT NOT NULL DEFAULT '建设单位',
          industry TEXT NOT NULL DEFAULT '涂料工程',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER,
          name TEXT NOT NULL,
          project_type TEXT NOT NULL DEFAULT '工程项目',
          address TEXT NOT NULL DEFAULT '',
          longitude REAL,
          latitude REAL,
          building_area REAL,
          status TEXT NOT NULL DEFAULT 'discovered',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS project_sections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL,
          name TEXT NOT NULL DEFAULT '待补充标段',
          phase TEXT NOT NULL DEFAULT '',
          cooperation_mode TEXT NOT NULL DEFAULT '待确认',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER,
          opportunity_id INTEGER,
          source_type TEXT NOT NULL,
          file_name TEXT NOT NULL,
          file_path TEXT NOT NULL,
          mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
          extracted_text TEXT NOT NULL DEFAULT '',
          extracted_json TEXT NOT NULL DEFAULT '{}',
          confidence REAL NOT NULL DEFAULT 0,
          review_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(id),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        CREATE TABLE IF NOT EXISTS discovery_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          status TEXT NOT NULL DEFAULT 'draft',
          input_type TEXT NOT NULL,
          evidence_id INTEGER,
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(evidence_id) REFERENCES project_evidence(id)
        );
        CREATE TABLE IF NOT EXISTS discovery_candidates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          customer_name TEXT NOT NULL DEFAULT '',
          project_name TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '',
          project_type TEXT NOT NULL DEFAULT '工程项目',
          product_lines TEXT NOT NULL DEFAULT '[]',
          estimated_amount INTEGER NOT NULL DEFAULT 0,
          confidence REAL NOT NULL DEFAULT 0,
          duplicate_status TEXT NOT NULL DEFAULT 'not_checked',
          duplicate_result_json TEXT NOT NULL DEFAULT '{}',
          review_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES discovery_runs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS duplicate_checks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          candidate_id INTEGER,
          opportunity_id INTEGER,
          project_name_score REAL NOT NULL DEFAULT 0,
          address_match INTEGER NOT NULL DEFAULT 0,
          customer_match INTEGER NOT NULL DEFAULT 0,
          duplicate_probability REAL NOT NULL DEFAULT 0,
          reason TEXT NOT NULL DEFAULT '',
          review_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          FOREIGN KEY(candidate_id) REFERENCES discovery_candidates(id),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        CREATE TABLE IF NOT EXISTS stage_definitions (
          code TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          sequence INTEGER NOT NULL,
          object_type TEXT NOT NULL DEFAULT 'opportunity',
          required_fields_json TEXT NOT NULL DEFAULT '[]',
          next_code TEXT,
          agent_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS opportunity_stage_transitions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          from_stage TEXT NOT NULL,
          to_stage TEXT NOT NULL,
          required_json TEXT NOT NULL DEFAULT '{}',
          validation_json TEXT NOT NULL DEFAULT '{}',
          actor TEXT NOT NULL DEFAULT '李盛云',
          created_at TEXT NOT NULL,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
        if "source_category" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN source_category TEXT NOT NULL DEFAULT '内部信息'")
        if "customer_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN customer_id INTEGER")
        if "project_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN project_id INTEGER")
        if "project_section_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN project_section_id INTEGER")
        now = datetime.now(timezone.utc).isoformat()
        for definition in STAGE_DEFINITIONS:
            db.execute("""INSERT OR IGNORE INTO stage_definitions
                (code, name, sequence, required_fields_json, next_code, agent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                definition["code"], definition["name"], definition["sequence"],
                json.dumps(definition["required"], ensure_ascii=False), definition["next"],
                definition["agent"], now, now))
        count = db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        if count == 0:
            for row in SEED_OPPORTUNITIES:
                name, customer, stage, amount, business_type, owner, description, risk, next_action, tags = row
                cur = db.execute("""INSERT INTO opportunities
                    (name, customer, stage, amount, business_type, owner, description, risk, next_action, source_category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, customer, stage, int(amount), business_type, owner, description, risk, next_action, "内部信息", now, now))
                oid = cur.lastrowid
                for tag in tags.split(','):
                    db.execute("INSERT INTO semantic_fields (opportunity_id, field_name, field_type, field_value) VALUES (?, ?, ?, ?)", (oid, "业务标签", "semantic_tag", tag))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, "created", "商机对象已初始化", now))
        backfill_opportunity_relations(db, now)
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_customer_id ON opportunities(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_project_id ON opportunities(project_id)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunities_project_section_id ON opportunities(project_section_id) WHERE project_section_id IS NOT NULL")
        agent_count = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if agent_count == 0:
            for agent_id, name, scene, description, skills, assets in SEED_AGENTS:
                db.execute("INSERT INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (agent_id, name, scene, description, now, now))
                for skill in skills.split(','):
                    db.execute("INSERT INTO agent_skills (agent_id, name, description, linked_assets) VALUES (?, ?, ?, ?)", (agent_id, skill, f"{skill}：读取客户、商机与涂料行业语义后生成可解释结果。", assets))

def backfill_opportunity_relations(db, now):
    """将旧版名称关联迁移为 Customer -> Project -> ProjectSection 外键关系。"""
    rows = db.execute("SELECT * FROM opportunities ORDER BY id").fetchall()
    for row in rows:
        customer = db.execute("SELECT * FROM customers WHERE name = ?", (row["customer"],)).fetchone()
        if customer:
            customer_id = customer["id"]
        else:
            cur = db.execute(
                "INSERT INTO customers (name, created_at, updated_at) VALUES (?, ?, ?)",
                (row["customer"], now, now),
            )
            customer_id = cur.lastrowid

        project = db.execute(
            "SELECT * FROM projects WHERE customer_id = ? AND name = ? ORDER BY id LIMIT 1",
            (customer_id, row["name"]),
        ).fetchone()
        if project:
            project_id = project["id"]
        else:
            cur = db.execute(
                """INSERT INTO projects
                    (customer_id, name, project_type, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'discovered', ?, ?)""",
                (customer_id, row["name"], "工程项目", now, now),
            )
            project_id = cur.lastrowid

        section = None
        if row["project_section_id"]:
            section = db.execute(
                "SELECT * FROM project_sections WHERE id = ?", (row["project_section_id"],)
            ).fetchone()
        if not section:
            section = db.execute(
                "SELECT * FROM project_sections WHERE project_id = ? ORDER BY id LIMIT 1",
                (project_id,),
            ).fetchone()
        if section:
            section_id = section["id"]
        else:
            cur = db.execute(
                """INSERT INTO project_sections
                    (project_id, name, cooperation_mode, created_at, updated_at)
                    VALUES (?, '待补充标段', '待确认', ?, ?)""",
                (project_id, now, now),
            )
            section_id = cur.lastrowid

        db.execute(
            """UPDATE opportunities
               SET customer_id = ?, project_id = ?, project_section_id = ?, updated_at = ?
               WHERE id = ?""",
            (customer_id, project_id, section_id, now, row["id"]),
        )

def attach_relationships(db, item):
    customer_id = item.get("customer_id")
    project_id = item.get("project_id")
    section_id = item.get("project_section_id")
    customer = db.execute("SELECT id, name, customer_type, industry, status FROM customers WHERE id = ?", (customer_id,)).fetchone() if customer_id else None
    project = db.execute("SELECT id, name, project_type, address, status FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id else None
    section = db.execute("SELECT id, name, phase, cooperation_mode, status FROM project_sections WHERE id = ?", (section_id,)).fetchone() if section_id else None
    item["customerId"] = customer_id
    item["projectId"] = project_id
    item["projectSectionId"] = section_id
    item["customerObject"] = dict(customer) if customer else None
    item["projectObject"] = dict(project) if project else None
    item["projectSectionObject"] = dict(section) if section else None
    return item

def serialize(row):
    return {
        "id": row["id"], "name": row["name"], "customer": row["customer"], "stage": row["stage"],
        "amount": row["amount"], "businessType": row["business_type"], "owner": row["owner"],
        "description": row["description"], "risk": row["risk"], "nextAction": row["next_action"], "sourceCategory": row["source_category"],
        "tags": [x["field_value"] for x in row.get("tags", [])] if isinstance(row, dict) else [],
    }

def stage_name(value):
    if value in {item["name"] for item in STAGE_DEFINITIONS}:
        return value
    return LEGACY_STAGE_MAP.get(value, value)

def stage_definition(db, value):
    if not value:
        return None
    name = stage_name(value)
    row = db.execute("SELECT * FROM stage_definitions WHERE name = ? OR code = ?", (name, value)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["required"] = json.loads(item.pop("required_fields_json") or "[]")
    item["nextCode"] = item.pop("next_code")
    return item

def target_name(db, code):
    if not code:
        return None
    row = db.execute("SELECT name FROM stage_definitions WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else None

def decorate_opportunity(db, item):
    item = attach_relationships(db, item)
    info = stage_definition(db, item.get("stage"))
    if info:
        item["stage"] = info["name"]
        item["stageName"] = info["name"]
        item["stageCode"] = info["code"]
        item["stageSequence"] = info["sequence"]
        next_row = db.execute("SELECT code, name FROM stage_definitions WHERE code = ?", (info["nextCode"],)).fetchone() if info["nextCode"] else None
        item["nextStage"] = dict(next_row) if next_row else None
    else:
        item["stageName"] = stage_name(item.get("stage"))
        item["stageCode"] = None
        item["stageSequence"] = None
        item["nextStage"] = None
    return item

def get_opportunity(db, oid):
    row = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["tags"] = [dict(x) for x in db.execute("SELECT * FROM semantic_fields WHERE opportunity_id = ?", (oid,)).fetchall()]
    item = decorate_opportunity(db, item)
    history = db.execute("""SELECT * FROM opportunity_stage_transitions
        WHERE opportunity_id = ? ORDER BY created_at ASC, id ASC""", (oid,)).fetchall()
    item["stageHistory"] = []
    for record in history:
        history_item = dict(record)
        history_item["required"] = json.loads(history_item.pop("required_json") or "{}")
        history_item["validation"] = json.loads(history_item.pop("validation_json") or "{}")
        item["stageHistory"].append(history_item)
    current_fields = {
        "项目名称": item["name"],
        "客户名称": item["customer"],
        "商机来源": item.get("sourceCategory") or item.get("source_category") or "内部信息",
    }
    if item["stageHistory"]:
        current_fields.update(item["stageHistory"][-1]["required"])
    item["stageFields"] = current_fields
    current_definition = stage_definition(db, item.get("stage"))
    current_sequence = current_definition["sequence"] if current_definition else 1
    history_by_stage = {record["to_stage"]: record for record in item["stageHistory"]}
    stage_tasks = []
    for definition in db.execute("SELECT * FROM stage_definitions ORDER BY sequence").fetchall():
        stage_item = dict(definition)
        stage_item["required"] = json.loads(stage_item.pop("required_fields_json") or "[]")
        stage_item.pop("next_code", None)
        record = history_by_stage.get(stage_item["name"])
        if stage_item["sequence"] < current_sequence:
            status = "completed"
            fields = record["required"] if record else {}
            note = "已完成"
            if not record:
                note = "历史阶段，待补录推进记录"
        elif stage_item["sequence"] == current_sequence:
            status = "current"
            fields = record["required"] if record else current_fields
            note = "当前阶段"
        else:
            status = "pending"
            fields = {}
            note = "待推进"
        stage_tasks.append({
            "code": stage_item["code"],
            "name": stage_item["name"],
            "sequence": stage_item["sequence"],
            "status": status,
            "note": note,
            "required": stage_item["required"],
            "fields": fields,
            "transitionId": record["id"] if record else None,
            "createdAt": record["created_at"] if record else None,
        })
    item["stageTasks"] = stage_tasks
    return item

def clean_candidate_text(value, fallback):
    value = str(value or "").strip()
    return value[:200] if value else fallback

def normalize_text(value):
    return re.sub(r"[\s\-_,，。.!！？:：/\\]+", "", str(value or "")).lower()

def build_discovery_candidate(data, file_name):
    notes = str(data.get("notes", "")).strip()
    stem = Path(file_name or "现场发现").stem
    project_name = clean_candidate_text(data.get("projectName"), stem if stem else "现场发现项目")
    customer_name = clean_candidate_text(data.get("customerName"), "待匹配建设单位")
    address = clean_candidate_text(data.get("address"), "")
    product_lines = data.get("productLines") or ["外墙涂料"]
    if isinstance(product_lines, str):
        product_lines = [x.strip() for x in product_lines.split(",") if x.strip()]
    return {
        "customerName": customer_name,
        "projectName": project_name,
        "address": address,
        "projectType": "工程项目",
        "productLines": product_lines[:8],
        "estimatedAmount": int(data.get("estimatedAmount", 0) or 0),
        "confidence": 0.72 if notes or data.get("projectName") else 0.48,
        "extractedText": notes or "MVP 识别适配层：已保存证据，等待接入 OCR / 视觉模型。",
        "recognitionMode": "规则化 MVP 草稿",
    }

def run_duplicate_check(db, candidate):
    project_name = normalize_text(candidate["projectName"])
    customer_name = normalize_text(candidate["customerName"])
    matches = []
    for row in db.execute("SELECT * FROM opportunities ORDER BY id").fetchall():
        existing_name = normalize_text(row["name"])
        existing_customer = normalize_text(row["customer"])
        name_score = 1.0 if project_name and project_name == existing_name else 0.0
        if project_name and existing_name and (project_name in existing_name or existing_name in project_name):
            name_score = max(name_score, 0.8)
        customer_match = int(customer_name and existing_customer and (customer_name in existing_customer or existing_customer in customer_name))
        probability = min(0.98, name_score * 0.7 + customer_match * 0.3)
        if probability >= 0.45:
            matches.append({
                "opportunityId": row["id"],
                "name": row["name"],
                "customer": row["customer"],
                "stage": row["stage"],
                "probability": round(probability, 2),
                "reason": "项目名称相似" + ("，客户名称匹配" if customer_match else ""),
            })
    matches.sort(key=lambda x: x["probability"], reverse=True)
    return {
        "status": "possible_duplicate" if matches else "clear",
        "probability": matches[0]["probability"] if matches else 0,
        "matches": matches[:5],
        "reason": matches[0]["reason"] if matches else "未发现名称或客户的明显冲突",
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        with connect() as db:
            if path == "/api/health":
                return self.send_json({"status": "ok", "database": str(DB_PATH)})
            if path == "/api/stage-definitions":
                rows = db.execute("SELECT * FROM stage_definitions ORDER BY sequence").fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["required"] = json.loads(item.pop("required_fields_json") or "[]")
                    item["nextStage"] = None
                    if item["next_code"]:
                        next_row = db.execute("SELECT code, name FROM stage_definitions WHERE code = ?", (item["next_code"],)).fetchone()
                        item["nextStage"] = dict(next_row) if next_row else None
                    item.pop("next_code", None)
                    result.append(item)
                return self.send_json(result)
            if path == "/api/opportunities":
                rows = db.execute("SELECT * FROM opportunities ORDER BY updated_at DESC, id DESC").fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["tags"] = [x["field_value"] for x in db.execute("SELECT field_value FROM semantic_fields WHERE opportunity_id = ?", (row["id"],)).fetchall()]
                    result.append(decorate_opportunity(db, item))
                return self.send_json(result)
            if path.startswith("/api/opportunities/"):
                parts = path.strip("/").split("/")
                try:
                    oid = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if len(parts) == 4 and parts[3] == "events":
                    events = db.execute("SELECT * FROM business_events WHERE opportunity_id = ? ORDER BY created_at DESC", (oid,)).fetchall()
                    return self.send_json([dict(x) for x in events])
                if len(parts) == 4 and parts[3] == "stage-history":
                    history = db.execute("""SELECT * FROM opportunity_stage_transitions
                        WHERE opportunity_id = ? ORDER BY created_at DESC, id DESC""", (oid,)).fetchall()
                    return self.send_json([dict(x) for x in history])
                item = get_opportunity(db, oid)
                return self.send_json(item or {"error": "opportunity not found"}, 200 if item else 404)
            if path.startswith("/api/discovery/"):
                parts = path.strip("/").split("/")
                try:
                    run_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid discovery run id"}, 400)
                run = db.execute("SELECT * FROM discovery_runs WHERE id = ?", (run_id,)).fetchone()
                if not run:
                    return self.send_json({"error": "discovery run not found"}, 404)
                candidate = db.execute("SELECT * FROM discovery_candidates WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
                evidence = db.execute("SELECT * FROM project_evidence WHERE id = ?", (run["evidence_id"],)).fetchone()
                payload = {"run": dict(run), "candidate": dict(candidate) if candidate else None, "evidence": dict(evidence) if evidence else None}
                if candidate:
                    payload["candidate"]["productLines"] = json.loads(candidate["product_lines"] or "[]")
                    payload["candidate"]["duplicateResult"] = json.loads(candidate["duplicate_result_json"] or "{}")
                return self.send_json(payload)
            if path == "/api/semantic-assets":
                rows = db.execute("SELECT * FROM semantic_assets ORDER BY updated_at DESC, id DESC").fetchall()
                return self.send_json([{**dict(row), "badges": json.loads(row["badges"] or "[]"), "fields": json.loads(row["fields_json"] or "[]")} for row in rows])
            if path == "/api/agents":
                agents = []
                for row in db.execute("SELECT * FROM agents ORDER BY scene, id").fetchall():
                    item = dict(row)
                    item["skills"] = [dict(x) for x in db.execute("SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (row["id"],)).fetchall()]
                    agents.append(item)
                return self.send_json(agents)
            if path.startswith("/api/agents/"):
                agent_id = path.strip("/").split("/")[2]
                row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "agent not found"}, 404)
                item = dict(row)
                item["skills"] = [dict(x) for x in db.execute("SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (agent_id,)).fetchall()]
                return self.send_json(item)
        if path == "/" or path == "/index.html":
            return self.serve_file(OUTPUTS / "index.html", "text/html; charset=utf-8")
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            if path == "/api/discovery/drafts":
                content = str(data.get("contentBase64", ""))
                if not content:
                    return self.send_json({"error": "contentBase64 is required"}, 400)
                if len(content) > 8 * 1024 * 1024:
                    return self.send_json({"error": "file is too large for MVP"}, 413)
                try:
                    raw = base64.b64decode(content, validate=True)
                except (ValueError, TypeError):
                    return self.send_json({"error": "invalid base64 content"}, 400)
                file_name = clean_candidate_text(data.get("fileName"), "evidence.bin")
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name)
                digest = hashlib.sha256(raw).hexdigest()[:16]
                evidence_dir = ROOT / "data" / "evidence"
                evidence_dir.mkdir(exist_ok=True)
                stored_name = f"{digest}_{safe_name}"
                stored_path = evidence_dir / stored_name
                stored_path.write_bytes(raw)
                candidate_data = build_discovery_candidate(data, file_name)
                cur = db.execute("""INSERT INTO project_evidence
                    (source_type, file_name, file_path, mime_type, extracted_text, extracted_json, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                    data.get("sourceType", "现场照片"), file_name, str(stored_path.relative_to(ROOT)),
                    data.get("mimeType") or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
                    candidate_data["extractedText"], json.dumps(candidate_data, ensure_ascii=False),
                    candidate_data["confidence"], now))
                evidence_id = cur.lastrowid
                cur = db.execute("""INSERT INTO discovery_runs
                    (status, input_type, evidence_id, result_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)""", (
                    "draft", data.get("sourceType", "现场照片"), evidence_id,
                    json.dumps({"recognitionMode": candidate_data["recognitionMode"]}, ensure_ascii=False), now, now))
                run_id = cur.lastrowid
                cur = db.execute("""INSERT INTO discovery_candidates
                    (run_id, customer_name, project_name, address, project_type, product_lines, estimated_amount, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    run_id, candidate_data["customerName"], candidate_data["projectName"], candidate_data["address"],
                    candidate_data["projectType"], json.dumps(candidate_data["productLines"], ensure_ascii=False),
                    candidate_data["estimatedAmount"], candidate_data["confidence"], now))
                candidate_id = cur.lastrowid
                return self.send_json({
                    "runId": run_id,
                    "candidateId": candidate_id,
                    "status": "draft",
                    "candidate": candidate_data,
                    "evidence": {"id": evidence_id, "fileName": file_name, "filePath": str(stored_path.relative_to(ROOT))}
                }, 201)
            if path.startswith("/api/discovery/") and path.endswith("/duplicate-check"):
                try:
                    run_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid discovery run id"}, 400)
                candidate = db.execute("SELECT * FROM discovery_candidates WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
                if not candidate:
                    return self.send_json({"error": "discovery candidate not found"}, 404)
                candidate_data = {
                    "projectName": candidate["project_name"],
                    "customerName": candidate["customer_name"],
                }
                result = run_duplicate_check(db, candidate_data)
                db.execute("""UPDATE discovery_candidates SET duplicate_status = ?, duplicate_result_json = ?, review_status = 'needs_review'
                    WHERE id = ?""", (result["status"], json.dumps(result, ensure_ascii=False), candidate["id"]))
                for match in result["matches"]:
                    db.execute("""INSERT INTO duplicate_checks
                        (candidate_id, opportunity_id, project_name_score, customer_match, duplicate_probability, reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                        candidate["id"], match["opportunityId"], match["probability"], int("客户名称匹配" in match["reason"]),
                        match["probability"], match["reason"], now))
                db.execute("UPDATE discovery_runs SET status = 'checked', updated_at = ? WHERE id = ?", (now, run_id))
                return self.send_json({"runId": run_id, **result}, 200)
            if path.startswith("/api/discovery/") and path.endswith("/confirm"):
                try:
                    run_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid discovery run id"}, 400)
                candidate = db.execute("SELECT * FROM discovery_candidates WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
                run = db.execute("SELECT * FROM discovery_runs WHERE id = ?", (run_id,)).fetchone()
                if not candidate or not run:
                    return self.send_json({"error": "discovery candidate not found"}, 404)
                if candidate["duplicate_status"] == "not_checked":
                    return self.send_json({"error": "duplicate check is required before confirmation"}, 409)
                customer_name = clean_candidate_text(data.get("customerName"), candidate["customer_name"])
                project_name = clean_candidate_text(data.get("projectName"), candidate["project_name"])
                address = clean_candidate_text(data.get("address"), candidate["address"])
                customer = db.execute("SELECT * FROM customers WHERE name = ?", (customer_name,)).fetchone()
                if customer:
                    customer_id = customer["id"]
                    db.execute("UPDATE customers SET updated_at = ? WHERE id = ?", (now, customer_id))
                else:
                    cur = db.execute("""INSERT INTO customers (name, created_at, updated_at) VALUES (?, ?, ?)""", (customer_name, now, now))
                    customer_id = cur.lastrowid
                cur = db.execute("""INSERT INTO projects
                    (customer_id, name, project_type, address, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'discovered', ?, ?)""", (
                    customer_id, project_name, candidate["project_type"], address, now, now))
                project_id = cur.lastrowid
                cur = db.execute("""INSERT INTO project_sections
                    (project_id, name, cooperation_mode, created_at, updated_at)
                    VALUES (?, '待补充标段', ?, ?, ?)""", (
                    project_id, data.get("cooperationMode", "待确认"), now, now))
                section_id = cur.lastrowid
                tags = json.loads(candidate["product_lines"] or "[]")
                cur = db.execute("""INSERT INTO opportunities
                    (name, customer, stage, amount, business_type, owner, description, risk, next_action, source_category, created_at, updated_at)
                    VALUES (?, ?, '初步接触', ?, ?, ?, ?, ?, ?, '现场发现', ?, ?)""", (
                    project_name, customer_name, int(candidate["estimated_amount"] or 0),
                    tags[0] if tags else "CRM通用", data.get("owner", "李盛云"),
                    f"由现场证据生成的商机报备草稿，关联项目 #{project_id}、标段 #{section_id}。",
                    "待补充标段、预算和决策链", "完成项目与标段信息确认", now, now))
                opportunity_id = cur.lastrowid
                db.execute(
                    "UPDATE opportunities SET customer_id = ?, project_id = ?, project_section_id = ? WHERE id = ?",
                    (customer_id, project_id, section_id, opportunity_id),
                )
                for tag in tags or ["现场发现"]:
                    db.execute("INSERT INTO semantic_fields (opportunity_id, field_name, field_type, field_value) VALUES (?, ?, ?, ?)", (opportunity_id, "业务标签", "semantic_tag", tag))
                db.execute("UPDATE project_evidence SET project_id = ?, opportunity_id = ?, review_status = 'confirmed' WHERE id = ?", (project_id, opportunity_id, run["evidence_id"]))
                db.execute("UPDATE discovery_candidates SET review_status = 'confirmed' WHERE id = ?", (candidate["id"],))
                db.execute("UPDATE discovery_runs SET status = 'confirmed', updated_at = ? WHERE id = ?", (now, run_id))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (opportunity_id, "discovery_confirmed", f"现场发现已确认，项目 #{project_id}、标段 #{section_id} 已创建", now))
                return self.send_json({"status": "confirmed", "opportunityId": opportunity_id, "customerId": customer_id, "projectId": project_id, "sectionId": section_id}, 201)
            if path == "/api/opportunities":
                required = ["name", "customer", "stage"]
                if any(not str(data.get(k, "")).strip() for k in required):
                    return self.send_json({"error": "name, customer and stage are required"}, 400)
                cur = db.execute("""INSERT INTO opportunities
                    (name, customer, stage, amount, business_type, owner, description, risk, next_action, source_category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                        data["name"], data["customer"], data["stage"], int(data.get("amount", 0) or 0), data.get("businessType", "CRM通用"),
                        data.get("owner", "李盛云"), data.get("description", "刚刚创建，等待补充商机背景与业务需求。"), data.get("risk", "待完善业务信息"), data.get("nextAction", "补充商机语义字段"), data.get("sourceCategory", "内部信息"), now, now))
                oid = cur.lastrowid
                tags = data.get("tags", ["新建对象"])
                for tag in tags:
                    db.execute("INSERT INTO semantic_fields (opportunity_id, field_name, field_type, field_value) VALUES (?, ?, ?, ?)", (oid, "业务标签", "semantic_tag", tag))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, "created", "商机对象已创建，已生成语义字段", now))
                backfill_opportunity_relations(db, now)
                return self.send_json(get_opportunity(db, oid), 201)
            if path.startswith("/api/opportunities/") and path.endswith("/events"):
                try:
                    oid = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if not db.execute("SELECT 1 FROM opportunities WHERE id = ?", (oid,)).fetchone():
                    return self.send_json({"error": "opportunity not found"}, 404)
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, data.get("eventType", "action"), data.get("message", "业务动作已记录"), now))
                db.execute("UPDATE opportunities SET updated_at = ? WHERE id = ?", (now, oid))
                return self.send_json({"status": "recorded"}, 201)
            if path == "/api/semantic-assets":
                required = ["category", "name", "description"]
                if any(not str(data.get(k, "")).strip() for k in required):
                    return self.send_json({"error": "category, name and description are required"}, 400)
                cur = db.execute("""INSERT INTO semantic_assets
                    (category, asset_type, name, description, badges, fields_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                        data["category"], data.get("assetType", data["category"]), data["name"], data["description"],
                        json.dumps(data.get("badges", ["新增资产"]), ensure_ascii=False), json.dumps(data.get("fields", []), ensure_ascii=False), now, now))
                return self.send_json({"id": cur.lastrowid, **data, "badges": data.get("badges", ["新增资产"]), "fields": data.get("fields", [])}, 201)
            if path.startswith("/api/opportunities/") and path.endswith("/stage"):
                try:
                    oid = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                row = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
                if not row:
                    return self.send_json({"error": "opportunity not found"}, 404)
                current = stage_definition(db, row["stage"])
                target_value = data.get("stage") or data.get("stageCode")
                target = stage_definition(db, target_value)
                if not target:
                    return self.send_json({"error": "unknown target stage"}, 400)
                if current and target["name"] == current["name"]:
                    return self.send_json({"status": "unchanged", "stage": current["name"], "missing": []}, 200)
                if current and target["code"] != current["nextCode"]:
                    return self.send_json({
                        "error": "stage transition is not allowed",
                        "fromStage": current["name"],
                        "allowedNextStage": target_name(db, current["nextCode"]),
                    }, 409)
                required = data.get("required", {})
                missing = [field["label"] for field in target["required"] if not str(required.get(field["key"], "")).strip()]
                if missing:
                    return self.send_json({"error": "stage fields required", "missing": missing}, 400)
                old_name = current["name"] if current else stage_name(row["stage"])
                new_stage = target["name"]
                validation = {
                    "required": required,
                    "agent": target["agent_id"],
                    "validated": True,
                }
                db.execute("UPDATE opportunities SET stage = ?, updated_at = ? WHERE id = ?", (new_stage, now, oid))
                db.execute("""INSERT INTO opportunity_stage_transitions
                    (opportunity_id, from_stage, to_stage, required_json, validation_json, actor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    oid, old_name, new_stage, json.dumps(required, ensure_ascii=False),
                    json.dumps(validation, ensure_ascii=False), data.get("actor", "李盛云"), now))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                           (oid, "stage_changed", f"商机阶段由 {old_name} 转换为 {new_stage}，阶段字段已校验", now))
                return self.send_json({
                    "status": "converted",
                    "stage": new_stage,
                    "stageCode": target["code"],
                    "missing": [],
                    "nextStage": target_name(db, target["nextCode"]),
                    "validation": validation,
                }, 200)
            if path.startswith("/api/agents/") and path.endswith("/run"):
                agent_id = path.strip("/").split("/")[2]
                if not db.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
                    return self.send_json({"error": "agent not found"}, 404)
                opportunity_id = data.get("opportunityId")
                result = data.get("result") or "已完成语义分析，生成待确认的客户开发建议。"
                cur = db.execute("INSERT INTO agent_runs (agent_id, opportunity_id, input_json, result, created_at) VALUES (?, ?, ?, ?, ?)", (agent_id, opportunity_id, json.dumps(data, ensure_ascii=False), result, now))
                if opportunity_id:
                    db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (opportunity_id, "agent_run", f"{agent_id} 已运行：{result}", now))
                return self.send_json({"id": cur.lastrowid, "agentId": agent_id, "result": result, "status": "completed"}, 201)
        return self.send_json({"error": "not found"}, 404)

    def serve_file(self, path, content_type):
        if not path.exists():
            return self.send_json({"error": "file not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_db()

    import os
    port = int(os.environ.get("PORT", 8765))

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        Handler
    )

    print(f"CRM backend running on port {port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
