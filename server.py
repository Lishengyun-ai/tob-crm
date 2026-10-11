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

SEED_SALES_ORGANIZATION = {
    "code": "S300",
    "name": "立邦工程材料（广州）有限公司",
    "units": [
        {
            "code": "343",
            "name": "山东商业与住宅客户业务部（工程）",
            "office_code": "3068",
            "office_name": "山东商业与住宅客户业务部（工程）",
            "group_code": "343",
            "group_name": "山东商业与住宅客户业务部（工程）",
            "distribution_channel_code": "P9",
            "distribution_channel_name": "P9",
            "division_code": "14",
            "division_name": "14",
        }
    ],
}

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
        CREATE TABLE IF NOT EXISTS sales_organizations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_organization_units (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sales_organization_id INTEGER NOT NULL,
          code TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(sales_organization_id, code),
          FOREIGN KEY(sales_organization_id) REFERENCES sales_organizations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS distribution_channels (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS divisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sales_offices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sales_organization_unit_id INTEGER NOT NULL,
          code TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(sales_organization_unit_id, code),
          FOREIGN KEY(sales_organization_unit_id) REFERENCES sales_organization_units(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sales_groups (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sales_office_id INTEGER NOT NULL,
          code TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(sales_office_id, code),
          FOREIGN KEY(sales_office_id) REFERENCES sales_offices(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_organizations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          parent_id INTEGER,
          code TEXT NOT NULL DEFAULT '',
          name TEXT NOT NULL,
          organization_type TEXT NOT NULL DEFAULT '集团总部',
          level INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(customer_id, code),
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(parent_id) REFERENCES customer_organizations(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS sales_assignments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          sales_organization_id INTEGER NOT NULL,
          sales_organization_unit_id INTEGER,
          sales_office_id INTEGER,
          sales_group_id INTEGER,
          distribution_channel_id INTEGER,
          division_id INTEGER,
          assignment_type TEXT NOT NULL DEFAULT 'default',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(sales_organization_id) REFERENCES sales_organizations(id),
          FOREIGN KEY(sales_organization_unit_id) REFERENCES sales_organization_units(id),
          FOREIGN KEY(sales_office_id) REFERENCES sales_offices(id),
          FOREIGN KEY(sales_group_id) REFERENCES sales_groups(id),
          FOREIGN KEY(distribution_channel_id) REFERENCES distribution_channels(id),
          FOREIGN KEY(division_id) REFERENCES divisions(id)
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
        CREATE TABLE IF NOT EXISTS project_parties (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL,
          customer_organization_id INTEGER,
          person_id INTEGER,
          party_type TEXT NOT NULL DEFAULT '其他',
          party_name TEXT NOT NULL,
          party_code TEXT NOT NULL DEFAULT '',
          is_primary INTEGER NOT NULL DEFAULT 0,
          source_type TEXT NOT NULL DEFAULT 'manual',
          confidence REAL NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'active',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
          FOREIGN KEY(customer_organization_id) REFERENCES customer_organizations(id) ON DELETE SET NULL,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS persons (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          organization TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          person_type TEXT NOT NULL DEFAULT '关键人',
          phone TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_persons (
          customer_id INTEGER NOT NULL,
          person_id INTEGER NOT NULL,
          role TEXT NOT NULL DEFAULT '联系人',
          is_primary INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          PRIMARY KEY(customer_id, person_id, role),
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS project_persons (
          project_id INTEGER NOT NULL,
          person_id INTEGER NOT NULL,
          role TEXT NOT NULL DEFAULT '项目联系人',
          is_primary INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          PRIMARY KEY(project_id, person_id, role),
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS opportunity_persons (
          opportunity_id INTEGER NOT NULL,
          person_id INTEGER NOT NULL,
          role TEXT NOT NULL DEFAULT '商机联系人',
          influence_level TEXT NOT NULL DEFAULT '未知',
          relationship_status TEXT NOT NULL DEFAULT '待建立',
          is_primary INTEGER NOT NULL DEFAULT 0,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(opportunity_id, person_id, role),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
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
        CREATE TABLE IF NOT EXISTS actions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          action_type TEXT NOT NULL DEFAULT 'follow_up',
          status TEXT NOT NULL DEFAULT 'pending',
          priority TEXT NOT NULL DEFAULT 'medium',
          assignee TEXT NOT NULL DEFAULT '',
          due_at TEXT,
          opportunity_id INTEGER,
          project_id INTEGER,
          customer_id INTEGER,
          customer_organization_id INTEGER,
          person_id INTEGER,
          stage_code TEXT,
          stage_name TEXT,
          source_type TEXT NOT NULL DEFAULT 'manual',
          source_id TEXT NOT NULL DEFAULT '',
          source_agent_id TEXT,
          source_agent_run_id INTEGER,
          created_by TEXT NOT NULL DEFAULT '李盛云',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT,
          dedupe_key TEXT UNIQUE,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
          FOREIGN KEY(customer_organization_id) REFERENCES customer_organizations(id) ON DELETE SET NULL,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
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
        for table, column, definition in [
            ("projects", "customer_organization_id", "INTEGER"),
            ("persons", "customer_organization_id", "INTEGER"),
            ("opportunities", "customer_organization_id", "INTEGER"),
            ("opportunities", "sales_assignment_id", "INTEGER"),
        ]:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
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
        seed_organization_ontology(db, now)
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_customer_id ON opportunities(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_project_id ON opportunities(project_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_customer_org_id ON opportunities(customer_organization_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_sales_assignment_id ON opportunities(sales_assignment_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_projects_customer_org_id ON projects(customer_organization_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_persons_customer_org_id ON persons(customer_organization_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_project_parties_project_id ON project_parties(project_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_project_parties_org_id ON project_parties(customer_organization_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_actions_opportunity_id ON actions(opportunity_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_actions_assignee ON actions(assignee)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunities_project_section_id ON opportunities(project_section_id) WHERE project_section_id IS NOT NULL")
        agent_count = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if agent_count == 0:
            for agent_id, name, scene, description, skills, assets in SEED_AGENTS:
                db.execute("INSERT INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (agent_id, name, scene, description, now, now))
                for skill in skills.split(','):
                    db.execute("INSERT INTO agent_skills (agent_id, name, description, linked_assets) VALUES (?, ?, ?, ?)", (agent_id, skill, f"{skill}：读取客户、商机与涂料行业语义后生成可解释结果。", assets))
        seed_initial_actions(db, now)

def seed_organization_ontology(db, now):
    """初始化我方销售组织，并为现有客户建立集团根节点。"""
    sales = SEED_SALES_ORGANIZATION
    sales_org = db.execute("SELECT * FROM sales_organizations WHERE code = ?", (sales["code"],)).fetchone()
    if sales_org:
        sales_org_id = sales_org["id"]
    else:
        cur = db.execute(
            "INSERT INTO sales_organizations (code, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sales["code"], sales["name"], now, now),
        )
        sales_org_id = cur.lastrowid

    default_assignment_id = None
    for unit in sales["units"]:
        row = db.execute(
            "SELECT * FROM sales_organization_units WHERE sales_organization_id = ? AND code = ?",
            (sales_org_id, unit["code"]),
        ).fetchone()
        if row:
            unit_id = row["id"]
        else:
            cur = db.execute(
                """INSERT INTO sales_organization_units
                   (sales_organization_id, code, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (sales_org_id, unit["code"], unit["name"], now, now),
            )
            unit_id = cur.lastrowid
        channel = db.execute(
            "SELECT * FROM distribution_channels WHERE code = ?", (unit["distribution_channel_code"],)
        ).fetchone()
        if channel:
            channel_id = channel["id"]
        else:
            cur = db.execute(
                "INSERT INTO distribution_channels (code, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (unit["distribution_channel_code"], unit["distribution_channel_name"], now, now),
            )
            channel_id = cur.lastrowid
        division = db.execute("SELECT * FROM divisions WHERE code = ?", (unit["division_code"],)).fetchone()
        if division:
            division_id = division["id"]
        else:
            cur = db.execute(
                "INSERT INTO divisions (code, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (unit["division_code"], unit["division_name"], now, now),
            )
            division_id = cur.lastrowid
        office = db.execute(
            "SELECT * FROM sales_offices WHERE sales_organization_unit_id = ? AND code = ?",
            (unit_id, unit["office_code"]),
        ).fetchone()
        if office:
            office_id = office["id"]
        else:
            cur = db.execute(
                """INSERT INTO sales_offices
                   (sales_organization_unit_id, code, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (unit_id, unit["office_code"], unit["office_name"], now, now),
            )
            office_id = cur.lastrowid
        group = db.execute(
            "SELECT * FROM sales_groups WHERE sales_office_id = ? AND code = ?",
            (office_id, unit["group_code"]),
        ).fetchone()
        if group:
            group_id = group["id"]
        else:
            cur = db.execute(
                """INSERT INTO sales_groups
                   (sales_office_id, code, name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (office_id, unit["group_code"], unit["group_name"], now, now),
            )
            group_id = cur.lastrowid
        assignment = db.execute(
            """SELECT * FROM sales_assignments
               WHERE sales_organization_id = ? AND sales_organization_unit_id = ?
                 AND sales_office_id = ? AND sales_group_id = ?
                 AND distribution_channel_id = ? AND division_id = ?""",
            (sales_org_id, unit_id, office_id, group_id, channel_id, division_id),
        ).fetchone()
        if assignment:
            default_assignment_id = assignment["id"]
        else:
            cur = db.execute(
                """INSERT INTO sales_assignments
                   (sales_organization_id, sales_organization_unit_id, sales_office_id,
                    sales_group_id, distribution_channel_id, division_id,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sales_org_id, unit_id, office_id, group_id, channel_id, division_id, now, now),
            )
            default_assignment_id = cur.lastrowid

    for customer in db.execute("SELECT * FROM customers ORDER BY id").fetchall():
        root = db.execute(
            """SELECT * FROM customer_organizations
               WHERE customer_id = ? AND parent_id IS NULL ORDER BY id LIMIT 1""",
            (customer["id"],),
        ).fetchone()
        if not root:
            db.execute(
                """INSERT INTO customer_organizations
                   (customer_id, code, name, organization_type, level, created_at, updated_at)
                   VALUES (?, ?, ?, '集团总部', 0, ?, ?)""",
                (customer["id"], f"CUST-{customer['id']}", customer["name"], now, now),
            )
            root = db.execute(
                """SELECT * FROM customer_organizations
                   WHERE customer_id = ? AND parent_id IS NULL ORDER BY id DESC LIMIT 1""",
                (customer["id"],),
            ).fetchone()
        db.execute(
            "UPDATE projects SET customer_organization_id = COALESCE(customer_organization_id, ?) WHERE customer_id = ?",
            (root["id"], customer["id"]),
        )
        db.execute(
            "UPDATE persons SET customer_organization_id = COALESCE(customer_organization_id, ?) WHERE id IN (SELECT person_id FROM customer_persons WHERE customer_id = ?)",
            (root["id"], customer["id"]),
        )
        db.execute(
            """UPDATE opportunities
               SET customer_organization_id = COALESCE(customer_organization_id, ?),
                   sales_assignment_id = COALESCE(sales_assignment_id, ?)
               WHERE customer_id = ?""",
            (root["id"], default_assignment_id, customer["id"]),
        )

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
                """SELECT ps.* FROM project_sections ps
                   WHERE ps.project_id = ?
                     AND NOT EXISTS (
                       SELECT 1 FROM opportunities o
                       WHERE o.project_section_id = ps.id AND o.id <> ?
                     )
                   ORDER BY ps.id LIMIT 1""",
                (project_id, row["id"]),
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
    customer_org = db.execute(
        """SELECT id, customer_id, parent_id, code, name, organization_type, level, status
           FROM customer_organizations WHERE id = ?""",
        (item.get("customer_organization_id"),),
    ).fetchone() if item.get("customer_organization_id") else None
    item["customerOrganizationId"] = item.get("customer_organization_id")
    item["customerOrganization"] = dict(customer_org) if customer_org else None
    assignment = db.execute(
        """SELECT sa.id, so.code AS sales_organization_code, so.name AS sales_organization_name,
                  sou.code AS unit_code, sou.name AS unit_name,
                  sof.code AS office_code, sof.name AS office_name,
                  sg.code AS group_code, sg.name AS group_name,
                  dc.code AS channel_code, dc.name AS channel_name,
                  d.code AS division_code, d.name AS division_name
           FROM sales_assignments sa
           JOIN sales_organizations so ON so.id = sa.sales_organization_id
           LEFT JOIN sales_organization_units sou ON sou.id = sa.sales_organization_unit_id
           LEFT JOIN sales_offices sof ON sof.id = sa.sales_office_id
           LEFT JOIN sales_groups sg ON sg.id = sa.sales_group_id
           LEFT JOIN distribution_channels dc ON dc.id = sa.distribution_channel_id
           LEFT JOIN divisions d ON d.id = sa.division_id
           WHERE sa.id = ?""",
        (item.get("sales_assignment_id"),),
    ).fetchone() if item.get("sales_assignment_id") else None
    item["salesAssignmentId"] = item.get("sales_assignment_id")
    item["salesAssignment"] = dict(assignment) if assignment else None
    return item

def get_opportunity_people(db, opportunity_id):
    rows = db.execute(
        """SELECT op.role, op.influence_level, op.relationship_status, op.is_primary,
                  op.notes AS relationship_notes, op.created_at AS linked_at,
                  p.id, p.name, p.organization, p.title, p.person_type,
                  p.customer_organization_id,
                  p.phone, p.email, p.notes, p.status
           FROM opportunity_persons op
           JOIN persons p ON p.id = op.person_id
           WHERE op.opportunity_id = ?
           ORDER BY op.is_primary DESC, op.updated_at DESC, p.id""",
        (opportunity_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def get_customer_people(db, customer_id):
    rows = db.execute(
        """SELECT cp.role, cp.is_primary, cp.created_at AS linked_at,
                  p.id, p.name, p.organization, p.title, p.person_type,
                  p.customer_organization_id,
                  p.phone, p.email, p.notes, p.status
           FROM customer_persons cp
           JOIN persons p ON p.id = cp.person_id
           WHERE cp.customer_id = ?
           ORDER BY cp.is_primary DESC, p.id""",
        (customer_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def get_project_parties(db, project_id):
    rows = db.execute(
        """SELECT pp.*, co.name AS customer_organization_name,
                  p.name AS person_name, p.title AS person_title
           FROM project_parties pp
           LEFT JOIN customer_organizations co ON co.id = pp.customer_organization_id
           LEFT JOIN persons p ON p.id = pp.person_id
           WHERE pp.project_id = ?
           ORDER BY pp.is_primary DESC, pp.party_type, pp.id""",
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def serialize_action(row):
    item = dict(row)
    item["isCompleted"] = item.get("status") == "completed"
    item["isOverdue"] = bool(
        item.get("due_at")
        and item.get("status") not in {"completed", "cancelled"}
        and item["due_at"] < datetime.now(timezone.utc).isoformat()[:10]
    )
    return item

def get_actions(db, opportunity_id=None, project_id=None, status=None):
    clauses = []
    values = []
    if opportunity_id is not None:
        clauses.append("a.opportunity_id = ?")
        values.append(opportunity_id)
    if project_id is not None:
        clauses.append("a.project_id = ?")
        values.append(project_id)
    if status:
        clauses.append("a.status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"""SELECT a.*, ag.name AS source_agent_name
            FROM actions a
            LEFT JOIN agents ag ON ag.id = a.source_agent_id
            {where}
            ORDER BY CASE a.status
                       WHEN 'in_progress' THEN 1
                       WHEN 'pending' THEN 2
                       WHEN 'overdue' THEN 3
                       WHEN 'completed' THEN 4
                       ELSE 5
                     END,
                     CASE WHEN a.due_at IS NULL THEN 1 ELSE 0 END,
                     a.due_at, a.updated_at DESC, a.id DESC""",
        tuple(values),
    ).fetchall()
    return [serialize_action(row) for row in rows]

def create_action_record(
    db,
    *,
    title,
    description="",
    action_type="follow_up",
    status="pending",
    priority="medium",
    assignee="",
    due_at=None,
    opportunity_id=None,
    project_id=None,
    customer_id=None,
    customer_organization_id=None,
    person_id=None,
    stage_code=None,
    stage_name=None,
    source_type="manual",
    source_id="",
    source_agent_id=None,
    source_agent_run_id=None,
    created_by="李盛云",
    dedupe_key=None,
    now=None,
):
    now = now or datetime.now(timezone.utc).isoformat()
    opportunity = None
    if opportunity_id is not None:
        opportunity = db.execute(
            "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
        if not opportunity:
            raise ValueError("opportunity not found")
        project_id = project_id or opportunity["project_id"]
        customer_id = customer_id or opportunity["customer_id"]
        customer_organization_id = customer_organization_id or opportunity["customer_organization_id"]
        assignee = assignee or opportunity["owner"]
    if project_id is not None and not db.execute(
        "SELECT 1 FROM projects WHERE id = ?", (project_id,)
    ).fetchone():
        raise ValueError("project not found")
    if customer_id is not None and not db.execute(
        "SELECT 1 FROM customers WHERE id = ?", (customer_id,)
    ).fetchone():
        raise ValueError("customer not found")
    if customer_organization_id is not None and not db.execute(
        "SELECT 1 FROM customer_organizations WHERE id = ?", (customer_organization_id,)
    ).fetchone():
        raise ValueError("customer organization not found")
    if source_agent_id is not None and not db.execute(
        "SELECT 1 FROM agents WHERE id = ?", (source_agent_id,)
    ).fetchone():
        raise ValueError("agent not found")
    completed_at = now if status == "completed" else None
    db.execute(
        """INSERT OR IGNORE INTO actions
           (title, description, action_type, status, priority, assignee, due_at,
            opportunity_id, project_id, customer_id, customer_organization_id, person_id,
            stage_code, stage_name, source_type, source_id, source_agent_id,
            source_agent_run_id, created_by, created_at, updated_at, completed_at, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(title).strip() or "未命名行动",
            str(description).strip(),
            str(action_type).strip() or "follow_up",
            str(status).strip() or "pending",
            str(priority).strip() or "medium",
            str(assignee).strip(),
            str(due_at).strip() if due_at else None,
            opportunity_id,
            project_id,
            customer_id,
            customer_organization_id,
            person_id,
            stage_code,
            stage_name,
            str(source_type).strip() or "manual",
            str(source_id).strip(),
            source_agent_id,
            source_agent_run_id,
            str(created_by).strip() or "李盛云",
            now,
            now,
            completed_at,
            dedupe_key,
        ),
    )
    if dedupe_key:
        row = db.execute("SELECT * FROM actions WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
    else:
        row = db.execute("SELECT * FROM actions WHERE rowid = last_insert_rowid()").fetchone()
    return serialize_action(row) if row else None

def create_stage_actions(db, opportunity, current_stage, source_type, source_id, now):
    next_code = current_stage.get("nextCode")
    if not next_code:
        return []
    next_stage = stage_definition(db, next_code)
    if not next_stage:
        return []
    required = next_stage.get("required") or []
    actions = []
    fields = required or [{"key": "stageGate", "label": f"{next_stage['name']}阶段准入条件"}]
    for field in fields:
        is_gate = field["key"] == "stageGate"
        actions.append(create_action_record(
            db,
            title=f"{'完成' if is_gate else '填写'}{next_stage['name']}：{field['label']}",
            description=(
                f"推进商机到“{next_stage['name']}”前，需要完成阶段准入条件。"
                if is_gate else
                f"为推进商机到“{next_stage['name']}”，补齐字段“{field['label']}”。"
            ),
            action_type="stage_gate" if is_gate else "stage_field",
            priority="high",
            assignee=opportunity["owner"],
            opportunity_id=opportunity["id"],
            stage_code=next_stage["code"],
            stage_name=next_stage["name"],
            source_type=source_type,
            source_id=str(source_id),
            created_by=opportunity["owner"],
            dedupe_key=f"{source_type}:{source_id}:{opportunity['id']}:{next_stage['code']}:{field['key']}",
            now=now,
        ))
    return [item for item in actions if item]

def complete_stage_actions(db, opportunity_id, stage_code, now):
    db.execute(
        """UPDATE actions
           SET status = 'completed', completed_at = ?, updated_at = ?
           WHERE opportunity_id = ? AND stage_code = ?
             AND action_type IN ('stage_gate', 'stage_field')
             AND status IN ('pending', 'in_progress')""",
        (now, now, opportunity_id, stage_code),
    )

def seed_initial_actions(db, now):
    for opportunity in db.execute("SELECT * FROM opportunities ORDER BY id").fetchall():
        current_stage = stage_definition(db, opportunity["stage"])
        if current_stage:
            create_stage_actions(
                db,
                opportunity,
                current_stage,
                "stage_plan",
                "bootstrap",
                now,
            )

def get_sales_organization_ontology(db):
    organizations = []
    for org in db.execute("SELECT * FROM sales_organizations ORDER BY code").fetchall():
        item = dict(org)
        item["units"] = []
        for unit in db.execute(
            "SELECT * FROM sales_organization_units WHERE sales_organization_id = ? ORDER BY code",
            (org["id"],),
        ).fetchall():
            unit_item = dict(unit)
            unit_item["offices"] = []
            for office in db.execute(
                "SELECT * FROM sales_offices WHERE sales_organization_unit_id = ? ORDER BY code",
                (unit["id"],),
            ).fetchall():
                office_item = dict(office)
                office_item["groups"] = [
                    dict(row) for row in db.execute(
                        "SELECT * FROM sales_groups WHERE sales_office_id = ? ORDER BY code",
                        (office["id"],),
                    ).fetchall()
                ]
                unit_item["offices"].append(office_item)
            item["units"].append(unit_item)
        organizations.append(item)
    return organizations

def get_customer_organization_tree(db, customer_id):
    rows = [
        dict(row) for row in db.execute(
            """SELECT co.*, c.name AS customer_name
               FROM customer_organizations co
               JOIN customers c ON c.id = co.customer_id
               WHERE co.customer_id = ?
               ORDER BY co.level, co.id""",
            (customer_id,),
        ).fetchall()
    ]
    by_id = {row["id"]: {**row, "children": []} for row in rows}
    roots = []
    for row in by_id.values():
        if row["parent_id"] and row["parent_id"] in by_id:
            by_id[row["parent_id"]]["children"].append(row)
        else:
            roots.append(row)
    return roots

def get_customer_organization_node(db, organization_id):
    row = db.execute(
        """SELECT co.*, c.name AS customer_name
           FROM customer_organizations co
           JOIN customers c ON c.id = co.customer_id
           WHERE co.id = ?""",
        (organization_id,),
    ).fetchone()
    return dict(row) if row else None

def get_customer_organization_options(db, customer_id):
    rows = db.execute(
        """SELECT id, parent_id, code, name, organization_type, level, status
           FROM customer_organizations
           WHERE customer_id = ?
           ORDER BY level, name, id""",
        (customer_id,),
    ).fetchall()
    return [dict(row) for row in rows]

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
    item["keyPersons"] = get_opportunity_people(db, oid)
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
    item["actions"] = get_actions(db, opportunity_id=oid)
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
            if path == "/api/ontology/sales-organizations":
                return self.send_json(get_sales_organization_ontology(db))
            if path == "/api/ontology/customer-organizations":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                customer_id = params.get("customerId")
                if customer_id:
                    try:
                        customer_id = int(customer_id)
                    except ValueError:
                        return self.send_json({"error": "invalid customer id"}, 400)
                    if not db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
                        return self.send_json({"error": "customer not found"}, 404)
                    return self.send_json(get_customer_organization_tree(db, customer_id))
                rows = db.execute(
                    """SELECT co.*, c.name AS customer_name
                       FROM customer_organizations co
                       JOIN customers c ON c.id = co.customer_id
                       ORDER BY c.name, co.level, co.id"""
                ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path == "/api/customers":
                rows = db.execute(
                    "SELECT id, name, customer_type, industry, status FROM customers ORDER BY name, id"
                ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path == "/api/projects":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                customer_id = params.get("customerId")
                if customer_id:
                    try:
                        customer_id = int(customer_id)
                    except ValueError:
                        return self.send_json({"error": "invalid customer id"}, 400)
                    rows = db.execute(
                        """SELECT p.id, p.customer_id, p.customer_organization_id, p.name,
                                  p.project_type, p.address, p.status,
                                  co.name AS customer_organization_name
                           FROM projects p
                           LEFT JOIN customer_organizations co ON co.id = p.customer_organization_id
                           WHERE p.customer_id = ?
                           ORDER BY p.updated_at DESC, p.id DESC""",
                        (customer_id,),
                    ).fetchall()
                else:
                    rows = db.execute(
                        """SELECT p.id, p.customer_id, p.customer_organization_id, p.name,
                                  p.project_type, p.address, p.status,
                                  co.name AS customer_organization_name
                           FROM projects p
                           LEFT JOIN customer_organizations co ON co.id = p.customer_organization_id
                           ORDER BY p.updated_at DESC, p.id DESC"""
                    ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path == "/api/actions":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                try:
                    opportunity_id = int(params["opportunityId"]) if params.get("opportunityId") else None
                    project_id = int(params["projectId"]) if params.get("projectId") else None
                except ValueError:
                    return self.send_json({"error": "invalid action filter"}, 400)
                return self.send_json(get_actions(db, opportunity_id, project_id, params.get("status")))
            if path.startswith("/api/projects/") and path.endswith("/parties"):
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project id"}, 400)
                if not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                    return self.send_json({"error": "project not found"}, 404)
                return self.send_json(get_project_parties(db, project_id))
            if path == "/api/ontology/sales-assignments":
                rows = db.execute(
                    """SELECT sa.*,
                              so.code AS sales_organization_code, so.name AS sales_organization_name,
                              sou.code AS unit_code, sou.name AS unit_name,
                              sof.code AS office_code, sof.name AS office_name,
                              sg.code AS group_code, sg.name AS group_name,
                              dc.code AS channel_code, dc.name AS channel_name,
                              d.code AS division_code, d.name AS division_name
                       FROM sales_assignments sa
                       JOIN sales_organizations so ON so.id = sa.sales_organization_id
                       LEFT JOIN sales_organization_units sou ON sou.id = sa.sales_organization_unit_id
                       LEFT JOIN sales_offices sof ON sof.id = sa.sales_office_id
                       LEFT JOIN sales_groups sg ON sg.id = sa.sales_group_id
                       LEFT JOIN distribution_channels dc ON dc.id = sa.distribution_channel_id
                       LEFT JOIN divisions d ON d.id = sa.division_id
                       ORDER BY sa.id"""
                ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path == "/api/opportunities":
                rows = db.execute("SELECT * FROM opportunities ORDER BY updated_at DESC, id DESC").fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["tags"] = [x["field_value"] for x in db.execute("SELECT field_value FROM semantic_fields WHERE opportunity_id = ?", (row["id"],)).fetchall()]
                    result.append(decorate_opportunity(db, item))
                return self.send_json(result)
            if path == "/api/people":
                rows = db.execute("SELECT * FROM persons ORDER BY updated_at DESC, id DESC").fetchall()
                return self.send_json([dict(row) for row in rows])
            if path.startswith("/api/customers/") and path.endswith("/people"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if not db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
                    return self.send_json({"error": "customer not found"}, 404)
                return self.send_json(get_customer_people(db, customer_id))
            if path.startswith("/api/opportunities/"):
                parts = path.strip("/").split("/")
                try:
                    oid = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if len(parts) == 4 and parts[3] == "events":
                    events = db.execute("SELECT * FROM business_events WHERE opportunity_id = ? ORDER BY created_at DESC", (oid,)).fetchall()
                    return self.send_json([dict(x) for x in events])
                if len(parts) == 4 and parts[3] == "actions":
                    if not db.execute("SELECT 1 FROM opportunities WHERE id = ?", (oid,)).fetchone():
                        return self.send_json({"error": "opportunity not found"}, 404)
                    return self.send_json(get_actions(db, opportunity_id=oid))
                if len(parts) == 4 and parts[3] == "stage-history":
                    history = db.execute("""SELECT * FROM opportunity_stage_transitions
                        WHERE opportunity_id = ? ORDER BY created_at DESC, id DESC""", (oid,)).fetchall()
                    return self.send_json([dict(x) for x in history])
                if len(parts) == 4 and parts[3] == "people":
                    if not db.execute("SELECT 1 FROM opportunities WHERE id = ?", (oid,)).fetchone():
                        return self.send_json({"error": "opportunity not found"}, 404)
                    return self.send_json(get_opportunity_people(db, oid))
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

    def do_PUT(self):
        path = urlparse(self.path).path
        data = self.read_json()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            if path.startswith("/api/actions/"):
                try:
                    action_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid action id"}, 400)
                action = db.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
                if not action:
                    return self.send_json({"error": "action not found"}, 404)
                status = str(data.get("status", action["status"])).strip() or action["status"]
                if status not in {"pending", "in_progress", "completed", "cancelled"}:
                    return self.send_json({"error": "invalid action status"}, 400)
                title = str(data.get("title", action["title"])).strip()
                if not title:
                    return self.send_json({"error": "title is required"}, 400)
                completed_at = now if status == "completed" else (
                    action["completed_at"] if status == "completed" else None
                )
                db.execute(
                    """UPDATE actions
                       SET title = ?, description = ?, status = ?, priority = ?,
                           assignee = ?, due_at = ?, updated_at = ?, completed_at = ?
                       WHERE id = ?""",
                    (
                        title,
                        str(data.get("description", action["description"])).strip(),
                        status,
                        str(data.get("priority", action["priority"])).strip() or "medium",
                        str(data.get("assignee", action["assignee"])).strip(),
                        str(data.get("dueAt", action["due_at"])).strip() if data.get("dueAt", action["due_at"]) else None,
                        now,
                        completed_at,
                        action_id,
                    ),
                )
                row = db.execute(
                    """SELECT a.*, ag.name AS source_agent_name
                       FROM actions a LEFT JOIN agents ag ON ag.id = a.source_agent_id
                       WHERE a.id = ?""",
                    (action_id,),
                ).fetchone()
                if action["opportunity_id"]:
                    db.execute(
                        "INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                        (action["opportunity_id"], "action_updated", f"行动任务“{title}”状态更新为 {status}", now),
                    )
                return self.send_json(serialize_action(row))
            if path.startswith("/api/projects/") and "/parties/" in path:
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[2])
                    party_id = int(parts[4])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project party id"}, 400)
                party = db.execute(
                    "SELECT * FROM project_parties WHERE id = ? AND project_id = ?",
                    (party_id, project_id),
                ).fetchone()
                if not party:
                    return self.send_json({"error": "project party not found"}, 404)
                party_name = str(data.get("partyName", party["party_name"])).strip()
                party_type = str(data.get("partyType", party["party_type"])).strip()
                if not party_name or not party_type:
                    return self.send_json({"error": "partyName and partyType are required"}, 400)
                db.execute(
                    """UPDATE project_parties
                       SET party_name = ?, party_type = ?, party_code = ?,
                           is_primary = ?, notes = ?, updated_at = ?
                       WHERE id = ? AND project_id = ?""",
                    (
                        party_name,
                        party_type,
                        str(data.get("partyCode", party["party_code"])).strip(),
                        int(bool(data.get("isPrimary", party["is_primary"]))),
                        str(data.get("notes", party["notes"])).strip(),
                        now,
                        party_id,
                        project_id,
                    ),
                )
                return self.send_json(get_project_parties(db, project_id))
            if path.startswith("/api/ontology/customer-organizations/"):
                try:
                    organization_id = int(path.strip("/").split("/")[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid organization id"}, 400)
                node = db.execute(
                    "SELECT * FROM customer_organizations WHERE id = ?", (organization_id,)
                ).fetchone()
                if not node:
                    return self.send_json({"error": "customer organization not found"}, 404)
                name = str(data.get("name", node["name"])).strip()
                organization_type = str(
                    data.get("organizationType", node["organization_type"])
                ).strip()
                status = str(data.get("status", node["status"])).strip()
                if not name:
                    return self.send_json({"error": "name is required"}, 400)
                if not organization_type:
                    return self.send_json({"error": "organizationType is required"}, 400)
                db.execute(
                    """UPDATE customer_organizations
                       SET name = ?, organization_type = ?, status = ?, updated_at = ?
                       WHERE id = ?""",
                    (name, organization_type, status or "active", now, organization_id),
                )
                return self.send_json(get_customer_organization_node(db, organization_id))
        return self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        with connect() as db:
            if path.startswith("/api/projects/") and "/parties/" in path:
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[2])
                    party_id = int(parts[4])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project party id"}, 400)
                cur = db.execute(
                    "DELETE FROM project_parties WHERE id = ? AND project_id = ?",
                    (party_id, project_id),
                )
                if not cur.rowcount:
                    return self.send_json({"error": "project party not found"}, 404)
                return self.send_json({"status": "deleted", "projectId": project_id, "partyId": party_id})
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            if path == "/api/actions":
                title = str(data.get("title", "")).strip()
                if not title:
                    return self.send_json({"error": "title is required"}, 400)
                try:
                    opportunity_id = int(data["opportunityId"]) if data.get("opportunityId") else None
                    project_id = int(data["projectId"]) if data.get("projectId") else None
                    customer_id = int(data["customerId"]) if data.get("customerId") else None
                    customer_organization_id = (
                        int(data["customerOrganizationId"])
                        if data.get("customerOrganizationId") else None
                    )
                    person_id = int(data["personId"]) if data.get("personId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid action relation id"}, 400)
                try:
                    action = create_action_record(
                        db,
                        title=title,
                        description=data.get("description", ""),
                        action_type=data.get("actionType", "follow_up"),
                        status=data.get("status", "pending"),
                        priority=data.get("priority", "medium"),
                        assignee=data.get("assignee", ""),
                        due_at=data.get("dueAt"),
                        opportunity_id=opportunity_id,
                        project_id=project_id,
                        customer_id=customer_id,
                        customer_organization_id=customer_organization_id,
                        person_id=person_id,
                        stage_code=data.get("stageCode"),
                        stage_name=data.get("stageName"),
                        source_type=data.get("sourceType", "manual"),
                        source_id=data.get("sourceId", ""),
                        created_by=data.get("createdBy", "李盛云"),
                        now=now,
                    )
                except ValueError as error:
                    return self.send_json({"error": str(error)}, 404)
                if opportunity_id:
                    db.execute(
                        "INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                        (opportunity_id, "action_created", f"已创建行动任务“{title}”", now),
                    )
                return self.send_json(action, 201)
            if path.startswith("/api/projects/") and path.endswith("/parties"):
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project id"}, 400)
                project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                if not project:
                    return self.send_json({"error": "project not found"}, 404)
                party_name = str(data.get("partyName", "")).strip()
                party_type = str(data.get("partyType", "其他")).strip() or "其他"
                if not party_name:
                    return self.send_json({"error": "partyName is required"}, 400)
                organization_id = data.get("customerOrganizationId")
                person_id = data.get("personId")
                if organization_id:
                    organization = db.execute(
                        "SELECT * FROM customer_organizations WHERE id = ? AND customer_id = ?",
                        (organization_id, project["customer_id"]),
                    ).fetchone()
                    if not organization:
                        return self.send_json({"error": "organization does not belong to project customer"}, 409)
                if person_id:
                    person = db.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
                    linked = db.execute(
                        "SELECT 1 FROM customer_persons WHERE person_id = ? AND customer_id = ?",
                        (person_id, project["customer_id"]),
                    ).fetchone()
                    if not person or not linked:
                        return self.send_json({"error": "person does not belong to project customer"}, 409)
                cur = db.execute(
                    """INSERT INTO project_parties
                       (project_id, customer_organization_id, person_id, party_type, party_name,
                        party_code, is_primary, source_type, confidence, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id,
                        organization_id,
                        person_id,
                        party_type,
                        party_name,
                        str(data.get("partyCode", "")).strip(),
                        int(bool(data.get("isPrimary"))),
                        str(data.get("sourceType", "manual")).strip() or "manual",
                        float(data.get("confidence", 1) or 1),
                        str(data.get("notes", "")).strip(),
                        now,
                        now,
                    ),
                )
                return self.send_json(get_project_parties(db, project_id), 201)
            if path == "/api/ontology/customer-organizations":
                try:
                    customer_id = int(data.get("customerId"))
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                if not db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
                    return self.send_json({"error": "customer not found"}, 404)
                parent_id = data.get("parentId")
                parent = None
                if parent_id:
                    try:
                        parent_id = int(parent_id)
                    except (TypeError, ValueError):
                        return self.send_json({"error": "invalid parentId"}, 400)
                    parent = db.execute(
                        "SELECT * FROM customer_organizations WHERE id = ? AND customer_id = ?",
                        (parent_id, customer_id),
                    ).fetchone()
                    if not parent:
                        return self.send_json({"error": "parent organization not found"}, 404)
                name = str(data.get("name", "")).strip()
                if not name:
                    return self.send_json({"error": "name is required"}, 400)
                code = str(data.get("code", "")).strip() or f"CUST-{customer_id}-ORG-{int(datetime.now().timestamp())}"
                organization_type = str(data.get("organizationType", "项目公司")).strip() or "项目公司"
                level = int(parent["level"]) + 1 if parent else 0
                try:
                    cur = db.execute(
                        """INSERT INTO customer_organizations
                           (customer_id, parent_id, code, name, organization_type, level, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (customer_id, parent_id, code, name, organization_type, level, now, now),
                    )
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "organization code already exists"}, 409)
                return self.send_json(get_customer_organization_node(db, cur.lastrowid), 201)
            if path.startswith("/api/projects/") and path.endswith("/customer-organization"):
                try:
                    project_id = int(path.strip("/").split("/")[2])
                    organization_id = int(data.get("customerOrganizationId"))
                except (TypeError, ValueError, IndexError):
                    return self.send_json({"error": "projectId and customerOrganizationId are required"}, 400)
                project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                organization = db.execute(
                    "SELECT * FROM customer_organizations WHERE id = ?", (organization_id,)
                ).fetchone()
                if not project:
                    return self.send_json({"error": "project not found"}, 404)
                if not organization or organization["customer_id"] != project["customer_id"]:
                    return self.send_json({"error": "organization does not belong to project customer"}, 409)
                db.execute(
                    "UPDATE projects SET customer_organization_id = ?, updated_at = ? WHERE id = ?",
                    (organization_id, now, project_id),
                )
                db.execute(
                    "UPDATE opportunities SET customer_organization_id = ?, updated_at = ? WHERE project_id = ?",
                    (organization_id, now, project_id),
                )
                return self.send_json({"status": "bound", "projectId": project_id, "customerOrganizationId": organization_id})
            if path.startswith("/api/people/") and path.endswith("/customer-organization"):
                try:
                    person_id = int(path.strip("/").split("/")[2])
                    organization_id = int(data.get("customerOrganizationId"))
                except (TypeError, ValueError, IndexError):
                    return self.send_json({"error": "personId and customerOrganizationId are required"}, 400)
                person = db.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()
                organization = db.execute(
                    "SELECT * FROM customer_organizations WHERE id = ?", (organization_id,)
                ).fetchone()
                if not person:
                    return self.send_json({"error": "person not found"}, 404)
                if not organization:
                    return self.send_json({"error": "customer organization not found"}, 404)
                linked = db.execute(
                    "SELECT 1 FROM customer_persons WHERE person_id = ? AND customer_id = ?",
                    (person_id, organization["customer_id"]),
                ).fetchone()
                if not linked:
                    return self.send_json({"error": "person is not linked to this customer"}, 409)
                db.execute(
                    "UPDATE persons SET customer_organization_id = ?, updated_at = ? WHERE id = ?",
                    (organization_id, now, person_id),
                )
                return self.send_json({"status": "bound", "personId": person_id, "customerOrganizationId": organization_id})
            if path == "/api/people":
                name = str(data.get("name", "")).strip()
                if not name:
                    return self.send_json({"error": "name is required"}, 400)
                customer_id = data.get("customerId")
                project_id = data.get("projectId")
                if customer_id and not db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
                    return self.send_json({"error": "customer not found"}, 404)
                if project_id and not db.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                    return self.send_json({"error": "project not found"}, 404)
                cur = db.execute(
                    """INSERT INTO persons
                       (name, organization, title, person_type, phone, email, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        str(data.get("organization", "")).strip(),
                        str(data.get("title", "")).strip(),
                        str(data.get("personType", "关键人")).strip() or "关键人",
                        str(data.get("phone", "")).strip(),
                        str(data.get("email", "")).strip(),
                        str(data.get("notes", "")).strip(),
                        now,
                        now,
                    ),
                )
                person_id = cur.lastrowid
                if customer_id:
                    db.execute(
                        """INSERT OR IGNORE INTO customer_persons
                           (customer_id, person_id, role, is_primary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (customer_id, person_id, data.get("customerRole", "联系人"), int(bool(data.get("isPrimary"))), now),
                    )
                if project_id:
                    db.execute(
                        """INSERT OR IGNORE INTO project_persons
                           (project_id, person_id, role, is_primary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (project_id, person_id, data.get("projectRole", "项目联系人"), int(bool(data.get("isPrimary"))), now),
                    )
                return self.send_json(dict(db.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()), 201)
            if path.startswith("/api/opportunities/") and path.endswith("/people"):
                parts = path.strip("/").split("/")
                try:
                    opportunity_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if not db.execute("SELECT 1 FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone():
                    return self.send_json({"error": "opportunity not found"}, 404)
                person_id = data.get("personId")
                if not person_id:
                    name = str(data.get("name", "")).strip()
                    if not name:
                        return self.send_json({"error": "personId or name is required"}, 400)
                    cur = db.execute(
                        """INSERT INTO persons
                           (name, organization, title, person_type, phone, email, notes, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            name,
                            str(data.get("organization", "")).strip(),
                            str(data.get("title", "")).strip(),
                            str(data.get("personType", "关键人")).strip() or "关键人",
                            str(data.get("phone", "")).strip(),
                            str(data.get("email", "")).strip(),
                            str(data.get("notes", "")).strip(),
                            now,
                            now,
                        ),
                    )
                    person_id = cur.lastrowid
                elif not db.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone():
                    return self.send_json({"error": "person not found"}, 404)
                role = str(data.get("role", "商机联系人")).strip() or "商机联系人"
                db.execute(
                    """INSERT INTO opportunity_persons
                       (opportunity_id, person_id, role, influence_level, relationship_status,
                        is_primary, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(opportunity_id, person_id, role) DO UPDATE SET
                         influence_level = excluded.influence_level,
                         relationship_status = excluded.relationship_status,
                         is_primary = excluded.is_primary,
                         notes = excluded.notes,
                         updated_at = excluded.updated_at""",
                    (
                        opportunity_id,
                        person_id,
                        role,
                        str(data.get("influenceLevel", "未知")).strip() or "未知",
                        str(data.get("relationshipStatus", "待建立")).strip() or "待建立",
                        int(bool(data.get("isPrimary"))),
                        str(data.get("relationshipNotes", data.get("notes", ""))).strip(),
                        now,
                        now,
                    ),
                )
                db.execute("UPDATE persons SET updated_at = ? WHERE id = ?", (now, person_id))
                return self.send_json({"status": "linked", "opportunityId": opportunity_id, "personId": person_id}, 201)
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
                created_opportunity = db.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
                current_stage = stage_definition(db, created_opportunity["stage"])
                if current_stage:
                    create_stage_actions(db, created_opportunity, current_stage, "stage_plan", "discovery_confirmed", now)
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
                created_opportunity = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
                current_stage = stage_definition(db, created_opportunity["stage"])
                if current_stage:
                    create_stage_actions(db, created_opportunity, current_stage, "stage_plan", "opportunity_created", now)
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
                transition_cur = db.execute("""INSERT INTO opportunity_stage_transitions
                    (opportunity_id, from_stage, to_stage, required_json, validation_json, actor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    oid, old_name, new_stage, json.dumps(required, ensure_ascii=False),
                    json.dumps(validation, ensure_ascii=False), data.get("actor", "李盛云"), now))
                complete_stage_actions(db, oid, target["code"], now)
                created_actions = create_stage_actions(
                    db,
                    row,
                    target,
                    "stage_transition",
                    transition_cur.lastrowid,
                    now,
                )
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
                           (oid, "stage_changed", f"商机阶段由 {old_name} 转换为 {new_stage}，阶段字段已校验", now))
                return self.send_json({
                    "status": "converted",
                    "stage": new_stage,
                    "stageCode": target["code"],
                    "missing": [],
                    "nextStage": target_name(db, target["nextCode"]),
                    "validation": validation,
                    "actions": created_actions,
                }, 200)
            if path.startswith("/api/agents/") and path.endswith("/run"):
                agent_id = path.strip("/").split("/")[2]
                agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
                if not agent_row:
                    return self.send_json({"error": "agent not found"}, 404)
                try:
                    opportunity_id = int(data["opportunityId"]) if data.get("opportunityId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if opportunity_id is not None and not db.execute(
                    "SELECT 1 FROM opportunities WHERE id = ?", (opportunity_id,)
                ).fetchone():
                    return self.send_json({"error": "opportunity not found"}, 404)
                result = data.get("result") or "已完成语义分析，生成待确认的客户开发建议。"
                cur = db.execute("INSERT INTO agent_runs (agent_id, opportunity_id, input_json, result, created_at) VALUES (?, ?, ?, ?, ?)", (agent_id, opportunity_id, json.dumps(data, ensure_ascii=False), result, now))
                action = None
                if opportunity_id:
                    opportunity = db.execute(
                        "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
                    ).fetchone()
                    action = create_action_record(
                        db,
                        title=data.get("actionTitle") or f"{agent_row['name']}：执行下一步建议",
                        description=data.get("actionDescription") or result,
                        action_type="agent_recommendation",
                        priority=data.get("priority", "medium"),
                        assignee=data.get("assignee") or opportunity["owner"],
                        due_at=data.get("dueAt"),
                        opportunity_id=opportunity_id,
                        stage_code=stage_definition(db, opportunity["stage"])["code"]
                        if stage_definition(db, opportunity["stage"]) else None,
                        stage_name=stage_name(opportunity["stage"]),
                        source_type="agent_recommendation",
                        source_id=str(cur.lastrowid),
                        source_agent_id=agent_id,
                        source_agent_run_id=cur.lastrowid,
                        created_by=data.get("actor", "李盛云"),
                        dedupe_key=f"agent_run:{cur.lastrowid}",
                        now=now,
                    )
                    db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (opportunity_id, "agent_run", f"{agent_id} 已运行：{result}", now))
                return self.send_json({"id": cur.lastrowid, "agentId": agent_id, "result": result, "status": "completed", "action": action}, 201)
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
