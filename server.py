import json
import os
import sqlite3
import base64
import hashlib
import mimetypes
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from customer_fact import CustomerFactRepository
from insight_controller import InsightController
from insight_repository import InsightRepository
from insight_service import InsightService
from opportunity_insight_controller import OpportunityInsightController
from opportunity_insight_repository import OpportunityInsightRepository
from opportunity_insight_service import OpportunityInsightService
from insight_action_controller import InsightActionController
from insight_action_repository import InsightActionRepository
from insight_action_service import InsightActionService
from customer_insight_agent import CustomerInsightAgent
from insight_score_controller import InsightScoreController
from insight_score_repository import InsightScoreRepository
from insight_score_service import InsightScoreService
from customer_potential_prediction import (
    get_latest_customer_potential_prediction,
    get_prediction_by_id,
    predict_customer_potential,
)
from customer_conversion_prediction import (
    get_customer_conversion_prediction,
    get_latest_customer_conversion_prediction,
    predict_customer_conversion,
)
from customer_value_prediction import (
    get_customer_value_prediction,
    get_latest_customer_value_prediction,
    predict_customer_value,
)
from customer_growth_prediction import (
    get_customer_growth_prediction,
    get_latest_customer_growth_prediction,
    predict_customer_growth,
)
from customer_growth_intelligence_agent import (
    get_customer_growth_intelligence_report,
    get_latest_customer_growth_intelligence_report,
    run_customer_growth_intelligence_agent,
)

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

SEED_INSIGHTS = [
    ("客户预算窗口", "Opportunity", "客户已确认营销自动化与渠道协同需求，存在扩大合作范围的机会。", "Customer Insight Agent"),
    ("决策链尚未闭合", "Risk", "当前商机尚未确认最终预算审批人，可能影响方案评审节奏。", "Opportunity Analysis Agent"),
    ("从渠道协同切入", "Breakthrough", "建议以渠道协同价值测算作为下一次客户沟通的切入点。", "拜访策略 Agent"),
    ("竞品在价格侧占优", "Competition", "已知竞品在报价阶段具备价格优势，需要强化交付与业务价值证明。", "Competition Agent"),
    ("安排方案评审会议", "Recommendation", "在本周内邀请客户业务与采购负责人参加方案评审，确认预算与决策节点。", "Sales Copilot"),
]

SEED_AGENTS = [
    ("customer-insight", "客户洞察 Agent", "客户开发", "从客户、商机、关系和经营指标生成画像、评分、机会与风险洞察。", "客户画像生成,客户评分计算,机会识别,风险扫描", "客户画像,涂料客户增长潜力模型,采购金额增长归因"),
    ("development-strategy", "客户开发策略 Agent", "客户开发", "结合客户 AT 阶段和涂料行业策略，生成突破路径、关键人策略与 30/60/90 天计划。", "开发目标拆解,工程入口识别,设计突破,方案植入,样板验证,关键人地图,30/60/90行动计划", "客户出货目标达成阈值,高潜工程客户增购策略,工程涂料项目推进 SOP"),
    ("visit-script", "拜访话术 Agent", "销售执行", "根据客户角色、当前 AT 阶段和商机风险，生成开场、提问与价值表达。", "开场话术,需求提问,价值表达,异议回应", "客户画像,涂料行业术语,商机关系图谱"),
    ("solution", "方案 Agent", "销售执行", "基于基材、应用场景、产品体系和客户目标推荐涂料解决方案与案例。", "场景分析,产品体系匹配,解决方案推荐,案例匹配,用量测算", "涂料产品,涂布率,工程涂料项目推进 SOP"),
    ("presentation", "PPT Agent", "销售执行", "将客户画像、方案、价值测算和竞争信息组织成客户交流材料与汇报大纲。", "客户交流材料,汇报方案,价值测算,一页纸摘要", "客户画像,采购金额,高潜工程客户增购策略"),
    ("competition", "竞争策略 Agent", "销售执行", "识别竞品、价格、关系和供应商准入风险，给出涂料商机突破打法。", "竞品分析,竞争位势,价格策略,突破打法", "商机关系图谱,涂料报价审批规则,采购金额增长归因"),
    ("opportunity-progress", "商机推进 Agent", "商机诊断", "识别商机所处 AT 阶段、缺失条件和下一步动作，推动商机形成可验证的业务事件。", "AT阶段判断,阶段准入校验,下一步动作,风险提示,业务事件记录", "推进涂料商机,样板验证完成,工程涂料项目推进 SOP"),
    ("opportunity-analysis", "商机分析 Agent", "商机诊断", "查询商机相关的已确认事实，并将未确认事实作为待核对提示。", "商机事实查询,事实一致性分析,风险提示", "商机关系图谱,事实审核规则"),
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

RELATIONSHIP_SCORE_FACTORS = (
    "interaction_frequency",
    "recency",
    "influence",
    "history",
    "duration",
)

DEFAULT_RELATIONSHIP_SCORE_WEIGHTS = {
    "interaction_frequency": 0.25,
    "recency": 0.25,
    "influence": 0.20,
    "history": 0.15,
    "duration": 0.15,
}

RELATIONSHIP_SCORE_MODEL_STATUSES = {
    "DRAFT",
    "TESTING",
    "PUBLISHED",
    "DISABLED",
}

RELATIONSHIP_SCORE_MODEL_VERSION_STATUSES = {
    "DRAFT",
    "TESTING",
    "PUBLISHED",
    "DISABLED",
}

DEFAULT_RELATIONSHIP_SCORE_DIMENSIONS = (
    ("interaction_frequency", "互动频率", 0.25, "根据关系事件和互动次数评估互动频率。"),
    ("recency", "最近联系时间", 0.25, "根据最近一次联系或关系事件评估联系新鲜度。"),
    ("influence", "职位影响力", 0.20, "根据关系角色和职位影响力评估关系价值。"),
    ("history", "历史合作", 0.15, "根据历史关系事件和合作影响评估历史合作程度。"),
    ("duration", "关系持续时间", 0.15, "根据关系建立时间评估关系持续时长。"),
)

RELATIONSHIP_SCORE_RULE_TYPES = {
    "RANGE",
    "TIME",
    "ENUM",
}

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
        CREATE TABLE IF NOT EXISTS insights (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          type TEXT NOT NULL CHECK (type IN (
            'Opportunity', 'Risk', 'Breakthrough', 'Competition', 'Recommendation'
          )),
          description TEXT NOT NULL,
          source TEXT NOT NULL,
          created_time TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS insight_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          insight_id INTEGER NOT NULL UNIQUE,
          confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
          business_value INTEGER NOT NULL CHECK (business_value BETWEEN 0 AND 100),
          urgency INTEGER NOT NULL CHECK (urgency BETWEEN 0 AND 100),
          actionability INTEGER NOT NULL CHECK (actionability BETWEEN 0 AND 100),
          score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
          created_time TEXT NOT NULL,
          FOREIGN KEY(insight_id) REFERENCES insights(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS opportunity_insights (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          insight_id INTEGER NOT NULL,
          created_time TEXT NOT NULL,
          UNIQUE(opportunity_id, insight_id),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE,
          FOREIGN KEY(insight_id) REFERENCES insights(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_facts (
          fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          fact_type TEXT NOT NULL CHECK (fact_type IN (
            'CUSTOMER_BASIC', 'ORGANIZATION', 'PURCHASE', 'PROJECT',
            'RELATIONSHIP', 'BEHAVIOR', 'COMPETITOR', 'STRATEGY'
          )),
          fact_name TEXT NOT NULL,
          fact_content TEXT NOT NULL DEFAULT '',
          fact_value TEXT NOT NULL DEFAULT '',
          unit TEXT NOT NULL DEFAULT '',
          source_type TEXT NOT NULL DEFAULT 'manual',
          source_id TEXT NOT NULL DEFAULT '',
          confidence_score INTEGER CHECK (confidence_score BETWEEN 0 AND 100),
          verification_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')),
          valid_from TEXT,
          valid_to TEXT,
          status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')),
          created_by TEXT NOT NULL DEFAULT 'system',
          created_time TEXT NOT NULL,
          updated_time TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS fact_candidates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fact_type TEXT NOT NULL,
          subject_type TEXT NOT NULL CHECK (subject_type IN ('Customer', 'Person', 'Opportunity', 'Project')),
          subject_id INTEGER NOT NULL,
          predicate TEXT NOT NULL,
          object_value TEXT NOT NULL,
          object_type TEXT NOT NULL,
          source_type TEXT NOT NULL CHECK (source_type IN ('recording', 'chat', 'document')),
          source_id TEXT NOT NULL,
          confidence INTEGER NOT NULL CHECK (confidence BETWEEN 0 AND 100),
          fact_quality_score INTEGER CHECK (fact_quality_score BETWEEN 0 AND 100),
          fact_quality_level TEXT CHECK (fact_quality_level IN ('A', 'B', 'C')),
          status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'MODIFIED')),
          created_by TEXT NOT NULL DEFAULT 'system',
          created_time TEXT NOT NULL,
          review_user TEXT,
          review_time TEXT
        );
        CREATE TABLE IF NOT EXISTS ontology_fact_values (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          subject_type TEXT NOT NULL CHECK (subject_type IN ('Customer', 'Person', 'Opportunity', 'Project')),
          subject_id INTEGER NOT NULL,
          predicate TEXT NOT NULL,
          object_value TEXT NOT NULL,
          object_type TEXT NOT NULL,
          fact_candidate_id INTEGER NOT NULL,
          created_time TEXT NOT NULL,
          updated_time TEXT NOT NULL,
          UNIQUE(subject_type, subject_id, predicate),
          FOREIGN KEY(fact_candidate_id) REFERENCES fact_candidates(id)
        );
        CREATE TABLE IF NOT EXISTS fact_candidate_review_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fact_candidate_id INTEGER NOT NULL,
          action TEXT NOT NULL CHECK (action IN ('APPROVE', 'REJECT', 'MODIFY')),
          before_json TEXT NOT NULL DEFAULT '{}',
          after_json TEXT NOT NULL DEFAULT '{}',
          review_user TEXT NOT NULL,
          review_time TEXT NOT NULL,
          ontology_result_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(fact_candidate_id) REFERENCES fact_candidates(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS fact_conflicts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fact_id_1 INTEGER NOT NULL,
          fact_id_2 INTEGER NOT NULL,
          conflict_type TEXT NOT NULL,
          resolution_status TEXT NOT NULL DEFAULT 'OPEN'
            CHECK (resolution_status IN ('OPEN', 'RESOLVED', 'IGNORED')),
          UNIQUE(fact_id_1, fact_id_2, conflict_type),
          CHECK (fact_id_1 < fact_id_2),
          FOREIGN KEY(fact_id_1) REFERENCES fact_candidates(id) ON DELETE CASCADE,
          FOREIGN KEY(fact_id_2) REFERENCES fact_candidates(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS fact_ontology_sync_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          fact_candidate_id INTEGER NOT NULL,
          attempt_no INTEGER NOT NULL,
          action TEXT NOT NULL DEFAULT 'SYNC',
          status TEXT NOT NULL CHECK (status IN ('STARTED', 'SUCCESS', 'FAILED')),
          subject_type TEXT NOT NULL,
          subject_id INTEGER NOT NULL,
          target_field TEXT,
          previous_value TEXT,
          new_value TEXT,
          error_message TEXT NOT NULL DEFAULT '',
          created_time TEXT NOT NULL,
          completed_time TEXT,
          UNIQUE(fact_candidate_id, attempt_no),
          FOREIGN KEY(fact_candidate_id) REFERENCES fact_candidates(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS fact_source (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_type TEXT NOT NULL CHECK (source_type IN (
            'CRM', 'ERP', '云筑', '人工录入', 'AI抽取', '会议记录'
          )),
          source_name TEXT NOT NULL,
          source_system TEXT NOT NULL,
          source_record_id TEXT NOT NULL DEFAULT '',
          extract_method TEXT NOT NULL DEFAULT '',
          created_time TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS insight_actions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          insight_id INTEGER NOT NULL,
          action_id INTEGER NOT NULL,
          priority TEXT NOT NULL DEFAULT 'medium',
          reason TEXT NOT NULL,
          created_time TEXT NOT NULL,
          UNIQUE(insight_id, action_id),
          FOREIGN KEY(insight_id) REFERENCES insights(id) ON DELETE CASCADE,
          FOREIGN KEY(action_id) REFERENCES actions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_developments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          customer_organization_id INTEGER,
          name TEXT NOT NULL,
          owner TEXT NOT NULL DEFAULT '',
          current_stage_code TEXT NOT NULL DEFAULT 'AT1',
          current_stage_name TEXT NOT NULL DEFAULT '客户立项',
          status TEXT NOT NULL DEFAULT 'active',
          target TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(customer_organization_id) REFERENCES customer_organizations(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_development_stage_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_development_id INTEGER NOT NULL,
          stage_code TEXT NOT NULL,
          stage_name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'in_progress',
          required_json TEXT NOT NULL DEFAULT '{}',
          notes TEXT NOT NULL DEFAULT '',
          started_at TEXT NOT NULL,
          completed_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(customer_development_id, stage_code),
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_development_health_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_development_id INTEGER NOT NULL,
          score INTEGER NOT NULL DEFAULT 0,
          dimensions_json TEXT NOT NULL DEFAULT '{}',
          reason TEXT NOT NULL DEFAULT '',
          assessed_by TEXT NOT NULL DEFAULT 'manual',
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_development_strategies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_development_id INTEGER NOT NULL,
          strategy_type TEXT NOT NULL DEFAULT '经营策略',
          title TEXT NOT NULL,
          content TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft',
          source_agent_id TEXT,
          source_agent_run_id INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE,
          FOREIGN KEY(source_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_development_opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_development_id INTEGER NOT NULL,
          opportunity_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '重点商机',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(customer_development_id, opportunity_id),
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_development_projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_development_id INTEGER NOT NULL,
          project_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '重点项目',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(customer_development_id, project_id),
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profiles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          customer_organization_id INTEGER,
          profile_type TEXT NOT NULL DEFAULT 'baseline',
          version_no INTEGER NOT NULL DEFAULT 1,
          scope_type TEXT NOT NULL DEFAULT 'customer',
          status TEXT NOT NULL DEFAULT 'active',
          profile_period_start TEXT,
          profile_period_end TEXT,
          completeness_score INTEGER,
          confidence_score INTEGER,
          last_assessed_at TEXT,
          source_agent_id TEXT,
          source_agent_run_id INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(customer_id, customer_organization_id, version_no),
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(customer_organization_id) REFERENCES customer_organizations(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_facts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          fact_code TEXT NOT NULL,
          fact_name TEXT NOT NULL,
          category TEXT NOT NULL,
          value_type TEXT NOT NULL DEFAULT 'text',
          value_json TEXT NOT NULL DEFAULT 'null',
          unit TEXT NOT NULL DEFAULT '',
          confidence INTEGER,
          source_type TEXT NOT NULL DEFAULT 'manual',
          source_id TEXT NOT NULL DEFAULT '',
          observed_at TEXT,
          valid_from TEXT,
          valid_to TEXT,
          status TEXT NOT NULL DEFAULT 'current',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(profile_id, fact_code),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          score_type TEXT NOT NULL,
          score INTEGER NOT NULL DEFAULT 0,
          level TEXT NOT NULL DEFAULT '',
          dimensions_json TEXT NOT NULL DEFAULT '{}',
          scoring_rule_version TEXT NOT NULL DEFAULT '',
          reason TEXT NOT NULL DEFAULT '',
          source_agent_id TEXT,
          source_agent_run_id INTEGER,
          assessed_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(profile_id, score_type, assessed_at),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(source_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(source_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_summaries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          summary_type TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL,
          structured_json TEXT NOT NULL DEFAULT '{}',
          generated_by_agent_id TEXT,
          generated_by_agent_run_id INTEGER,
          model_name TEXT NOT NULL DEFAULT '',
          prompt_version TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'published',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(generated_by_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(generated_by_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_evidences (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          evidence_type TEXT NOT NULL,
          source_object_type TEXT NOT NULL,
          source_object_id TEXT NOT NULL,
          evidence_text TEXT NOT NULL DEFAULT '',
          evidence_json TEXT NOT NULL DEFAULT '{}',
          confidence INTEGER,
          observed_at TEXT,
          extracted_by_agent_id TEXT,
          extracted_by_agent_run_id INTEGER,
          created_at TEXT NOT NULL,
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(extracted_by_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(extracted_by_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          project_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '重点项目',
          importance INTEGER,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(profile_id, project_id),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          opportunity_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '重点商机',
          importance INTEGER,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(profile_id, opportunity_id),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_persons (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          person_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '关键关系',
          influence_level TEXT NOT NULL DEFAULT '',
          relationship_health TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(profile_id, person_id),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_developments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id INTEGER NOT NULL,
          customer_development_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT '当前开发主线',
          relevance_score INTEGER,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(profile_id, customer_development_id),
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(customer_development_id) REFERENCES customer_developments(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_fact_extraction_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          profile_id INTEGER NOT NULL,
          trigger_type TEXT NOT NULL DEFAULT 'manual',
          source_types_json TEXT NOT NULL DEFAULT '[]',
          rule_version TEXT NOT NULL DEFAULT 'customer-fact-extraction-v1',
          status TEXT NOT NULL DEFAULT 'running',
          dry_run INTEGER NOT NULL DEFAULT 0,
          candidate_count INTEGER NOT NULL DEFAULT 0,
          accepted_count INTEGER NOT NULL DEFAULT 0,
          review_count INTEGER NOT NULL DEFAULT 0,
          agent_id TEXT,
          agent_run_id INTEGER,
          error_message TEXT NOT NULL DEFAULT '',
          started_at TEXT NOT NULL,
          completed_at TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE SET NULL,
          FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_fact_extraction_candidates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          customer_id INTEGER NOT NULL,
          profile_id INTEGER NOT NULL,
          fact_code TEXT NOT NULL,
          fact_name TEXT NOT NULL,
          category TEXT NOT NULL,
          value_type TEXT NOT NULL DEFAULT 'text',
          value_json TEXT NOT NULL DEFAULT 'null',
          confidence INTEGER NOT NULL DEFAULT 0,
          rule_code TEXT NOT NULL,
          source_object_type TEXT NOT NULL,
          source_object_id TEXT NOT NULL,
          source_text TEXT NOT NULL DEFAULT '',
          observed_at TEXT,
          status TEXT NOT NULL DEFAULT 'needs_review',
          applied_fact_id INTEGER,
          created_at TEXT NOT NULL,
          reviewed_at TEXT,
          FOREIGN KEY(run_id) REFERENCES customer_fact_extraction_runs(id) ON DELETE CASCADE,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE,
          FOREIGN KEY(applied_fact_id) REFERENCES customer_profile_facts(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_refresh_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_profile_id INTEGER NOT NULL,
          sources TEXT NOT NULL DEFAULT '[]',
          mode TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          start_time TEXT,
          end_time TEXT,
          error_message TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY(customer_profile_id) REFERENCES customer_profiles(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          profile_id INTEGER,
          event_type TEXT NOT NULL,
          source_object_type TEXT NOT NULL,
          source_object_id TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          fact_extraction_run_id INTEGER,
          agent_run_id INTEGER,
          error_message TEXT NOT NULL DEFAULT '',
          occurred_at TEXT NOT NULL,
          processed_at TEXT,
          created_at TEXT NOT NULL,
          dedupe_key TEXT NOT NULL UNIQUE,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
          FOREIGN KEY(profile_id) REFERENCES customer_profiles(id) ON DELETE SET NULL,
          FOREIGN KEY(fact_extraction_run_id) REFERENCES customer_fact_extraction_runs(id) ON DELETE SET NULL,
          FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profile_scoring_models (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          model_code TEXT NOT NULL,
          name TEXT NOT NULL,
          version_no TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',
          target_scope TEXT NOT NULL DEFAULT 'customer_profile',
          description TEXT NOT NULL DEFAULT '',
          is_default INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          published_at TEXT,
          UNIQUE(model_code, version_no)
        );
        CREATE TABLE IF NOT EXISTS customer_profile_scoring_dimensions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          model_id INTEGER NOT NULL,
          dimension_code TEXT NOT NULL,
          name TEXT NOT NULL,
          calculation_type TEXT NOT NULL DEFAULT 'rules',
          weight REAL NOT NULL DEFAULT 0,
          score_min INTEGER NOT NULL DEFAULT 0,
          score_max INTEGER NOT NULL DEFAULT 100,
          source_fact_codes_json TEXT NOT NULL DEFAULT '[]',
          source_metrics_json TEXT NOT NULL DEFAULT '[]',
          config_json TEXT NOT NULL DEFAULT '{}',
          enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(model_id, dimension_code),
          FOREIGN KEY(model_id) REFERENCES customer_profile_scoring_models(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS customer_profile_scoring_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          model_id INTEGER NOT NULL,
          dimension_id INTEGER,
          rule_code TEXT NOT NULL,
          name TEXT NOT NULL,
          condition_json TEXT NOT NULL DEFAULT '{}',
          score REAL NOT NULL DEFAULT 0,
          priority INTEGER NOT NULL DEFAULT 0,
          explanation TEXT NOT NULL DEFAULT '',
          config_json TEXT NOT NULL DEFAULT '{}',
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(model_id, rule_code),
          FOREIGN KEY(model_id) REFERENCES customer_profile_scoring_models(id) ON DELETE CASCADE,
          FOREIGN KEY(dimension_id) REFERENCES customer_profile_scoring_dimensions(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS relationship_entities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_type TEXT NOT NULL,
          entity_ref_id TEXT NOT NULL,
          entity_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(entity_type, entity_ref_id)
        );
        CREATE TABLE IF NOT EXISTS relationship_types (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          source_entity_type TEXT NOT NULL,
          target_entity_type TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT '',
          directionality TEXT NOT NULL DEFAULT 'directed',
          description TEXT NOT NULL DEFAULT '',
          default_weight INTEGER NOT NULL DEFAULT 50,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relationships (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_entity_id INTEGER NOT NULL,
          target_entity_id INTEGER NOT NULL,
          relationship_type_id INTEGER NOT NULL,
          strength_score INTEGER NOT NULL DEFAULT 0,
          strength_level TEXT NOT NULL DEFAULT '未知关系',
          status TEXT NOT NULL DEFAULT 'active',
          confidence INTEGER NOT NULL DEFAULT 0,
          last_contact_at TEXT,
          interaction_count INTEGER NOT NULL DEFAULT 0,
          first_established_at TEXT,
          last_evaluated_at TEXT,
          notes TEXT NOT NULL DEFAULT '',
          evidence_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(source_entity_id, target_entity_id, relationship_type_id),
          FOREIGN KEY(source_entity_id) REFERENCES relationship_entities(id) ON DELETE CASCADE,
          FOREIGN KEY(target_entity_id) REFERENCES relationship_entities(id) ON DELETE CASCADE,
          FOREIGN KEY(relationship_type_id) REFERENCES relationship_types(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS relationship_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          relationship_id INTEGER NOT NULL,
          score INTEGER NOT NULL DEFAULT 0,
          level TEXT NOT NULL DEFAULT '未知关系',
          interaction_frequency_score INTEGER,
          recency_score INTEGER,
          influence_score INTEGER,
          history_score INTEGER,
           duration_score INTEGER,
           weights_json TEXT NOT NULL DEFAULT '{}',
           components_json TEXT NOT NULL DEFAULT '{}',
          reason TEXT NOT NULL DEFAULT '',
          calculated_by TEXT NOT NULL DEFAULT 'manual',
          calculated_at TEXT NOT NULL,
          FOREIGN KEY(relationship_id) REFERENCES relationships(id) ON DELETE CASCADE
        );
         CREATE TABLE IF NOT EXISTS relationship_score_configs (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           code TEXT NOT NULL UNIQUE,
           name TEXT NOT NULL,
           interaction_frequency_weight REAL NOT NULL DEFAULT 0.25,
           recency_weight REAL NOT NULL DEFAULT 0.25,
           influence_weight REAL NOT NULL DEFAULT 0.20,
           history_weight REAL NOT NULL DEFAULT 0.15,
           duration_weight REAL NOT NULL DEFAULT 0.15,
           status TEXT NOT NULL DEFAULT 'active',
           is_default INTEGER NOT NULL DEFAULT 0,
           description TEXT NOT NULL DEFAULT '',
           created_at TEXT NOT NULL,
           updated_at TEXT NOT NULL
         );
        CREATE TABLE IF NOT EXISTS relationship_score_models (
          model_id TEXT PRIMARY KEY,
          model_name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'DRAFT',
          created_by TEXT NOT NULL,
          created_time TEXT NOT NULL,
          updated_time TEXT NOT NULL,
          CHECK (status IN ('DRAFT', 'TESTING', 'PUBLISHED', 'DISABLED'))
        );
        CREATE TABLE IF NOT EXISTS relationship_score_model_versions (
          version_id TEXT PRIMARY KEY,
          model_id TEXT NOT NULL,
          version_no TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'DRAFT',
          created_by TEXT NOT NULL,
          created_time TEXT NOT NULL,
          published_time TEXT,
          UNIQUE(model_id, version_no),
          CHECK (status IN ('DRAFT', 'TESTING', 'PUBLISHED', 'DISABLED')),
          FOREIGN KEY(model_id) REFERENCES relationship_score_models(model_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS relationship_score_dimensions (
          dimension_id TEXT PRIMARY KEY,
          version_id TEXT NOT NULL,
          dimension_code TEXT NOT NULL,
          dimension_name TEXT NOT NULL,
          weight REAL NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 1,
          description TEXT NOT NULL DEFAULT '',
          UNIQUE(version_id, dimension_code),
          FOREIGN KEY(version_id) REFERENCES relationship_score_model_versions(version_id) ON DELETE CASCADE,
          CHECK (weight >= 0)
        );
        CREATE TABLE IF NOT EXISTS relationship_score_rules (
          rule_id TEXT NOT NULL,
          dimension_id TEXT NOT NULL,
          rule_type TEXT NOT NULL,
          condition_json TEXT NOT NULL DEFAULT '{}',
          score REAL NOT NULL DEFAULT 0,
          priority INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(rule_id, dimension_id),
          FOREIGN KEY(dimension_id) REFERENCES relationship_score_dimensions(dimension_id) ON DELETE CASCADE,
          CHECK (rule_type IN ('RANGE', 'TIME', 'ENUM')),
          CHECK (priority >= 0)
        );
        CREATE TABLE IF NOT EXISTS relationship_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          relationship_id INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          event_time TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          impact_score INTEGER NOT NULL DEFAULT 0,
          before_score INTEGER NOT NULL DEFAULT 0,
          after_score INTEGER NOT NULL DEFAULT 0,
          description TEXT NOT NULL DEFAULT '',
          evidence_type TEXT NOT NULL DEFAULT '',
          evidence_ref TEXT NOT NULL DEFAULT '',
          created_by TEXT NOT NULL DEFAULT 'manual',
          created_at TEXT NOT NULL,
          FOREIGN KEY(relationship_id) REFERENCES relationships(id) ON DELETE CASCADE
        );
        """)
        score_columns = {row[1] for row in db.execute("PRAGMA table_info(relationship_scores)").fetchall()}
        for column, definition in [
            ("duration_score", "INTEGER"),
            ("weights_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("components_json", "TEXT NOT NULL DEFAULT '{}'"),
        ]:
            if column not in score_columns:
                db.execute(f"ALTER TABLE relationship_scores ADD COLUMN {column} {definition}")
        columns = {row[1] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
        if "source_category" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN source_category TEXT NOT NULL DEFAULT '内部信息'")
        if "customer_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN customer_id INTEGER")
        if "project_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN project_id INTEGER")
        if "project_section_id" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN project_section_id INTEGER")
        insight_columns = {row[1] for row in db.execute("PRAGMA table_info(insights)").fetchall()}
        if "customer_id" not in insight_columns:
            db.execute("ALTER TABLE insights ADD COLUMN customer_id INTEGER")
        default_customer = db.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()
        if default_customer:
            db.execute(
                "UPDATE insights SET customer_id = ? WHERE customer_id IS NULL",
                (default_customer["id"],),
            )
        for table, column, definition in [
            ("customers", "customer_level", "TEXT"),
            ("persons", "role", "TEXT"),
            ("fact_candidates", "fact_quality_score", "INTEGER"),
            ("fact_candidates", "fact_quality_level", "TEXT"),
            ("projects", "customer_organization_id", "INTEGER"),
            ("persons", "customer_organization_id", "INTEGER"),
            ("opportunities", "customer_organization_id", "INTEGER"),
            ("opportunities", "sales_assignment_id", "INTEGER"),
            ("actions", "customer_development_id", "INTEGER"),
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
        refresh_job_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_profile_refresh_jobs)").fetchall()
        }
        if "result_json" not in refresh_job_columns:
            db.execute(
                "ALTER TABLE customer_profile_refresh_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'"
            )
        backfill_opportunity_relations(db, now)
        seed_organization_ontology(db, now)
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_customer_id ON opportunities(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_insights_type_created_time ON insights(type, created_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_insights_customer_id ON insights(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_insight_scores_score ON insight_scores(score DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunity_insights_opportunity_id ON opportunity_insights(opportunity_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_opportunity_insights_insight_id ON opportunity_insights(insight_id)")
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
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_developments_customer_id ON customer_developments(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_stage_records_development_id ON customer_development_stage_records(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_health_scores_development_id ON customer_development_health_scores(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_strategies_development_id ON customer_development_strategies(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_opportunities_development_id ON customer_development_opportunities(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_opportunities_opportunity_id ON customer_development_opportunities(opportunity_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_projects_development_id ON customer_development_projects(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_development_projects_project_id ON customer_development_projects(project_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_actions_customer_development_id ON actions(customer_development_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_insight_actions_insight_id ON insight_actions(insight_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_insight_actions_action_id ON insight_actions(action_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profiles_customer_id ON customer_profiles(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_facts_customer_type_status ON customer_facts(customer_id, fact_type, status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_facts_source ON customer_facts(source_type, source_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_candidates_review_queue ON fact_candidates(status, confidence DESC, created_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_candidates_quality_queue ON fact_candidates(status, fact_quality_score DESC, confidence DESC, created_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_candidates_subject ON fact_candidates(subject_type, subject_id, status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_candidates_source ON fact_candidates(source_type, source_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_ontology_fact_values_subject ON ontology_fact_values(subject_type, subject_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_candidate_review_logs_candidate ON fact_candidate_review_logs(fact_candidate_id, review_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_conflicts_open ON fact_conflicts(resolution_status, fact_id_1, fact_id_2)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_fact_ontology_sync_logs_candidate ON fact_ontology_sync_logs(fact_candidate_id, attempt_no DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profiles_status ON customer_profiles(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_facts_profile_id ON customer_profile_facts(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_scores_profile_id ON customer_profile_scores(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_summaries_profile_id ON customer_profile_summaries(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_evidences_profile_id ON customer_profile_evidences(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_projects_profile_id ON customer_profile_projects(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_opportunities_profile_id ON customer_profile_opportunities(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_persons_profile_id ON customer_profile_persons(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_developments_profile_id ON customer_profile_developments(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_fact_extraction_runs_profile_id ON customer_fact_extraction_runs(profile_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_fact_extraction_runs_customer_id ON customer_fact_extraction_runs(customer_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_fact_extraction_candidates_run_id ON customer_fact_extraction_candidates(run_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_fact_extraction_candidates_profile_fact ON customer_fact_extraction_candidates(profile_id, fact_code)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_refresh_jobs_profile_status ON customer_profile_refresh_jobs(customer_profile_id, status, id DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_events_customer_id ON customer_profile_events(customer_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_events_profile_status ON customer_profile_events(profile_id, status, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_events_source ON customer_profile_events(source_object_type, source_object_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_scoring_models_status ON customer_profile_scoring_models(status, is_default)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_scoring_dimensions_model ON customer_profile_scoring_dimensions(model_id, enabled, sort_order)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_profile_scoring_rules_model_dimension ON customer_profile_scoring_rules(model_id, dimension_id, enabled, priority)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_entities_type_ref ON relationship_entities(entity_type, entity_ref_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source_entity_id ON relationships(source_entity_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target_entity_id ON relationships(target_entity_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationships_type_id ON relationships(relationship_type_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_scores_relationship_id ON relationship_scores(relationship_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_configs_status ON relationship_score_configs(status, is_default)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_models_status_updated ON relationship_score_models(status, updated_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_model_versions_model ON relationship_score_model_versions(model_id, created_time DESC)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_model_versions_status ON relationship_score_model_versions(model_id, status)")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_score_model_versions_one_published
                     ON relationship_score_model_versions(model_id)
                     WHERE status = 'PUBLISHED'""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_dimensions_version ON relationship_score_dimensions(version_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_dimensions_enabled ON relationship_score_dimensions(version_id, enabled)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_rules_dimension_priority ON relationship_score_rules(dimension_id, priority, rule_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_score_rules_enabled ON relationship_score_rules(dimension_id, enabled)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_relationship_events_relationship_id ON relationship_events(relationship_id)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunities_project_section_id ON opportunities(project_section_id) WHERE project_section_id IS NOT NULL")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_potential_predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          potential_score INTEGER NOT NULL CHECK (potential_score BETWEEN 0 AND 100),
          potential_level TEXT NOT NULL,
          annual_potential REAL NOT NULL DEFAULT 0,
          development_priority TEXT NOT NULL,
          dimensions_json TEXT NOT NULL DEFAULT '{}',
          input_snapshot_json TEXT NOT NULL DEFAULT '{}',
          model_version TEXT NOT NULL,
          assessed_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_potential_predictions_customer ON customer_potential_predictions(customer_id, assessed_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_conversion_predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          conversion_probability INTEGER NOT NULL CHECK (conversion_probability BETWEEN 0 AND 100),
          expected_conversion_days INTEGER NOT NULL,
          expected_conversion_at TEXT NOT NULL,
          blockers_json TEXT NOT NULL DEFAULT '[]',
          recommended_actions_json TEXT NOT NULL DEFAULT '[]',
          evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
          model_version TEXT NOT NULL,
          assessed_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_conversion_predictions_customer ON customer_conversion_predictions(customer_id, assessed_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_value_predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          value_score INTEGER NOT NULL CHECK (value_score BETWEEN 0 AND 100),
          future_revenue REAL NOT NULL DEFAULT 0,
          growth_space REAL NOT NULL DEFAULT 0,
          dimensions_json TEXT NOT NULL DEFAULT '{}',
          input_snapshot_json TEXT NOT NULL DEFAULT '{}',
          model_version TEXT NOT NULL,
          assessed_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_value_predictions_customer ON customer_value_predictions(customer_id, assessed_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_growth_predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          growth_score INTEGER NOT NULL CHECK (growth_score BETWEEN 0 AND 100),
          growth_direction TEXT NOT NULL CHECK (growth_direction IN ('UP', 'FLAT', 'DOWN')),
          growth_reason_json TEXT NOT NULL DEFAULT '[]',
          input_snapshot_json TEXT NOT NULL DEFAULT '{}',
          model_version TEXT NOT NULL,
          assessed_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_growth_predictions_customer ON customer_growth_predictions(customer_id, assessed_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS customer_growth_intelligence_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_id INTEGER NOT NULL,
          strategy_report_json TEXT NOT NULL DEFAULT '{}',
          key_person_advice_json TEXT NOT NULL DEFAULT '[]',
          visit_strategy_json TEXT NOT NULL DEFAULT '{}',
          next_actions_json TEXT NOT NULL DEFAULT '[]',
          prediction_snapshot_json TEXT NOT NULL DEFAULT '{}',
          input_snapshot_json TEXT NOT NULL DEFAULT '{}',
          model_version TEXT NOT NULL,
          generated_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_customer_growth_intelligence_customer ON customer_growth_intelligence_reports(customer_id, generated_at DESC)")
        agent_count = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if agent_count == 0:
            for agent_id, name, scene, description, skills, assets in SEED_AGENTS:
                db.execute("INSERT INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (agent_id, name, scene, description, now, now))
                for skill in skills.split(','):
                    db.execute("INSERT INTO agent_skills (agent_id, name, description, linked_assets) VALUES (?, ?, ?, ?)", (agent_id, skill, f"{skill}：读取客户、商机与涂料行业语义后生成可解释结果。", assets))
        analysis_agent = next(item for item in SEED_AGENTS if item[0] == "opportunity-analysis")
        db.execute("INSERT OR IGNORE INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (analysis_agent[0], analysis_agent[1], analysis_agent[2], analysis_agent[3], now, now))
        db.execute("INSERT OR IGNORE INTO agent_skills (agent_id, name, description, linked_assets) VALUES (?, ?, ?, ?)", (analysis_agent[0], "商机事实查询", "查询商机相关的已确认事实，并标记待核对信息。", analysis_agent[5]))
        seed_initial_actions(db, now)
        seed_customer_developments(db, now)
        seed_customer_development_links(db, now)
        seed_customer_profiles(db, now)
        seed_customer_facts(db, now)
        seed_insights(db, now)
        seed_insight_scores(db, now)
        seed_opportunity_insights(db, now)
        seed_insight_actions(db, now)
        seed_customer_profile_scoring_models(db, now)
        seed_relationship_ontology(db, now)
        seed_relationship_score_config(db, now)
        backfill_relationship_scores(db, now)

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
    if "insight_score" in item:
        item["insightScore"] = item.pop("insight_score")
    item["isOverdue"] = bool(
        item.get("due_at")
        and item.get("status") not in {"completed", "cancelled"}
        and item["due_at"] < datetime.now(timezone.utc).isoformat()[:10]
    )
    return item

def get_actions(db, opportunity_id=None, project_id=None, status=None, customer_development_id=None):
    clauses = []
    values = []
    if opportunity_id is not None:
        clauses.append("a.opportunity_id = ?")
        values.append(opportunity_id)
    if project_id is not None:
        clauses.append("a.project_id = ?")
        values.append(project_id)
    if customer_development_id is not None:
        clauses.append("a.customer_development_id = ?")
        values.append(customer_development_id)
    if status:
        clauses.append("a.status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"""SELECT a.*, ag.name AS source_agent_name
            FROM actions a
            LEFT JOIN agents ag ON ag.id = a.source_agent_id
            LEFT JOIN (
              SELECT ia.action_id, MAX(s.score) AS insight_score
              FROM insight_actions ia
              JOIN insight_scores s ON s.insight_id = ia.insight_id
              GROUP BY ia.action_id
            ) insight_priority ON insight_priority.action_id = a.id
            {where}
            ORDER BY CASE a.status
                       WHEN 'in_progress' THEN 1
                       WHEN 'pending' THEN 2
                       WHEN 'overdue' THEN 3
                       WHEN 'completed' THEN 4
                       ELSE 5
                     END,
                     COALESCE(insight_priority.insight_score, 0) DESC,
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
    customer_development_id=None,
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
    if customer_development_id is not None:
        development = db.execute(
            "SELECT * FROM customer_developments WHERE id = ?",
            (customer_development_id,),
        ).fetchone()
        if not development:
            raise ValueError("customer development not found")
        customer_id = customer_id or development["customer_id"]
        customer_organization_id = customer_organization_id or development["customer_organization_id"]
    if person_id is not None and not db.execute(
        "SELECT 1 FROM persons WHERE id = ?", (person_id,)
    ).fetchone():
        raise ValueError("person not found")
    if source_agent_id is not None and not db.execute(
        "SELECT 1 FROM agents WHERE id = ?", (source_agent_id,)
    ).fetchone():
        raise ValueError("agent not found")
    completed_at = now if status == "completed" else None
    db.execute(
        """INSERT OR IGNORE INTO actions
           (title, description, action_type, status, priority, assignee, due_at,
            opportunity_id, project_id, customer_id, customer_organization_id, customer_development_id, person_id,
            stage_code, stage_name, source_type, source_id, source_agent_id,
            source_agent_run_id, created_by, created_at, updated_at, completed_at, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            customer_development_id,
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

ACTION_RELATIONSHIP_EVENT_TYPES = {
    "visit": ("拜访", 5),
    "call": ("电话", 2),
    "meeting": ("会议", 5),
    "wechat": ("微信沟通", 2),
    "business_event": ("商务活动", 3),
    "拜访": ("拜访", 5),
    "电话": ("电话", 2),
    "会议": ("会议", 5),
    "微信沟通": ("微信沟通", 2),
    "商务活动": ("商务活动", 3),
}

def record_action_relationship_event(db, action, now=None):
    """将已完成的互动行动沉淀为关系事件，并保证同一行动只记一次。"""
    action = dict(action)
    if action.get("status") != "completed" or not action.get("person_id"):
        return None
    event_definition = ACTION_RELATIONSHIP_EVENT_TYPES.get(str(action.get("action_type", "")).strip())
    if not event_definition:
        return None
    now = now or datetime.now(timezone.utc).isoformat()
    evidence_ref = f"action:{action['id']}"
    existing = db.execute(
        "SELECT relationship_id FROM relationship_events WHERE evidence_type = 'action' AND evidence_ref = ?",
        (evidence_ref,),
    ).fetchone()
    if existing:
        return get_relationship_detail(db, existing["relationship_id"])
    target_candidates = []
    if action.get("opportunity_id"):
        target_candidates.append(("Opportunity", action["opportunity_id"]))
    if action.get("project_id"):
        target_candidates.append(("Project", action["project_id"]))
    if action.get("customer_id"):
        target_candidates.append(("Customer", action["customer_id"]))
    relationship = None
    for target_type, target_id in target_candidates:
        relationship = db.execute(
            """SELECT r.*
               FROM relationships r
               JOIN relationship_entities se ON se.id = r.source_entity_id
               JOIN relationship_entities te ON te.id = r.target_entity_id
               WHERE se.entity_type = 'Person' AND se.entity_ref_id = ?
                 AND te.entity_type = ? AND te.entity_ref_id = ?
               ORDER BY r.strength_score DESC, r.id DESC LIMIT 1""",
            (str(action["person_id"]), target_type, str(target_id)),
        ).fetchone()
        if relationship:
            break
    if not relationship:
        return None
    event_type, impact_score = event_definition
    before_score = int(relationship["strength_score"] or 0)
    after_score = before_score
    event_time = action.get("completed_at") or now
    event_cur = db.execute(
        """INSERT INTO relationship_events
           (relationship_id, event_type, event_time, source, impact_score,
            before_score, after_score, description, evidence_type,
            evidence_ref, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            relationship["id"],
            event_type,
            event_time,
            "action",
            impact_score,
            before_score,
            after_score,
            str(action.get("description") or action.get("title") or "").strip(),
            "action",
            evidence_ref,
            str(action.get("created_by") or "李盛云").strip() or "李盛云",
            now,
        ),
    )
    db.execute(
        """UPDATE relationships
           SET strength_score = ?, strength_level = ?, last_contact_at = ?,
               interaction_count = interaction_count + 1, updated_at = ?
           WHERE id = ?""",
        (after_score, relationship_score_level(after_score), event_time, now, relationship["id"]),
    )
    detail = calculate_relationship_strength_auto(db, relationship["id"], now)
    db.execute(
        "UPDATE relationship_events SET after_score = ? WHERE id = ?",
        (detail["strength_score"], event_cur.lastrowid),
    )
    return get_relationship_detail(db, relationship["id"])

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

CUSTOMER_DEVELOPMENT_STAGES = [
    ("AT1", "客户立项", 1, ["customerConfirmed", "decisionMap"]),
    ("AT2", "需求引导", 2, ["businessNeed", "solutionPlan"]),
    ("AT3", "招投标", 3, ["bidPlan", "priceStrategy"]),
    ("AT4", "履约交付", 4, ["deliveryPlan", "qualityPlan"]),
    ("AT5", "履约服务", 5, ["servicePlan", "satisfaction"]),
    ("AT6", "复盘沉淀", 6, ["reviewResult", "bestPractice"]),
]

RELATIONSHIP_TYPE_DEFINITIONS = [
    ("person_customer_owner", "客户负责人", "Person", "Customer", "人-客户", "负责人"),
    ("person_customer_contact", "客户联系人", "Person", "Customer", "人-客户", "联系人"),
    ("person_customer_decision_maker", "客户决策人", "Person", "Customer", "人-客户", "决策链"),
    ("person_customer_influencer", "客户影响人", "Person", "Customer", "人-客户", "决策链"),
    ("person_customer_procurement_owner", "采购负责人", "Person", "Customer", "人-客户", "决策链"),
    ("person_customer_technical_owner", "技术负责人", "Person", "Customer", "人-客户", "决策链"),
    ("person_project_owner", "项目负责人", "Person", "Project", "人-项目", "项目管理"),
    ("person_project_client_representative", "甲方代表", "Person", "Project", "人-项目", "项目管理"),
    ("person_project_design_lead", "设计负责人", "Person", "Project", "人-项目", "项目管理"),
    ("person_project_contractor_lead", "施工负责人", "Person", "Project", "人-项目", "项目管理"),
    ("person_project_procurement_owner", "项目采购负责人", "Person", "Project", "人-项目", "项目管理"),
    ("person_opportunity_sponsor", "商机发起人", "Person", "Opportunity", "人-商机", "商机推进"),
    ("person_opportunity_decision_maker", "商机关键决策人", "Person", "Opportunity", "人-商机", "商机推进"),
    ("person_opportunity_influencer", "商机竞争影响人", "Person", "Opportunity", "人-商机", "商机推进"),
    ("organization_parent_subsidiary", "母子公司", "Organization", "Organization", "企业关系", "组织关系"),
    ("organization_partner", "合作伙伴", "Organization", "Organization", "企业关系", "生态关系"),
    ("organization_competitor", "竞争关系", "Organization", "Organization", "企业关系", "竞争关系"),
    ("organization_supplier", "供应关系", "Organization", "Organization", "企业关系", "供应链"),
    ("agent_supports_object", "Agent服务对象", "Agent", "Customer", "智能体关系", "Agent"),
]

def customer_development_stage(code):
    for item in CUSTOMER_DEVELOPMENT_STAGES:
        if item[0] == code:
            return {"code": item[0], "name": item[1], "sequence": item[2], "required": item[3]}
    return None

def get_customer_development(db, development_id):
    row = db.execute(
        """SELECT cd.*, c.name AS customer_name, co.name AS customer_organization_name
           FROM customer_developments cd
           JOIN customers c ON c.id = cd.customer_id
           LEFT JOIN customer_organizations co ON co.id = cd.customer_organization_id
           WHERE cd.id = ?""",
        (development_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["currentStage"] = {
        "code": item["current_stage_code"],
        "name": item["current_stage_name"],
        "sequence": customer_development_stage(item["current_stage_code"])["sequence"]
        if customer_development_stage(item["current_stage_code"]) else None,
    }
    item["stageRecords"] = []
    for record in db.execute(
        """SELECT * FROM customer_development_stage_records
           WHERE customer_development_id = ?
           ORDER BY id""",
        (development_id,),
    ).fetchall():
        record_item = dict(record)
        record_item["required"] = json.loads(record_item.pop("required_json") or "{}")
        item["stageRecords"].append(record_item)
    health = db.execute(
        """SELECT * FROM customer_development_health_scores
           WHERE customer_development_id = ?
           ORDER BY created_at DESC, id DESC LIMIT 1""",
        (development_id,),
    ).fetchone()
    item["healthScore"] = None
    if health:
        health_item = dict(health)
        health_item["dimensions"] = json.loads(health_item.pop("dimensions_json") or "{}")
        item["healthScore"] = health_item
    item["strategies"] = [dict(x) for x in db.execute(
        """SELECT cds.*, a.name AS source_agent_name
           FROM customer_development_strategies cds
           LEFT JOIN agents a ON a.id = cds.source_agent_id
           WHERE cds.customer_development_id = ?
           ORDER BY cds.updated_at DESC, cds.id DESC""",
        (development_id,),
    ).fetchall()]
    item["actions"] = get_actions(db, customer_development_id=development_id)
    item["opportunities"] = [dict(x) for x in db.execute(
        """SELECT cdo.*, o.name, o.customer, o.stage, o.amount, o.business_type,
                         o.owner, o.project_id, p.name AS project_name
           FROM customer_development_opportunities cdo
           JOIN opportunities o ON o.id = cdo.opportunity_id
           LEFT JOIN projects p ON p.id = o.project_id
           WHERE cdo.customer_development_id = ?
           ORDER BY cdo.updated_at DESC, cdo.id DESC""",
        (development_id,),
    ).fetchall()]
    item["projects"] = [dict(x) for x in db.execute(
        """SELECT cdp.*, p.name, p.project_type, p.address, p.status,
                         p.customer_organization_id, co.name AS customer_organization_name
           FROM customer_development_projects cdp
           JOIN projects p ON p.id = cdp.project_id
           LEFT JOIN customer_organizations co ON co.id = p.customer_organization_id
           WHERE cdp.customer_development_id = ?
           ORDER BY cdp.updated_at DESC, cdp.id DESC""",
        (development_id,),
    ).fetchall()]
    item["stageDefinitions"] = [
        {"code": code, "name": name, "sequence": sequence, "required": required}
        for code, name, sequence, required in CUSTOMER_DEVELOPMENT_STAGES
    ]
    return item

def seed_customer_development_links(db, now):
    development = db.execute(
        "SELECT * FROM customer_developments ORDER BY id LIMIT 1"
    ).fetchone()
    if not development:
        return
    for row in db.execute(
        """SELECT id FROM opportunities
           WHERE customer_id = ?
           ORDER BY updated_at DESC, id DESC LIMIT 3""",
        (development["customer_id"],),
    ).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_development_opportunities
               (customer_development_id, opportunity_id, relation_type, created_at, updated_at)
               VALUES (?, ?, '重点商机', ?, ?)""",
            (development["id"], row["id"], now, now),
        )
    for row in db.execute(
        """SELECT id FROM projects
           WHERE customer_id = ?
           ORDER BY updated_at DESC, id DESC LIMIT 3""",
        (development["customer_id"],),
    ).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_development_projects
               (customer_development_id, project_id, relation_type, created_at, updated_at)
               VALUES (?, ?, '重点项目', ?, ?)""",
            (development["id"], row["id"], now, now),
        )

def seed_customer_developments(db, now):
    if db.execute("SELECT COUNT(*) FROM customer_developments").fetchone()[0]:
        return
    customer = db.execute("SELECT * FROM customers ORDER BY id LIMIT 1").fetchone()
    if not customer:
        return
    organization = db.execute(
        """SELECT * FROM customer_organizations
           WHERE customer_id = ? ORDER BY parent_id IS NOT NULL, id LIMIT 1""",
        (customer["id"],),
    ).fetchone()
    cur = db.execute(
        """INSERT INTO customer_developments
           (customer_id, customer_organization_id, name, owner, current_stage_code,
            current_stage_name, target, summary, next_action, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            customer["id"],
            organization["id"] if organization else None,
            f"{customer['name']}客户开发",
            "李盛云",
            "AT2",
            "需求引导",
            "建立集团客户长期合作与工程项目入口",
            "已完成客户立项，进入需求引导与关键人覆盖。",
            "补齐采购、设计和工程关键人，完成方案共创。",
            now,
            now,
        ),
    )
    development_id = cur.lastrowid
    for index, (code, name, sequence, required) in enumerate(CUSTOMER_DEVELOPMENT_STAGES):
        if sequence > 2:
            break
        db.execute(
            """INSERT INTO customer_development_stage_records
               (customer_development_id, stage_code, stage_name, status, required_json,
                notes, started_at, completed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                development_id,
                code,
                name,
                "completed" if code == "AT1" else "in_progress",
                json.dumps({key: "已确认" for key in required}, ensure_ascii=False),
                "初始化客户开发阶段记录",
                now,
                now if code == "AT1" else None,
                now,
                now,
            ),
        )
    db.execute(
        """INSERT INTO customer_development_health_scores
           (customer_development_id, score, dimensions_json, reason, assessed_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            development_id,
            78,
            json.dumps({"customerValue": 90, "opportunity": 80, "relationshipCoverage": 60}, ensure_ascii=False),
            "客户价值高，但采购与财务关系尚未完整建立。",
            "customer-insight",
            now,
        ),
    )

PROFILE_FACT_DEFINITIONS = [
    ("business_model", "业务模式", "business_model", "text"),
    ("purchase_mode", "采购模式", "purchase_behavior", "enum"),
    ("decision_cycle", "决策周期", "purchase_behavior", "text"),
    ("strategic_importance", "战略重要性", "customer_value", "enum"),
    ("annual_purchase_value", "年度采购规模", "customer_value", "number"),
    ("growth_direction", "增长方向", "business_model", "text"),
    ("relationship_coverage", "关系覆盖情况", "relationship", "json"),
    ("product_penetration_gap", "产品渗透缺口", "product_penetration", "json"),
    ("competitor_pattern", "竞品使用情况", "product_penetration", "json"),
    ("customer_risk", "客户经营风险", "risk", "json"),
]

FACT_EXTRACTION_SOURCE_TYPES = {
    "visit_record": "拜访记录 / 业务事件",
    "action": "Action行动任务",
    "opportunity": "商机数据",
    "project": "项目数据",
    "document_ocr": "文档 / OCR文本",
    "person": "关键人 / 关系数据",
}

CUSTOMER_FACT_EXTRACTION_RULES = [
    {
        "code": "opportunity.business_model",
        "factCode": "business_model",
        "name": "从商机和项目识别业务模式",
        "sources": ["opportunity", "project", "document_ocr"],
        "description": "出现工程项目、厂房、园区或项目型业务描述时，识别为工程项目型客户。",
        "autoAcceptThreshold": 70,
    },
    {
        "code": "opportunity.purchase_mode",
        "factCode": "purchase_mode",
        "name": "从商机阶段和文本识别采购模式",
        "sources": ["visit_record", "action", "opportunity", "person", "document_ocr"],
        "description": "根据招投标、采购、供应商准入等关键词识别客户采购路径。",
        "autoAcceptThreshold": 70,
    },
    {
        "code": "conversation.decision_cycle",
        "factCode": "decision_cycle",
        "name": "从业务文本识别决策周期",
        "sources": ["visit_record", "action", "opportunity", "document_ocr"],
        "description": "从文本中的天、周、月和招投标节点提取决策周期。",
        "autoAcceptThreshold": 75,
    },
    {
        "code": "relationship.role_coverage",
        "factCode": "relationship_coverage",
        "name": "识别客户关系角色覆盖",
        "sources": ["visit_record", "action", "opportunity", "project", "document_ocr"],
        "description": "识别甲方、采购、设计院、总包、决策人和技术推动者等关系角色。",
        "autoAcceptThreshold": 65,
    },
    {
        "code": "opportunity.growth_direction",
        "factCode": "growth_direction",
        "name": "从业务类型和产品线识别增长方向",
        "sources": ["opportunity", "project", "document_ocr"],
        "description": "根据商机业务类型和OCR识别产品线归纳客户潜在增长方向。",
        "autoAcceptThreshold": 70,
    },
    {
        "code": "opportunity.strategic_importance",
        "factCode": "strategic_importance",
        "name": "从商机规模识别战略重要性",
        "sources": ["opportunity"],
        "description": "根据客户关联商机金额和项目储备估计客户战略重要性。",
        "autoAcceptThreshold": 80,
    },
    {
        "code": "document.competitor_pattern",
        "factCode": "competitor_pattern",
        "name": "从文档和沟通文本识别竞品",
        "sources": ["visit_record", "action", "opportunity", "document_ocr"],
        "description": "识别文本中出现的竞品品牌或竞品描述，并保留原始来源。",
        "autoAcceptThreshold": 75,
    },
    {
        "code": "opportunity.customer_risk",
        "factCode": "customer_risk",
        "name": "从风险字段和行动描述识别客户风险",
        "sources": ["visit_record", "action", "opportunity", "document_ocr"],
        "description": "提取商机风险、供应商准入、决策链缺口和信息不完整等风险信号。",
        "autoAcceptThreshold": 70,
    },
]

def _json_value(value, fallback=None):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback if fallback is not None else value

def _contains_any(text, keywords):
    text = str(text or "")
    return [keyword for keyword in keywords if keyword in text]

def _fact_definition(fact_code):
    for code, name, category, value_type in PROFILE_FACT_DEFINITIONS:
        if code == fact_code:
            return {"code": code, "name": name, "category": category, "valueType": value_type}
    return {"code": fact_code, "name": fact_code, "category": "general", "valueType": "text"}

def _extraction_source(source_type, source_object_type, source_object_id, customer_id, text, observed_at, confidence=60, metadata=None):
    return {
        "sourceType": source_type,
        "sourceObjectType": source_object_type,
        "sourceObjectId": str(source_object_id),
        "customerId": customer_id,
        "text": str(text or "")[:2000],
        "observedAt": observed_at,
        "confidence": int(max(0, min(100, confidence))),
        "metadata": metadata or {},
    }

def collect_customer_fact_sources(db, customer_id, source_types):
    sources = []
    if "visit_record" in source_types:
        for row in db.execute(
            """SELECT be.id, be.event_type, be.message, be.created_at,
                      o.name AS opportunity_name, o.customer_id, o.project_id
               FROM business_events be
               JOIN opportunities o ON o.id = be.opportunity_id
               WHERE o.customer_id = ?
               ORDER BY be.created_at DESC""",
            (customer_id,),
        ).fetchall():
            sources.append(_extraction_source(
                "visit_record", "business_event", row["id"], customer_id,
                f"{row['event_type']} {row['message']} 商机：{row['opportunity_name']}",
                row["created_at"], 62, {"projectId": row["project_id"]},
            ))
    if "action" in source_types:
        for row in db.execute(
            """SELECT a.*, COALESCE(a.customer_id, o.customer_id, p.customer_id, cd.customer_id) AS resolved_customer_id
               FROM actions a
               LEFT JOIN opportunities o ON o.id = a.opportunity_id
               LEFT JOIN projects p ON p.id = a.project_id
               LEFT JOIN customer_developments cd ON cd.id = a.customer_development_id
               WHERE COALESCE(a.customer_id, o.customer_id, p.customer_id, cd.customer_id) = ?
               ORDER BY a.updated_at DESC""",
            (customer_id,),
        ).fetchall():
            sources.append(_extraction_source(
                "action", "action", row["id"], customer_id,
                f"任务：{row['title']} 描述：{row['description']} 阶段：{row['stage_name'] or row['stage_code']}",
                row["updated_at"], 58, {"status": row["status"], "priority": row["priority"]},
            ))
    if "person" in source_types:
        for row in db.execute(
            """SELECT p.id, p.name, p.organization, p.title, p.person_type, p.notes,
                      cp.role AS customer_role, cp.is_primary, p.updated_at
               FROM persons p
               JOIN customer_persons cp ON cp.person_id = p.id
               WHERE cp.customer_id = ?
               ORDER BY p.updated_at DESC, p.id DESC""",
            (customer_id,),
        ).fetchall():
            sources.append(_extraction_source(
                "person", "person", row["id"], customer_id,
                f"关键人：{row['name']} 组织：{row['organization']} 职位：{row['title']} 人员类型：{row['person_type']} 客户角色：{row['customer_role']} 备注：{row['notes']}",
                row["updated_at"], 74,
                {"role": row["customer_role"], "personType": row["person_type"], "isPrimary": row["is_primary"]},
            ))
    if "opportunity" in source_types:
        for row in db.execute(
            """SELECT o.*, p.name AS project_name, p.project_type, p.address
               FROM opportunities o
               LEFT JOIN projects p ON p.id = o.project_id
               WHERE o.customer_id = ?
               ORDER BY o.updated_at DESC""",
            (customer_id,),
        ).fetchall():
            sources.append(_extraction_source(
                "opportunity", "opportunity", row["id"], customer_id,
                f"商机：{row['name']} 阶段：{row['stage']} 业务类型：{row['business_type']} 描述：{row['description']} 风险：{row['risk']} 下一步：{row['next_action']}",
                row["updated_at"], 72, {"stage": row["stage"], "businessType": row["business_type"], "amount": row["amount"], "projectId": row["project_id"]},
            ))
    if "project" in source_types:
        for row in db.execute(
            """SELECT * FROM projects WHERE customer_id = ? ORDER BY updated_at DESC""",
            (customer_id,),
        ).fetchall():
            sources.append(_extraction_source(
                "project", "project", row["id"], customer_id,
                f"项目：{row['name']} 类型：{row['project_type']} 地址：{row['address']} 状态：{row['status']}",
                row["updated_at"], 70, {"projectType": row["project_type"], "status": row["status"]},
            ))
    if "document_ocr" in source_types:
        for row in db.execute(
            """SELECT pe.*, COALESCE(p.customer_id, o.customer_id) AS resolved_customer_id,
                      p.name AS project_name, o.name AS opportunity_name
               FROM project_evidence pe
               LEFT JOIN projects p ON p.id = pe.project_id
               LEFT JOIN opportunities o ON o.id = pe.opportunity_id
               WHERE COALESCE(p.customer_id, o.customer_id) = ?
               ORDER BY pe.created_at DESC""",
            (customer_id,),
        ).fetchall():
            payload = _json_value(row["extracted_json"], {}) or {}
            sources.append(_extraction_source(
                "document_ocr", "project_evidence", row["id"], customer_id,
                f"文件：{row['file_name']} 文本：{row['extracted_text']} OCR结果：{json.dumps(payload, ensure_ascii=False)}",
                row["created_at"], int(float(row["confidence"] or 0) * 100),
                {"fileName": row["file_name"], "mimeType": row["mime_type"], "reviewStatus": row["review_status"], "extracted": payload},
            ))
    return sources

def extract_customer_fact_candidates(sources, customer_id):
    candidates = []
    fact_names = {item[0]: item[1] for item in PROFILE_FACT_DEFINITIONS}

    def add(rule_code, fact_code, value, confidence, source, reason=""):
        definition = _fact_definition(fact_code)
        candidates.append({
            "factCode": fact_code,
            "factName": fact_names.get(fact_code, definition["name"]),
            "category": definition["category"],
            "valueType": definition["valueType"],
            "value": value,
            "confidence": int(max(0, min(100, confidence))),
            "ruleCode": rule_code,
            "sourceObjectType": source["sourceObjectType"],
            "sourceObjectId": source["sourceObjectId"],
            "sourceText": source["text"],
            "observedAt": source["observedAt"],
            "reason": reason,
        })

    role_keywords = ["甲方", "建设单位", "采购", "设计院", "总包", "经销商", "决策人", "技术推动者", "负责人"]
    competitor_keywords = ["多乐士", "三棵树", "立邦", "竞品", "竞争品牌"]
    for source in sources:
        text = source["text"]
        metadata = source["metadata"] or {}
        roles = _contains_any(text, role_keywords)
        if roles:
            add(
                "relationship.role_coverage", "relationship_coverage",
                {"mentionedRoles": roles, "sourceType": source["sourceType"]},
                max(65, source["confidence"]), source, "文本中识别到客户关系角色。",
            )
        competitors = _contains_any(text, competitor_keywords)
        if competitors:
            add(
                "document.competitor_pattern", "competitor_pattern",
                {"mentionedCompetitors": competitors}, max(68, source["confidence"]), source,
                "文本中识别到竞品或竞争品牌。",
            )
        if _contains_any(text, ["招投标", "招标", "投标", "标书"]):
            add("opportunity.purchase_mode", "purchase_mode", "招投标采购", max(72, source["confidence"]), source, "识别到招投标关键词。")
        elif _contains_any(text, ["采购", "供应商准入", "采购流程"]):
            add("opportunity.purchase_mode", "purchase_mode", "项目采购", max(68, source["confidence"]), source, "识别到采购或供应商准入关键词。")
        cycle = re.search(r"(\d+)\s*(天|周|个月|月)", text)
        if cycle:
            add("conversation.decision_cycle", "decision_cycle", cycle.group(0), max(70, source["confidence"]), source, "从文本提取到明确时间周期。")
        elif _contains_any(text, ["招投标", "招标", "投标"]):
            add("conversation.decision_cycle", "decision_cycle", "按招投标节点推进", 68, source, "通过招投标节点推断决策周期。")
        risk_terms = _contains_any(text, ["风险", "供应商准入", "决策链缺口", "信息不完整", "待补齐", "竞争激烈", "预算不明"])
        if risk_terms:
            add("opportunity.customer_risk", "customer_risk", {"signals": risk_terms, "source": text[:240]}, max(65, source["confidence"]), source, "识别到客户经营风险信号。")
        if source["sourceType"] in {"opportunity", "project", "document_ocr"}:
            project_terms = _contains_any(text, ["工程", "项目", "厂房", "园区", "施工", "建筑"])
            project_type = metadata.get("projectType") or metadata.get("businessType")
            if project_terms or project_type:
                add("opportunity.business_model", "business_model", "工程项目型客户", max(70, source["confidence"]), source, "从项目型业务描述识别业务模式。")
        if source["sourceType"] == "opportunity":
            business_type = metadata.get("businessType")
            if business_type:
                add("opportunity.growth_direction", "growth_direction", f"重点拓展{business_type}", 72, source, "根据商机业务类型归纳增长方向。")
            amount = float(metadata.get("amount") or 0)
            if amount >= 1000000:
                add("opportunity.strategic_importance", "strategic_importance", "高", 82, source, "关联商机金额达到重点项目阈值。")
        if source["sourceType"] == "document_ocr":
            extracted = metadata.get("extracted") or {}
            product_lines = extracted.get("productLines") or []
            if product_lines:
                add("opportunity.growth_direction", "growth_direction", f"重点拓展{'、'.join(map(str, product_lines))}", max(68, source["confidence"]), source, "从OCR结构化结果识别产品线方向。")
                add("opportunity.business_model", "business_model", "工程项目型客户", max(68, source["confidence"]), source, "OCR识别到工程项目证据。")
    return candidates

def get_customer_fact_extraction_run(db, run_id):
    row = db.execute(
        """SELECT r.*, c.name AS customer_name
           FROM customer_fact_extraction_runs r
           JOIN customers c ON c.id = r.customer_id
           WHERE r.id = ?""",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["sourceTypes"] = _json_value(item.pop("source_types_json"), [])
    item["dryRun"] = bool(item.pop("dry_run"))
    item["candidates"] = []
    for candidate in db.execute(
        """SELECT * FROM customer_fact_extraction_candidates
           WHERE run_id = ? ORDER BY confidence DESC, id""",
        (run_id,),
    ).fetchall():
        candidate_item = dict(candidate)
        candidate_item["value"] = _json_value(candidate_item.pop("value_json"), None)
        item["candidates"].append(candidate_item)
    return item

def list_customer_fact_extraction_candidates(db, run_id, status=None):
    clauses = ["run_id = ?"]
    values = [run_id]
    if status:
        clauses.append("status = ?")
        values.append(str(status).strip())
    rows = db.execute(
        f"""SELECT * FROM customer_fact_extraction_candidates
            WHERE {' AND '.join(clauses)}
            ORDER BY confidence DESC, id""",
        tuple(values),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["value"] = _json_value(item.pop("value_json"), None)
        result.append(item)
    return result

def _refresh_fact_extraction_run_counts(db, run_id):
    counts = db.execute(
        """SELECT
             COUNT(*) AS candidate_count,
             SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted_count,
             SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) AS review_count
           FROM customer_fact_extraction_candidates
           WHERE run_id = ?""",
        (run_id,),
    ).fetchone()
    db.execute(
        """UPDATE customer_fact_extraction_runs
           SET candidate_count = ?, accepted_count = ?, review_count = ?
           WHERE id = ?""",
        (
            counts["candidate_count"] or 0,
            counts["accepted_count"] or 0,
            counts["review_count"] or 0,
            run_id,
        ),
    )

def review_customer_fact_extraction_candidate(db, candidate_id, decision, payload=None, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    payload = payload or {}
    candidate = db.execute(
        """SELECT c.*, r.status AS run_status
           FROM customer_fact_extraction_candidates c
           JOIN customer_fact_extraction_runs r ON r.id = c.run_id
           WHERE c.id = ?""",
        (candidate_id,),
    ).fetchone()
    if not candidate:
        raise LookupError("customer fact extraction candidate not found")
    decision = str(decision or "").strip().lower()
    if decision not in {"accept", "reject"}:
        raise ValueError("decision must be accept or reject")
    if candidate["status"] == "accepted" and decision == "accept":
        return get_customer_fact_extraction_run(db, candidate["run_id"])
    if candidate["status"] == "rejected" and decision == "reject":
        return get_customer_fact_extraction_run(db, candidate["run_id"])
    if candidate["status"] == "supporting":
        raise ValueError("supporting candidates cannot be reviewed directly")
    if candidate["status"] == "preview":
        raise ValueError("preview candidates cannot be reviewed")

    if decision == "reject":
        db.execute(
            "UPDATE customer_fact_extraction_candidates SET status = 'rejected', reviewed_at = ? WHERE id = ?",
            (now, candidate_id),
        )
    else:
        value = payload["value"] if "value" in payload else _json_value(candidate["value_json"], None)
        fact_code = candidate["fact_code"]
        definition = _fact_definition(fact_code)
        fact_name = str(payload.get("factName") or candidate["fact_name"]).strip()
        source_id = f"extraction:{candidate['run_id']}:{candidate['source_object_type']}:{candidate['source_object_id']}"
        db.execute(
            """INSERT INTO customer_profile_facts
               (profile_id, fact_code, fact_name, category, value_type, value_json, unit,
                confidence, source_type, source_id, observed_at, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, 'current', ?, ?)
               ON CONFLICT(profile_id, fact_code) DO UPDATE SET
                 fact_name = excluded.fact_name, category = excluded.category,
                 value_type = excluded.value_type, value_json = excluded.value_json,
                 confidence = excluded.confidence, source_type = excluded.source_type,
                 source_id = excluded.source_id, observed_at = excluded.observed_at,
                 status = excluded.status, updated_at = excluded.updated_at""",
            (
                candidate["profile_id"],
                fact_code,
                fact_name or (definition["name"] if definition else fact_code),
                candidate["category"],
                candidate["value_type"],
                json.dumps(value, ensure_ascii=False),
                payload.get("confidence", candidate["confidence"]),
                "fact_review",
                source_id,
                candidate["observed_at"],
                now,
                now,
            ),
        )
        fact = db.execute(
            "SELECT id FROM customer_profile_facts WHERE profile_id = ? AND fact_code = ?",
            (candidate["profile_id"], fact_code),
        ).fetchone()
        db.execute(
            """UPDATE customer_fact_extraction_candidates
               SET status = 'accepted', applied_fact_id = ?, value_json = ?, reviewed_at = ?
               WHERE id = ?""",
            (fact["id"], json.dumps(value, ensure_ascii=False), now, candidate_id),
        )
        db.execute(
            """UPDATE customer_profiles
               SET updated_at = ?
               WHERE id = ?""",
            (now, candidate["profile_id"]),
        )
        db.execute(
            """UPDATE customer_profile_summaries
               SET status = 'stale', updated_at = ?
               WHERE profile_id = ? AND status = 'published'""",
            (now, candidate["profile_id"]),
        )
    _refresh_fact_extraction_run_counts(db, candidate["run_id"])
    return get_customer_fact_extraction_run(db, candidate["run_id"])

def run_customer_fact_extraction(db, profile_id, source_types=None, dry_run=False, trigger_type="manual", now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    profile = _profile_row(db, profile_id)
    if not profile:
        return None
    requested = source_types or list(FACT_EXTRACTION_SOURCE_TYPES)
    source_types = [item for item in requested if item in FACT_EXTRACTION_SOURCE_TYPES]
    if not source_types:
        raise ValueError("sourceTypes must contain at least one supported source")
    agent = db.execute("SELECT id FROM agents WHERE id = 'customer-insight'").fetchone()
    cur = db.execute(
        """INSERT INTO customer_fact_extraction_runs
           (customer_id, profile_id, trigger_type, source_types_json, rule_version, status, dry_run, started_at, created_at)
           VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)""",
        (profile["customer_id"], profile_id, trigger_type, json.dumps(source_types, ensure_ascii=False), "customer-fact-extraction-v1", int(bool(dry_run)), now, now),
    )
    run_id = cur.lastrowid
    try:
        sources = collect_customer_fact_sources(db, profile["customer_id"], source_types)
        candidates = extract_customer_fact_candidates(sources, profile["customer_id"])
        grouped = {}
        for candidate in candidates:
            grouped.setdefault(candidate["factCode"], []).append(candidate)
        winners = {fact_code: max(rows, key=lambda item: (item["confidence"], item.get("observedAt") or "")) for fact_code, rows in grouped.items()}
        accepted_count = 0
        review_count = 0
        evidence_ids = []
        rule_thresholds = {rule["factCode"]: rule["autoAcceptThreshold"] for rule in CUSTOMER_FACT_EXTRACTION_RULES}
        for candidate in candidates:
            is_winner = winners.get(candidate["factCode"]) is candidate
            threshold = rule_thresholds.get(candidate["factCode"], 70)
            status = "preview" if dry_run else ("accepted" if is_winner and candidate["confidence"] >= threshold else ("needs_review" if is_winner else "supporting"))
            candidate_cur = db.execute(
                """INSERT INTO customer_fact_extraction_candidates
                   (run_id, customer_id, profile_id, fact_code, fact_name, category, value_type,
                    value_json, confidence, rule_code, source_object_type, source_object_id,
                    source_text, observed_at, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, profile["customer_id"], profile_id, candidate["factCode"], candidate["factName"], candidate["category"], candidate["valueType"], json.dumps(candidate["value"], ensure_ascii=False), candidate["confidence"], candidate["ruleCode"], candidate["sourceObjectType"], candidate["sourceObjectId"], candidate["sourceText"], candidate["observedAt"], status, now),
            )
            if status == "accepted":
                accepted_count += 1
                definition = _fact_definition(candidate["factCode"])
                source_id = f"extraction:{run_id}:{candidate['sourceObjectType']}:{candidate['sourceObjectId']}"
                db.execute(
                    """INSERT INTO customer_profile_facts
                       (profile_id, fact_code, fact_name, category, value_type, value_json, unit,
                        confidence, source_type, source_id, observed_at, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', ?, 'fact_extraction', ?, ?, 'current', ?, ?)
                       ON CONFLICT(profile_id, fact_code) DO UPDATE SET
                         fact_name = excluded.fact_name, category = excluded.category,
                         value_type = excluded.value_type, value_json = excluded.value_json,
                         confidence = excluded.confidence, source_type = excluded.source_type,
                         source_id = excluded.source_id, observed_at = excluded.observed_at,
                         status = excluded.status, updated_at = excluded.updated_at""",
                    (profile_id, candidate["factCode"], definition["name"], definition["category"], definition["valueType"], json.dumps(candidate["value"], ensure_ascii=False), candidate["confidence"], source_id, candidate["observedAt"], now, now),
                )
                fact_row = db.execute("SELECT id FROM customer_profile_facts WHERE profile_id = ? AND fact_code = ?", (profile_id, candidate["factCode"])).fetchone()
                db.execute("UPDATE customer_fact_extraction_candidates SET applied_fact_id = ? WHERE id = ?", (fact_row["id"], candidate_cur.lastrowid))
                evidence_cur = db.execute(
                    """INSERT INTO customer_profile_evidences
                       (profile_id, evidence_type, source_object_type, source_object_id,
                        evidence_text, evidence_json, confidence, observed_at,
                        extracted_by_agent_id, extracted_by_agent_run_id, created_at)
                       VALUES (?, 'fact_extraction', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (profile_id, candidate["sourceObjectType"], candidate["sourceObjectId"], candidate["sourceText"], json.dumps({"factCode": candidate["factCode"], "ruleCode": candidate["ruleCode"], "extractionRunId": run_id, "reason": candidate["reason"]}, ensure_ascii=False), candidate["confidence"], candidate["observedAt"], agent["id"] if agent else None, None, now),
                )
                evidence_ids.append(evidence_cur.lastrowid)
            elif status == "needs_review":
                review_count += 1
        agent_run_id = None
        if agent:
            agent_cur = db.execute(
                """INSERT INTO agent_runs (agent_id, input_json, result, status, created_at)
                   VALUES (?, ?, ?, 'completed', ?)""",
                (agent["id"], json.dumps({"profileId": profile_id, "customerId": profile["customer_id"], "sourceTypes": source_types, "runId": run_id}, ensure_ascii=False), f"客户画像事实抽取完成：候选 {len(candidates)} 条，自动采纳 {accepted_count} 条，待复核 {review_count} 条。", now),
            )
            agent_run_id = agent_cur.lastrowid
        if agent_run_id:
            db.execute("UPDATE customer_fact_extraction_runs SET agent_run_id = ? WHERE id = ?", (agent_run_id, run_id))
            for evidence_id in evidence_ids:
                db.execute("UPDATE customer_profile_evidences SET extracted_by_agent_run_id = ? WHERE id = ?", (agent_run_id, evidence_id))
        if not dry_run:
            db.execute("UPDATE customer_profiles SET last_assessed_at = ?, updated_at = ? WHERE id = ?", (now, now, profile_id))
        db.execute(
            """UPDATE customer_fact_extraction_runs
               SET status = ?, candidate_count = ?, accepted_count = ?, review_count = ?, completed_at = ?
               WHERE id = ?""",
            ("preview" if dry_run else "completed", len(candidates), accepted_count, review_count, now, run_id),
        )
        return get_customer_fact_extraction_run(db, run_id)
    except Exception as error:
        db.execute("UPDATE customer_fact_extraction_runs SET status = 'failed', error_message = ?, completed_at = ? WHERE id = ?", (str(error), now, run_id))
        raise

CUSTOMER_PROFILE_EVENT_TYPES = {
    "project_created": "项目新增",
    "opportunity_created": "商机创建",
    "opportunity_stage_changed": "商机阶段变化",
    "person_changed": "关键人变化",
    "action_completed": "Action完成",
}

CUSTOMER_PROFILE_EVENT_SOURCE_TYPES = {
    "project_created": ["project", "opportunity", "document_ocr"],
    "opportunity_created": ["opportunity", "project", "document_ocr"],
    "opportunity_stage_changed": ["visit_record", "action", "opportunity", "project", "person"],
    "person_changed": ["person", "visit_record", "opportunity"],
    "action_completed": ["action", "visit_record", "opportunity", "project", "person"],
}

def sync_customer_profile_relations(db, profile_id, customer_id, now):
    """Keep the profile's read model links aligned with current customer objects."""
    for row in db.execute("SELECT id FROM projects WHERE customer_id = ?", (customer_id,)).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_projects
               (profile_id, project_id, relation_type, importance, created_at, updated_at)
               VALUES (?, ?, '客户关联项目', 60, ?, ?)""",
            (profile_id, row["id"], now, now),
        )
    for row in db.execute("SELECT id FROM opportunities WHERE customer_id = ?", (customer_id,)).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_opportunities
               (profile_id, opportunity_id, relation_type, importance, created_at, updated_at)
               VALUES (?, ?, '客户关联商机', 60, ?, ?)""",
            (profile_id, row["id"], now, now),
        )
    person_rows = db.execute(
        """SELECT DISTINCT p.id
           FROM persons p
           JOIN customer_persons cp ON cp.person_id = p.id
           WHERE cp.customer_id = ?
           UNION
           SELECT DISTINCT p.id
           FROM persons p
           JOIN opportunity_persons op ON op.person_id = p.id
           JOIN opportunities o ON o.id = op.opportunity_id
           WHERE o.customer_id = ?""",
        (customer_id, customer_id),
    ).fetchall()
    for row in person_rows:
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_persons
               (profile_id, person_id, relation_type, relationship_health, created_at, updated_at)
               VALUES (?, ?, '客户关键关系', '待评估', ?, ?)""",
            (profile_id, row["id"], now, now),
        )

def get_customer_profile_scoring_model(db, model_id=None, model_code=None, version_no=None, active_only=True):
    clauses = []
    values = []
    if model_id:
        clauses.append("id = ?")
        values.append(model_id)
    if model_code:
        clauses.append("model_code = ?")
        values.append(model_code)
    if version_no:
        clauses.append("version_no = ?")
        values.append(version_no)
    if active_only:
        clauses.append("status = 'active'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ORDER BY is_default DESC, published_at DESC, id DESC"
    row = db.execute(f"SELECT * FROM customer_profile_scoring_models {where} {order} LIMIT 1", tuple(values)).fetchone()
    if not row:
        return None
    model = dict(row)
    model["isDefault"] = bool(model.pop("is_default"))
    model["dimensions"] = []
    dimensions = db.execute(
        "SELECT * FROM customer_profile_scoring_dimensions WHERE model_id = ? ORDER BY sort_order, id",
        (row["id"],),
    ).fetchall()
    for dimension in dimensions:
        item = dict(dimension)
        item["sourceFactCodes"] = _json_value(item.pop("source_fact_codes_json"), [])
        item["sourceMetrics"] = _json_value(item.pop("source_metrics_json"), [])
        item["config"] = _json_value(item.pop("config_json"), {})
        item["enabled"] = bool(item["enabled"])
        item["rules"] = []
        rules = db.execute(
            "SELECT * FROM customer_profile_scoring_rules WHERE model_id = ? AND dimension_id = ? ORDER BY priority, id",
            (row["id"], dimension["id"]),
        ).fetchall()
        for rule in rules:
            rule_item = dict(rule)
            rule_item["condition"] = _json_value(rule_item.pop("condition_json"), {})
            rule_item["config"] = _json_value(rule_item.pop("config_json"), {})
            rule_item["enabled"] = bool(rule_item["enabled"])
            item["rules"].append(rule_item)
        model["dimensions"].append(item)
    return model

def _scoring_condition_matches(condition, metrics, facts):
    if condition.get("factCode"):
        fact_code = condition["factCode"]
        if condition.get("operator") == "exists":
            return (fact_code in facts) == bool(condition.get("value", True))
        if fact_code not in facts:
            return False
        actual = facts[fact_code]
    else:
        metric = condition.get("metric")
        if metric not in metrics:
            return False
        actual = metrics[metric]
    expected = condition.get("value")
    operator = condition.get("operator", "=")
    try:
        if operator == ">=":
            return actual >= expected
        if operator == ">":
            return actual > expected
        if operator == "<=":
            return actual <= expected
        if operator == "<":
            return actual < expected
        if operator in {"=", "=="}:
            return actual == expected
        if operator == "!=":
            return actual != expected
        if operator == "contains":
            return expected in actual
    except (TypeError, ValueError):
        return False
    return False

def recalculate_customer_profile_scores(db, profile_id, now, source_agent_run_id=None, model_id=None, model_code=None, version_no=None):
    profile = _profile_row(db, profile_id)
    if not profile:
        return []
    model = get_customer_profile_scoring_model(db, model_id, model_code, version_no)
    if not model:
        seed_customer_profile_scoring_models(db, now)
        model = get_customer_profile_scoring_model(db, model_id, model_code, version_no)
    if not model:
        raise ValueError("active customer profile scoring model not found")
    customer_id = profile["customer_id"]
    project_count = db.execute("SELECT COUNT(*) AS n FROM projects WHERE customer_id = ?", (customer_id,)).fetchone()["n"]
    opportunity_rows = db.execute(
        """SELECT amount, stage, risk FROM opportunities
           WHERE customer_id = ? AND stage NOT IN ('失败', '结束')""",
        (customer_id,),
    ).fetchall()
    person_rows = db.execute(
        """SELECT DISTINCT p.id, COALESCE(cp.role, op.role, '') AS role
           FROM persons p
           LEFT JOIN customer_persons cp ON cp.person_id = p.id AND cp.customer_id = ?
           LEFT JOIN opportunity_persons op ON op.person_id = p.id
           LEFT JOIN opportunities o ON o.id = op.opportunity_id AND o.customer_id = ?
           WHERE cp.person_id IS NOT NULL OR o.id IS NOT NULL""",
        (customer_id, customer_id),
    ).fetchall()
    roles = {str(row["role"] or "").strip() for row in person_rows if str(row["role"] or "").strip()}
    facts = db.execute(
        "SELECT fact_code, category, value_json FROM customer_profile_facts WHERE profile_id = ? AND status = 'current'",
        (profile_id,),
    ).fetchall()
    fact_map = {row["fact_code"]: _json_value(row["value_json"], None) for row in facts}
    risk_fact_count = sum(1 for row in facts if row["category"] == "risk")
    active_amount = sum(float(row["amount"] or 0) for row in opportunity_rows)
    risk_text = " ".join(str(row["risk"] or "") for row in opportunity_rows)
    metrics = {
        "projectCount": project_count,
        "opportunityCount": len(opportunity_rows),
        "activeOpportunityAmount": active_amount,
        "personCount": len(person_rows),
        "roleCount": len(roles),
        "riskFactCount": risk_fact_count,
        "hasGrowthDirection": bool(fact_map.get("growth_direction")),
        "activeRiskSignal": _contains_any(risk_text, ["风险", "待完善", "竞争", "供应商准入"]),
        "strategicImportanceHigh": fact_map.get("strategic_importance") == "高",
    }
    dimension_scores = {}
    score_details = {}
    for dimension in model["dimensions"]:
        if not dimension["enabled"]:
            continue
        if dimension["calculation_type"] == "weighted_average":
            continue
        matched_rules = [rule for rule in dimension["rules"] if rule["enabled"] and _scoring_condition_matches(rule["condition"], metrics, fact_map)]
        base_score = float((dimension["config"] or {}).get("baseScore", 0))
        raw_score = base_score + sum(float(rule["score"]) for rule in matched_rules)
        score = int(max(dimension["score_min"], min(dimension["score_max"], round(raw_score))))
        dimension_scores[dimension["dimension_code"]] = score
        score_details[dimension["dimension_code"]] = {
            "matchedRules": [rule["rule_code"] for rule in matched_rules],
            "explanations": [rule["explanation"] for rule in matched_rules],
        }
    scores = []
    for dimension in model["dimensions"]:
        if not dimension["enabled"]:
            continue
        code = dimension["dimension_code"]
        if dimension["calculation_type"] == "weighted_average":
            config = dimension["config"] or {}
            source_codes = config.get("sourceDimensions") or [item["dimension_code"] for item in model["dimensions"] if item["calculation_type"] != "weighted_average" and item["enabled"]]
            inverse_codes = set(config.get("inverseDimensions") or (["customer_risk"] if code == "customer_value" else []))
            source_dimensions = {item["dimension_code"]: item for item in model["dimensions"]}
            total_weight = sum(float(source_dimensions[item]["weight"]) for item in source_codes if item in source_dimensions)
            weighted_score = 0
            if total_weight:
                weighted_score = sum(
                    (100 - dimension_scores[item] if item in inverse_codes else dimension_scores.get(item, 0)) * float(source_dimensions[item]["weight"])
                    for item in source_codes if item in source_dimensions
                ) / total_weight
            score = int(max(dimension["score_min"], min(dimension["score_max"], round(weighted_score))))
            reason = f"按评分模型 {model['model_code']} {model['version_no']} 的维度权重汇总。"
            score_details[code] = {"sourceDimensions": source_codes, "inverseDimensions": list(inverse_codes), "totalWeight": total_weight}
        else:
            score = dimension_scores.get(code, 0)
            reason = "；".join(score_details.get(code, {}).get("explanations", [])) or f"按评分模型 {model['model_code']} {model['version_no']} 的配置规则计算。"
        scores.append((code, score, reason))
    dimensions_payload = {"metrics": metrics, "dimensions": score_details, "modelId": model["id"], "modelCode": model["model_code"], "modelVersion": model["version_no"]}
    agent = db.execute("SELECT id FROM agents WHERE id = 'customer-insight'").fetchone()
    scoring_rule_version = f"{model['model_code']}-{model['version_no']}"
    for score_type, score, reason in scores:
        db.execute(
            """INSERT INTO customer_profile_scores
               (profile_id, score_type, score, level, dimensions_json, scoring_rule_version,
                reason, source_agent_id, source_agent_run_id, assessed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(profile_id, score_type, assessed_at) DO UPDATE SET
                 score = excluded.score, level = excluded.level,
                 dimensions_json = excluded.dimensions_json,
                 scoring_rule_version = excluded.scoring_rule_version,
                 reason = excluded.reason, source_agent_id = excluded.source_agent_id,
                 source_agent_run_id = excluded.source_agent_run_id""",
            (profile_id, score_type, int(max(0, min(100, score))), profile_score_level(score), json.dumps(dimensions_payload, ensure_ascii=False), scoring_rule_version, reason, agent["id"] if agent else None, source_agent_run_id, now, now),
        )
    db.execute(
        "UPDATE customer_profiles SET last_assessed_at = ?, updated_at = ?, source_agent_id = COALESCE(?, source_agent_id), source_agent_run_id = COALESCE(?, source_agent_run_id) WHERE id = ?",
        (now, now, agent["id"] if agent else None, source_agent_run_id, profile_id),
    )
    return [{"scoreType": score_type, "score": int(max(0, min(100, score))), "level": profile_score_level(score), "modelId": model["id"], "modelCode": model["model_code"], "modelVersion": model["version_no"]} for score_type, score, _ in scores]

def get_customer_profile_event(db, event_id):
    row = db.execute(
        """SELECT e.*, c.name AS customer_name
           FROM customer_profile_events e
           JOIN customers c ON c.id = e.customer_id
           WHERE e.id = ?""",
        (event_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["eventName"] = CUSTOMER_PROFILE_EVENT_TYPES.get(item["event_type"], item["event_type"])
    item["payload"] = _json_value(item.pop("payload_json"), {})
    return item

def process_customer_profile_event(db, event_id, now=None, force=False):
    now = now or datetime.now(timezone.utc).isoformat()
    event = db.execute("SELECT * FROM customer_profile_events WHERE id = ?", (event_id,)).fetchone()
    if not event:
        return None
    if event["status"] == "completed" and not force:
        return get_customer_profile_event(db, event_id)
    if event["status"] == "skipped" and not force:
        return get_customer_profile_event(db, event_id)
    db.execute(
        "UPDATE customer_profile_events SET status = 'processing', attempts = attempts + 1, error_message = '' WHERE id = ?",
        (event_id,),
    )
    try:
        profile_id = event["profile_id"]
        if not profile_id:
            profile = get_current_customer_profile(db, event["customer_id"])
            profile_id = profile["id"] if profile else None
        if not profile_id:
            db.execute(
                "UPDATE customer_profile_events SET status = 'skipped', error_message = 'customer profile not found', processed_at = ? WHERE id = ?",
                (now, event_id),
            )
            return get_customer_profile_event(db, event_id)
        source_types = CUSTOMER_PROFILE_EVENT_SOURCE_TYPES.get(event["event_type"], list(FACT_EXTRACTION_SOURCE_TYPES))
        extraction = run_customer_fact_extraction(
            db,
            profile_id,
            source_types=source_types,
            dry_run=False,
            trigger_type=f"event:{event['event_type']}",
            now=now,
        )
        sync_customer_profile_relations(db, profile_id, event["customer_id"], now)
        scores = recalculate_customer_profile_scores(db, profile_id, now, extraction.get("agent_run_id"))
        db.execute(
            "UPDATE customer_profile_summaries SET status = 'stale', updated_at = ? WHERE profile_id = ? AND status = 'published'",
            (now, profile_id),
        )
        db.execute(
            """UPDATE customer_profile_events
               SET profile_id = ?, status = 'completed', fact_extraction_run_id = ?,
                   agent_run_id = ?, processed_at = ?, error_message = ''
               WHERE id = ?""",
            (profile_id, extraction["id"], extraction.get("agent_run_id"), now, event_id),
        )
        result = get_customer_profile_event(db, event_id)
        result["scores"] = scores
        result["summaryStatus"] = "stale"
        return result
    except Exception as error:
        db.execute(
            "UPDATE customer_profile_events SET status = 'failed', error_message = ?, processed_at = ? WHERE id = ?",
            (str(error), now, event_id),
        )
        return get_customer_profile_event(db, event_id)

def emit_customer_profile_event(db, event_type, customer_id, source_object_type, source_object_id, payload=None, now=None, process=True, dedupe_key=None):
    now = now or datetime.now(timezone.utc).isoformat()
    if event_type not in CUSTOMER_PROFILE_EVENT_TYPES:
        raise ValueError("unsupported customer profile event type")
    customer = db.execute("SELECT id FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not customer:
        raise ValueError("customer not found")
    profile = get_current_customer_profile(db, customer_id)
    dedupe_key = dedupe_key or f"{event_type}:{source_object_type}:{source_object_id}"
    existing = db.execute("SELECT id FROM customer_profile_events WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
    if existing:
        return get_customer_profile_event(db, existing["id"])
    cur = db.execute(
        """INSERT INTO customer_profile_events
           (customer_id, profile_id, event_type, source_object_type, source_object_id,
            payload_json, status, occurred_at, created_at, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, profile["id"] if profile else None, event_type, source_object_type, str(source_object_id), json.dumps(payload or {}, ensure_ascii=False), "pending" if profile else "skipped", now, now, dedupe_key),
    )
    event_id = cur.lastrowid
    if not profile:
        db.execute("UPDATE customer_profile_events SET error_message = 'customer profile not found', processed_at = ? WHERE id = ?", (now, event_id))
        return get_customer_profile_event(db, event_id)
    return process_customer_profile_event(db, event_id, now=now) if process else get_customer_profile_event(db, event_id)

def _profile_row(db, profile_id):
    return db.execute(
        """SELECT cp.*, c.name AS customer_name, c.customer_type, c.industry,
                  co.name AS customer_organization_name
           FROM customer_profiles cp
           JOIN customers c ON c.id = cp.customer_id
           LEFT JOIN customer_organizations co ON co.id = cp.customer_organization_id
           WHERE cp.id = ?""",
        (profile_id,),
    ).fetchone()

def get_customer_profile(db, profile_id):
    row = _profile_row(db, profile_id)
    if not row:
        return None
    item = dict(row)
    item["facts"] = []
    for fact in db.execute(
        """SELECT * FROM customer_profile_facts
           WHERE profile_id = ? ORDER BY category, fact_name, id""",
        (profile_id,),
    ).fetchall():
        fact_item = dict(fact)
        fact_item["value"] = json.loads(fact_item.pop("value_json") or "null")
        item["facts"].append(fact_item)
    item["scores"] = []
    for score in db.execute(
        """SELECT cps.*, a.name AS source_agent_name
           FROM customer_profile_scores cps
           LEFT JOIN agents a ON a.id = cps.source_agent_id
           WHERE cps.profile_id = ?
           ORDER BY cps.assessed_at DESC, cps.id DESC""",
        (profile_id,),
    ).fetchall():
        score_item = dict(score)
        score_item["dimensions"] = json.loads(score_item.pop("dimensions_json") or "{}")
        item["scores"].append(score_item)
    item["summaries"] = []
    for summary in db.execute(
        """SELECT cps.*, a.name AS generated_by_agent_name
           FROM customer_profile_summaries cps
           LEFT JOIN agents a ON a.id = cps.generated_by_agent_id
           WHERE cps.profile_id = ?
           ORDER BY cps.updated_at DESC, cps.id DESC""",
        (profile_id,),
    ).fetchall():
        summary_item = dict(summary)
        summary_item["structured"] = json.loads(summary_item.pop("structured_json") or "{}")
        item["summaries"].append(summary_item)
    item["evidences"] = []
    for evidence in db.execute(
        """SELECT cpe.*, a.name AS extracted_by_agent_name
           FROM customer_profile_evidences cpe
           LEFT JOIN agents a ON a.id = cpe.extracted_by_agent_id
           WHERE cpe.profile_id = ? ORDER BY cpe.observed_at DESC, cpe.id DESC""",
        (profile_id,),
    ).fetchall():
        evidence_item = dict(evidence)
        evidence_item["evidence"] = json.loads(evidence_item.pop("evidence_json") or "{}")
        item["evidences"].append(evidence_item)
    item["projects"] = [dict(x) for x in db.execute(
        """SELECT cpp.*, p.name, p.project_type, p.address, p.status,
                         co.name AS customer_organization_name
           FROM customer_profile_projects cpp
           JOIN projects p ON p.id = cpp.project_id
           LEFT JOIN customer_organizations co ON co.id = p.customer_organization_id
           WHERE cpp.profile_id = ? ORDER BY cpp.importance DESC, cpp.id DESC""",
        (profile_id,),
    ).fetchall()]
    item["opportunities"] = [dict(x) for x in db.execute(
        """SELECT cpo.*, o.name, o.stage, o.amount, o.business_type, o.owner,
                         p.name AS project_name
           FROM customer_profile_opportunities cpo
           JOIN opportunities o ON o.id = cpo.opportunity_id
           LEFT JOIN projects p ON p.id = o.project_id
           WHERE cpo.profile_id = ? ORDER BY cpo.importance DESC, cpo.id DESC""",
        (profile_id,),
    ).fetchall()]
    item["persons"] = [dict(x) for x in db.execute(
        """SELECT cpp.*, p.name, p.organization, p.title, p.person_type
           FROM customer_profile_persons cpp
           JOIN persons p ON p.id = cpp.person_id
           WHERE cpp.profile_id = ? ORDER BY cpp.id DESC""",
        (profile_id,),
    ).fetchall()]
    item["developments"] = [dict(x) for x in db.execute(
        """SELECT cpd.*, cd.name, cd.current_stage_code, cd.current_stage_name,
                         cd.status, cd.owner
           FROM customer_profile_developments cpd
           JOIN customer_developments cd ON cd.id = cpd.customer_development_id
           WHERE cpd.profile_id = ? ORDER BY cpd.id DESC""",
        (profile_id,),
    ).fetchall()]
    return item

def get_current_customer_profile(db, customer_id, customer_organization_id=None):
    if customer_organization_id:
        row = db.execute(
            """SELECT id FROM customer_profiles
               WHERE customer_id = ? AND customer_organization_id = ? AND status = 'active'
               ORDER BY version_no DESC, id DESC LIMIT 1""",
            (customer_id, customer_organization_id),
        ).fetchone()
    else:
        row = db.execute(
            """SELECT id FROM customer_profiles
               WHERE customer_id = ? AND status = 'active'
               ORDER BY version_no DESC, id DESC LIMIT 1""",
            (customer_id,),
        ).fetchone()
    return get_customer_profile(db, row["id"]) if row else None

def get_customer_profile_context(db, profile_id):
    profile = get_customer_profile(db, profile_id)
    if not profile:
        return None
    return {
        "profile": profile,
        "customer": {
            "id": profile["customer_id"],
            "name": profile["customer_name"],
            "type": profile["customer_type"],
            "industry": profile["industry"],
        },
        "facts": profile["facts"],
        "scores": profile["scores"],
        "summaries": profile["summaries"],
        "evidence": profile["evidences"],
        "relatedObjects": {
            "projects": profile["projects"],
            "opportunities": profile["opportunities"],
            "persons": profile["persons"],
            "customerDevelopments": profile["developments"],
        },
    }

def profile_score_level(score):
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"

def generate_customer_profile_summary(db, profile_id, now):
    profile = get_customer_profile(db, profile_id)
    if not profile:
        return None
    scores = {x["score_type"]: x for x in profile["scores"]}
    value_level = scores.get("customer_value", {}).get("level") or "待评估"
    relationship_score = scores.get("relationship_coverage", {}).get("score")
    growth_score = scores.get("growth_potential", {}).get("score")
    risks = [x for x in profile["facts"] if x["category"] == "risk"]
    summary = (
        f"{profile['customer_name']}是{profile['industry']}行业客户，当前客户价值等级为{value_level}。"
        f"已关联{len(profile['projects'])}个项目、{len(profile['opportunities'])}个商机和{len(profile['persons'])}位关键人。"
    )
    if relationship_score is not None:
        summary += f"关系覆盖评分为{relationship_score}分。"
    if growth_score is not None:
        summary += f"客户增长潜力评分为{growth_score}分。"
    if risks:
        summary += "当前需要关注：" + "、".join(x["fact_name"] for x in risks) + "。"
    else:
        summary += "当前暂无已记录的主要经营风险。"
    structured = {
        "customerValueLevel": value_level,
        "projectCount": len(profile["projects"]),
        "opportunityCount": len(profile["opportunities"]),
        "personCount": len(profile["persons"]),
        "relationshipScore": relationship_score,
        "growthScore": growth_score,
        "riskFacts": [x["fact_code"] for x in risks],
        "generatedAt": now,
    }
    agent = db.execute("SELECT id FROM agents WHERE id = 'customer-insight'").fetchone()
    run_id = None
    if agent:
        run = db.execute(
            """INSERT INTO agent_runs
               (agent_id, input_json, result, status, created_at)
               VALUES (?, ?, ?, 'completed', ?)""",
            (
                agent["id"],
                json.dumps({"profileId": profile_id, "purpose": "customer_profile_summary"}, ensure_ascii=False),
                summary,
                now,
            ),
        )
        run_id = run.lastrowid
    db.execute(
        """INSERT INTO customer_profile_summaries
           (profile_id, summary_type, title, content, structured_json,
            generated_by_agent_id, generated_by_agent_run_id, model_name,
            prompt_version, status, created_at, updated_at)
           VALUES (?, 'executive_summary', ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)""",
        (
            profile_id,
            "AI客户摘要",
            summary,
            json.dumps(structured, ensure_ascii=False),
            agent["id"] if agent else None,
            run_id,
            "rule-based-mvp",
            "customer-profile-v1",
            now,
            now,
        ),
    )
    db.execute(
        "UPDATE customer_profiles SET last_assessed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, profile_id),
    )
    return get_customer_profile(db, profile_id)

class ProfileRefreshService:
    """在一个事务中执行客户画像刷新流水线。"""

    def execute(self, db, profile_id, source_types=None, dry_run=False, trigger_type="manual", now=None):
        now = now or datetime.now(timezone.utc).isoformat()
        profile = _profile_row(db, profile_id)
        if not profile:
            raise LookupError("customer profile not found")
        if dry_run:
            return self._execute_preview(db, profile_id, source_types, trigger_type, now)
        return self._execute_formal(db, profile_id, source_types, trigger_type, now)

    def _execute_formal(self, db, profile_id, source_types, trigger_type, now):
        """执行完整流水线；调用方负责提交或回滚事务。"""
        profile = _profile_row(db, profile_id)
        before_facts = self._fact_snapshot(db, profile_id)
        before_scores = self._score_snapshot(db, profile_id)
        before_summary = self._summary_snapshot(db, profile_id)
        sync_customer_profile_relations(db, profile_id, profile["customer_id"], now)
        extraction = run_customer_fact_extraction(
            db,
            profile_id,
            source_types=source_types,
            dry_run=False,
            trigger_type=trigger_type,
            now=now,
        )
        scores = recalculate_customer_profile_scores(
            db,
            profile_id,
            now,
            extraction.get("agent_run_id"),
        )
        db.execute(
            """UPDATE customer_profile_summaries
               SET status = 'stale', updated_at = ?
               WHERE profile_id = ? AND status = 'published'""",
            (now, profile_id),
        )
        summary = generate_customer_profile_summary(db, profile_id, now)
        result = {
            "profileId": profile_id,
            "dryRun": False,
            "extraction": extraction,
            "scores": scores,
            "summary": summary["summaries"][0] if summary and summary.get("summaries") else None,
            "profile": summary,
        }
        result.update(self._build_result_diff(
            before_facts,
            before_scores,
            before_summary,
            self._fact_snapshot(db, profile_id),
            self._score_snapshot(db, profile_id),
            self._summary_snapshot(db, profile_id),
            int(extraction.get("review_count", 0)),
        ))
        return result

    def _fact_snapshot(self, db, profile_id):
        rows = db.execute(
            """SELECT fact_code, fact_name, value_json, confidence, source_type
               FROM customer_profile_facts WHERE profile_id = ?""",
            (profile_id,),
        ).fetchall()
        return {
            row["fact_code"]: {
                "fact_code": row["fact_code"],
                "fact_name": row["fact_name"],
                "value": _json_value(row["value_json"], None),
                "confidence": row["confidence"],
                "source_type": row["source_type"],
            }
            for row in rows
        }

    def _score_snapshot(self, db, profile_id):
        rows = db.execute(
            """SELECT score_type, score, level, reason
               FROM customer_profile_scores
               WHERE profile_id = ?
               ORDER BY assessed_at DESC, id DESC""",
            (profile_id,),
        ).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row["score_type"], {
                "score_type": row["score_type"],
                "score": row["score"],
                "level": row["level"],
                "reason": row["reason"],
            })
        return result

    def _summary_snapshot(self, db, profile_id):
        row = db.execute(
            """SELECT title, content, structured_json
               FROM customer_profile_summaries
               WHERE profile_id = ? AND status = 'published'
               ORDER BY id DESC LIMIT 1""",
            (profile_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "title": row["title"],
            "content": row["content"],
            "structured": _json_value(row["structured_json"], {}),
        }

    def _build_result_diff(self, before_facts, before_scores, before_summary,
                           after_facts, after_scores, after_summary, pending_candidates):
        new_facts = [value for key, value in after_facts.items() if key not in before_facts]
        deleted_facts = [value for key, value in before_facts.items() if key not in after_facts]
        score_changes = []
        for score_type in sorted(set(before_scores) | set(after_scores)):
            before = before_scores.get(score_type)
            after = after_scores.get(score_type)
            if before != after:
                score_changes.append({"score_type": score_type, "before": before, "after": after})
        return {
            "newFacts": new_facts,
            "deletedFacts": deleted_facts,
            "scoreChanges": score_changes,
            "summaryChange": {"before": before_summary, "after": after_summary},
            "pendingCandidateCount": pending_candidates,
        }

    def _execute_preview(self, db, profile_id, source_types, trigger_type, now):
        before_facts = self._fact_snapshot(db, profile_id)
        before_scores = self._score_snapshot(db, profile_id)
        before_summary = self._summary_snapshot(db, profile_id)
        savepoint = f"profile_refresh_preview_{profile_id}"
        db.execute(f"SAVEPOINT {savepoint}")
        try:
            formal_result = self._execute_formal(db, profile_id, source_types, trigger_type, now)
            after_facts = self._fact_snapshot(db, profile_id)
            after_scores = self._score_snapshot(db, profile_id)
            after_summary = self._summary_snapshot(db, profile_id)
            pending_candidates = int(formal_result.get("extraction", {}).get("review_count", 0))
            diff = self._build_result_diff(
                before_facts, before_scores, before_summary,
                after_facts, after_scores, after_summary, pending_candidates,
            )
            db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            return {
                "profileId": profile_id,
                "dryRun": True,
                "mode": "preview",
                **diff,
                "extraction": formal_result.get("extraction"),
                "scores": [],
                "summary": None,
            }
        except Exception:
            db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            db.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise


def refresh_customer_profile(db, profile_id, source_types=None, dry_run=False, trigger_type="manual", now=None):
    """保留旧调用入口，由 ProfileRefreshService 执行实际刷新。"""
    return ProfileRefreshService().execute(
        db,
        profile_id,
        source_types=source_types,
        dry_run=dry_run,
        trigger_type=trigger_type,
        now=now,
    )


REFRESH_JOB_SOURCE_VALUES = {"ALL", "CRM", "PROJECT", "CONVERSATION", "MANUAL_FACT"}
REFRESH_JOB_SOURCE_TYPES = {
    "CRM": ["visit_record", "action", "opportunity", "person"],
    "PROJECT": ["project"],
    "CONVERSATION": ["visit_record"],
    # Manual facts are already part of the profile context; use the full
    # supported source set so a manual-only refresh still recalculates safely.
    "MANUAL_FACT": list(FACT_EXTRACTION_SOURCE_TYPES),
}


def _refresh_job_source_types(sources):
    if "ALL" in sources:
        return list(FACT_EXTRACTION_SOURCE_TYPES)
    source_types = []
    for source in sources:
        for source_type in REFRESH_JOB_SOURCE_TYPES.get(source, []):
            if source_type not in source_types:
                source_types.append(source_type)
    return source_types or list(FACT_EXTRACTION_SOURCE_TYPES)


def create_customer_profile_refresh_job(db, profile_id, sources, mode, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    if not _profile_row(db, profile_id):
        raise LookupError("customer profile not found")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty array")
    normalized_sources = [str(source).strip().upper() for source in sources]
    invalid_sources = [source for source in normalized_sources if source not in REFRESH_JOB_SOURCE_VALUES]
    if invalid_sources:
        raise ValueError(f"unsupported refresh source: {invalid_sources[0]}")
    if mode not in {"formal", "preview"}:
        raise ValueError("mode must be formal or preview")
    cursor = db.execute(
        """INSERT INTO customer_profile_refresh_jobs
           (customer_profile_id, sources, mode, status, start_time, end_time, error_message)
           VALUES (?, ?, ?, 'queued', NULL, NULL, '')""",
        (profile_id, json.dumps(normalized_sources, ensure_ascii=False), mode),
    )
    db.commit()
    return {"jobId": cursor.lastrowid, "customerProfileId": profile_id, "status": "queued"}


def run_customer_profile_refresh_job(job_id):
    """后台执行刷新；画像写入和任务完成状态分别受事务保护。"""
    started_at = datetime.now(timezone.utc).isoformat()
    db = connect()
    try:
        job = db.execute("SELECT * FROM customer_profile_refresh_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return
        db.execute(
            "UPDATE customer_profile_refresh_jobs SET status = 'running', start_time = ?, error_message = '' WHERE id = ?",
            (started_at, job_id),
        )
        db.commit()
    finally:
        db.close()

    try:
        sources = json.loads(job["sources"] or "[]")
        source_types = _refresh_job_source_types(sources)
        db = connect()
        try:
            result = refresh_customer_profile(
                db,
                job["customer_profile_id"],
                source_types=source_types,
                dry_run=job["mode"] == "preview",
                trigger_type="manual",
                now=started_at,
            )
            ended_at = datetime.now(timezone.utc).isoformat()
            db.execute(
                "UPDATE customer_profile_refresh_jobs SET status = 'completed', end_time = ?, error_message = '', result_json = ? WHERE id = ?",
                (ended_at, json.dumps(result, ensure_ascii=False), job_id),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except Exception as error:
        ended_at = datetime.now(timezone.utc).isoformat()
        db = connect()
        try:
            db.execute(
                "UPDATE customer_profile_refresh_jobs SET status = 'failed', end_time = ?, error_message = ? WHERE id = ?",
                (ended_at, str(error), job_id),
            )
            db.commit()
        finally:
            db.close()


def get_customer_profile_refresh_job_status(db, job_id):
    row = db.execute(
        """SELECT id, status, error_message, result_json
           FROM customer_profile_refresh_jobs
           WHERE id = ?""",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    progress_by_status = {"queued": 0, "running": 50, "completed": 100, "failed": 100}
    message_by_status = {
        "queued": "等待刷新任务执行",
        "running": "正在刷新客户画像",
        "completed": "客户画像刷新完成",
        "failed": "客户画像刷新失败",
    }
    status = row["status"]
    result = _json_value(row["result_json"], None)
    response = {
        "status": status,
        "progress": progress_by_status.get(status, 0),
        "message": message_by_status.get(status, "刷新任务状态未知"),
        "error_message": row["error_message"] or "",
    }
    if result:
        response["result"] = result
    return response

def upsert_customer_profile_fact(db, profile_id, payload, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    profile = _profile_row(db, profile_id)
    if not profile:
        raise LookupError("customer profile not found")
    fact_code = str(payload.get("factCode", payload.get("fact_code", ""))).strip()
    if not fact_code:
        raise ValueError("factCode is required")
    if "value" not in payload:
        raise ValueError("value is required")
    definition = next((item for item in PROFILE_FACT_DEFINITIONS if item[0] == fact_code), None)
    fact_name = str(payload.get("factName") or (definition[1] if definition else fact_code)).strip()
    db.execute(
        """INSERT INTO customer_profile_facts
           (profile_id, fact_code, fact_name, category, value_type, value_json, unit,
            confidence, source_type, source_id, observed_at, valid_from, valid_to, status,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(profile_id, fact_code) DO UPDATE SET
             fact_name = excluded.fact_name, category = excluded.category,
             value_type = excluded.value_type, value_json = excluded.value_json,
             unit = excluded.unit, confidence = excluded.confidence,
             source_type = excluded.source_type, source_id = excluded.source_id,
             observed_at = excluded.observed_at, valid_from = excluded.valid_from,
             valid_to = excluded.valid_to, status = excluded.status,
             updated_at = excluded.updated_at""",
        (
            profile_id,
            fact_code,
            fact_name,
            str(payload.get("category") or (definition[2] if definition else "general")),
            str(payload.get("valueType") or (definition[3] if definition else "text")),
            json.dumps(payload["value"], ensure_ascii=False),
            str(payload.get("unit", "")).strip(),
            payload.get("confidence"),
            str(payload.get("sourceType", "manual")).strip() or "manual",
            str(payload.get("sourceId", "")).strip(),
            payload.get("observedAt") or now,
            payload.get("validFrom"),
            payload.get("validTo"),
            str(payload.get("status", "current")).strip() or "current",
            now,
            now,
        ),
    )
    db.execute(
        """UPDATE customer_profiles
           SET updated_at = ?
           WHERE id = ?""",
        (now, profile_id),
    )
    row = db.execute(
        "SELECT * FROM customer_profile_facts WHERE profile_id = ? AND fact_code = ?",
        (profile_id, fact_code),
    ).fetchone()
    item = dict(row)
    item["value"] = _json_value(item.pop("value_json"), None)
    return item

def delete_customer_profile_fact(db, profile_id, fact_id, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    if not _profile_row(db, profile_id):
        raise LookupError("customer profile not found")
    cur = db.execute(
        "DELETE FROM customer_profile_facts WHERE profile_id = ? AND id = ?",
        (profile_id, fact_id),
    )
    if not cur.rowcount:
        raise LookupError("customer profile fact not found")
    db.execute(
        "UPDATE customer_profiles SET updated_at = ? WHERE id = ?",
        (now, profile_id),
    )
    return {"status": "deleted", "profileId": profile_id, "factId": fact_id}

def seed_customer_profiles(db, now):
    if db.execute("SELECT COUNT(*) FROM customer_profiles").fetchone()[0]:
        return
    customer = db.execute("SELECT * FROM customers ORDER BY id LIMIT 1").fetchone()
    if not customer:
        return
    organization = db.execute(
        """SELECT id FROM customer_organizations
           WHERE customer_id = ? ORDER BY parent_id IS NOT NULL, id LIMIT 1""",
        (customer["id"],),
    ).fetchone()
    agent = db.execute("SELECT id FROM agents WHERE id = 'customer-insight'").fetchone()
    cur = db.execute(
        """INSERT INTO customer_profiles
           (customer_id, customer_organization_id, profile_type, version_no,
            scope_type, status, completeness_score, confidence_score,
            source_agent_id, created_at, updated_at)
           VALUES (?, ?, 'baseline', 1, 'customer', 'active', 72, 78, ?, ?, ?)""",
        (customer["id"], organization["id"] if organization else None, agent["id"] if agent else None, now, now),
    )
    profile_id = cur.lastrowid
    facts = [
        ("business_model", "业务模式", "business_model", "text", "工程项目型客户"),
        ("strategic_importance", "战略重要性", "customer_value", "enum", "高"),
        ("purchase_mode", "采购模式", "purchase_behavior", "enum", "项目采购"),
        ("relationship_coverage", "关系覆盖情况", "relationship", "json", {"采购": 60, "设计": 55, "决策层": 45}),
        ("customer_risk", "客户经营风险", "risk", "json", {"code": "decision_chain_gap", "label": "决策链覆盖不足"}),
    ]
    for code, name, category, value_type, value in facts:
        db.execute(
            """INSERT INTO customer_profile_facts
               (profile_id, fact_code, fact_name, category, value_type, value_json,
                confidence, source_type, observed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'baseline', ?, ?, ?)""",
            (profile_id, code, name, category, value_type, json.dumps(value, ensure_ascii=False), 78, now, now, now),
        )
    for score_type, score, reason in [
        ("customer_value", 82, "战略重要性高，存在持续工程项目入口"),
        ("growth_potential", 76, "已存在多个项目和商机，可扩展产品线"),
        ("relationship_coverage", 58, "采购、设计和决策层关系仍需补齐"),
        ("project_potential", 80, "客户关联项目储备较充足"),
        ("customer_risk", 42, "决策链不完整，存在供应商准入风险"),
    ]:
        db.execute(
            """INSERT INTO customer_profile_scores
               (profile_id, score_type, score, level, reason, assessed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, score_type, score, profile_score_level(score), reason, now, now),
        )
    development = db.execute(
        "SELECT id FROM customer_developments WHERE customer_id = ? ORDER BY id LIMIT 1",
        (customer["id"],),
    ).fetchone()
    if development:
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_developments
               (profile_id, customer_development_id, relevance_score, created_at, updated_at)
               VALUES (?, ?, 90, ?, ?)""",
            (profile_id, development["id"], now, now),
        )
    for row in db.execute("SELECT id FROM projects WHERE customer_id = ? ORDER BY id LIMIT 3", (customer["id"],)).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_projects
               (profile_id, project_id, relation_type, importance, created_at, updated_at)
               VALUES (?, ?, '重点项目', 80, ?, ?)""",
            (profile_id, row["id"], now, now),
        )
    for row in db.execute("SELECT id FROM opportunities WHERE customer_id = ? ORDER BY id LIMIT 3", (customer["id"],)).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_opportunities
               (profile_id, opportunity_id, relation_type, importance, created_at, updated_at)
               VALUES (?, ?, '重点商机', 80, ?, ?)""",
            (profile_id, row["id"], now, now),
        )
    for row in db.execute(
        """SELECT p.id
           FROM persons p
           JOIN customer_persons cp ON cp.person_id = p.id
           WHERE cp.customer_id = ?
           ORDER BY p.id LIMIT 5""",
        (customer["id"],),
    ).fetchall():
        db.execute(
            """INSERT OR IGNORE INTO customer_profile_persons
               (profile_id, person_id, relation_type, relationship_health, created_at, updated_at)
               VALUES (?, ?, '关键关系', '待评估', ?, ?)""",
            (profile_id, row["id"], now, now),
        )
    generate_customer_profile_summary(db, profile_id, now)


def seed_insights(db, now):
    """初始化第一阶段 Insight 演示数据，重复初始化不会产生重复记录。"""
    if db.execute("SELECT COUNT(*) FROM insights").fetchone()[0] > 0:
        return
    customer = db.execute("SELECT id FROM customers ORDER BY id LIMIT 1").fetchone()
    if not customer:
        return
    db.executemany(
        """INSERT INTO insights (customer_id, name, type, description, source, created_time)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [(customer["id"], *insight, now) for insight in SEED_INSIGHTS],
    )


def seed_insight_scores(db, now):
    """为已有 Insight 初始化评分，评分结果可被 Action 和 Agent 直接复用。"""
    repository = InsightScoreRepository(db)
    for row in db.execute("SELECT id FROM insights ORDER BY id").fetchall():
        repository.score(row["id"], now)


def seed_opportunity_insights(db, now):
    """为首个演示商机建立四类商机洞察关联。"""
    opportunity = db.execute("SELECT id FROM opportunities ORDER BY id LIMIT 1").fetchone()
    if not opportunity:
        return
    insight_rows = db.execute(
        """SELECT id FROM insights
           WHERE type IN ('Opportunity', 'Risk', 'Breakthrough', 'Competition')
           ORDER BY id"""
    ).fetchall()
    db.executemany(
        """INSERT OR IGNORE INTO opportunity_insights
           (opportunity_id, insight_id, created_time)
           VALUES (?, ?, ?)""",
        [(opportunity["id"], row["id"], now) for row in insight_rows],
    )


def seed_insight_actions(db, now):
    """初始化一条 Insight -> Action 闭环演示数据。"""
    insight = db.execute(
        """SELECT * FROM insights
           WHERE type = 'Breakthrough' ORDER BY id LIMIT 1"""
    ).fetchone()
    opportunity = db.execute("SELECT * FROM opportunities ORDER BY id LIMIT 1").fetchone()
    if not insight or not opportunity:
        return
    if db.execute(
        "SELECT 1 FROM insight_actions WHERE insight_id = ? LIMIT 1", (insight["id"],)
    ).fetchone():
        return
    action = create_action_record(
        db,
        title="创建设计院拜访任务",
        description="根据 Insight 制定设计院关系突破拜访，确认关键设计影响人。",
        action_type="visit",
        priority="high",
        opportunity_id=opportunity["id"],
        customer_id=insight["customer_id"],
        source_type="insight",
        source_id=f"insight:{insight['id']}",
        created_by="AI Insight Agent",
        dedupe_key=f"insight:{insight['id']}:创建设计院拜访任务",
        now=now,
    )
    if action:
        InsightActionRepository(db).create(
            insight["id"],
            action["id"],
            "high",
            "该洞察表明设计院关系不足，需要通过拜访建立关键关系。",
            now,
        )


def seed_customer_facts(db, now):
    """初始化默认客户事实和 CustomerFact 联调测试数据。"""
    customer = db.execute("SELECT id, name FROM customers ORDER BY id LIMIT 1").fetchone()
    repository = CustomerFactRepository(db)
    default_payloads = [
        {
            "factType": "CUSTOMER_BASIC",
            "factName": "客户类型",
            "factContent": "客户基础类型来自客户主数据",
            "factValue": "建设单位",
            "sourceType": "customer",
            "sourceId": str(customer["id"]),
            "confidenceScore": 100,
            "verificationStatus": "VERIFIED",
            "createdBy": "system",
        },
        {
            "factType": "PURCHASE",
            "factName": "采购模式",
            "factContent": "当前客户以项目采购为主",
            "factValue": "项目采购",
            "sourceType": "baseline",
            "confidenceScore": 78,
            "verificationStatus": "PENDING",
            "createdBy": "system",
        },
        {
            "factType": "STRATEGY",
            "factName": "客户经营策略",
            "factContent": "优先围绕重点工程项目扩大合作范围",
            "factValue": "重点项目深耕",
            "sourceType": "baseline",
            "confidenceScore": 70,
            "verificationStatus": "PENDING",
            "createdBy": "system",
        },
    ]
    if customer and not db.execute(
        "SELECT 1 FROM customer_facts WHERE customer_id = ? LIMIT 1", (customer["id"],)
    ).fetchone():
        for payload in default_payloads:
            repository.create(customer["id"], payload, now)

    test_customer = db.execute(
        "SELECT id FROM customers WHERE name = ?", ("江西头部地产集团",)
    ).fetchone()
    if not test_customer:
        cursor = db.execute(
            """INSERT INTO customers
               (name, customer_type, industry, status, created_at, updated_at)
               VALUES (?, '地产集团', '房地产', 'active', ?, ?)""",
            ("江西头部地产集团", now, now),
        )
        test_customer_id = cursor.lastrowid
    else:
        test_customer_id = test_customer["id"]

    for fact_type, fact_name, content in [
        ("COMPETITOR", "当前竞品", "当前使用多乐士"),
        ("PROJECT", "项目储备", "2027年有3个项目"),
        ("RELATIONSHIP", "工程关系", "已认识工程负责人"),
    ]:
        exists = db.execute(
            """SELECT 1 FROM customer_facts
               WHERE customer_id = ? AND fact_type = ? AND fact_content = ?""",
            (test_customer_id, fact_type, content),
        ).fetchone()
        if not exists:
            repository.create(
                test_customer_id,
                {
                    "factType": fact_type,
                    "factName": fact_name,
                    "factContent": content,
                    "factValue": content,
                    "sourceType": "manual",
                    "confidenceScore": 90,
                    "createdBy": "seed",
                },
                now,
            )

def seed_customer_profile_scoring_models(db, now):
    existing_default = db.execute(
        "SELECT id FROM customer_profile_scoring_models WHERE model_code = 'customer-profile' AND version_no = '2.0'"
    ).fetchone()
    if existing_default:
        db.execute(
            """UPDATE customer_profile_scoring_dimensions
               SET config_json = ?, updated_at = ?
               WHERE model_id = ? AND dimension_code = 'customer_risk' AND COALESCE(config_json, '') IN ('', '{}')""",
            (json.dumps({"baseScore": 20}, ensure_ascii=False), now, existing_default["id"]),
        )
        db.execute(
            """UPDATE customer_profile_scoring_dimensions
               SET config_json = ?, updated_at = ?
               WHERE model_id = ? AND dimension_code = 'customer_value' AND COALESCE(config_json, '') IN ('', '{}')""",
            (json.dumps({"sourceDimensions": ["relationship_coverage", "growth_potential", "project_potential", "customer_risk"], "inverseDimensions": ["customer_risk"]}, ensure_ascii=False), now, existing_default["id"]),
        )
        return
    if db.execute("SELECT COUNT(*) FROM customer_profile_scoring_models").fetchone()[0]:
        return
    cur = db.execute(
        """INSERT INTO customer_profile_scoring_models
           (model_code, name, version_no, status, target_scope, description, is_default, created_at, updated_at, published_at)
           VALUES ('customer-profile', '客户画像评分模型', '2.0', 'active', 'customer_profile', ?, 1, ?, ?, ?)""",
        ("支持客户价值、增长潜力、关系覆盖、项目潜力和风险评分的可配置版本。", now, now, now),
    )
    model_id = cur.lastrowid
    dimensions = [
        ("relationship_coverage", "关系覆盖评分", "rules", 25, ["relationship_coverage"], ["personCount", "roleCount"]),
        ("growth_potential", "增长潜力评分", "rules", 30, ["growth_direction", "business_model"], ["projectCount", "opportunityCount", "activeOpportunityAmount", "hasGrowthDirection"]),
        ("project_potential", "项目潜力评分", "rules", 25, ["business_model", "strategic_importance"], ["projectCount", "opportunityCount"]),
        ("customer_risk", "风险评分", "rules", 20, ["customer_risk"], ["riskFactCount", "activeRiskSignal"]),
        ("customer_value", "客户价值评分", "weighted_average", 0, ["strategic_importance"], ["relationship_coverage", "growth_potential", "project_potential", "customer_risk"]),
    ]
    dimension_ids = {}
    for order, (code, name, calculation_type, weight, fact_codes, metrics) in enumerate(dimensions, 1):
        dimension_cur = db.execute(
            """INSERT INTO customer_profile_scoring_dimensions
               (model_id, dimension_code, name, calculation_type, weight, source_fact_codes_json,
                source_metrics_json, sort_order, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (model_id, code, name, calculation_type, weight, json.dumps(fact_codes, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False), order, now, now),
        )
        dimension_ids[code] = dimension_cur.lastrowid
    db.execute(
        "UPDATE customer_profile_scoring_dimensions SET config_json = ? WHERE id = ?",
        (json.dumps({"baseScore": 20}, ensure_ascii=False), dimension_ids["customer_risk"]),
    )
    db.execute(
        "UPDATE customer_profile_scoring_dimensions SET config_json = ? WHERE id = ?",
        (json.dumps({"sourceDimensions": ["relationship_coverage", "growth_potential", "project_potential", "customer_risk"], "inverseDimensions": ["customer_risk"]}, ensure_ascii=False), dimension_ids["customer_value"]),
    )
    rules = [
        ("relationship.person", "关键人覆盖", "relationship_coverage", {"metric": "personCount", "operator": ">=", "value": 1}, 25, 10, "至少识别到1位关键人。"),
        ("relationship.role", "业务角色覆盖", "relationship_coverage", {"metric": "roleCount", "operator": ">=", "value": 1}, 25, 20, "至少识别到1类业务角色。"),
        ("relationship.role_depth", "多角色覆盖", "relationship_coverage", {"metric": "roleCount", "operator": ">=", "value": 3}, 25, 30, "已覆盖3类及以上业务角色。"),
        ("growth.project", "项目储备", "growth_potential", {"metric": "projectCount", "operator": ">=", "value": 1}, 20, 10, "客户存在关联项目。"),
        ("growth.opportunity", "在途商机", "growth_potential", {"metric": "opportunityCount", "operator": ">=", "value": 1}, 25, 20, "客户存在在途商机。"),
        ("growth.amount", "商机规模", "growth_potential", {"metric": "activeOpportunityAmount", "operator": ">=", "value": 1000000}, 30, 30, "在途商机金额达到重点规模。"),
        ("growth.direction", "增长方向", "growth_potential", {"metric": "hasGrowthDirection", "operator": "=", "value": True}, 25, 40, "已识别客户增长方向。"),
        ("project.project", "项目数量", "project_potential", {"metric": "projectCount", "operator": ">=", "value": 1}, 40, 10, "客户存在项目储备。"),
        ("project.opportunity", "项目商机", "project_potential", {"metric": "opportunityCount", "operator": ">=", "value": 1}, 30, 20, "客户存在项目型商机。"),
        ("project.scale", "多项目储备", "project_potential", {"metric": "opportunityCount", "operator": ">=", "value": 3}, 30, 30, "客户存在多个在途商机。"),
        ("risk.fact", "风险事实", "customer_risk", {"metric": "riskFactCount", "operator": ">=", "value": 1}, 40, 10, "画像中存在客户风险事实。"),
        ("risk.signal", "商机风险信号", "customer_risk", {"metric": "activeRiskSignal", "operator": "=", "value": True}, 35, 20, "在途商机存在风险描述。"),
    ]
    for code, name, dimension_code, condition, score, priority, explanation in rules:
        db.execute(
            """INSERT INTO customer_profile_scoring_rules
               (model_id, dimension_id, rule_code, name, condition_json, score, priority, explanation, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (model_id, dimension_ids[dimension_code], code, name, json.dumps(condition, ensure_ascii=False), score, priority, explanation, now, now),
        )

RELATIONSHIP_ENTITY_TYPES = {"Customer", "Organization", "Person", "Project", "Opportunity", "Agent"}

def relationship_score_level(score):
    score = int(score or 0)
    if score >= 80:
        return "强关系"
    if score >= 50:
        return "中关系"
    if score > 0:
        return "弱关系"
    return "未知关系"

def relationship_entity_name(db, entity_type, entity_ref_id):
    queries = {
        "Customer": "SELECT name FROM customers WHERE id = ?",
        "Person": "SELECT name FROM persons WHERE id = ?",
        "Project": "SELECT name FROM projects WHERE id = ?",
        "Opportunity": "SELECT name FROM opportunities WHERE id = ?",
        "Agent": "SELECT name FROM agents WHERE id = ?",
    }
    if entity_type in queries:
        row = db.execute(queries[entity_type], (entity_ref_id,)).fetchone()
        return row["name"] if row else None
    ref = str(entity_ref_id)
    if ref.startswith("customer:"):
        ref = ref.split(":", 1)[1]
        row = db.execute("SELECT name FROM customer_organizations WHERE id = ?", (ref,)).fetchone()
        return row["name"] if row else None
    if ref.startswith("sales:"):
        ref = ref.split(":", 1)[1]
        row = db.execute("SELECT name FROM sales_organizations WHERE id = ?", (ref,)).fetchone()
        return row["name"] if row else None
    row = db.execute(
        "SELECT name FROM customer_organizations WHERE id = ?",
        (entity_ref_id,),
    ).fetchone()
    if row:
        return row["name"]
    row = db.execute("SELECT name FROM sales_organizations WHERE id = ?", (entity_ref_id,)).fetchone()
    return row["name"] if row else None

def ensure_relationship_entity(db, entity_type, entity_ref_id, entity_name=None, metadata=None, now=None):
    entity_type = str(entity_type or "").strip()
    entity_ref_id = str(entity_ref_id or "").strip()
    if entity_type not in RELATIONSHIP_ENTITY_TYPES or not entity_ref_id:
        raise ValueError("entityType and entityRefId are required")
    now = now or datetime.now(timezone.utc).isoformat()
    resolved_name = str(entity_name or "").strip() or relationship_entity_name(db, entity_type, entity_ref_id)
    if not resolved_name:
        raise ValueError(f"{entity_type} entity not found")
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    db.execute(
        """INSERT INTO relationship_entities
           (entity_type, entity_ref_id, entity_name, metadata_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(entity_type, entity_ref_id)
           DO UPDATE SET entity_name = excluded.entity_name,
                         metadata_json = CASE WHEN excluded.metadata_json = '{}' THEN relationship_entities.metadata_json ELSE excluded.metadata_json END,
                         updated_at = excluded.updated_at""",
        (entity_type, entity_ref_id, resolved_name, metadata_json, now, now),
    )
    return db.execute(
        "SELECT * FROM relationship_entities WHERE entity_type = ? AND entity_ref_id = ?",
        (entity_type, entity_ref_id),
    ).fetchone()

def relationship_type_row(db, code=None, type_id=None):
    if type_id is not None:
        return db.execute("SELECT * FROM relationship_types WHERE id = ?", (type_id,)).fetchone()
    return db.execute("SELECT * FROM relationship_types WHERE code = ?", (code,)).fetchone()

def upsert_relationship(db, source_entity_id, target_entity_id, relationship_type_id, payload=None, now=None):
    payload = payload or {}
    now = now or datetime.now(timezone.utc).isoformat()
    score = max(0, min(100, int(payload.get("strengthScore", payload.get("score", 0)) or 0)))
    status = str(payload.get("status", "active")).strip() or "active"
    confidence = max(0, min(100, int(payload.get("confidence", 0) or 0)))
    db.execute(
        """INSERT INTO relationships
           (source_entity_id, target_entity_id, relationship_type_id,
            strength_score, strength_level, status, confidence, last_contact_at,
            interaction_count, first_established_at, last_evaluated_at, notes,
            evidence_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_entity_id, target_entity_id, relationship_type_id)
           DO UPDATE SET strength_score = excluded.strength_score,
                         strength_level = excluded.strength_level,
                         status = excluded.status,
                         confidence = excluded.confidence,
                         last_contact_at = COALESCE(excluded.last_contact_at, relationships.last_contact_at),
                         interaction_count = MAX(relationships.interaction_count, excluded.interaction_count),
                         first_established_at = COALESCE(relationships.first_established_at, excluded.first_established_at),
                         last_evaluated_at = COALESCE(excluded.last_evaluated_at, relationships.last_evaluated_at),
                         notes = excluded.notes,
                         evidence_json = excluded.evidence_json,
                         updated_at = excluded.updated_at""",
        (
            source_entity_id,
            target_entity_id,
            relationship_type_id,
            score,
            relationship_score_level(score),
            status,
            confidence,
            payload.get("lastContactAt"),
            max(0, int(payload.get("interactionCount", 0) or 0)),
            payload.get("firstEstablishedAt") or now,
            payload.get("lastEvaluatedAt") or now,
            str(payload.get("notes", "")).strip(),
            json.dumps(payload.get("evidence") or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    return db.execute(
        """SELECT * FROM relationships
           WHERE source_entity_id = ? AND target_entity_id = ? AND relationship_type_id = ?""",
        (source_entity_id, target_entity_id, relationship_type_id),
    ).fetchone()

def seed_relationship_ontology(db, now):
    # 组织主键来自两棵独立组织树，关系层使用命名空间避免数字 ID 碰撞。
    for row in db.execute(
        "SELECT id, entity_ref_id FROM relationship_entities WHERE entity_type = 'Organization'"
    ).fetchall():
        ref = str(row["entity_ref_id"])
        if ":" in ref:
            continue
        if db.execute("SELECT 1 FROM customer_organizations WHERE id = ?", (ref,)).fetchone():
            db.execute("UPDATE relationship_entities SET entity_ref_id = ? WHERE id = ?", (f"customer:{ref}", row["id"]))
        elif db.execute("SELECT 1 FROM sales_organizations WHERE id = ?", (ref,)).fetchone():
            db.execute("UPDATE relationship_entities SET entity_ref_id = ? WHERE id = ?", (f"sales:{ref}", row["id"]))
    for code, name, source_type, target_type, category, description in RELATIONSHIP_TYPE_DEFINITIONS:
        db.execute(
            """INSERT OR IGNORE INTO relationship_types
               (code, name, source_entity_type, target_entity_type, category, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, name, source_type, target_type, category, description, now, now),
        )
    for table, entity_type, id_column, ref_prefix in [
        ("customers", "Customer", "id", ""),
        ("customer_organizations", "Organization", "id", "customer:"),
        ("persons", "Person", "id", ""),
        ("projects", "Project", "id", ""),
        ("opportunities", "Opportunity", "id", ""),
        ("agents", "Agent", "id", ""),
    ]:
        for row in db.execute(f"SELECT {id_column} AS id, name FROM {table}").fetchall():
            ensure_relationship_entity(db, entity_type, f"{ref_prefix}{row['id']}", row["name"], now=now)
    for row in db.execute("SELECT id, name FROM sales_organizations").fetchall():
        ensure_relationship_entity(db, "Organization", f"sales:{row['id']}", row["name"], now=now)

    def seed_legacy(source_type, source_id, target_type, target_id, type_code, score=0, status="active", notes=""):
        source = ensure_relationship_entity(db, source_type, source_id, now=now)
        target = ensure_relationship_entity(db, target_type, target_id, now=now)
        rel_type = relationship_type_row(db, code=type_code)
        if source and target and rel_type:
            upsert_relationship(db, source["id"], target["id"], rel_type["id"], {
                "strengthScore": score,
                "status": status,
                "notes": notes,
                "confidence": 80,
            }, now)

    customer_roles = {
        "负责人": "person_customer_owner", "联系人": "person_customer_contact",
        "决策人": "person_customer_decision_maker", "影响人": "person_customer_influencer",
        "采购负责人": "person_customer_procurement_owner", "技术负责人": "person_customer_technical_owner",
    }
    for row in db.execute("SELECT customer_id, person_id, role FROM customer_persons").fetchall():
        seed_legacy("Person", row["person_id"], "Customer", row["customer_id"], customer_roles.get(row["role"], "person_customer_contact"))
    project_roles = {
        "项目负责人": "person_project_owner", "甲方代表": "person_project_client_representative",
        "设计负责人": "person_project_design_lead", "施工负责人": "person_project_contractor_lead",
        "采购负责人": "person_project_procurement_owner",
    }
    for row in db.execute("SELECT project_id, person_id, role FROM project_persons").fetchall():
        seed_legacy("Person", row["person_id"], "Project", row["project_id"], project_roles.get(row["role"], "person_project_owner"))
    opportunity_roles = {
        "业务发起人": "person_opportunity_sponsor", "决策人": "person_opportunity_decision_maker",
        "技术推动者": "person_opportunity_influencer", "采购把关人": "person_opportunity_decision_maker",
    }
    for row in db.execute("SELECT opportunity_id, person_id, role, influence_level, relationship_status, notes FROM opportunity_persons").fetchall():
        score = {"高": 85, "中": 60, "低": 30}.get(row["influence_level"], 0)
        status = "inactive" if row["relationship_status"] == "已失联" else "active"
        seed_legacy("Person", row["person_id"], "Opportunity", row["opportunity_id"], opportunity_roles.get(row["role"], "person_opportunity_influencer"), score, status, row["notes"])
    party_roles = {
        "甲方代表": "person_project_client_representative", "设计院": "person_project_design_lead",
        "总包": "person_project_contractor_lead", "采购负责人": "person_project_procurement_owner",
    }
    for row in db.execute("SELECT project_id, person_id, party_type, notes FROM project_parties WHERE person_id IS NOT NULL").fetchall():
        seed_legacy("Person", row["person_id"], "Project", row["project_id"], party_roles.get(row["party_type"], "person_project_owner"), notes=row["notes"])

def seed_relationship_score_config(db, now):
    weights = DEFAULT_RELATIONSHIP_SCORE_WEIGHTS
    db.execute(
        """INSERT OR IGNORE INTO relationship_score_configs
           (code, name, interaction_frequency_weight, recency_weight,
            influence_weight, history_weight, duration_weight, status,
            is_default, description, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?)""",
        (
            "relationship-score-v1",
            "关系强度自动评分 V1",
            weights["interaction_frequency"],
            weights["recency"],
            weights["influence"],
            weights["history"],
            weights["duration"],
            "按互动频率、最近联系、职位影响力、历史合作和关系持续时间自动计算关系强度。",
            now,
            now,
        ),
    )

def relationship_item(db, row):
    item = dict(row)
    item["sourceEntity"] = {
        "id": item.pop("source_entity_id"), "type": item.pop("source_entity_type"),
        "refId": item.pop("source_entity_ref_id"), "name": item.pop("source_entity_name"),
    }
    item["targetEntity"] = {
        "id": item.pop("target_entity_id"), "type": item.pop("target_entity_type"),
        "refId": item.pop("target_entity_ref_id"), "name": item.pop("target_entity_name"),
    }
    item["relationshipType"] = {
        "id": item.pop("relationship_type_id"), "code": item.pop("relationship_type_code"),
        "name": item.pop("relationship_type_name"), "category": item.pop("relationship_category"),
    }
    return item

def get_relationships(db, entity_type=None, entity_ref_id=None, relationship_type_code=None, status=None):
    clauses = []
    values = []
    if entity_type and entity_ref_id is not None:
        clauses.append("(se.entity_type = ? AND se.entity_ref_id = ? OR te.entity_type = ? AND te.entity_ref_id = ?)")
        values.extend([entity_type, str(entity_ref_id), entity_type, str(entity_ref_id)])
    if relationship_type_code:
        clauses.append("rt.code = ?")
        values.append(relationship_type_code)
    if status:
        clauses.append("r.status = ?")
        values.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"""SELECT r.*, se.entity_type AS source_entity_type, se.entity_ref_id AS source_entity_ref_id,
                   se.entity_name AS source_entity_name, te.entity_type AS target_entity_type,
                   te.entity_ref_id AS target_entity_ref_id, te.entity_name AS target_entity_name,
                   rt.code AS relationship_type_code, rt.name AS relationship_type_name,
                   rt.category AS relationship_category
            FROM relationships r
            JOIN relationship_entities se ON se.id = r.source_entity_id
            JOIN relationship_entities te ON te.id = r.target_entity_id
            JOIN relationship_types rt ON rt.id = r.relationship_type_id
            {where}
            ORDER BY r.strength_score DESC, r.updated_at DESC, r.id DESC""",
        tuple(values),
    ).fetchall()
    return [relationship_item(db, row) for row in rows]

def get_relationship_detail(db, relationship_id):
    rows = db.execute(
        """SELECT r.*, se.entity_type AS source_entity_type, se.entity_ref_id AS source_entity_ref_id,
                  se.entity_name AS source_entity_name, te.entity_type AS target_entity_type,
                  te.entity_ref_id AS target_entity_ref_id, te.entity_name AS target_entity_name,
                  rt.code AS relationship_type_code, rt.name AS relationship_type_name,
                  rt.category AS relationship_category
           FROM relationships r
           JOIN relationship_entities se ON se.id = r.source_entity_id
           JOIN relationship_entities te ON te.id = r.target_entity_id
           JOIN relationship_types rt ON rt.id = r.relationship_type_id
           WHERE r.id = ?""",
        (relationship_id,),
    ).fetchone()
    if not rows:
        return None
    item = relationship_item(db, rows)
    item["scores"] = [dict(x) for x in db.execute(
        "SELECT * FROM relationship_scores WHERE relationship_id = ? ORDER BY calculated_at DESC, id DESC",
        (relationship_id,),
    ).fetchall()]
    item["events"] = [dict(x) for x in db.execute(
        "SELECT * FROM relationship_events WHERE relationship_id = ? ORDER BY event_time DESC, id DESC",
        (relationship_id,),
    ).fetchall()]
    item["scoreConfig"] = get_relationship_score_config(db)
    item["latestScore"] = item["scores"][0] if item["scores"] else None
    return item

def relationship_score_config_item(row):
    if not row:
        weights = dict(DEFAULT_RELATIONSHIP_SCORE_WEIGHTS)
        return {
            "id": None,
            "code": "relationship-score-v1",
            "name": "关系强度自动评分 V1",
            "weights": weights,
            "status": "active",
            "isDefault": True,
            "description": "按互动频率、最近联系、职位影响力、历史合作和关系持续时间自动计算关系强度。",
        }
    item = dict(row)
    weights = {
        "interaction_frequency": float(item.pop("interaction_frequency_weight")),
        "recency": float(item.pop("recency_weight")),
        "influence": float(item.pop("influence_weight")),
        "history": float(item.pop("history_weight")),
        "duration": float(item.pop("duration_weight")),
    }
    total = sum(weights.values())
    if total > 1:
        weights = {factor: value / 100 for factor, value in weights.items()}
        total = sum(weights.values())
    if total > 0 and abs(total - 1) > 0.000001:
        weights = {factor: round(value / total, 6) for factor, value in weights.items()}
    item["weights"] = weights
    item["isDefault"] = bool(item.pop("is_default", 0))
    return item

def get_relationship_score_config(db):
    published = db.execute(
        """SELECT v.version_id, v.model_id, v.version_no
           FROM relationship_score_model_versions v
           WHERE v.status = 'PUBLISHED'
           ORDER BY v.published_time DESC, v.created_time DESC, v.version_id DESC
           LIMIT 1"""
    ).fetchone()
    if published:
        dimensions = db.execute(
            """SELECT dimension_code, weight
               FROM relationship_score_dimensions
               WHERE version_id = ? AND enabled = 1""",
            (published["version_id"],),
        ).fetchall()
        weights = {factor: 0.0 for factor in RELATIONSHIP_SCORE_FACTORS}
        for dimension in dimensions:
            if dimension["dimension_code"] in weights:
                weights[dimension["dimension_code"]] = float(dimension["weight"])
        total = sum(weights.values())
        if total > 0:
            weights = {factor: round(value / total, 6) for factor, value in weights.items()}
        return {
            "id": None,
            "code": f"{published['model_id']}:{published['version_no']}",
            "name": f"已发布关系评分版本 {published['version_no']}",
            "weights": weights,
            "status": "active",
            "isDefault": True,
            "description": "当前由已发布 RelationshipScoreModelVersion 提供评分维度权重。",
            "modelId": published["model_id"],
            "versionId": published["version_id"],
            "versionNo": published["version_no"],
        }
    row = db.execute(
        """SELECT * FROM relationship_score_configs
           WHERE status = 'active'
           ORDER BY is_default DESC, id DESC LIMIT 1"""
    ).fetchone()
    return relationship_score_config_item(row)

def _relationship_score_model_item(row):
    return dict(row) if row else None

def _validate_relationship_score_model_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")

    model_id = str(payload.get("model_id", payload.get("modelId", ""))).strip()
    model_name = str(payload.get("model_name", payload.get("modelName", ""))).strip()
    description = str(payload.get("description", "")).strip()
    status = str(payload.get("status", "DRAFT")).strip().upper()
    created_by = str(payload.get("created_by", payload.get("createdBy", ""))).strip()

    if not partial and not model_id:
        raise ValueError("model_id is required")
    if "model_name" in payload or "modelName" in payload or not partial:
        if not model_name:
            raise ValueError("model_name is required")
    if "created_by" in payload or "createdBy" in payload or not partial:
        if not created_by:
            raise ValueError("created_by is required")
    if "status" in payload and status not in RELATIONSHIP_SCORE_MODEL_STATUSES:
        raise ValueError("status must be one of DRAFT, TESTING, PUBLISHED, DISABLED")

    return {
        "model_id": model_id,
        "model_name": model_name,
        "description": description,
        "status": status,
        "created_by": created_by,
    }

def list_relationship_score_models(db, status=None):
    clauses = []
    values = []
    if status:
        normalized_status = str(status).strip().upper()
        if normalized_status not in RELATIONSHIP_SCORE_MODEL_STATUSES:
            raise ValueError("status must be one of DRAFT, TESTING, PUBLISHED, DISABLED")
        clauses.append("status = ?")
        values.append(normalized_status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"""SELECT model_id, model_name, description, status, created_by,
                   created_time, updated_time
            FROM relationship_score_models
            {where}
            ORDER BY updated_time DESC, model_id DESC""",
        tuple(values),
    ).fetchall()
    return [_relationship_score_model_item(row) for row in rows]

def get_relationship_score_model(db, model_id):
    row = db.execute(
        """SELECT model_id, model_name, description, status, created_by,
                  created_time, updated_time
           FROM relationship_score_models
           WHERE model_id = ?""",
        (str(model_id).strip(),),
    ).fetchone()
    return _relationship_score_model_item(row)

def create_relationship_score_model(db, payload, now=None):
    values = _validate_relationship_score_model_payload(payload)
    now = now or datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            """INSERT INTO relationship_score_models
               (model_id, model_name, description, status, created_by, created_time, updated_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                values["model_id"],
                values["model_name"],
                values["description"],
                values["status"],
                values["created_by"],
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("model_id already exists") from exc
    return get_relationship_score_model(db, values["model_id"])

def update_relationship_score_model(db, model_id, payload, now=None):
    values = _validate_relationship_score_model_payload(payload, partial=True)
    existing = get_relationship_score_model(db, model_id)
    if not existing:
        raise LookupError("relationship score model not found")
    if values["model_id"] and values["model_id"] != str(model_id).strip():
        raise ValueError("model_id cannot be changed")

    fields = []
    params = []
    for key in ("model_name", "description", "status"):
        if key in payload or key == "model_name" and "modelName" in payload:
            fields.append(f"{key} = ?")
            params.append(values[key])
    if "created_by" in payload or "createdBy" in payload:
        fields.append("created_by = ?")
        params.append(values["created_by"])
    if not fields:
        raise ValueError("at least one editable field is required")

    now = now or datetime.now(timezone.utc).isoformat()
    fields.append("updated_time = ?")
    params.extend([now, str(model_id).strip()])
    db.execute(
        f"UPDATE relationship_score_models SET {', '.join(fields)} WHERE model_id = ?",
        tuple(params),
    )
    return get_relationship_score_model(db, model_id)

def _relationship_score_model_version_item(row):
    return dict(row) if row else None

def _validate_relationship_score_model_version_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")

    version_id = str(payload.get("version_id", payload.get("versionId", ""))).strip()
    model_id = str(payload.get("model_id", payload.get("modelId", ""))).strip()
    version_no = str(payload.get("version_no", payload.get("versionNo", ""))).strip()
    status = str(payload.get("status", "DRAFT")).strip().upper()
    created_by = str(payload.get("created_by", payload.get("createdBy", ""))).strip()

    if not partial and not version_id:
        raise ValueError("version_id is required")
    if not partial and not model_id:
        raise ValueError("model_id is required")
    if not partial and not version_no:
        raise ValueError("version_no is required")
    if ("version_no" in payload or "versionNo" in payload or not partial) and not version_no:
        raise ValueError("version_no is required")
    if ("created_by" in payload or "createdBy" in payload or not partial) and not created_by:
        raise ValueError("created_by is required")
    if "status" in payload and status not in RELATIONSHIP_SCORE_MODEL_VERSION_STATUSES:
        raise ValueError("status must be one of DRAFT, TESTING, PUBLISHED, DISABLED")
    if status == "PUBLISHED" and "status" in payload:
        raise ValueError("published versions must be published through the publish API")

    return {
        "version_id": version_id,
        "model_id": model_id,
        "version_no": version_no,
        "status": status,
        "created_by": created_by,
    }

def list_relationship_score_model_versions(db, model_id, status=None):
    if not get_relationship_score_model(db, model_id):
        raise LookupError("relationship score model not found")
    clauses = ["model_id = ?"]
    values = [str(model_id).strip()]
    if status:
        normalized_status = str(status).strip().upper()
        if normalized_status not in RELATIONSHIP_SCORE_MODEL_VERSION_STATUSES:
            raise ValueError("status must be one of DRAFT, TESTING, PUBLISHED, DISABLED")
        clauses.append("status = ?")
        values.append(normalized_status)
    rows = db.execute(
        f"""SELECT version_id, model_id, version_no, status, created_by,
                   created_time, published_time
            FROM relationship_score_model_versions
            WHERE {' AND '.join(clauses)}
            ORDER BY version_no DESC, created_time DESC, version_id DESC""",
        tuple(values),
    ).fetchall()
    return [_relationship_score_model_version_item(row) for row in rows]

def get_relationship_score_model_version(db, model_id, version_id):
    row = db.execute(
        """SELECT version_id, model_id, version_no, status, created_by,
                  created_time, published_time
           FROM relationship_score_model_versions
           WHERE model_id = ? AND version_id = ?""",
        (str(model_id).strip(), str(version_id).strip()),
    ).fetchone()
    return _relationship_score_model_version_item(row)

def create_relationship_score_model_version(db, model_id, payload, now=None):
    if not get_relationship_score_model(db, model_id):
        raise LookupError("relationship score model not found")
    values = _validate_relationship_score_model_version_payload(payload)
    if values["model_id"] != str(model_id).strip():
        raise ValueError("model_id does not match the parent model")
    if values["status"] == "PUBLISHED":
        raise ValueError("new versions must be published through the publish API")
    now = now or datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            """INSERT INTO relationship_score_model_versions
               (version_id, model_id, version_no, status, created_by, created_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                values["version_id"],
                values["model_id"],
                values["version_no"],
                values["status"],
                values["created_by"],
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("version_id or version_no already exists") from exc
    seed_default_relationship_score_dimensions(db, values["version_id"])
    return get_relationship_score_model_version(db, model_id, values["version_id"])

def update_relationship_score_model_version(db, model_id, version_id, payload, now=None):
    existing = get_relationship_score_model_version(db, model_id, version_id)
    if not existing:
        raise LookupError("relationship score model version not found")
    if existing["status"] == "PUBLISHED":
        raise ValueError("published versions cannot be modified; create a new version")
    values = _validate_relationship_score_model_version_payload(payload, partial=True)
    if values["version_id"] and values["version_id"] != str(version_id).strip():
        raise ValueError("version_id cannot be changed")
    if values["model_id"] and values["model_id"] != str(model_id).strip():
        raise ValueError("model_id cannot be changed")

    fields = []
    params = []
    if "version_no" in payload or "versionNo" in payload:
        fields.append("version_no = ?")
        params.append(values["version_no"])
    if "status" in payload:
        fields.append("status = ?")
        params.append(values["status"])
    if "created_by" in payload or "createdBy" in payload:
        fields.append("created_by = ?")
        params.append(values["created_by"])
    if not fields:
        raise ValueError("at least one editable field is required")

    now = now or datetime.now(timezone.utc).isoformat()
    params.append(str(model_id).strip())
    params.append(str(version_id).strip())
    try:
        db.execute(
            f"""UPDATE relationship_score_model_versions
                SET {', '.join(fields)}
                WHERE model_id = ? AND version_id = ?""",
            tuple(params),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("version_no already exists") from exc
    return get_relationship_score_model_version(db, model_id, version_id)

def publish_relationship_score_model_version(db, model_id, version_id, now=None):
    existing = get_relationship_score_model_version(db, model_id, version_id)
    if not existing:
        raise LookupError("relationship score model version not found")
    if existing["status"] == "PUBLISHED":
        return existing
    validation = validate_relationship_score_model_version(db, model_id, version_id)
    if not validation["valid"]:
        raise ValueError(json.dumps(validation, ensure_ascii=False))

    now = now or datetime.now(timezone.utc).isoformat()
    db.execute(
        """UPDATE relationship_score_model_versions
           SET status = 'DISABLED'
           WHERE model_id = ? AND status = 'PUBLISHED' AND version_id <> ?""",
        (str(model_id).strip(), str(version_id).strip()),
    )
    db.execute(
        """UPDATE relationship_score_model_versions
           SET status = 'PUBLISHED', published_time = ?
           WHERE model_id = ? AND version_id = ?""",
        (now, str(model_id).strip(), str(version_id).strip()),
    )
    db.execute(
        """UPDATE relationship_score_models
           SET status = 'PUBLISHED', updated_time = ?
           WHERE model_id = ?""",
        (now, str(model_id).strip()),
    )
    return get_relationship_score_model_version(db, model_id, version_id)

def _relationship_score_dimension_item(row):
    if not row:
        return None
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    return item

def _validate_relationship_score_dimension_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    dimension_id = str(payload.get("dimension_id", payload.get("dimensionId", ""))).strip()
    version_id = str(payload.get("version_id", payload.get("versionId", ""))).strip()
    dimension_code = str(payload.get("dimension_code", payload.get("dimensionCode", ""))).strip()
    dimension_name = str(payload.get("dimension_name", payload.get("dimensionName", ""))).strip()
    description = str(payload.get("description", "")).strip()
    try:
        weight = float(payload.get("weight", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("weight must be numeric") from exc
    if not partial and not dimension_id:
        raise ValueError("dimension_id is required")
    if not partial and not version_id:
        raise ValueError("version_id is required")
    if not partial and not dimension_code:
        raise ValueError("dimension_code is required")
    if not partial and not dimension_name:
        raise ValueError("dimension_name is required")
    if "dimension_code" in payload or "dimensionCode" in payload or not partial:
        if not dimension_code:
            raise ValueError("dimension_code is required")
    if "dimension_name" in payload or "dimensionName" in payload or not partial:
        if not dimension_name:
            raise ValueError("dimension_name is required")
    if "weight" in payload and weight < 0:
        raise ValueError("weight must be non-negative")
    if "enabled" in payload and not isinstance(payload["enabled"], (bool, int)):
        raise ValueError("enabled must be boolean")
    return {
        "dimension_id": dimension_id,
        "version_id": version_id,
        "dimension_code": dimension_code,
        "dimension_name": dimension_name,
        "weight": weight,
        "enabled": int(bool(payload.get("enabled", True))),
        "description": description,
    }

def _relationship_score_model_version_for_dimension(db, version_id):
    row = db.execute(
        "SELECT version_id, status FROM relationship_score_model_versions WHERE version_id = ?",
        (str(version_id).strip(),),
    ).fetchone()
    if not row:
        raise LookupError("relationship score model version not found")
    return row

def _ensure_dimension_parent_model(db, model_id, version_id):
    if not get_relationship_score_model_version(db, model_id, version_id):
        raise LookupError("relationship score model version not found")

def _ensure_dimension_version_editable(db, version_id):
    version = _relationship_score_model_version_for_dimension(db, version_id)
    if version["status"] == "PUBLISHED":
        raise ValueError("published versions cannot modify dimensions; create a new version")
    return version

def list_relationship_score_dimensions(db, version_id):
    _relationship_score_model_version_for_dimension(db, version_id)
    rows = db.execute(
        """SELECT dimension_id, version_id, dimension_code, dimension_name,
                  weight, enabled, description
           FROM relationship_score_dimensions
           WHERE version_id = ?
           ORDER BY dimension_code, dimension_id""",
        (str(version_id).strip(),),
    ).fetchall()
    return [_relationship_score_dimension_item(row) for row in rows]

def get_relationship_score_dimension(db, version_id, dimension_id):
    row = db.execute(
        """SELECT dimension_id, version_id, dimension_code, dimension_name,
                  weight, enabled, description
           FROM relationship_score_dimensions
           WHERE version_id = ? AND dimension_id = ?""",
        (str(version_id).strip(), str(dimension_id).strip()),
    ).fetchone()
    return _relationship_score_dimension_item(row)

def create_relationship_score_dimension(db, version_id, payload):
    _ensure_dimension_version_editable(db, version_id)
    values = _validate_relationship_score_dimension_payload(payload)
    if values["version_id"] != str(version_id).strip():
        raise ValueError("version_id does not match the parent version")
    try:
        db.execute(
            """INSERT INTO relationship_score_dimensions
               (dimension_id, version_id, dimension_code, dimension_name,
                weight, enabled, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                values["dimension_id"],
                values["version_id"],
                values["dimension_code"],
                values["dimension_name"],
                values["weight"],
                values["enabled"],
                values["description"],
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("dimension_id or dimension_code already exists") from exc
    return get_relationship_score_dimension(db, version_id, values["dimension_id"])

def update_relationship_score_dimension(db, version_id, dimension_id, payload):
    _ensure_dimension_version_editable(db, version_id)
    existing = get_relationship_score_dimension(db, version_id, dimension_id)
    if not existing:
        raise LookupError("relationship score dimension not found")
    values = _validate_relationship_score_dimension_payload(payload, partial=True)
    if values["dimension_id"] and values["dimension_id"] != str(dimension_id).strip():
        raise ValueError("dimension_id cannot be changed")
    if values["version_id"] and values["version_id"] != str(version_id).strip():
        raise ValueError("version_id cannot be changed")

    fields = []
    params = []
    aliases = {
        "dimension_code": ("dimension_code", "dimensionCode"),
        "dimension_name": ("dimension_name", "dimensionName"),
        "weight": ("weight",),
        "enabled": ("enabled",),
        "description": ("description",),
    }
    for field, keys in aliases.items():
        if any(key in payload for key in keys):
            fields.append(f"{field} = ?")
            params.append(values[field])
    if not fields:
        raise ValueError("at least one editable field is required")
    params.extend([str(version_id).strip(), str(dimension_id).strip()])
    try:
        db.execute(
            f"""UPDATE relationship_score_dimensions
                SET {', '.join(fields)}
                WHERE version_id = ? AND dimension_id = ?""",
            tuple(params),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("dimension_code already exists") from exc
    return get_relationship_score_dimension(db, version_id, dimension_id)

def delete_relationship_score_dimension(db, version_id, dimension_id):
    _ensure_dimension_version_editable(db, version_id)
    cur = db.execute(
        """DELETE FROM relationship_score_dimensions
           WHERE version_id = ? AND dimension_id = ?""",
        (str(version_id).strip(), str(dimension_id).strip()),
    )
    if not cur.rowcount:
        raise LookupError("relationship score dimension not found")
    return {
        "status": "deleted",
        "version_id": str(version_id).strip(),
        "dimension_id": str(dimension_id).strip(),
    }

def seed_default_relationship_score_dimensions(db, version_id):
    for code, name, weight, description in DEFAULT_RELATIONSHIP_SCORE_DIMENSIONS:
        dimension_id = f"{version_id}-{code}"
        db.execute(
            """INSERT OR IGNORE INTO relationship_score_dimensions
               (dimension_id, version_id, dimension_code, dimension_name,
                weight, enabled, description)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (dimension_id, version_id, code, name, weight, description),
        )

def _relationship_score_rule_item(row):
    if not row:
        return None
    item = dict(row)
    item["condition"] = _json_value(item.pop("condition_json"), {})
    item["enabled"] = bool(item["enabled"])
    return item

def _validate_relationship_score_rule_condition(rule_type, condition):
    if not isinstance(condition, dict):
        raise ValueError("condition must be an object")
    rule_type = str(rule_type).strip().upper()
    if rule_type not in RELATIONSHIP_SCORE_RULE_TYPES:
        raise ValueError("rule_type must be one of RANGE, TIME, ENUM")

    field = str(condition.get("field", "")).strip()
    if not field:
        raise ValueError("condition.field is required")

    if rule_type == "RANGE":
        operator = str(condition.get("operator", "")).strip()
        if operator not in {">", ">=", "<", "<=", "=", "==", "!="}:
            raise ValueError("RANGE condition.operator is invalid")
        if "value" not in condition:
            raise ValueError("RANGE condition.value is required")
        try:
            float(condition["value"])
        except (TypeError, ValueError) as exc:
            raise ValueError("RANGE condition.value must be numeric") from exc
    elif rule_type == "TIME":
        if "withinDays" not in condition:
            raise ValueError("TIME condition.withinDays is required")
        try:
            within_days = int(condition["withinDays"])
        except (TypeError, ValueError) as exc:
            raise ValueError("TIME condition.withinDays must be an integer") from exc
        if within_days < 0:
            raise ValueError("TIME condition.withinDays must be non-negative")
    elif rule_type == "ENUM":
        operator = str(condition.get("operator", "=")).strip()
        if operator not in {"=", "==", "in", "contains"}:
            raise ValueError("ENUM condition.operator is invalid")
        if "value" not in condition:
            raise ValueError("ENUM condition.value is required")
        if operator == "in" and not isinstance(condition["value"], list):
            raise ValueError("ENUM condition.value must be an array for operator in")
    return condition

def _validate_relationship_score_rule_payload(payload, partial=False):
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    rule_id = str(payload.get("rule_id", payload.get("ruleId", ""))).strip()
    dimension_id = str(payload.get("dimension_id", payload.get("dimensionId", ""))).strip()
    rule_type = str(payload.get("rule_type", payload.get("ruleType", ""))).strip().upper()
    condition = payload.get("condition")
    try:
        score = float(payload.get("score", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("score must be numeric") from exc
    try:
        priority = int(payload.get("priority", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("priority must be an integer") from exc

    if not partial and not rule_id:
        raise ValueError("rule_id is required")
    if not partial and not dimension_id:
        raise ValueError("dimension_id is required")
    if not partial and not rule_type:
        raise ValueError("rule_type is required")
    if not partial and condition is None:
        raise ValueError("condition is required")
    if "rule_type" in payload or "ruleType" in payload or not partial:
        if rule_type not in RELATIONSHIP_SCORE_RULE_TYPES:
            raise ValueError("rule_type must be one of RANGE, TIME, ENUM")
    if "condition" in payload:
        _validate_relationship_score_rule_condition(rule_type, condition)
    if "score" in payload and not isinstance(payload["score"], (int, float, str)):
        raise ValueError("score must be numeric")
    if "priority" in payload and priority < 0:
        raise ValueError("priority must be non-negative")
    if "enabled" in payload and not isinstance(payload["enabled"], (bool, int)):
        raise ValueError("enabled must be boolean")
    return {
        "rule_id": rule_id,
        "dimension_id": dimension_id,
        "rule_type": rule_type,
        "condition": condition,
        "score": score,
        "priority": priority,
        "enabled": int(bool(payload.get("enabled", True))),
    }

def _ensure_rule_dimension_editable(db, dimension_id):
    row = _relationship_score_rule_dimension(db, dimension_id)
    if row["status"] == "PUBLISHED":
        raise ValueError("published versions cannot modify rules; create a new version")
    return row

def _relationship_score_rule_dimension(db, dimension_id):
    row = db.execute(
        """SELECT d.dimension_id, v.status
           FROM relationship_score_dimensions d
           JOIN relationship_score_model_versions v ON v.version_id = d.version_id
           WHERE d.dimension_id = ?""",
        (str(dimension_id).strip(),),
    ).fetchone()
    if not row:
        raise LookupError("relationship score dimension not found")
    return row

def list_relationship_score_rules(db, dimension_id):
    _relationship_score_rule_dimension(db, dimension_id)
    rows = db.execute(
        """SELECT rule_id, dimension_id, rule_type, condition_json,
                  score, priority, enabled
           FROM relationship_score_rules
           WHERE dimension_id = ?
           ORDER BY priority, rule_id""",
        (str(dimension_id).strip(),),
    ).fetchall()
    return [_relationship_score_rule_item(row) for row in rows]

def get_relationship_score_rule(db, dimension_id, rule_id):
    _relationship_score_rule_dimension(db, dimension_id)
    row = db.execute(
        """SELECT rule_id, dimension_id, rule_type, condition_json,
                  score, priority, enabled
           FROM relationship_score_rules
           WHERE dimension_id = ? AND rule_id = ?""",
        (str(dimension_id).strip(), str(rule_id).strip()),
    ).fetchone()
    return _relationship_score_rule_item(row)

def create_relationship_score_rule(db, dimension_id, payload):
    _ensure_rule_dimension_editable(db, dimension_id)
    values = _validate_relationship_score_rule_payload(payload)
    if values["dimension_id"] != str(dimension_id).strip():
        raise ValueError("dimension_id does not match the parent dimension")
    try:
        db.execute(
            """INSERT INTO relationship_score_rules
               (rule_id, dimension_id, rule_type, condition_json,
                score, priority, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                values["rule_id"],
                values["dimension_id"],
                values["rule_type"],
                json.dumps(values["condition"], ensure_ascii=False),
                values["score"],
                values["priority"],
                values["enabled"],
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("rule_id already exists") from exc
    return get_relationship_score_rule(db, dimension_id, values["rule_id"])

def update_relationship_score_rule(db, dimension_id, rule_id, payload):
    _ensure_rule_dimension_editable(db, dimension_id)
    existing = get_relationship_score_rule(db, dimension_id, rule_id)
    if not existing:
        raise LookupError("relationship score rule not found")
    validation_payload = dict(payload)
    if "condition" in validation_payload and "rule_type" not in validation_payload and "ruleType" not in validation_payload:
        validation_payload["rule_type"] = existing["rule_type"]
    values = _validate_relationship_score_rule_payload(validation_payload, partial=True)
    if values["rule_id"] and values["rule_id"] != str(rule_id).strip():
        raise ValueError("rule_id cannot be changed")
    if values["dimension_id"] and values["dimension_id"] != str(dimension_id).strip():
        raise ValueError("dimension_id cannot be changed")

    fields = []
    params = []
    if "rule_type" in payload or "ruleType" in payload:
        fields.append("rule_type = ?")
        params.append(values["rule_type"])
    if "condition" in payload:
        fields.append("condition_json = ?")
        params.append(json.dumps(values["condition"], ensure_ascii=False))
    if "score" in payload:
        fields.append("score = ?")
        params.append(values["score"])
    if "priority" in payload:
        fields.append("priority = ?")
        params.append(values["priority"])
    if "enabled" in payload:
        fields.append("enabled = ?")
        params.append(values["enabled"])
    if not fields:
        raise ValueError("at least one editable field is required")
    params.extend([str(dimension_id).strip(), str(rule_id).strip()])
    db.execute(
        f"""UPDATE relationship_score_rules
            SET {', '.join(fields)}
            WHERE dimension_id = ? AND rule_id = ?""",
        tuple(params),
    )
    return get_relationship_score_rule(db, dimension_id, rule_id)

def reorder_relationship_score_rules(db, dimension_id, rule_ids):
    _ensure_rule_dimension_editable(db, dimension_id)
    if not isinstance(rule_ids, list) or not rule_ids:
        raise ValueError("ruleIds must be a non-empty array")
    normalized = [str(rule_id).strip() for rule_id in rule_ids]
    if len(normalized) != len(set(normalized)):
        raise ValueError("ruleIds must not contain duplicates")
    rows = db.execute(
        "SELECT rule_id FROM relationship_score_rules WHERE dimension_id = ?",
        (str(dimension_id).strip(),),
    ).fetchall()
    existing_ids = {row["rule_id"] for row in rows}
    if set(normalized) != existing_ids:
        raise ValueError("ruleIds must contain every rule in the dimension exactly once")
    for priority, rule_id in enumerate(normalized):
        db.execute(
            "UPDATE relationship_score_rules SET priority = ? WHERE dimension_id = ? AND rule_id = ?",
            (priority, str(dimension_id).strip(), rule_id),
        )
    return list_relationship_score_rules(db, dimension_id)

def delete_relationship_score_rule(db, dimension_id, rule_id):
    _ensure_rule_dimension_editable(db, dimension_id)
    cur = db.execute(
        "DELETE FROM relationship_score_rules WHERE dimension_id = ? AND rule_id = ?",
        (str(dimension_id).strip(), str(rule_id).strip()),
    )
    if not cur.rowcount:
        raise LookupError("relationship score rule not found")
    return {"status": "deleted", "dimension_id": str(dimension_id).strip(), "rule_id": str(rule_id).strip()}

def evaluate_relationship_score_rule(rule, context, now=None):
    """解析并执行单条规则，返回是否命中。"""
    rule_type = str(rule["rule_type"]).upper()
    condition = rule["condition"] if isinstance(rule.get("condition"), dict) else _json_value(rule.get("condition_json"), {})
    _validate_relationship_score_rule_condition(rule_type, condition)
    context = context or {}
    actual = context.get(condition["field"])
    if rule_type == "RANGE":
        expected = float(condition["value"])
        actual = float(actual)
        return {
            ">": actual > expected, ">=": actual >= expected, "<": actual < expected,
            "<=": actual <= expected, "=": actual == expected, "==": actual == expected,
            "!=": actual != expected,
        }[condition["operator"]]
    if rule_type == "ENUM":
        operator = condition.get("operator", "=")
        expected = condition["value"]
        return (
            actual in expected if operator == "in"
            else expected in actual if operator == "contains" and isinstance(actual, (list, str))
            else actual == expected
        )
    if not actual:
        return False
    parsed = _parse_relationship_score_time(actual)
    now_dt = _parse_relationship_score_time(now) or datetime.now(timezone.utc)
    return parsed is not None and 0 <= (now_dt - parsed).total_seconds() <= int(condition["withinDays"]) * 86400

def _rules_conflict(left, right):
    left_condition = left["condition"]
    right_condition = right["condition"]
    if left_condition.get("field") != right_condition.get("field"):
        return False
    if left["rule_type"] != right["rule_type"]:
        return True
    if left["rule_type"] == "RANGE":
        left_value = float(left_condition["value"])
        right_value = float(right_condition["value"])
        left_operator = left_condition["operator"]
        right_operator = right_condition["operator"]
        if left_operator in {"=", "=="}:
            return evaluate_relationship_score_rule(right, {left_condition["field"]: left_value})
        if right_operator in {"=", "=="}:
            return evaluate_relationship_score_rule(left, {left_condition["field"]: right_value})
        if left_operator in {">", ">="} and right_operator in {">", ">="}:
            return True
        if left_operator in {"<", "<="} and right_operator in {"<", "<="}:
            return True
        return False
    if left["rule_type"] == "TIME":
        return True
    left_value = left_condition["value"]
    right_value = right_condition["value"]
    left_values = set(left_value if isinstance(left_value, list) else [left_value])
    right_values = set(right_value if isinstance(right_value, list) else [right_value])
    return bool(left_values & right_values)

def validate_relationship_score_model_version(db, model_id, version_id):
    version = get_relationship_score_model_version(db, model_id, version_id)
    errors = []
    if not version:
        raise LookupError("relationship score model version not found")
    if version["status"] != "TESTING":
        errors.append({
            "code": "INVALID_STATUS",
            "message": "只有 TESTING 状态的版本可以发布。",
            "status": version["status"],
        })

    dimensions = db.execute(
        """SELECT dimension_id, dimension_code, dimension_name, weight, enabled
           FROM relationship_score_dimensions
           WHERE version_id = ?
           ORDER BY dimension_code, dimension_id""",
        (version_id,),
    ).fetchall()
    enabled_dimensions = [row for row in dimensions if row["enabled"]]
    if not enabled_dimensions:
        errors.append({
            "code": "NO_ENABLED_DIMENSION",
            "message": "至少需要一个启用的评分维度。",
        })
    total_weight = sum(float(row["weight"] or 0) for row in enabled_dimensions)
    if enabled_dimensions and abs(total_weight - 1.0) > 0.000001:
        errors.append({
            "code": "INVALID_WEIGHT_SUM",
            "message": f"启用维度权重总和必须等于100%，当前为{round(total_weight * 100, 4)}%。",
            "actual": total_weight,
            "expected": 1.0,
        })

    for dimension in enabled_dimensions:
        rule_rows = db.execute(
            """SELECT rule_id, rule_type, condition_json, score, priority, enabled
               FROM relationship_score_rules
               WHERE dimension_id = ? AND enabled = 1
               ORDER BY priority, rule_id""",
            (dimension["dimension_id"],),
        ).fetchall()
        if not rule_rows:
            errors.append({
                "code": "NO_ENABLED_RULE",
                "message": f"维度“{dimension['dimension_name']}”至少需要一条启用规则。",
                "dimensionId": dimension["dimension_id"],
            })
            continue
        parsed_rules = []
        for row in rule_rows:
            try:
                condition = _json_value(row["condition_json"], {})
                _validate_relationship_score_rule_condition(row["rule_type"], condition)
                parsed_rules.append({
                    "rule_id": row["rule_id"],
                    "rule_type": row["rule_type"],
                    "condition": condition,
                })
            except ValueError as exc:
                errors.append({
                    "code": "INVALID_RULE",
                    "message": f"规则“{row['rule_id']}”无效：{exc}",
                    "dimensionId": dimension["dimension_id"],
                    "ruleId": row["rule_id"],
                })
        for index, left in enumerate(parsed_rules):
            for right in parsed_rules[index + 1:]:
                if _rules_conflict(left, right):
                    errors.append({
                        "code": "CONFLICTING_RULES",
                        "message": f"规则“{left['rule_id']}”与“{right['rule_id']}”条件冲突。",
                        "dimensionId": dimension["dimension_id"],
                        "ruleIds": [left["rule_id"], right["rule_id"]],
                    })
    return {
        "valid": not errors,
        "modelId": model_id,
        "versionId": version_id,
        "versionNo": version["version_no"],
        "errors": errors,
        "summary": {
            "dimensionCount": len(dimensions),
            "enabledDimensionCount": len(enabled_dimensions),
            "enabledWeight": total_weight,
        },
    }

def normalize_relationship_score_weights(payload):
    raw = payload.get("weights") if isinstance(payload.get("weights"), dict) else payload
    aliases = {
        "interaction_frequency": ("interaction_frequency", "interactionFrequency", "interactionFrequencyWeight"),
        "recency": ("recency", "recencyWeight"),
        "influence": ("influence", "influenceWeight"),
        "history": ("history", "historyWeight"),
        "duration": ("duration", "durationWeight"),
    }
    values = {}
    try:
        for factor in RELATIONSHIP_SCORE_FACTORS:
            value = next((raw[key] for key in aliases[factor] if key in raw), None)
            if value is None:
                raise ValueError(f"missing weight: {factor}")
            values[factor] = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc))
    if any(value < 0 for value in values.values()):
        raise ValueError("weights must be non-negative")
    total = sum(values.values())
    if total <= 0:
        raise ValueError("at least one weight is required")
    if total > 1:
        values = {factor: value / 100 for factor, value in values.items()}
        total = sum(values.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    return {factor: round(value / total, 6) for factor, value in values.items()}

def _parse_relationship_score_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

def calculate_interaction_frequency_score(events, interaction_count=0, now=None):
    """根据最近 90 天关系事件数量计算互动频率分。"""
    now_dt = _parse_relationship_score_time(now) or datetime.now(timezone.utc)
    valid_times = [
        _parse_relationship_score_time(event["event_time"])
        for event in events or []
    ]
    recent_count = sum(
        1 for event_time in valid_times
        if event_time and 0 <= (now_dt - event_time).days <= 90
    )
    if not recent_count:
        recent_count = min(max(int(interaction_count or 0), 0), 5)
    return min(100, recent_count * 20)

def calculate_recency_score(last_contact_at=None, events=None, now=None):
    """根据最近一次联系时间计算新鲜度分。"""
    now_dt = _parse_relationship_score_time(now) or datetime.now(timezone.utc)
    contact_times = [
        event_time
        for event_time in (
            _parse_relationship_score_time(event["event_time"])
            for event in events or []
        )
        if event_time
    ]
    last_contact = _parse_relationship_score_time(last_contact_at)
    if last_contact:
        contact_times.append(last_contact)
    if not contact_times:
        return 0
    age_days = max(0, (now_dt - max(contact_times)).days)
    return (
        100 if age_days <= 7
        else 85 if age_days <= 14
        else 70 if age_days <= 30
        else 45 if age_days <= 60
        else 25 if age_days <= 90
        else 10
    )

def calculate_influence_score(db, relationship):
    """根据职位影响力和关系类型计算影响力分。"""
    score = int(relationship["default_weight"] or 50)
    if relationship["source_entity_type"] != "Person":
        return max(0, min(100, score))

    influence_level = None
    if relationship["target_entity_type"] == "Opportunity":
        row = db.execute(
            """SELECT influence_level FROM opportunity_persons
               WHERE opportunity_id = ? AND person_id = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (relationship["target_entity_ref_id"], relationship["source_entity_ref_id"]),
        ).fetchone()
        influence_level = row["influence_level"] if row else None
    score = {"高": 100, "中": 70, "低": 40, "未知": 25}.get(influence_level, score)
    if not influence_level and "决策" in str(relationship["relationship_type_name"]):
        score = max(score, 90)
    return max(0, min(100, score))

def calculate_history_score(events):
    """根据历史关系事件数量和正向影响计算历史合作分。"""
    event_rows = list(events or [])
    positive_impact_score = min(
        30,
        max(
            0,
            sum(
                int(event["impact_score"] or 0)
                for event in event_rows
                if _parse_relationship_score_time(event["event_time"])
            ) * 3,
        ),
    )
    return min(100, min(70, len(event_rows) * 10) + positive_impact_score)

def calculate_duration_score(first_established_at=None, now=None):
    """根据关系建立时长计算持续时间分。"""
    now_dt = _parse_relationship_score_time(now) or datetime.now(timezone.utc)
    first_established = _parse_relationship_score_time(first_established_at)
    if not first_established:
        return 0
    duration_days = max(0, (now_dt - first_established).days)
    return (
        100 if duration_days >= 730
        else 85 if duration_days >= 365
        else 70 if duration_days >= 180
        else 45 if duration_days >= 90
        else 20 if duration_days >= 30
        else 0
    )

def calculate_relationship_strength_auto(db, relationship_id, now=None):
    """按五项可配置因素自动计算关系强度，并保存完整评分明细。"""
    now = now or datetime.now(timezone.utc).isoformat()
    relationship = db.execute(
        """SELECT r.*, se.entity_type AS source_entity_type, se.entity_ref_id AS source_entity_ref_id,
                  te.entity_type AS target_entity_type, te.entity_ref_id AS target_entity_ref_id,
                  rt.name AS relationship_type_name, rt.default_weight
           FROM relationships r
           JOIN relationship_entities se ON se.id = r.source_entity_id
           JOIN relationship_entities te ON te.id = r.target_entity_id
           JOIN relationship_types rt ON rt.id = r.relationship_type_id
           WHERE r.id = ?""",
        (relationship_id,),
    ).fetchone()
    if not relationship:
        raise LookupError("relationship not found")

    now_dt = _parse_relationship_score_time(now) or datetime.now(timezone.utc)
    events = db.execute(
        "SELECT event_time, impact_score FROM relationship_events WHERE relationship_id = ? ORDER BY event_time DESC, id DESC",
        (relationship_id,),
    ).fetchall()
    interaction_frequency_score = calculate_interaction_frequency_score(
        events, relationship["interaction_count"], now_dt
    )
    recency_score = calculate_recency_score(
        relationship["last_contact_at"], events, now_dt
    )
    influence_score = calculate_influence_score(db, relationship)
    history_score = calculate_history_score(events)
    duration_score = calculate_duration_score(
        relationship["first_established_at"], now_dt
    )

    config = get_relationship_score_config(db)
    weights = config["weights"]
    components = {
        "interaction_frequency": {"score": interaction_frequency_score, "weight": weights["interaction_frequency"], "weightedScore": round(interaction_frequency_score * weights["interaction_frequency"], 2)},
        "recency": {"score": recency_score, "weight": weights["recency"], "weightedScore": round(recency_score * weights["recency"], 2)},
        "influence": {"score": influence_score, "weight": weights["influence"], "weightedScore": round(influence_score * weights["influence"], 2)},
        "history": {"score": history_score, "weight": weights["history"], "weightedScore": round(history_score * weights["history"], 2)},
        "duration": {"score": duration_score, "weight": weights["duration"], "weightedScore": round(duration_score * weights["duration"], 2)},
    }

    score = round(
        sum(item["weightedScore"] for item in components.values())
    )
    level = relationship_score_level(score)
    reason = (
        f"自动评分 V1：互动频率 {interaction_frequency_score}（{round(weights['interaction_frequency'] * 100)}%）、"
        f"最近联系 {recency_score}（{round(weights['recency'] * 100)}%）、职位影响力 {influence_score}（{round(weights['influence'] * 100)}%）、"
        f"历史合作 {history_score}（{round(weights['history'] * 100)}%）、关系持续时间 {duration_score}（{round(weights['duration'] * 100)}%）。"
    )
    db.execute(
        """INSERT INTO relationship_scores
           (relationship_id, score, level, interaction_frequency_score,
            recency_score, influence_score, history_score, duration_score,
            weights_json, components_json, reason,
            calculated_by, calculated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            relationship_id,
            score,
            level,
            interaction_frequency_score,
            recency_score,
            influence_score,
            history_score,
            duration_score,
            json.dumps(weights, ensure_ascii=False),
            json.dumps(components, ensure_ascii=False),
            reason,
            "relationship_score_engine_v1",
            now,
        ),
    )
    db.execute(
        """UPDATE relationships
           SET strength_score = ?, strength_level = ?, last_evaluated_at = ?, updated_at = ?
           WHERE id = ?""",
        (score, level, now, now, relationship_id),
    )
    return get_relationship_detail(db, relationship_id)

def recalculate_relationship_scores(
    db,
    now=None,
    relationship_ids=None,
    relationship_type_code=None,
    updated_since=None,
    force=True,
):
    """批量重算关系评分，并返回可审计的执行统计。"""
    now = now or datetime.now(timezone.utc).isoformat()
    clauses = ["1 = 1"]
    values = []

    if relationship_ids is not None:
        normalized_ids = []
        for relationship_id in relationship_ids:
            try:
                normalized_ids.append(int(relationship_id))
            except (TypeError, ValueError) as exc:
                raise ValueError("relationshipIds must contain numeric ids") from exc
        normalized_ids = list(dict.fromkeys(normalized_ids))
        if not normalized_ids:
            return {
                "requested": 0,
                "calculated": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
            }
        placeholders = ",".join("?" for _ in normalized_ids)
        clauses.append(f"r.id IN ({placeholders})")
        values.extend(normalized_ids)

    if relationship_type_code:
        clauses.append("rt.code = ?")
        values.append(str(relationship_type_code).strip())

    if updated_since:
        if not _parse_relationship_score_time(updated_since):
            raise ValueError("updatedSince must be a valid ISO datetime")
        clauses.append("r.updated_at >= ?")
        values.append(str(updated_since))

    rows = db.execute(
        f"""SELECT r.id
            FROM relationships r
            JOIN relationship_types rt ON rt.id = r.relationship_type_id
            WHERE {' AND '.join(clauses)}
            ORDER BY r.id""",
        tuple(values),
    ).fetchall()
    results = []
    for row in rows:
        relationship_id = row["id"]
        if not force:
            existing = db.execute(
                """SELECT 1 FROM relationship_scores
                   WHERE relationship_id = ?
                     AND calculated_by = 'relationship_score_engine_v1'
                   LIMIT 1""",
                (relationship_id,),
            ).fetchone()
            if existing:
                results.append({"relationshipId": relationship_id, "status": "skipped"})
                continue
        try:
            detail = calculate_relationship_strength_auto(db, relationship_id, now)
            results.append({
                "relationshipId": relationship_id,
                "status": "calculated",
                "score": detail["strength_score"],
            })
        except (LookupError, sqlite3.Error, ValueError) as exc:
            results.append({
                "relationshipId": relationship_id,
                "status": "failed",
                "error": str(exc),
            })

    return {
        "requested": len(rows),
        "calculated": sum(1 for item in results if item["status"] == "calculated"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "results": results,
    }

def backfill_relationship_scores(db, now=None):
    """为旧关系补一次 V1 自动评分，避免每次启动重复写评分历史。"""
    return recalculate_relationship_scores(db, now=now, force=False)

def save_manual_relationship_score(db, relationship_id, payload, now=None):
    """保存人工评分；人工接口不得伪造自动评分来源。"""
    requested_source = payload.get("calculatedBy")
    if requested_source not in (None, "", "manual"):
        raise ValueError("manual scores must use calculatedBy=manual")
    mode = str(payload.get("mode", "manual") or "manual").strip().lower()
    if mode != "manual":
        raise ValueError("manual score mode must be manual")
    try:
        score = float(payload.get("score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("numeric score is required") from exc
    if not 0 <= score <= 100:
        raise ValueError("score must be between 0 and 100")
    relationship = db.execute(
        "SELECT * FROM relationships WHERE id = ?", (relationship_id,)
    ).fetchone()
    if not relationship:
        raise LookupError("relationship not found")

    now = now or datetime.now(timezone.utc).isoformat()
    score = round(score, 2)
    calculated_at = payload.get("calculatedAt") or now
    level = str(payload.get("level") or relationship_score_level(score))
    db.execute(
        """INSERT INTO relationship_scores
           (relationship_id, score, level, interaction_frequency_score,
            recency_score, influence_score, history_score, duration_score,
            reason, calculated_by, calculated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            relationship_id,
            score,
            level,
            payload.get("interactionFrequencyScore"),
            payload.get("recencyScore"),
            payload.get("influenceScore"),
            payload.get("historyScore"),
            payload.get("durationScore"),
            str(payload.get("reason", "")).strip(),
            "manual",
            calculated_at,
        ),
    )
    db.execute(
        """UPDATE relationships
           SET strength_score = ?, strength_level = ?, last_evaluated_at = ?, updated_at = ?
           WHERE id = ?""",
        (score, level, calculated_at, now, relationship_id),
    )
    return get_relationship_detail(db, relationship_id)

def get_relationship_network(db, entity_type, entity_ref_id):
    center = db.execute(
        "SELECT * FROM relationship_entities WHERE entity_type = ? AND entity_ref_id = ?",
        (entity_type, str(entity_ref_id)),
    ).fetchone()
    if not center:
        return None
    relations = get_relationships(db, entity_type, entity_ref_id)
    nodes = {center["id"]: {"id": center["id"], "type": center["entity_type"], "refId": center["entity_ref_id"], "name": center["entity_name"]}}
    edges = []
    for relation in relations:
        source = relation["sourceEntity"]
        target = relation["targetEntity"]
        nodes[source["id"]] = source
        nodes[target["id"]] = target
        edges.append({
            "id": relation["id"], "source": source["id"], "target": target["id"],
            "type": relation["relationshipType"], "score": relation["strength_score"],
            "level": relation["strength_level"], "status": relation["status"],
        })
    return {"center": nodes[center["id"]], "nodes": list(nodes.values()), "edges": edges}

def seed_relationship_analysis(db, entity_type, entity_ref_id):
    network = get_relationship_network(db, entity_type, entity_ref_id)
    if not network:
        return None
    return {
        "entity": network["center"],
        "network": network,
        "relationshipCount": len(network["edges"]),
        "strongRelationshipCount": sum(1 for edge in network["edges"] if edge["score"] >= 80),
        "gaps": ["决策人", "采购负责人", "技术负责人"] if entity_type == "Customer" else [],
    }

class RelationshipService:
    """关系认知层服务，统一承载网络查询、决策链推荐和关系变化计算。"""

    def __init__(self, db, now=None):
        self.db = db
        self.now = now or datetime.now(timezone.utc).isoformat()

    def query_customer_network(self, customer_id):
        result = seed_relationship_analysis(self.db, "Customer", customer_id)
        if not result:
            raise LookupError("customer relationship entity not found")
        return result

    def find_decision_makers(self, opportunity_id):
        opportunity = self.db.execute(
            "SELECT id, name, customer_id, project_id FROM opportunities WHERE id = ?",
            (opportunity_id,),
        ).fetchone()
        if not opportunity:
            raise LookupError("opportunity not found")
        relations = get_relationships(self.db, "Opportunity", opportunity_id)
        candidates = [
            relation for relation in relations
            if relation["sourceEntity"]["type"] == "Person"
            and "决策" in relation["relationshipType"]["name"]
        ]
        source = "opportunity"
        if not candidates and opportunity["customer_id"]:
            relations = get_relationships(self.db, "Customer", opportunity["customer_id"])
            candidates = [
                relation for relation in relations
                if relation["sourceEntity"]["type"] == "Person"
                and "决策" in relation["relationshipType"]["name"]
            ]
            source = "customer_fallback"
        return {
            "opportunity": dict(opportunity),
            "recommended": candidates[:10],
            "source": source,
            "reason": "按关系强度、影响力和最近活动排序；当前商机没有直接决策人时回退到客户关系。",
        }

    def recommend_breakthrough_path(self, project_id):
        project = self.db.execute(
            "SELECT id, name, customer_id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            raise LookupError("project not found")
        relations = get_relationships(self.db, "Project", project_id)
        candidates = [
            relation for relation in relations
            if relation["sourceEntity"]["type"] == "Person"
        ]
        source = "project"
        if not candidates and project["customer_id"]:
            candidates = [
                relation for relation in get_relationships(self.db, "Customer", project["customer_id"])
                if relation["sourceEntity"]["type"] == "Person"
            ]
            source = "customer_fallback"
        return {
            "project": dict(project),
            "recommendedPath": candidates[:10],
            "source": source,
            "reason": "优先推荐关系强度高、影响力高且有近期互动的联系人。",
        }

    def calculate_strength(self, relationship_id, payload):
        if str(payload.get("mode", "")).strip().lower() == "auto" or payload.get("score") in (None, ""):
            return calculate_relationship_strength_auto(self.db, relationship_id, self.now)
        return save_manual_relationship_score(
            self.db, relationship_id, payload, self.now
        )

    def record_change(self, relationship_id, payload):
        relationship = self.db.execute("SELECT * FROM relationships WHERE id = ?", (relationship_id,)).fetchone()
        if not relationship:
            raise LookupError("relationship not found")
        event_time = str(payload.get("eventTime") or self.now).strip()
        try:
            impact_score = int(payload.get("impactScore", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError("impactScore must be numeric")
        before_score = int(relationship["strength_score"] or 0)
        after_score = before_score
        event_cur = self.db.execute(
            """INSERT INTO relationship_events
               (relationship_id, event_type, event_time, source, impact_score,
                before_score, after_score, description, evidence_type,
                evidence_ref, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                relationship_id,
                str(payload.get("eventType", "interaction")).strip() or "interaction",
                event_time,
                str(payload.get("source", "manual")).strip() or "manual",
                impact_score,
                before_score,
                after_score,
                str(payload.get("description", "")).strip(),
                str(payload.get("evidenceType", "")).strip(),
                str(payload.get("evidenceRef", "")).strip(),
                str(payload.get("createdBy", "manual")).strip() or "manual",
                self.now,
            ),
        )
        self.db.execute(
            """UPDATE relationships
               SET strength_score = ?, strength_level = ?, last_contact_at = ?,
                   interaction_count = interaction_count + 1, updated_at = ?
               WHERE id = ?""",
            (after_score, relationship_score_level(after_score), event_time, self.now, relationship_id),
        )
        detail = calculate_relationship_strength_auto(self.db, relationship_id, self.now)
        self.db.execute(
            "UPDATE relationship_events SET after_score = ? WHERE id = ?",
            (detail["strength_score"], event_cur.lastrowid),
        )
        return get_relationship_detail(self.db, relationship_id)

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
            if path.startswith("/api/customers/") and path.endswith("/growth-intelligence-report"):
                try:
                    customer_id = int(path.split("/")[3])
                    report = get_latest_customer_growth_intelligence_report(db, customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if report is None:
                    return self.send_json({"error": "customer growth intelligence report not found"}, 404)
                return self.send_json(report)
            if path.startswith("/api/customer-growth-intelligence-reports/"):
                try:
                    report_id = int(path.rsplit("/", 1)[1])
                    return self.send_json(get_customer_growth_intelligence_report(db, report_id))
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid report id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-growth-intelligence/report":
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query.get("customerId", [""])[0])
                except ValueError:
                    return self.send_json({"error": "customerId is required"}, 400)
                report = get_latest_customer_growth_intelligence_report(db, customer_id)
                if report is None:
                    return self.send_json({"error": "customer growth intelligence report not found"}, 404)
                return self.send_json(report)
            if path.startswith("/api/customers/") and path.endswith("/growth-prediction"):
                try:
                    customer_id = int(path.split("/")[3])
                    prediction = get_latest_customer_growth_prediction(db, customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if prediction is None:
                    return self.send_json({"error": "customer growth prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customer-growth-predictions/"):
                try:
                    prediction_id = int(path.rsplit("/", 1)[1])
                    return self.send_json(get_customer_growth_prediction(db, prediction_id))
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid prediction id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-growth/prediction":
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query.get("customerId", [""])[0])
                except ValueError:
                    return self.send_json({"error": "customerId is required"}, 400)
                prediction = get_latest_customer_growth_prediction(db, customer_id)
                if prediction is None:
                    return self.send_json({"error": "customer growth prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customers/") and path.endswith("/value-prediction"):
                try:
                    customer_id = int(path.split("/")[3])
                    prediction = get_latest_customer_value_prediction(db, customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if prediction is None:
                    return self.send_json({"error": "customer value prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customer-value-predictions/"):
                try:
                    prediction_id = int(path.rsplit("/", 1)[1])
                    return self.send_json(get_customer_value_prediction(db, prediction_id))
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid prediction id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-value/prediction":
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query.get("customerId", [""])[0])
                except ValueError:
                    return self.send_json({"error": "customerId is required"}, 400)
                prediction = get_latest_customer_value_prediction(db, customer_id)
                if prediction is None:
                    return self.send_json({"error": "customer value prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customers/") and path.endswith("/conversion-prediction"):
                try:
                    customer_id = int(path.split("/")[3])
                    prediction = get_latest_customer_conversion_prediction(db, customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if prediction is None:
                    return self.send_json({"error": "customer conversion prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customer-conversion-predictions/"):
                try:
                    prediction_id = int(path.rsplit("/", 1)[1])
                    return self.send_json(get_customer_conversion_prediction(db, prediction_id))
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid prediction id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-conversion/prediction":
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query.get("customerId", [""])[0])
                except ValueError:
                    return self.send_json({"error": "customerId is required"}, 400)
                prediction = get_latest_customer_conversion_prediction(db, customer_id)
                if prediction is None:
                    return self.send_json({"error": "customer conversion prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customers/") and path.endswith("/potential-prediction"):
                try:
                    customer_id = int(path.split("/")[3])
                    prediction = get_latest_customer_potential_prediction(db, customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                if prediction is None:
                    return self.send_json({"error": "customer potential prediction not found"}, 404)
                return self.send_json(prediction)
            if path.startswith("/api/customer-potential-predictions/"):
                try:
                    prediction_id = int(path.rsplit("/", 1)[1])
                    return self.send_json(get_prediction_by_id(db, prediction_id))
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid prediction id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-potential/prediction":
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query.get("customerId", [""])[0])
                except ValueError:
                    return self.send_json({"error": "customerId is required"}, 400)
                prediction = get_latest_customer_potential_prediction(db, customer_id)
                if prediction is None:
                    return self.send_json({"error": "customer potential prediction not found"}, 404)
                return self.send_json(prediction)
            if path == "/api/insight-scores" or (path.startswith("/api/insights/") and path.endswith("/score")):
                try:
                    query = parse_qs(urlparse(self.path).query)
                    minimum_score = int(query["minScore"][0]) if query.get("minScore") else None
                    status, result = InsightScoreController(
                        InsightScoreService(InsightScoreRepository(db))
                    ).handle("GET", path, minimum_score=minimum_score)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/insights/") and path.endswith("/actions"):
                try:
                    status, result = InsightActionController(
                        InsightActionService(InsightActionRepository(db))
                    ).handle("GET", path)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if (
                path == "/api/insights"
                or path.startswith("/api/insights/")
                or (path.startswith("/api/customers/") and path.endswith("/insights"))
            ):
                try:
                    status, result = InsightController(
                        InsightService(InsightRepository(db))
                    ).handle("GET", path, query=parse_qs(urlparse(self.path).query))
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/opportunities/") and path.endswith("/insights"):
                try:
                    status, result = OpportunityInsightController(
                        OpportunityInsightService(OpportunityInsightRepository(db))
                    ).handle("GET", path)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path == "/api/facts/pending":
                from fact_review_service import list_pending_fact_candidates
                try:
                    limit = parse_qs(urlparse(self.path).query).get("limit", [100])[0]
                    return self.send_json(list_pending_fact_candidates(db, int(limit)))
                except (TypeError, ValueError):
                    return self.send_json({"error": "limit must be an integer"}, 400)
            if path.startswith("/api/facts/"):
                parts = path.strip("/").split("/")
                if len(parts) != 3:
                    return self.send_json({"error": "invalid fact candidate path"}, 400)
                try:
                    candidate_id = int(parts[2])
                except ValueError:
                    return self.send_json({"error": "invalid fact candidate id"}, 400)
                from fact_review_service import get_fact_candidate
                candidate = get_fact_candidate(db, candidate_id)
                return self.send_json(candidate or {"error": "fact candidate not found"}, 200 if candidate else 404)
            if path == "/api/health":
                return self.send_json({"status": "ok", "database": str(DB_PATH)})
            if path.startswith("/api/profile-refresh-jobs/"):
                parts = path.strip("/").split("/")
                if len(parts) != 3 or parts[0:2] != ["api", "profile-refresh-jobs"]:
                    return self.send_json({"error": "invalid profile refresh job path"}, 400)
                try:
                    job_id = int(parts[2])
                except ValueError:
                    return self.send_json({"error": "invalid profile refresh job id"}, 400)
                status = get_customer_profile_refresh_job_status(db, job_id)
                return self.send_json(
                    status or {"error": "profile refresh job not found"},
                    200 if status else 404,
                )
            if path == "/api/relationship-score/config":
                return self.send_json(get_relationship_score_config(db))
            if path == "/api/relationship-score-models":
                params = parse_qs(urlparse(self.path).query)
                try:
                    return self.send_json(
                        list_relationship_score_models(db, params.get("status", [None])[0])
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if path.startswith("/api/relationship-score-models/") and "/dimensions" in path:
                parts = path.strip("/").split("/")
                if len(parts) in (8, 9) and parts[5] == "dimensions" and parts[7] == "rules":
                    model_id = unquote(parts[2]).strip()
                    version_id = unquote(parts[4]).strip()
                    dimension_id = unquote(parts[6]).strip()
                    try:
                        _ensure_dimension_parent_model(db, model_id, version_id)
                        if len(parts) == 8:
                            return self.send_json(list_relationship_score_rules(db, dimension_id))
                        rule = get_relationship_score_rule(db, dimension_id, unquote(parts[8]))
                        return self.send_json(
                            rule or {"error": "relationship score rule not found"},
                            200 if rule else 404,
                        )
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
                if len(parts) not in (6, 7) or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "dimensions":
                    return self.send_json({"error": "invalid relationship score dimension path"}, 400)
                model_id = unquote(parts[2]).strip()
                version_id = unquote(parts[4]).strip()
                try:
                    _ensure_dimension_parent_model(db, model_id, version_id)
                    if len(parts) == 6:
                        return self.send_json(list_relationship_score_dimensions(db, version_id))
                    dimension = get_relationship_score_dimension(db, version_id, unquote(parts[6]))
                    return self.send_json(
                        dimension or {"error": "relationship score dimension not found"},
                        200 if dimension else 404,
                    )
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and "/versions" in path:
                parts = path.strip("/").split("/")
                if len(parts) not in (4, 5) or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions":
                    return self.send_json({"error": "invalid relationship score model version path"}, 400)
                model_id = unquote(parts[2]).strip()
                try:
                    if len(parts) == 4:
                        params = parse_qs(urlparse(self.path).query)
                        return self.send_json(
                            list_relationship_score_model_versions(
                                db, model_id, params.get("status", [None])[0]
                            )
                        )
                    version = get_relationship_score_model_version(db, model_id, unquote(parts[4]))
                    return self.send_json(
                        version or {"error": "relationship score model version not found"},
                        200 if version else 404,
                    )
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if path.startswith("/api/relationship-score-models/"):
                model_id = unquote(path.split("/api/relationship-score-models/", 1)[1]).strip()
                if not model_id or "/" in model_id:
                    return self.send_json({"error": "invalid relationship score model id"}, 400)
                item = get_relationship_score_model(db, model_id)
                return self.send_json(
                    item or {"error": "relationship score model not found"},
                    200 if item else 404,
                )
            if path == "/api/relationship-types":
                params = parse_qs(urlparse(self.path).query)
                clauses = []
                values = []
                if params.get("sourceEntityType"):
                    clauses.append("source_entity_type = ?")
                    values.append(params["sourceEntityType"][0])
                if params.get("targetEntityType"):
                    clauses.append("target_entity_type = ?")
                    values.append(params["targetEntityType"][0])
                if params.get("status"):
                    clauses.append("status = ?")
                    values.append(params["status"][0])
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = db.execute(
                    f"SELECT * FROM relationship_types {where} ORDER BY category, name, id",
                    tuple(values),
                ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path == "/api/relationship-entities":
                params = parse_qs(urlparse(self.path).query)
                clauses = []
                values = []
                if params.get("entityType"):
                    clauses.append("entity_type = ?")
                    values.append(params["entityType"][0])
                if params.get("status"):
                    clauses.append("status = ?")
                    values.append(params["status"][0])
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = db.execute(
                    f"SELECT * FROM relationship_entities {where} ORDER BY entity_type, entity_name, id",
                    tuple(values),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                    result.append(item)
                return self.send_json(result)
            if path == "/api/relationships":
                params = parse_qs(urlparse(self.path).query)
                return self.send_json(get_relationships(
                    db,
                    entity_type=params.get("entityType", [None])[0],
                    entity_ref_id=params.get("entityRefId", [None])[0],
                    relationship_type_code=params.get("relationshipTypeCode", [None])[0],
                    status=params.get("status", [None])[0],
                ))
            if path.startswith("/api/relationships/"):
                parts = path.strip("/").split("/")
                try:
                    relationship_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid relationship id"}, 400)
                if len(parts) == 3:
                    item = get_relationship_detail(db, relationship_id)
                    return self.send_json(item or {"error": "relationship not found"}, 200 if item else 404)
            if path.startswith("/api/relationship-network/"):
                parts = path.strip("/").split("/")
                if len(parts) != 3:
                    return self.send_json({"error": "entity type and ref id are required"}, 400)
                network = get_relationship_network(db, unquote(parts[1]), unquote(parts[2]))
                return self.send_json(network or {"error": "relationship entity not found"}, 200 if network else 404)
            if path.startswith("/api/relationship-service/customers/") and path.endswith("/network"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[3])
                    result = RelationshipService(db).query_customer_network(customer_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result)
            if path.startswith("/api/relationship-service/opportunities/") and path.endswith("/decision-makers"):
                parts = path.strip("/").split("/")
                try:
                    opportunity_id = int(parts[3])
                    result = RelationshipService(db).find_decision_makers(opportunity_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result)
            if path.startswith("/api/relationship-service/projects/") and path.endswith("/breakthrough-path"):
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[3])
                    result = RelationshipService(db).recommend_breakthrough_path(project_id)
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result)
            if path.startswith("/api/relationship-analysis/customer/"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                analysis = seed_relationship_analysis(db, "Customer", customer_id)
                return self.send_json(analysis or {"error": "customer relationship entity not found"}, 200 if analysis else 404)
            if path.startswith("/api/relationship-analysis/opportunity/") and path.endswith("/decision-maker"):
                parts = path.strip("/").split("/")
                try:
                    opportunity_id = int(parts[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                opportunity = db.execute(
                    "SELECT id, name, customer_id, project_id FROM opportunities WHERE id = ?",
                    (opportunity_id,),
                ).fetchone()
                if not opportunity:
                    return self.send_json({"error": "opportunity not found"}, 404)
                relations = get_relationships(db, "Opportunity", opportunity_id)
                candidates = [
                    relation for relation in relations
                    if relation["sourceEntity"]["type"] == "Person"
                    and "决策" in relation["relationshipType"]["name"]
                ]
                if not candidates and opportunity["customer_id"]:
                    relations = get_relationships(db, "Customer", opportunity["customer_id"])
                    candidates = [
                        relation for relation in relations
                        if relation["sourceEntity"]["type"] == "Person"
                        and "决策" in relation["relationshipType"]["name"]
                    ]
                return self.send_json({
                    "opportunity": dict(opportunity),
                    "recommended": candidates[:10],
                    "reason": "按关系强度、影响力和最近活动排序；当前商机没有直接决策人时回退到客户关系。",
                })
            if path.startswith("/api/relationship-analysis/project/") and path.endswith("/path"):
                parts = path.strip("/").split("/")
                try:
                    project_id = int(parts[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid project id"}, 400)
                project = db.execute(
                    "SELECT id, name, customer_id FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if not project:
                    return self.send_json({"error": "project not found"}, 404)
                relations = get_relationships(db, "Project", project_id)
                candidates = [
                    relation for relation in relations
                    if relation["sourceEntity"]["type"] == "Person"
                ]
                if not candidates and project["customer_id"]:
                    candidates = [
                        relation for relation in get_relationships(db, "Customer", project["customer_id"])
                        if relation["sourceEntity"]["type"] == "Person"
                    ]
                return self.send_json({
                    "project": dict(project),
                    "recommendedPath": candidates[:10],
                    "reason": "优先推荐关系强度高、影响力高且有近期互动的联系人。",
                })
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
            if path.startswith("/api/customers/") and path.endswith("/facts"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                params = parse_qs(urlparse(self.path).query)
                try:
                    facts = CustomerFactRepository(db).list_for_customer(
                        customer_id,
                        params.get("factType", [None])[0],
                        params.get("status", [None])[0],
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json([fact.to_dict() for fact in facts])
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
            if path == "/api/customer-profile-fact-definitions":
                return self.send_json([
                    {"code": code, "name": name, "category": category, "valueType": value_type}
                    for code, name, category, value_type in PROFILE_FACT_DEFINITIONS
                ])
            if path == "/api/customer-profile-scoring/models":
                params = parse_qs(urlparse(self.path).query)
                status = params.get("status", [None])[0]
                rows = db.execute(
                    "SELECT id FROM customer_profile_scoring_models " + ("WHERE status = ? " if status else "") + "ORDER BY is_default DESC, model_code, version_no",
                    (status,) if status else (),
                ).fetchall()
                return self.send_json([get_customer_profile_scoring_model(db, row["id"], active_only=False) for row in rows])
            if path.startswith("/api/customer-profile-scoring/models/"):
                try:
                    model_id = int(path.strip("/").split("/")[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid scoring model id"}, 400)
                model = get_customer_profile_scoring_model(db, model_id, active_only=False)
                return self.send_json(model or {"error": "scoring model not found"}, 200 if model else 404)
            if path == "/api/customer-profile-events":
                params = parse_qs(urlparse(self.path).query)
                clauses = []
                values = []
                for key, column in [("profileId", "profile_id"), ("customerId", "customer_id"), ("status", "status"), ("eventType", "event_type")]:
                    if params.get(key):
                        clauses.append(f"{column} = ?")
                        values.append(params[key][0])
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = db.execute(
                    f"SELECT * FROM customer_profile_events {where} ORDER BY created_at DESC, id DESC LIMIT 100",
                    tuple(values),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["eventName"] = CUSTOMER_PROFILE_EVENT_TYPES.get(item["event_type"], item["event_type"])
                    item["payload"] = _json_value(item.pop("payload_json"), {})
                    result.append(item)
                return self.send_json(result)
            if path.startswith("/api/customer-profile-events/"):
                try:
                    event_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer profile event id"}, 400)
                event = get_customer_profile_event(db, event_id)
                return self.send_json(event or {"error": "customer profile event not found"}, 200 if event else 404)
            if path == "/api/customer-fact-extraction/rules":
                return self.send_json({
                    "ruleVersion": "customer-fact-extraction-v1",
                    "sourceTypes": [{"code": code, "name": name} for code, name in FACT_EXTRACTION_SOURCE_TYPES.items()],
                    "rules": CUSTOMER_FACT_EXTRACTION_RULES,
                })
            if path.startswith("/api/customer-fact-extraction-runs/"):
                parts = path.strip("/").split("/")
                try:
                    run_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid fact extraction run id"}, 400)
                if len(parts) == 4 and parts[3] == "candidates":
                    if not db.execute(
                        "SELECT id FROM customer_fact_extraction_runs WHERE id = ?",
                        (run_id,),
                    ).fetchone():
                        return self.send_json({"error": "fact extraction run not found"}, 404)
                    params = parse_qs(urlparse(self.path).query)
                    return self.send_json(
                        list_customer_fact_extraction_candidates(
                            db, run_id, params.get("status", [None])[0]
                        )
                    )
                run = get_customer_fact_extraction_run(db, run_id)
                return self.send_json(run or {"error": "fact extraction run not found"}, 200 if run else 404)
            if path == "/api/customer-profiles":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                values = []
                conditions = []
                if params.get("customerId"):
                    try:
                        values.append(int(params["customerId"]))
                    except ValueError:
                        return self.send_json({"error": "invalid customer id"}, 400)
                    conditions.append("cp.customer_id = ?")
                if params.get("status"):
                    values.append(params["status"])
                    conditions.append("cp.status = ?")
                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                rows = db.execute(
                    f"""SELECT cp.*, c.name AS customer_name,
                              co.name AS customer_organization_name,
                              (SELECT COUNT(*) FROM customer_profile_facts cpf WHERE cpf.profile_id = cp.id) AS fact_count,
                              (SELECT COUNT(*) FROM customer_profile_scores cps WHERE cps.profile_id = cp.id) AS score_count,
                              (SELECT COUNT(*) FROM customer_profile_summaries cpsu WHERE cpsu.profile_id = cp.id) AS summary_count,
                              (SELECT COUNT(*) FROM customer_profile_evidences cpe WHERE cpe.profile_id = cp.id) AS evidence_count
                       FROM customer_profiles cp
                       JOIN customers c ON c.id = cp.customer_id
                       LEFT JOIN customer_organizations co ON co.id = cp.customer_organization_id
                       {where}
                       ORDER BY cp.updated_at DESC, cp.id DESC""",
                    tuple(values),
                ).fetchall()
                return self.send_json([dict(row) for row in rows])
            if path.startswith("/api/customer-profiles/"):
                parts = path.strip("/").split("/")
                try:
                    profile_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer profile id"}, 400)
                if len(parts) == 4 and parts[3] == "fact-extraction-runs":
                    if not _profile_row(db, profile_id):
                        return self.send_json({"error": "customer profile not found"}, 404)
                    rows = db.execute(
                        """SELECT * FROM customer_fact_extraction_runs
                           WHERE profile_id = ? ORDER BY started_at DESC, id DESC""",
                        (profile_id,),
                    ).fetchall()
                    result = []
                    for row in rows:
                        item = dict(row)
                        item["sourceTypes"] = _json_value(item.pop("source_types_json"), [])
                        item["dryRun"] = bool(item.pop("dry_run"))
                        result.append(item)
                    return self.send_json(result)
                if len(parts) == 4 and parts[3] == "context":
                    context = get_customer_profile_context(db, profile_id)
                    return self.send_json(context or {"error": "customer profile not found"}, 200 if context else 404)
                if len(parts) == 3:
                    profile = get_customer_profile(db, profile_id)
                    return self.send_json(profile or {"error": "customer profile not found"}, 200 if profile else 404)
            if path == "/api/customer-developments":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                customer_id = params.get("customerId")
                values = []
                where = ""
                if customer_id:
                    try:
                        values.append(int(customer_id))
                    except ValueError:
                        return self.send_json({"error": "invalid customer id"}, 400)
                    where = "WHERE cd.customer_id = ?"
                rows = db.execute(
                    f"""SELECT cd.*, c.name AS customer_name, co.name AS customer_organization_name
                        FROM customer_developments cd
                        JOIN customers c ON c.id = cd.customer_id
                        LEFT JOIN customer_organizations co ON co.id = cd.customer_organization_id
                        {where}
                        ORDER BY cd.updated_at DESC, cd.id DESC""",
                    tuple(values),
                ).fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["currentStage"] = customer_development_stage(item["current_stage_code"])
                    item["actionCount"] = db.execute(
                        """SELECT COUNT(*) FROM actions
                           WHERE customer_development_id = ?
                             AND status NOT IN ('completed', 'cancelled')""",
                        (row["id"],),
                    ).fetchone()[0]
                    item["opportunityCount"] = db.execute(
                        "SELECT COUNT(*) FROM customer_development_opportunities WHERE customer_development_id = ?",
                        (row["id"],),
                    ).fetchone()[0]
                    item["projectCount"] = db.execute(
                        "SELECT COUNT(*) FROM customer_development_projects WHERE customer_development_id = ?",
                        (row["id"],),
                    ).fetchone()[0]
                    result.append(item)
                return self.send_json(result)
            if path.startswith("/api/customer-developments/"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer development id"}, 400)
                if len(parts) == 4 and parts[3] == "link-options":
                    development = db.execute(
                        "SELECT customer_id FROM customer_developments WHERE id = ?",
                        (development_id,),
                    ).fetchone()
                    if not development:
                        return self.send_json({"error": "customer development not found"}, 404)
                    opportunities = db.execute(
                        """SELECT o.id, o.name, o.stage, o.amount, o.business_type, o.owner,
                                  p.name AS project_name
                           FROM opportunities o
                           LEFT JOIN projects p ON p.id = o.project_id
                           WHERE o.customer_id = ?
                             AND NOT EXISTS (
                               SELECT 1 FROM customer_development_opportunities cdo
                               WHERE cdo.customer_development_id = ? AND cdo.opportunity_id = o.id
                             )
                           ORDER BY o.updated_at DESC, o.id DESC""",
                        (development["customer_id"], development_id),
                    ).fetchall()
                    projects = db.execute(
                        """SELECT p.id, p.name, p.project_type, p.address, p.status
                           FROM projects p
                           WHERE p.customer_id = ?
                             AND NOT EXISTS (
                               SELECT 1 FROM customer_development_projects cdp
                               WHERE cdp.customer_development_id = ? AND cdp.project_id = p.id
                             )
                           ORDER BY p.updated_at DESC, p.id DESC""",
                        (development["customer_id"], development_id),
                    ).fetchall()
                    return self.send_json({
                        "opportunities": [dict(x) for x in opportunities],
                        "projects": [dict(x) for x in projects],
                    })
                if len(parts) == 3:
                    item = get_customer_development(db, development_id)
                    return self.send_json(item or {"error": "customer development not found"}, 200 if item else 404)
                if len(parts) == 4 and parts[3] == "actions":
                    if not db.execute("SELECT 1 FROM customer_developments WHERE id = ?", (development_id,)).fetchone():
                        return self.send_json({"error": "customer development not found"}, 404)
                    return self.send_json(get_actions(db, customer_development_id=development_id))
            if path == "/api/actions":
                query = urlparse(self.path).query
                params = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
                try:
                    opportunity_id = int(params["opportunityId"]) if params.get("opportunityId") else None
                    project_id = int(params["projectId"]) if params.get("projectId") else None
                    customer_development_id = int(params["customerDevelopmentId"]) if params.get("customerDevelopmentId") else None
                except ValueError:
                    return self.send_json({"error": "invalid action filter"}, 400)
                return self.send_json(get_actions(db, opportunity_id, project_id, params.get("status"), customer_development_id))
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
            if path.startswith("/api/customers/") and path.endswith("/profile"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                profile = get_current_customer_profile(db, customer_id)
                return self.send_json(profile or {"error": "customer profile not found"}, 200 if profile else 404)
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
            if path.startswith("/api/semantic-assets/"):
                try:
                    asset_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid semantic asset id"}, 400)
                row = db.execute("SELECT * FROM semantic_assets WHERE id = ?", (asset_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "semantic asset not found"}, 404)
                item = dict(row)
                item["badges"] = json.loads(item.pop("badges") or "[]")
                item["fields"] = json.loads(item.pop("fields_json") or "[]")
                item["type"] = item["asset_type"]
                return self.send_json(item)
            if path == "/api/agents":
                agents = []
                for row in db.execute("SELECT * FROM agents ORDER BY scene, id").fetchall():
                    item = dict(row)
                    item["skills"] = [dict(x) for x in db.execute("SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (row["id"],)).fetchall()]
                    agents.append(item)
                return self.send_json(agents)
            if path.startswith("/api/agents/") and path.endswith("/facts"):
                agent_id = path.strip("/").split("/")[2]
                if not db.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
                    return self.send_json({"error": "agent not found"}, 404)
                query = parse_qs(urlparse(self.path).query)
                try:
                    customer_id = int(query["customerId"][0]) if query.get("customerId") else None
                    opportunity_id = int(query["opportunityId"][0]) if query.get("opportunityId") else None
                    limit = int(query["limit"][0]) if query.get("limit") else 20
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid fact context parameters"}, 400)
                try:
                    from fact_agent_service import get_agent_fact_context
                    context = get_agent_fact_context(
                        db, agent_id, customer_id=customer_id,
                        opportunity_id=opportunity_id, limit=limit,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                return self.send_json(context)
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
            if path.startswith("/api/insights/"):
                try:
                    status, result = InsightController(
                        InsightService(InsightRepository(db))
                    ).handle("PUT", path, data)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/customer-facts/"):
                try:
                    fact_id = int(path.strip("/").split("/")[2])
                    fact = CustomerFactRepository(db).update(fact_id, data, now)
                except (IndexError, ValueError) as exc:
                    return self.send_json({"error": str(exc) or "invalid customer fact id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(fact.to_dict())
            if path.startswith("/api/relationship-score-models/") and "/rules/" in path:
                parts = path.strip("/").split("/")
                if len(parts) != 9 or parts[5] != "dimensions" or parts[7] != "rules":
                    return self.send_json({"error": "invalid relationship score rule path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    return self.send_json(
                        update_relationship_score_rule(
                            db,
                            unquote(parts[6]),
                            unquote(parts[8]),
                            data,
                        )
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and "/dimensions/" in path:
                parts = path.strip("/").split("/")
                if len(parts) != 7 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "dimensions":
                    return self.send_json({"error": "invalid relationship score dimension path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    return self.send_json(
                        update_relationship_score_dimension(
                            db,
                            unquote(parts[4]),
                            unquote(parts[6]),
                            data,
                        )
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and "/versions/" in path:
                parts = path.strip("/").split("/")
                if len(parts) != 5 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions":
                    return self.send_json({"error": "invalid relationship score model version path"}, 400)
                model_id = unquote(parts[2]).strip()
                version_id = unquote(parts[4]).strip()
                try:
                    return self.send_json(
                        update_relationship_score_model_version(
                            db, model_id, version_id, data, now
                        ),
                        200,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/"):
                model_id = unquote(path.split("/api/relationship-score-models/", 1)[1]).strip()
                if not model_id or "/" in model_id:
                    return self.send_json({"error": "invalid relationship score model id"}, 400)
                try:
                    return self.send_json(
                        update_relationship_score_model(db, model_id, data, now),
                        200,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/customer-profiles/"):
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[3] == "facts":
                    try:
                        profile_id = int(parts[2])
                        fact_id = int(parts[4])
                    except (IndexError, ValueError):
                        return self.send_json({"error": "invalid customer profile fact id"}, 400)
                    try:
                        current = db.execute(
                            "SELECT fact_code FROM customer_profile_facts WHERE profile_id = ? AND id = ?",
                            (profile_id, fact_id),
                        ).fetchone()
                        if not current:
                            raise LookupError("customer profile fact not found")
                        fact_payload = dict(data)
                        fact_payload.setdefault("factCode", current["fact_code"])
                        return self.send_json(
                            upsert_customer_profile_fact(db, profile_id, fact_payload, now)
                        )
                    except ValueError as exc:
                        return self.send_json({"error": str(exc)}, 400)
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
            if path == "/api/relationship-score/config":
                try:
                    weights = normalize_relationship_score_weights(data)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                description = str(data.get("description", "按五项关系因素自动计算关系强度。")).strip()
                config = db.execute(
                    "SELECT id FROM relationship_score_configs WHERE code = 'relationship-score-v1'"
                ).fetchone()
                if config:
                    db.execute(
                        """UPDATE relationship_score_configs
                           SET interaction_frequency_weight = ?, recency_weight = ?,
                               influence_weight = ?, history_weight = ?, duration_weight = ?,
                               description = ?, status = 'active', is_default = 1, updated_at = ?
                           WHERE id = ?""",
                        (
                            weights["interaction_frequency"], weights["recency"],
                            weights["influence"], weights["history"], weights["duration"],
                            description, now, config["id"],
                        ),
                    )
                else:
                    db.execute(
                        """INSERT INTO relationship_score_configs
                           (code, name, interaction_frequency_weight, recency_weight,
                            influence_weight, history_weight, duration_weight, status,
                            is_default, description, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?)""",
                        (
                            "relationship-score-v1", "关系强度自动评分 V1",
                            weights["interaction_frequency"], weights["recency"],
                            weights["influence"], weights["history"], weights["duration"],
                            description, now, now,
                        ),
                    )
                recalculation = recalculate_relationship_scores(db, now=now, force=True)
                config_result = get_relationship_score_config(db)
                config_result["recalculation"] = recalculation
                return self.send_json(config_result)
            if path.startswith("/api/customer-developments/"):
                parts = path.strip("/").split("/")
                if len(parts) == 3:
                    try:
                        development_id = int(parts[2])
                    except (IndexError, ValueError):
                        return self.send_json({"error": "invalid customer development id"}, 400)
                    development = db.execute(
                        "SELECT * FROM customer_developments WHERE id = ?", (development_id,)
                    ).fetchone()
                    if not development:
                        return self.send_json({"error": "customer development not found"}, 404)
                    db.execute(
                        """UPDATE customer_developments
                           SET name = ?, owner = ?, status = ?, target = ?, summary = ?,
                               next_action = ?, updated_at = ?
                           WHERE id = ?""",
                        (
                            str(data.get("name", development["name"])).strip(),
                            str(data.get("owner", development["owner"])).strip(),
                            str(data.get("status", development["status"])).strip(),
                            str(data.get("target", development["target"])).strip(),
                            str(data.get("summary", development["summary"])).strip(),
                            str(data.get("nextAction", development["next_action"])).strip(),
                            now,
                            development_id,
                        ),
                    )
                    return self.send_json(get_customer_development(db, development_id))
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
                try:
                    person_id = int(data["personId"]) if data.get("personId") else action["person_id"]
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid person id"}, 400)
                if person_id and not db.execute("SELECT 1 FROM persons WHERE id = ?", (person_id,)).fetchone():
                    return self.send_json({"error": "person not found"}, 404)
                completed_at = now if status == "completed" else None
                db.execute(
                    """UPDATE actions
                       SET title = ?, description = ?, action_type = ?, status = ?, priority = ?,
                           assignee = ?, due_at = ?, person_id = ?, updated_at = ?, completed_at = ?
                       WHERE id = ?""",
                    (
                        title,
                        str(data.get("description", action["description"])).strip(),
                        str(data.get("actionType", action["action_type"])).strip() or "follow_up",
                        status,
                        str(data.get("priority", action["priority"])).strip() or "medium",
                        str(data.get("assignee", action["assignee"])).strip(),
                        str(data.get("dueAt", action["due_at"])).strip() if data.get("dueAt", action["due_at"]) else None,
                        person_id,
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
                record_action_relationship_event(db, row, now)
                if status == "completed" and action["status"] != "completed":
                    customer_row = db.execute(
                        """SELECT COALESCE(a.customer_id, o.customer_id, p.customer_id, cd.customer_id) AS customer_id
                           FROM actions a
                           LEFT JOIN opportunities o ON o.id = a.opportunity_id
                           LEFT JOIN projects p ON p.id = a.project_id
                           LEFT JOIN customer_developments cd ON cd.id = a.customer_development_id
                           WHERE a.id = ?""",
                        (action_id,),
                    ).fetchone()
                    if customer_row and customer_row["customer_id"]:
                        emit_customer_profile_event(
                            db,
                            "action_completed",
                            customer_row["customer_id"],
                            "action",
                            action_id,
                            {"title": title, "opportunityId": action["opportunity_id"], "completedAt": completed_at},
                            now=now,
                            dedupe_key=f"action_completed:action:{action_id}:{completed_at}",
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
            if path.startswith("/api/semantic-assets/"):
                try:
                    asset_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid semantic asset id"}, 400)
                row = db.execute("SELECT * FROM semantic_assets WHERE id = ?", (asset_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "semantic asset not found"}, 404)
                category = str(data.get("category", row["category"])).strip()
                asset_type = str(data.get("assetType", row["asset_type"])).strip() or category
                name = str(data.get("name", row["name"])).strip()
                description = str(data.get("description", row["description"])).strip()
                if not category or not name or not description:
                    return self.send_json({"error": "category, name and description are required"}, 400)
                badges = data.get("badges", json.loads(row["badges"] or "[]"))
                fields = data.get("fields", json.loads(row["fields_json"] or "[]"))
                if not isinstance(fields, list):
                    return self.send_json({"error": "fields must be an array"}, 400)
                db.execute(
                    """UPDATE semantic_assets
                       SET category = ?, asset_type = ?, name = ?, description = ?,
                           badges = ?, fields_json = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        category,
                        asset_type,
                        name,
                        description,
                        json.dumps(badges, ensure_ascii=False),
                        json.dumps(fields, ensure_ascii=False),
                        now,
                        asset_id,
                    ),
                )
                return self.send_json({
                    "id": asset_id,
                    "category": category,
                    "assetType": asset_type,
                    "type": asset_type,
                    "name": name,
                    "description": description,
                    "badges": badges,
                    "fields": fields,
                    "updated_at": now,
                })
        return self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        with connect() as db:
            if path.startswith("/api/insights/"):
                try:
                    status, result = InsightController(
                        InsightService(InsightRepository(db))
                    ).handle("DELETE", path)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/customer-facts/"):
                try:
                    fact_id = int(path.strip("/").split("/")[2])
                    CustomerFactRepository(db).delete(fact_id)
                except (IndexError, ValueError) as exc:
                    return self.send_json({"error": str(exc) or "invalid customer fact id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json({"status": "deleted", "factId": fact_id})
            if path.startswith("/api/relationship-score-models/") and "/dimensions/" in path:
                parts = path.strip("/").split("/")
                if len(parts) == 9 and parts[5] == "dimensions" and parts[7] == "rules":
                    try:
                        _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                        result = delete_relationship_score_rule(
                            db, unquote(parts[6]), unquote(parts[8])
                        )
                        return self.send_json(result, 200)
                    except ValueError as exc:
                        return self.send_json({"error": str(exc)}, 400)
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
                if len(parts) != 7 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "dimensions":
                    return self.send_json({"error": "invalid relationship score dimension path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    result = delete_relationship_score_dimension(
                        db,
                        unquote(parts[4]),
                        unquote(parts[6]),
                    )
                    return self.send_json(result, 200)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/customer-profiles/"):
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[3] == "facts":
                    try:
                        profile_id = int(parts[2])
                        fact_id = int(parts[4])
                    except (IndexError, ValueError):
                        return self.send_json({"error": "invalid customer profile fact id"}, 400)
                    try:
                        return self.send_json(
                            delete_customer_profile_fact(db, profile_id, fact_id, now)
                        )
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
                if len(parts) == 5 and parts[3] in {"projects", "opportunities", "persons", "developments"}:
                    try:
                        profile_id = int(parts[2])
                        object_id = int(parts[4])
                    except (IndexError, ValueError):
                        return self.send_json({"error": "invalid customer profile relation id"}, 400)
                    config = {
                        "projects": ("customer_profile_projects", "project_id"),
                        "opportunities": ("customer_profile_opportunities", "opportunity_id"),
                        "persons": ("customer_profile_persons", "person_id"),
                        "developments": ("customer_profile_developments", "customer_development_id"),
                    }[parts[3]]
                    table, object_column = config
                    cur = db.execute(
                        f"DELETE FROM {table} WHERE profile_id = ? AND {object_column} = ?",
                        (profile_id, object_id),
                    )
                    if not cur.rowcount:
                        return self.send_json({"error": "customer profile relation not found"}, 404)
                    return self.send_json(get_customer_profile(db, profile_id))
            if path.startswith("/api/customer-developments/"):
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[3] in {"opportunities", "projects"}:
                    try:
                        development_id = int(parts[2])
                        object_id = int(parts[4])
                    except (ValueError, IndexError):
                        return self.send_json({"error": "invalid customer development relation id"}, 400)
                    table = "customer_development_opportunities" if parts[3] == "opportunities" else "customer_development_projects"
                    object_column = "opportunity_id" if parts[3] == "opportunities" else "project_id"
                    cur = db.execute(
                        f"DELETE FROM {table} WHERE customer_development_id = ? AND {object_column} = ?",
                        (development_id, object_id),
                    )
                    if not cur.rowcount:
                        return self.send_json({"error": "customer development relation not found"}, 404)
                    return self.send_json({
                        "status": "deleted",
                        "customerDevelopmentId": development_id,
                        "objectId": object_id,
                        "objectType": parts[3][:-1],
                    })
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
            if path.startswith("/api/semantic-assets/"):
                try:
                    asset_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid semantic asset id"}, 400)
                cur = db.execute("DELETE FROM semantic_assets WHERE id = ?", (asset_id,))
                if not cur.rowcount:
                    return self.send_json({"error": "semantic asset not found"}, 404)
                return self.send_json({"status": "deleted", "id": asset_id})
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            if path == "/api/agents/customer-growth-intelligence/run":
                try:
                    customer_id = int(data.get("customerId"))
                    report = run_customer_growth_intelligence_agent(db, customer_id, now=now)
                    db.commit()
                    return self.send_json(report, 201)
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-growth/predict":
                try:
                    customer_id = int(data.get("customerId"))
                    prediction = predict_customer_growth(db, customer_id, now=now)
                    db.commit()
                    return self.send_json(prediction, 201)
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-value/predict":
                try:
                    customer_id = int(data.get("customerId"))
                    prediction = predict_customer_value(db, customer_id, now=now)
                    db.commit()
                    return self.send_json(prediction, 201)
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-conversion/predict":
                try:
                    customer_id = int(data.get("customerId"))
                    prediction = predict_customer_conversion(db, customer_id, now=now)
                    db.commit()
                    return self.send_json(prediction, 201)
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/agents/customer-potential/predict":
                try:
                    customer_id = int(data.get("customerId"))
                    prediction = predict_customer_potential(db, customer_id, now=now)
                    db.commit()
                    return self.send_json(prediction, 201)
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/insights/") and path.endswith("/score"):
                try:
                    status, result = InsightScoreController(
                        InsightScoreService(InsightScoreRepository(db))
                    ).handle("POST", path, now=now)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/insights/") and path.endswith("/actions"):
                try:
                    status, result = InsightActionController(
                        InsightActionService(InsightActionRepository(db))
                    ).handle(
                        "POST",
                        path,
                        data,
                        action_creator=lambda **kwargs: create_action_record(db, **kwargs),
                        now=now,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path == "/api/insights":
                try:
                    status, result = InsightController(
                        InsightService(InsightRepository(db))
                    ).handle("POST", path, data)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, status)
            if path.startswith("/api/facts/") and path.endswith("/sync/retry"):
                parts = path.strip("/").split("/")
                try:
                    candidate_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid fact candidate id"}, 400)
                from fact_approval_ontology_sync import retry_ontology_sync
                try:
                    result = retry_ontology_sync(db, candidate_id, now)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 409)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, 200 if result.get("success") else 409)
            if path.startswith("/api/facts/") and path.count("/") == 4:
                parts = path.strip("/").split("/")
                try:
                    candidate_id = int(parts[2])
                except ValueError:
                    return self.send_json({"error": "invalid fact candidate id"}, 400)
                action = {"approve": "approve", "reject": "reject", "modify": "modify"}.get(parts[3])
                if not action:
                    return self.send_json({"error": "unsupported fact review operation"}, 404)
                from fact_review_service import review_fact_candidate
                try:
                    result = review_fact_candidate(
                        db, candidate_id, action,
                        data.get("reviewUser") or data.get("review_user"), data, now,
                    )
                except ValueError as exc:
                    db.rollback()
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    db.rollback()
                    return self.send_json({"error": str(exc)}, 404)
                if not result.get("ontologyResult", {}).get("success", True):
                    return self.send_json(result, 409)
                return self.send_json(result)
            if path.startswith("/api/customers/") and path.endswith("/facts"):
                parts = path.strip("/").split("/")
                try:
                    customer_id = int(parts[2])
                    fact = CustomerFactRepository(db).create(customer_id, data, now)
                except (IndexError, ValueError) as exc:
                    return self.send_json({"error": str(exc) or "invalid customer id"}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(fact.to_dict(), 201)
            if path.startswith("/api/customer-fact-extraction-candidates/") and path.endswith("/review"):
                parts = path.strip("/").split("/")
                try:
                    candidate_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid fact extraction candidate id"}, 400)
                try:
                    result = review_customer_fact_extraction_candidate(
                        db,
                        candidate_id,
                        data.get("decision"),
                        data,
                        now,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, 200)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/rules/reorder"):
                parts = path.strip("/").split("/")
                if len(parts) != 9 or parts[5] != "dimensions" or parts[7] != "rules" or parts[8] != "reorder":
                    return self.send_json({"error": "invalid relationship score rule reorder path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    return self.send_json(
                        reorder_relationship_score_rules(
                            db, unquote(parts[6]), data.get("ruleIds")
                        )
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/rules"):
                parts = path.strip("/").split("/")
                if len(parts) != 8 or parts[5] != "dimensions" or parts[7] != "rules":
                    return self.send_json({"error": "invalid relationship score rule path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    return self.send_json(
                        create_relationship_score_rule(db, unquote(parts[6]), data),
                        201,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/dimensions"):
                parts = path.strip("/").split("/")
                if len(parts) != 6 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "dimensions":
                    return self.send_json({"error": "invalid relationship score dimension path"}, 400)
                try:
                    _ensure_dimension_parent_model(db, unquote(parts[2]), unquote(parts[4]))
                    return self.send_json(
                        create_relationship_score_dimension(
                            db,
                            unquote(parts[4]),
                            data,
                        ),
                        201,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/publish"):
                parts = path.strip("/").split("/")
                if len(parts) != 6 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "publish":
                    return self.send_json({"error": "invalid relationship score model publish path"}, 400)
                model_id = unquote(parts[2]).strip()
                version_id = unquote(parts[4]).strip()
                try:
                    return self.send_json(
                        publish_relationship_score_model_version(
                            db, model_id, version_id, now
                        ),
                        200,
                    )
                except ValueError as exc:
                    try:
                        details = json.loads(str(exc))
                    except json.JSONDecodeError:
                        details = {"valid": False, "errors": [{"code": "PUBLISH_VALIDATION_FAILED", "message": str(exc)}]}
                    return self.send_json({"error": "version publish validation failed", "validation": details}, 409)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/validate"):
                parts = path.strip("/").split("/")
                if len(parts) != 6 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions" or parts[5] != "validate":
                    return self.send_json({"error": "invalid relationship score model validation path"}, 400)
                try:
                    return self.send_json(
                        validate_relationship_score_model_version(
                            db, unquote(parts[2]), unquote(parts[4])
                        )
                    )
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationship-score-models/") and path.endswith("/versions"):
                parts = path.strip("/").split("/")
                if len(parts) != 4 or parts[0:2] != ["api", "relationship-score-models"] or parts[3] != "versions":
                    return self.send_json({"error": "invalid relationship score model version path"}, 400)
                model_id = unquote(parts[2]).strip()
                try:
                    return self.send_json(
                        create_relationship_score_model_version(
                            db, model_id, data, now
                        ),
                        201,
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path == "/api/relationship-score-models":
                try:
                    return self.send_json(create_relationship_score_model(db, data, now), 201)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if path == "/api/relationship-score/recalculate":
                relationship_ids = data.get("relationshipIds")
                if relationship_ids is not None and not isinstance(relationship_ids, list):
                    return self.send_json({"error": "relationshipIds must be an array"}, 400)
                try:
                    result = recalculate_relationship_scores(
                        db,
                        now=now,
                        relationship_ids=relationship_ids,
                        relationship_type_code=data.get("relationshipTypeCode"),
                        updated_since=data.get("updatedSince"),
                        force=bool(data.get("force", True)),
                    )
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                return self.send_json(result, 200)
            if path == "/api/customer-profile-scoring/models":
                model_code = str(data.get("modelCode", "")).strip()
                name = str(data.get("name", "")).strip()
                version_no = str(data.get("versionNo", "")).strip()
                if not model_code or not name or not version_no:
                    return self.send_json({"error": "modelCode, name and versionNo are required"}, 400)
                try:
                    cur = db.execute(
                        """INSERT INTO customer_profile_scoring_models
                           (model_code, name, version_no, status, target_scope, description, is_default, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (model_code, name, version_no, str(data.get("status", "draft")), str(data.get("targetScope", "customer_profile")), str(data.get("description", "")), int(bool(data.get("isDefault"))), now, now),
                    )
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "scoring model version already exists"}, 409)
                return self.send_json(get_customer_profile_scoring_model(db, cur.lastrowid, active_only=False), 201)
            if path.startswith("/api/customer-profile-scoring/models/") and path.endswith("/dimensions"):
                try:
                    model_id = int(path.strip("/").split("/")[3])
                    weight = float(data.get("weight", 0))
                    score_min = int(data.get("scoreMin", 0))
                    score_max = int(data.get("scoreMax", 100))
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "invalid scoring dimension payload"}, 400)
                dimension_code = str(data.get("dimensionCode", "")).strip()
                name = str(data.get("name", "")).strip()
                if not dimension_code or not name or not 0 <= score_min <= score_max:
                    return self.send_json({"error": "dimensionCode, name and score range are required"}, 400)
                if not db.execute("SELECT id FROM customer_profile_scoring_models WHERE id = ?", (model_id,)).fetchone():
                    return self.send_json({"error": "scoring model not found"}, 404)
                db.execute(
                    """INSERT INTO customer_profile_scoring_dimensions
                       (model_id, dimension_code, name, calculation_type, weight, score_min, score_max,
                        source_fact_codes_json, source_metrics_json, config_json, enabled, sort_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(model_id, dimension_code) DO UPDATE SET
                         name = excluded.name, calculation_type = excluded.calculation_type,
                         weight = excluded.weight, score_min = excluded.score_min, score_max = excluded.score_max,
                         source_fact_codes_json = excluded.source_fact_codes_json,
                         source_metrics_json = excluded.source_metrics_json, config_json = excluded.config_json,
                         enabled = excluded.enabled, sort_order = excluded.sort_order, updated_at = excluded.updated_at""",
                    (model_id, dimension_code, name, str(data.get("calculationType", "rules")), weight, score_min, score_max, json.dumps(data.get("sourceFactCodes") or [], ensure_ascii=False), json.dumps(data.get("sourceMetrics") or [], ensure_ascii=False), json.dumps(data.get("config") or {}, ensure_ascii=False), int(bool(data.get("enabled", True))), int(data.get("sortOrder", 0) or 0), now, now),
                )
                return self.send_json(get_customer_profile_scoring_model(db, model_id, active_only=False), 201)
            if path.startswith("/api/customer-profile-scoring/models/") and path.endswith("/rules"):
                try:
                    model_id = int(path.strip("/").split("/")[3])
                    score = float(data.get("score", 0))
                    priority = int(data.get("priority", 0))
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "invalid scoring rule payload"}, 400)
                rule_code = str(data.get("ruleCode", "")).strip()
                name = str(data.get("name", "")).strip()
                condition = data.get("condition") or {}
                dimension_code = str(data.get("dimensionCode", "")).strip()
                if not rule_code or not name or not dimension_code or not isinstance(condition, dict):
                    return self.send_json({"error": "ruleCode, name, dimensionCode and condition are required"}, 400)
                dimension = db.execute("SELECT id FROM customer_profile_scoring_dimensions WHERE model_id = ? AND dimension_code = ?", (model_id, dimension_code)).fetchone()
                if not dimension:
                    return self.send_json({"error": "scoring dimension not found"}, 404)
                db.execute(
                    """INSERT INTO customer_profile_scoring_rules
                       (model_id, dimension_id, rule_code, name, condition_json, score, priority, explanation, config_json, enabled, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(model_id, rule_code) DO UPDATE SET
                         dimension_id = excluded.dimension_id, name = excluded.name,
                         condition_json = excluded.condition_json, score = excluded.score,
                         priority = excluded.priority, explanation = excluded.explanation,
                         config_json = excluded.config_json, enabled = excluded.enabled, updated_at = excluded.updated_at""",
                    (model_id, dimension["id"], rule_code, name, json.dumps(condition, ensure_ascii=False), score, priority, str(data.get("explanation", "")), json.dumps(data.get("config") or {}, ensure_ascii=False), int(bool(data.get("enabled", True))), now, now),
                )
                return self.send_json(get_customer_profile_scoring_model(db, model_id, active_only=False), 201)
            if path.startswith("/api/customer-profile-scoring/models/") and path.endswith("/publish"):
                try:
                    model_id = int(path.strip("/").split("/")[3])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid scoring model id"}, 400)
                model = db.execute("SELECT * FROM customer_profile_scoring_models WHERE id = ?", (model_id,)).fetchone()
                if not model:
                    return self.send_json({"error": "scoring model not found"}, 404)
                if not db.execute("SELECT 1 FROM customer_profile_scoring_dimensions WHERE model_id = ? AND enabled = 1", (model_id,)).fetchone():
                    return self.send_json({"error": "at least one enabled scoring dimension is required"}, 409)
                db.execute("UPDATE customer_profile_scoring_models SET status = 'retired', is_default = 0, updated_at = ? WHERE model_code = ? AND id <> ? AND status = 'active'", (now, model["model_code"], model_id))
                if data.get("isDefault", True):
                    db.execute("UPDATE customer_profile_scoring_models SET is_default = 0, updated_at = ? WHERE id <> ?", (now, model_id))
                db.execute("UPDATE customer_profile_scoring_models SET status = 'active', is_default = ?, published_at = ?, updated_at = ? WHERE id = ?", (int(bool(data.get("isDefault", True))), now, now, model_id))
                return self.send_json(get_customer_profile_scoring_model(db, model_id, active_only=False), 200)
            if path.startswith("/api/relationship-service/relationships/") and path.endswith("/calculate-strength"):
                parts = path.strip("/").split("/")
                try:
                    relationship_id = int(parts[3])
                    result = RelationshipService(db, now).calculate_strength(relationship_id, data)
                except (IndexError, ValueError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, 201)
            if path.startswith("/api/relationship-service/relationships/") and path.endswith("/record-change"):
                parts = path.strip("/").split("/")
                try:
                    relationship_id = int(parts[3])
                    result = RelationshipService(db, now).record_change(relationship_id, data)
                except (IndexError, ValueError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
                return self.send_json(result, 201)
            if path == "/api/relationships":
                source = data.get("sourceEntity") or {}
                target = data.get("targetEntity") or {}
                source_type = data.get("sourceEntityType") or source.get("type")
                source_ref_id = data.get("sourceEntityRefId") or source.get("refId")
                target_type = data.get("targetEntityType") or target.get("type")
                target_ref_id = data.get("targetEntityRefId") or target.get("refId")
                try:
                    relationship_type_id = data.get("relationshipTypeId")
                    if relationship_type_id not in (None, ""):
                        relationship_type_id = int(relationship_type_id)
                        type_row = relationship_type_row(db, type_id=relationship_type_id)
                    else:
                        type_row = relationship_type_row(db, code=str(data.get("relationshipTypeCode", "")).strip())
                    if not type_row:
                        return self.send_json({"error": "relationship type not found"}, 404)
                    if source_type != type_row["source_entity_type"] or target_type != type_row["target_entity_type"]:
                        return self.send_json({
                            "error": "relationship entity types do not match relationship type",
                            "expected": {
                                "sourceEntityType": type_row["source_entity_type"],
                                "targetEntityType": type_row["target_entity_type"],
                            },
                        }, 409)
                    source_entity = ensure_relationship_entity(
                        db, source_type, source_ref_id, source.get("name"), source.get("metadata"), now
                    )
                    target_entity = ensure_relationship_entity(
                        db, target_type, target_ref_id, target.get("name"), target.get("metadata"), now
                    )
                    relationship = upsert_relationship(
                        db, source_entity["id"], target_entity["id"], type_row["id"], data, now
                    )
                    return self.send_json(calculate_relationship_strength_auto(db, relationship["id"], now), 201)
                except (TypeError, ValueError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
            if path.startswith("/api/relationships/") and path.endswith("/scores"):
                parts = path.strip("/").split("/")
                if str(data.get("mode", "")).strip().lower() == "auto" or data.get("score") in (None, ""):
                    try:
                        relationship_id = int(parts[2])
                        return self.send_json(
                            calculate_relationship_strength_auto(db, relationship_id, now),
                            201,
                        )
                    except (IndexError, ValueError) as exc:
                        return self.send_json({"error": str(exc)}, 400)
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
                try:
                    relationship_id = int(parts[2])
                    return self.send_json(
                        save_manual_relationship_score(db, relationship_id, data, now),
                        201,
                    )
                except (IndexError, TypeError, ValueError) as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/relationships/") and path.endswith("/events"):
                parts = path.strip("/").split("/")
                try:
                    relationship_id = int(parts[2])
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "invalid relationship id"}, 400)
                try:
                    return self.send_json(RelationshipService(db, now).record_change(relationship_id, data), 201)
                except ValueError as exc:
                    return self.send_json({"error": str(exc)}, 400)
                except LookupError as exc:
                    return self.send_json({"error": str(exc)}, 404)
            if path.startswith("/api/customer-profile-events/") and path.endswith("/process"):
                try:
                    event_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer profile event id"}, 400)
                event = db.execute("SELECT id FROM customer_profile_events WHERE id = ?", (event_id,)).fetchone()
                if not event:
                    return self.send_json({"error": "customer profile event not found"}, 404)
                return self.send_json(process_customer_profile_event(db, event_id, now=now, force=True), 200)
            if path == "/api/customer-profile-events":
                event_type = str(data.get("eventType", "")).strip()
                source_object_type = str(data.get("sourceObjectType", "")).strip()
                source_object_id = str(data.get("sourceObjectId", "")).strip()
                if event_type not in CUSTOMER_PROFILE_EVENT_TYPES:
                    return self.send_json({"error": "unsupported customer profile event type"}, 400)
                if not source_object_type or not source_object_id:
                    return self.send_json({"error": "sourceObjectType and sourceObjectId are required"}, 400)
                try:
                    profile_id = int(data.get("profileId")) if data.get("profileId") else None
                    customer_id = int(data.get("customerId")) if data.get("customerId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "profileId or customerId must be numeric"}, 400)
                if profile_id:
                    profile = db.execute("SELECT * FROM customer_profiles WHERE id = ?", (profile_id,)).fetchone()
                    if not profile:
                        return self.send_json({"error": "customer profile not found"}, 404)
                    customer_id = profile["customer_id"]
                if not customer_id:
                    return self.send_json({"error": "profileId or customerId is required"}, 400)
                try:
                    result = emit_customer_profile_event(
                        db,
                        event_type,
                        customer_id,
                        source_object_type,
                        source_object_id,
                        data.get("payload") or {},
                        now=data.get("occurredAt") or now,
                        process=bool(data.get("process", True)),
                        dedupe_key=str(data.get("dedupeKey") or "").strip() or None,
                    )
                except ValueError as error:
                    return self.send_json({"error": str(error)}, 400)
                return self.send_json(result, 201)
            if path == "/api/customer-fact-extraction/run":
                try:
                    profile_id = int(data.get("profileId")) if data.get("profileId") else None
                    customer_id = int(data.get("customerId")) if data.get("customerId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "profileId or customerId must be numeric"}, 400)
                if not profile_id and customer_id:
                    current_profile = get_current_customer_profile(db, customer_id)
                    profile_id = current_profile["id"] if current_profile else None
                if not profile_id:
                    return self.send_json({"error": "profileId or an active customer profile is required"}, 400)
                source_types = data.get("sourceTypes")
                if source_types is not None and not isinstance(source_types, list):
                    return self.send_json({"error": "sourceTypes must be an array"}, 400)
                try:
                    result = run_customer_fact_extraction(
                        db,
                        profile_id,
                        source_types=source_types,
                        dry_run=bool(data.get("dryRun", False)),
                        trigger_type=str(data.get("triggerType", "manual")).strip() or "manual",
                        now=now,
                    )
                except ValueError as error:
                    return self.send_json({"error": str(error)}, 400)
                return self.send_json(result, 201)
            if path == "/api/customer-profiles":
                try:
                    customer_id = int(data.get("customerId"))
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                if not db.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
                    return self.send_json({"error": "customer not found"}, 404)
                organization_id = data.get("customerOrganizationId")
                if organization_id is not None and organization_id != "":
                    try:
                        organization_id = int(organization_id)
                    except (TypeError, ValueError):
                        return self.send_json({"error": "invalid customer organization id"}, 400)
                    if not db.execute(
                        "SELECT 1 FROM customer_organizations WHERE id = ? AND customer_id = ?",
                        (organization_id, customer_id),
                    ).fetchone():
                        return self.send_json({"error": "customer organization does not belong to customer"}, 409)
                else:
                    organization_id = None
                profile_type = str(data.get("profileType", "account_profile")).strip() or "account_profile"
                scope_type = str(data.get("scopeType", "customer")).strip() or "customer"
                status = str(data.get("status", "active")).strip() or "active"
                if status not in {"draft", "active", "archived"}:
                    return self.send_json({"error": "invalid customer profile status"}, 400)
                version_no = db.execute(
                    """SELECT COALESCE(MAX(version_no), 0) + 1
                       FROM customer_profiles
                       WHERE customer_id = ? AND customer_organization_id IS ?""",
                    (customer_id, organization_id),
                ).fetchone()[0]
                if status == "active":
                    db.execute(
                        """UPDATE customer_profiles SET status = 'archived', updated_at = ?
                           WHERE customer_id = ? AND customer_organization_id IS ? AND status = 'active'""",
                        (now, customer_id, organization_id),
                    )
                cur = db.execute(
                    """INSERT INTO customer_profiles
                       (customer_id, customer_organization_id, profile_type, version_no, scope_type,
                        status, profile_period_start, profile_period_end, completeness_score,
                        confidence_score, source_agent_id, source_agent_run_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        customer_id,
                        organization_id,
                        profile_type,
                        version_no,
                        scope_type,
                        status,
                        data.get("profilePeriodStart"),
                        data.get("profilePeriodEnd"),
                        data.get("completenessScore"),
                        data.get("confidenceScore"),
                        data.get("sourceAgentId"),
                        data.get("sourceAgentRunId"),
                        now,
                        now,
                    ),
                )
                return self.send_json(get_customer_profile(db, cur.lastrowid), 201)
            if path.startswith("/api/customer-profiles/"):
                parts = path.strip("/").split("/")
                try:
                    profile_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer profile id"}, 400)
                profile = db.execute("SELECT * FROM customer_profiles WHERE id = ?", (profile_id,)).fetchone()
                if not profile:
                    return self.send_json({"error": "customer profile not found"}, 404)
                if len(parts) == 5 and parts[3] == "scores" and parts[4] == "recalculate":
                    try:
                        model_id = int(data.get("modelId")) if data.get("modelId") else None
                    except (TypeError, ValueError):
                        return self.send_json({"error": "modelId must be numeric"}, 400)
                    try:
                        scores = recalculate_customer_profile_scores(
                            db,
                            profile_id,
                            now,
                            model_id=model_id,
                            model_code=str(data.get("modelCode", "")).strip() or None,
                            version_no=str(data.get("versionNo", "")).strip() or None,
                        )
                    except ValueError as error:
                        return self.send_json({"error": str(error)}, 409)
                    selected_model = get_customer_profile_scoring_model(
                        db,
                        model_id,
                        str(data.get("modelCode", "")).strip() or None,
                        str(data.get("versionNo", "")).strip() or None,
                    )
                    return self.send_json({"profileId": profile_id, "scores": scores, "model": selected_model}, 201)
                if len(parts) == 5 and parts[3] == "fact-extraction" and parts[4] == "run":
                    source_types = data.get("sourceTypes")
                    if source_types is not None and not isinstance(source_types, list):
                        return self.send_json({"error": "sourceTypes must be an array"}, 400)
                    try:
                        result = run_customer_fact_extraction(
                            db,
                            profile_id,
                            source_types=source_types,
                            dry_run=bool(data.get("dryRun", False)),
                            trigger_type=str(data.get("triggerType", "manual")).strip() or "manual",
                            now=now,
                        )
                    except ValueError as error:
                        return self.send_json({"error": str(error)}, 400)
                    return self.send_json(result, 201)
                if len(parts) == 4 and parts[3] == "refresh":
                    sources = data.get("sources")
                    mode = str(data.get("mode", "formal")).strip().lower()
                    try:
                        job = create_customer_profile_refresh_job(db, profile_id, sources, mode, now=now)
                    except ValueError as error:
                        return self.send_json({"error": str(error)}, 400)
                    except LookupError as error:
                        return self.send_json({"error": str(error)}, 404)
                    threading.Thread(
                        target=run_customer_profile_refresh_job,
                        args=(job["jobId"],),
                        name=f"customer-profile-refresh-{job['jobId']}",
                        daemon=True,
                    ).start()
                    return self.send_json(job, 202)
                if len(parts) == 5 and parts[3] == "summaries" and parts[4] == "generate":
                    return self.send_json(generate_customer_profile_summary(db, profile_id, now), 201)
                if len(parts) != 4:
                    return self.send_json({"error": "unsupported customer profile operation"}, 404)
                relation = parts[3]
                if relation == "facts":
                    fact_code = str(data.get("factCode", "")).strip()
                    if not fact_code:
                        return self.send_json({"error": "factCode is required"}, 400)
                    definition = next((item for item in PROFILE_FACT_DEFINITIONS if item[0] == fact_code), None)
                    fact_name = str(data.get("factName") or (definition[1] if definition else fact_code)).strip()
                    value = data.get("value")
                    if value is None:
                        return self.send_json({"error": "value is required"}, 400)
                    db.execute(
                        """INSERT INTO customer_profile_facts
                           (profile_id, fact_code, fact_name, category, value_type, value_json, unit,
                            confidence, source_type, source_id, observed_at, valid_from, valid_to, status,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(profile_id, fact_code) DO UPDATE SET
                             fact_name = excluded.fact_name, category = excluded.category,
                             value_type = excluded.value_type, value_json = excluded.value_json,
                             unit = excluded.unit, confidence = excluded.confidence,
                             source_type = excluded.source_type, source_id = excluded.source_id,
                             observed_at = excluded.observed_at, valid_from = excluded.valid_from,
                             valid_to = excluded.valid_to, status = excluded.status,
                             updated_at = excluded.updated_at""",
                        (
                            profile_id,
                            fact_code,
                            fact_name,
                            str(data.get("category") or (definition[2] if definition else "general")),
                            str(data.get("valueType") or (definition[3] if definition else "text")),
                            json.dumps(value, ensure_ascii=False),
                            str(data.get("unit", "")).strip(),
                            data.get("confidence"),
                            str(data.get("sourceType", "manual")).strip() or "manual",
                            str(data.get("sourceId", "")).strip(),
                            data.get("observedAt") or now,
                            data.get("validFrom"),
                            data.get("validTo"),
                            str(data.get("status", "active")).strip() or "active",
                            now,
                            now,
                        ),
                    )
                    db.execute("UPDATE customer_profiles SET updated_at = ? WHERE id = ?", (now, profile_id))
                    return self.send_json(get_customer_profile(db, profile_id), 201)
                if relation == "scores":
                    score_type = str(data.get("scoreType", "")).strip()
                    try:
                        score = float(data.get("score"))
                    except (TypeError, ValueError):
                        return self.send_json({"error": "scoreType and numeric score are required"}, 400)
                    if not score_type or not 0 <= score <= 100:
                        return self.send_json({"error": "score must be between 0 and 100"}, 400)
                    db.execute(
                        """INSERT INTO customer_profile_scores
                           (profile_id, score_type, score, level, dimensions_json, scoring_rule_version,
                            reason, source_agent_id, source_agent_run_id, assessed_at, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            profile_id,
                            score_type,
                            score,
                            str(data.get("level") or profile_score_level(score)),
                            json.dumps(data.get("dimensions") or {}, ensure_ascii=False),
                            str(data.get("scoringRuleVersion", "customer-profile-v1")).strip(),
                            str(data.get("reason", "")).strip(),
                            data.get("sourceAgentId"),
                            data.get("sourceAgentRunId"),
                            data.get("assessedAt") or now,
                            now,
                        ),
                    )
                    db.execute("UPDATE customer_profiles SET updated_at = ?, last_assessed_at = ? WHERE id = ?", (now, now, profile_id))
                    return self.send_json(get_customer_profile(db, profile_id), 201)
                if relation == "summaries":
                    title = str(data.get("title", "")).strip()
                    content = str(data.get("content", "")).strip()
                    if not title or not content:
                        return self.send_json({"error": "title and content are required"}, 400)
                    db.execute(
                        """INSERT INTO customer_profile_summaries
                           (profile_id, summary_type, title, content, structured_json,
                            generated_by_agent_id, generated_by_agent_run_id, model_name,
                            prompt_version, status, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            profile_id,
                            str(data.get("summaryType", "executive_summary")).strip() or "executive_summary",
                            title,
                            content,
                            json.dumps(data.get("structured") or {}, ensure_ascii=False),
                            data.get("generatedByAgentId"),
                            data.get("generatedByAgentRunId"),
                            str(data.get("modelName", "manual")).strip() or "manual",
                            str(data.get("promptVersion", "")).strip(),
                            str(data.get("status", "draft")).strip() or "draft",
                            now,
                            now,
                        ),
                    )
                    db.execute("UPDATE customer_profiles SET updated_at = ? WHERE id = ?", (now, profile_id))
                    return self.send_json(get_customer_profile(db, profile_id), 201)
                if relation == "evidences":
                    evidence_text = str(data.get("evidenceText", "")).strip()
                    if not evidence_text:
                        return self.send_json({"error": "evidenceText is required"}, 400)
                    db.execute(
                        """INSERT INTO customer_profile_evidences
                           (profile_id, evidence_type, source_object_type, source_object_id,
                            evidence_text, evidence_json, confidence, observed_at,
                            extracted_by_agent_id, extracted_by_agent_run_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            profile_id,
                            str(data.get("evidenceType", "observation")).strip() or "observation",
                            str(data.get("sourceObjectType", "")).strip(),
                            str(data.get("sourceObjectId", "")).strip(),
                            evidence_text,
                            json.dumps(data.get("evidence") or {}, ensure_ascii=False),
                            data.get("confidence"),
                            data.get("observedAt") or now,
                            data.get("extractedByAgentId"),
                            data.get("extractedByAgentRunId"),
                            now,
                        ),
                    )
                    db.execute("UPDATE customer_profiles SET updated_at = ? WHERE id = ?", (now, profile_id))
                    return self.send_json(get_customer_profile(db, profile_id), 201)
                relation_config = {
                    "projects": ("customer_profile_projects", "project_id", "projects", "id", "relation_type, importance, notes"),
                    "opportunities": ("customer_profile_opportunities", "opportunity_id", "opportunities", "id", "relation_type, importance, notes"),
                    "persons": ("customer_profile_persons", "person_id", "persons", "id", "relation_type, influence_level, relationship_health, notes"),
                    "developments": ("customer_profile_developments", "customer_development_id", "customer_developments", "id", "relation_type, relevance_score, notes"),
                }
                if relation not in relation_config:
                    return self.send_json({"error": "unsupported customer profile relation"}, 404)
                table, object_column, object_table, object_id_column, _ = relation_config[relation]
                body_key = {
                    "projects": "projectId",
                    "opportunities": "opportunityId",
                    "persons": "personId",
                    "developments": "customerDevelopmentId",
                }[relation]
                try:
                    object_id = int(data.get(body_key))
                except (TypeError, ValueError):
                    return self.send_json({"error": f"{body_key} is required"}, 400)
                object_row = db.execute(
                    f"SELECT * FROM {object_table} WHERE {object_id_column} = ?", (object_id,)
                ).fetchone()
                if not object_row:
                    return self.send_json({"error": f"{relation[:-1]} not found"}, 404)
                if relation == "persons":
                    belongs_to_customer = db.execute(
                        "SELECT 1 FROM customer_persons WHERE customer_id = ? AND person_id = ?",
                        (profile["customer_id"], object_id),
                    ).fetchone()
                else:
                    belongs_to_customer = object_row["customer_id"] == profile["customer_id"]
                if not belongs_to_customer:
                    return self.send_json({"error": "related object does not belong to profile customer"}, 409)
                if relation == "projects":
                    values = (profile_id, object_id, str(data.get("relationType", "重点项目")).strip() or "重点项目", data.get("importance"), str(data.get("notes", "")).strip(), now, now)
                    sql = f"""INSERT INTO {table} (profile_id, {object_column}, relation_type, importance, notes, created_at, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?)
                              ON CONFLICT(profile_id, {object_column}) DO UPDATE SET relation_type = excluded.relation_type, importance = excluded.importance, notes = excluded.notes, updated_at = excluded.updated_at"""
                elif relation == "opportunities":
                    values = (profile_id, object_id, str(data.get("relationType", "重点商机")).strip() or "重点商机", data.get("importance"), str(data.get("notes", "")).strip(), now, now)
                    sql = f"""INSERT INTO {table} (profile_id, {object_column}, relation_type, importance, notes, created_at, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?)
                              ON CONFLICT(profile_id, {object_column}) DO UPDATE SET relation_type = excluded.relation_type, importance = excluded.importance, notes = excluded.notes, updated_at = excluded.updated_at"""
                elif relation == "persons":
                    values = (profile_id, object_id, str(data.get("relationType", "关键人")).strip() or "关键人", str(data.get("influenceLevel", "medium")).strip() or "medium", str(data.get("relationshipHealth", "unknown")).strip() or "unknown", str(data.get("notes", "")).strip(), now, now)
                    sql = f"""INSERT INTO {table} (profile_id, {object_column}, relation_type, influence_level, relationship_health, notes, created_at, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                              ON CONFLICT(profile_id, {object_column}) DO UPDATE SET relation_type = excluded.relation_type, influence_level = excluded.influence_level, relationship_health = excluded.relationship_health, notes = excluded.notes, updated_at = excluded.updated_at"""
                else:
                    values = (profile_id, object_id, str(data.get("relationType", "客户开发主线")).strip() or "客户开发主线", data.get("relevanceScore"), str(data.get("notes", "")).strip(), now, now)
                    sql = f"""INSERT INTO {table} (profile_id, {object_column}, relation_type, relevance_score, notes, created_at, updated_at)
                              VALUES (?, ?, ?, ?, ?, ?, ?)
                              ON CONFLICT(profile_id, {object_column}) DO UPDATE SET relation_type = excluded.relation_type, relevance_score = excluded.relevance_score, notes = excluded.notes, updated_at = excluded.updated_at"""
                db.execute(sql, values)
                db.execute("UPDATE customer_profiles SET updated_at = ? WHERE id = ?", (now, profile_id))
                return self.send_json(get_customer_profile(db, profile_id), 201)
            if path == "/api/customer-developments":
                try:
                    customer_id = int(data.get("customerId"))
                except (TypeError, ValueError):
                    return self.send_json({"error": "customerId is required"}, 400)
                customer = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
                if not customer:
                    return self.send_json({"error": "customer not found"}, 404)
                organization_id = data.get("customerOrganizationId")
                if organization_id:
                    try:
                        organization_id = int(organization_id)
                    except (TypeError, ValueError):
                        return self.send_json({"error": "invalid customer organization id"}, 400)
                    if not db.execute(
                        "SELECT 1 FROM customer_organizations WHERE id = ? AND customer_id = ?",
                        (organization_id, customer_id),
                    ).fetchone():
                        return self.send_json({"error": "customer organization does not belong to customer"}, 409)
                name = str(data.get("name") or f"{customer['name']}客户开发").strip()
                if not name:
                    return self.send_json({"error": "name is required"}, 400)
                stage = customer_development_stage(data.get("stageCode", "AT1"))
                if not stage:
                    return self.send_json({"error": "invalid customer development stage"}, 400)
                cur = db.execute(
                    """INSERT INTO customer_developments
                       (customer_id, customer_organization_id, name, owner, current_stage_code,
                        current_stage_name, target, summary, next_action, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        customer_id,
                        organization_id,
                        name,
                        str(data.get("owner", "")).strip(),
                        stage["code"],
                        stage["name"],
                        str(data.get("target", "")).strip(),
                        str(data.get("summary", "")).strip(),
                        str(data.get("nextAction", "")).strip(),
                        now,
                        now,
                    ),
                )
                development_id = cur.lastrowid
                db.execute(
                    """INSERT INTO customer_development_stage_records
                       (customer_development_id, stage_code, stage_name, status, required_json,
                        started_at, created_at, updated_at)
                       VALUES (?, ?, ?, 'in_progress', ?, ?, ?, ?)""",
                    (development_id, stage["code"], stage["name"], "{}", now, now, now),
                )
                return self.send_json(get_customer_development(db, development_id), 201)
            if path.startswith("/api/customer-developments/") and path.endswith("/opportunities"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                    opportunity_id = int(data.get("opportunityId"))
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "development id and opportunityId are required"}, 400)
                development = db.execute(
                    "SELECT * FROM customer_developments WHERE id = ?", (development_id,)
                ).fetchone()
                opportunity = db.execute(
                    "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
                ).fetchone()
                if not development:
                    return self.send_json({"error": "customer development not found"}, 404)
                if not opportunity:
                    return self.send_json({"error": "opportunity not found"}, 404)
                if opportunity["customer_id"] != development["customer_id"]:
                    return self.send_json({"error": "opportunity does not belong to customer development customer"}, 409)
                db.execute(
                    """INSERT INTO customer_development_opportunities
                       (customer_development_id, opportunity_id, relation_type, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(customer_development_id, opportunity_id)
                       DO UPDATE SET relation_type = excluded.relation_type,
                                     notes = excluded.notes, updated_at = excluded.updated_at""",
                    (
                        development_id,
                        opportunity_id,
                        str(data.get("relationType", "重点商机")).strip() or "重点商机",
                        str(data.get("notes", "")).strip(),
                        now,
                        now,
                    ),
                )
                return self.send_json(get_customer_development(db, development_id), 201)
            if path.startswith("/api/customer-developments/") and path.endswith("/projects"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                    project_id = int(data.get("projectId"))
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "development id and projectId are required"}, 400)
                development = db.execute(
                    "SELECT * FROM customer_developments WHERE id = ?", (development_id,)
                ).fetchone()
                project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                if not development:
                    return self.send_json({"error": "customer development not found"}, 404)
                if not project:
                    return self.send_json({"error": "project not found"}, 404)
                if project["customer_id"] != development["customer_id"]:
                    return self.send_json({"error": "project does not belong to customer development customer"}, 409)
                db.execute(
                    """INSERT INTO customer_development_projects
                       (customer_development_id, project_id, relation_type, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(customer_development_id, project_id)
                       DO UPDATE SET relation_type = excluded.relation_type,
                                     notes = excluded.notes, updated_at = excluded.updated_at""",
                    (
                        development_id,
                        project_id,
                        str(data.get("relationType", "重点项目")).strip() or "重点项目",
                        str(data.get("notes", "")).strip(),
                        now,
                        now,
                    ),
                )
                return self.send_json(get_customer_development(db, development_id), 201)
            if path.startswith("/api/customer-developments/") and path.endswith("/stage"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer development id"}, 400)
                development = db.execute(
                    "SELECT * FROM customer_developments WHERE id = ?", (development_id,)
                ).fetchone()
                if not development:
                    return self.send_json({"error": "customer development not found"}, 404)
                target = customer_development_stage(data.get("stageCode"))
                if not target:
                    return self.send_json({"error": "invalid customer development stage"}, 400)
                current = customer_development_stage(development["current_stage_code"])
                if current and target["sequence"] != current["sequence"] + 1:
                    return self.send_json({"error": "customer development stages must advance sequentially"}, 409)
                required = data.get("required") or {}
                missing = [key for key in target["required"] if not str(required.get(key, "")).strip()]
                if missing:
                    return self.send_json({"error": "required fields are missing", "missing": missing}, 400)
                db.execute(
                    """UPDATE customer_development_stage_records
                       SET status = 'completed', required_json = ?, completed_at = ?, updated_at = ?
                       WHERE customer_development_id = ? AND stage_code = ?""",
                    (json.dumps(required, ensure_ascii=False), now, now, development_id, development["current_stage_code"]),
                )
                db.execute(
                    """INSERT INTO customer_development_stage_records
                       (customer_development_id, stage_code, stage_name, status, required_json,
                        started_at, created_at, updated_at)
                       VALUES (?, ?, ?, 'in_progress', ?, ?, ?, ?)""",
                    (development_id, target["code"], target["name"], "{}", now, now, now),
                )
                db.execute(
                    """UPDATE customer_developments
                       SET current_stage_code = ?, current_stage_name = ?, next_action = ?, updated_at = ?
                       WHERE id = ?""",
                    (target["code"], target["name"], str(data.get("nextAction", "")).strip(), now, development_id),
                )
                development = db.execute("SELECT * FROM customer_developments WHERE id = ?", (development_id,)).fetchone()
                create_action_record(
                    db,
                    title=f"推进客户开发：完成{target['name']}阶段关键动作",
                    description=f"客户开发已进入{target['name']}，请根据阶段记录持续推进。",
                    action_type="customer_development_stage",
                    priority="high",
                    assignee=development["owner"],
                    customer_id=development["customer_id"],
                    customer_organization_id=development["customer_organization_id"],
                    customer_development_id=development_id,
                    stage_code=target["code"],
                    stage_name=target["name"],
                    source_type="customer_development_stage",
                    source_id=str(development_id),
                    created_by=data.get("actor", "李盛云"),
                    dedupe_key=f"customer-development-stage:{development_id}:{target['code']}",
                    now=now,
                )
                return self.send_json(get_customer_development(db, development_id))
            if path.startswith("/api/customer-developments/") and path.endswith("/health"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                    score = int(data.get("score"))
                except (IndexError, TypeError, ValueError):
                    return self.send_json({"error": "development id and score are required"}, 400)
                if not 0 <= score <= 100:
                    return self.send_json({"error": "score must be between 0 and 100"}, 400)
                if not db.execute("SELECT 1 FROM customer_developments WHERE id = ?", (development_id,)).fetchone():
                    return self.send_json({"error": "customer development not found"}, 404)
                db.execute(
                    """INSERT INTO customer_development_health_scores
                       (customer_development_id, score, dimensions_json, reason, assessed_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        development_id,
                        score,
                        json.dumps(data.get("dimensions") or {}, ensure_ascii=False),
                        str(data.get("reason", "")).strip(),
                        str(data.get("assessedBy", "manual")).strip() or "manual",
                        now,
                    ),
                )
                db.execute(
                    "UPDATE customer_developments SET updated_at = ? WHERE id = ?",
                    (now, development_id),
                )
                return self.send_json(get_customer_development(db, development_id))
            if path.startswith("/api/customer-developments/") and path.endswith("/strategies"):
                parts = path.strip("/").split("/")
                try:
                    development_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid customer development id"}, 400)
                if not db.execute("SELECT 1 FROM customer_developments WHERE id = ?", (development_id,)).fetchone():
                    return self.send_json({"error": "customer development not found"}, 404)
                title = str(data.get("title", "")).strip()
                if not title:
                    return self.send_json({"error": "title is required"}, 400)
                db.execute(
                    """INSERT INTO customer_development_strategies
                       (customer_development_id, strategy_type, title, content, status,
                        source_agent_id, source_agent_run_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        development_id,
                        str(data.get("strategyType", "经营策略")).strip(),
                        title,
                        str(data.get("content", "")).strip(),
                        str(data.get("status", "draft")).strip(),
                        data.get("sourceAgentId"),
                        data.get("sourceAgentRunId"),
                        now,
                        now,
                    ),
                )
                db.execute("UPDATE customer_developments SET updated_at = ? WHERE id = ?", (now, development_id))
                return self.send_json(get_customer_development(db, development_id), 201)
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
                    customer_development_id = (
                        int(data["customerDevelopmentId"])
                        if data.get("customerDevelopmentId") else None
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
                        customer_development_id=customer_development_id,
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
                record_action_relationship_event(db, action, now)
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
                project_row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id else None
                if project_id and not project_row:
                    return self.send_json({"error": "project not found"}, 404)
                resolved_customer_id = customer_id or (project_row["customer_id"] if project_row else None)
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
                if resolved_customer_id:
                    db.execute(
                        """INSERT OR IGNORE INTO customer_persons
                           (customer_id, person_id, role, is_primary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (resolved_customer_id, person_id, data.get("customerRole", "联系人"), int(bool(data.get("isPrimary"))), now),
                    )
                if project_id:
                    db.execute(
                        """INSERT OR IGNORE INTO project_persons
                           (project_id, person_id, role, is_primary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (project_id, person_id, data.get("projectRole", "项目联系人"), int(bool(data.get("isPrimary"))), now),
                    )
                if resolved_customer_id:
                    emit_customer_profile_event(
                        db,
                        "person_changed",
                        resolved_customer_id,
                        "person",
                        person_id,
                        {"change": "created", "role": data.get("customerRole", "联系人"), "projectId": project_id},
                        now=now,
                        dedupe_key=f"person_changed:person:{person_id}:created",
                    )
                return self.send_json(dict(db.execute("SELECT * FROM persons WHERE id = ?", (person_id,)).fetchone()), 201)
            if path.startswith("/api/opportunities/") and path.endswith("/people"):
                parts = path.strip("/").split("/")
                try:
                    opportunity_id = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                opportunity_row = db.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
                if not opportunity_row:
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
                opportunity_role_types = {
                    "业务发起人": "person_opportunity_sponsor",
                    "决策人": "person_opportunity_decision_maker",
                    "采购把关人": "person_opportunity_decision_maker",
                    "技术推动者": "person_opportunity_influencer",
                }
                relationship_type = relationship_type_row(
                    db,
                    code=opportunity_role_types.get(role, "person_opportunity_influencer"),
                )
                source_entity = ensure_relationship_entity(db, "Person", person_id, now=now)
                target_entity = ensure_relationship_entity(db, "Opportunity", opportunity_id, now=now)
                if source_entity and target_entity and relationship_type:
                    influence_score = {"高": 85, "中": 60, "低": 30}.get(
                        str(data.get("influenceLevel", "未知")).strip(), 0
                    )
                    relationship_status = str(data.get("relationshipStatus", "待建立")).strip() or "待建立"
                    upsert_relationship(
                        db,
                        source_entity["id"],
                        target_entity["id"],
                        relationship_type["id"],
                        {
                            "strengthScore": influence_score,
                            "status": "inactive" if relationship_status == "已失联" else "active",
                            "confidence": 80,
                            "notes": str(data.get("relationshipNotes", data.get("notes", ""))).strip(),
                        },
                        now,
                    )
                db.execute("UPDATE persons SET updated_at = ? WHERE id = ?", (now, person_id))
                if opportunity_row["customer_id"]:
                    db.execute(
                        """INSERT OR IGNORE INTO customer_persons
                           (customer_id, person_id, role, is_primary, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (opportunity_row["customer_id"], person_id, role, int(bool(data.get("isPrimary"))), now),
                    )
                    emit_customer_profile_event(
                        db,
                        "person_changed",
                        opportunity_row["customer_id"],
                        "opportunity_person",
                        f"{opportunity_id}:{person_id}:{role}",
                        {"change": "linked", "opportunityId": opportunity_id, "personId": person_id, "role": role},
                        now=now,
                        dedupe_key=f"person_changed:opportunity_person:{opportunity_id}:{person_id}:{role}:{now}",
                    )
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
                emit_customer_profile_event(
                    db,
                    "project_created",
                    customer_id,
                    "project",
                    project_id,
                    {"projectId": project_id, "opportunityId": opportunity_id, "source": "discovery_confirm"},
                    now=now,
                    dedupe_key=f"project_created:project:{project_id}",
                )
                emit_customer_profile_event(
                    db,
                    "opportunity_created",
                    customer_id,
                    "opportunity",
                    opportunity_id,
                    {"projectId": project_id, "sectionId": section_id, "source": "discovery_confirm"},
                    now=now,
                    dedupe_key=f"opportunity_created:opportunity:{opportunity_id}",
                )
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
                customer_row = db.execute("SELECT id FROM customers WHERE name = ?", (data["customer"],)).fetchone()
                if customer_row:
                    db.execute("UPDATE opportunities SET customer_id = ? WHERE id = ?", (customer_row["id"], oid))
                backfill_opportunity_relations(db, now)
                created_opportunity = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
                current_stage = stage_definition(db, created_opportunity["stage"])
                if current_stage:
                    create_stage_actions(db, created_opportunity, current_stage, "stage_plan", "opportunity_created", now)
                if customer_row:
                    emit_customer_profile_event(
                        db,
                        "opportunity_created",
                        customer_row["id"],
                        "opportunity",
                        oid,
                        {"stage": created_opportunity["stage"], "amount": created_opportunity["amount"]},
                        now=now,
                        dedupe_key=f"opportunity_created:opportunity:{oid}",
                    )
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
            if path.startswith("/api/semantic-assets/"):
                try:
                    asset_id = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid semantic asset id"}, 400)
                row = db.execute("SELECT * FROM semantic_assets WHERE id = ?", (asset_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "semantic asset not found"}, 404)
                category = str(data.get("category", row["category"])).strip()
                asset_type = str(data.get("assetType", row["asset_type"])).strip() or category
                name = str(data.get("name", row["name"])).strip()
                description = str(data.get("description", row["description"])).strip()
                if not category or not name or not description:
                    return self.send_json({"error": "category, name and description are required"}, 400)
                badges = data.get("badges", json.loads(row["badges"] or "[]"))
                fields = data.get("fields", json.loads(row["fields_json"] or "[]"))
                if not isinstance(fields, list):
                    return self.send_json({"error": "fields must be an array"}, 400)
                db.execute(
                    """UPDATE semantic_assets
                       SET category = ?, asset_type = ?, name = ?, description = ?,
                           badges = ?, fields_json = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        category,
                        asset_type,
                        name,
                        description,
                        json.dumps(badges, ensure_ascii=False),
                        json.dumps(fields, ensure_ascii=False),
                        now,
                        asset_id,
                    ),
                )
                return self.send_json({
                    "id": asset_id,
                    "category": category,
                    "assetType": asset_type,
                    "type": asset_type,
                    "name": name,
                    "description": description,
                    "badges": badges,
                    "fields": fields,
                    "updated_at": now,
                })
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
                if row["customer_id"]:
                    emit_customer_profile_event(
                        db,
                        "opportunity_stage_changed",
                        row["customer_id"],
                        "opportunity_stage_transition",
                        transition_cur.lastrowid,
                        {"opportunityId": oid, "fromStage": old_name, "toStage": new_stage, "required": required},
                        now=now,
                        dedupe_key=f"opportunity_stage_changed:transition:{transition_cur.lastrowid}",
                    )
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
                if agent_id == "customer-insight":
                    try:
                        customer_id = int(data["customerId"])
                    except (KeyError, TypeError, ValueError):
                        return self.send_json({"error": "customerId is required and must be an integer"}, 400)
                    try:
                        report = CustomerInsightAgent(db).run(customer_id, now)
                    except LookupError as exc:
                        return self.send_json({"error": str(exc)}, 404)
                    run_cur = db.execute(
                        """INSERT INTO agent_runs
                           (agent_id, opportunity_id, input_json, result, status, created_at)
                           VALUES (?, NULL, ?, ?, 'completed', ?)""",
                        (agent_id, json.dumps(data, ensure_ascii=False), json.dumps(report, ensure_ascii=False), now),
                    )
                    return self.send_json({
                        "id": run_cur.lastrowid,
                        "agentId": agent_id,
                        "status": "completed",
                        "insights": report["insights"],
                        "report": report["report"],
                        "contextSummary": report["contextSummary"],
                    }, 201)
                try:
                    opportunity_id = int(data["opportunityId"]) if data.get("opportunityId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if opportunity_id is not None and not db.execute(
                    "SELECT 1 FROM opportunities WHERE id = ?", (opportunity_id,)
                ).fetchone():
                    return self.send_json({"error": "opportunity not found"}, 404)
                try:
                    customer_id = int(data["customerId"]) if data.get("customerId") else None
                except (TypeError, ValueError):
                    return self.send_json({"error": "invalid customer id"}, 400)
                result = data.get("result") or "已完成语义分析，生成待确认的客户开发建议。"
                fact_context = {"facts": [], "confirmedFacts": [], "suggestions": []}
                try:
                    from fact_agent_service import get_agent_fact_context
                    fact_context = get_agent_fact_context(
                        db, agent_id, customer_id=customer_id,
                        opportunity_id=opportunity_id,
                    )
                    if fact_context["businessBasis"]:
                        result = f"{result} 业务依据：{'；'.join(fact_context['businessBasis'])}。"
                    if fact_context["提示"]:
                        result = f"{result} 待确认提示：{'；'.join(fact_context['提示'])}。"
                except ValueError:
                    pass
                relationship_context = ""
                if opportunity_id:
                    relationship_analysis = RelationshipService(db).find_decision_makers(opportunity_id)
                    recommended = (relationship_analysis.get("recommended") or [None])[0]
                    if recommended:
                        relationship_context = (
                            f"关系分析：建议优先联系{recommended['sourceEntity']['name']}，"
                            f"当前关系强度{recommended.get('strength_score', 0)}分。"
                        )
                    else:
                        relationship_context = "关系分析：当前商机暂无直接决策人关系，建议先补齐关键人并建立联系。"
                    result = f"{result} {relationship_context}"
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
                return self.send_json({"id": cur.lastrowid, "agentId": agent_id, "result": result, "factContext": fact_context, "status": "completed", "action": action}, 201)
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
    port = int(os.environ.get("PORT", 8877))

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        Handler
    )

    print(f"CRM backend running on port {port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
