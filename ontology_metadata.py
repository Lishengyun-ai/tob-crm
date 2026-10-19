"""本体元数据注册层。

该模块只保存本体定义、物理字段映射和治理信息，不复制任何业务实例数据。
业务表仍由 server.py 中既有模型负责；本模块通过 source_table/source_column
以及 relationship_type_id 建立引用关系。
"""

import json
import re
from datetime import datetime, timezone


# 元数据治理使用两套独立维度。旧目录中已有“部分实现”“已确认”“草案”值，
# 继续接受这些值以保持兼容，但新建和编辑页面优先使用下列规范枚举。
DEVELOPMENT_STATUS_OPTIONS = ("待核实", "规划中", "开发中", "已完成", "已停用")
DEVELOPMENT_STATUS_COMPATIBLE = ("部分实现", "已确认")
MATURITY_OPTIONS = ("待核实", "设计稿", "MVP", "基础版", "过渡版", "正式版")
MATURITY_COMPATIBLE = ("草案",)
DEVELOPMENT_STATUS_ALLOWED = set(DEVELOPMENT_STATUS_OPTIONS + DEVELOPMENT_STATUS_COMPATIBLE)
MATURITY_ALLOWED = set(MATURITY_OPTIONS + MATURITY_COMPATIBLE)

ONTOLOGY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ontology_domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name_zh TEXT NOT NULL,
  name_en TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  data_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  code TEXT NOT NULL UNIQUE,
  name_zh TEXT NOT NULL,
  name_en TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  source_type TEXT NOT NULL DEFAULT 'business_table',
  source_table TEXT NOT NULL DEFAULT '',
  source_pk TEXT NOT NULL DEFAULT 'id',
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  data_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES ontology_domains(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ontology_attributes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id INTEGER NOT NULL,
  code TEXT NOT NULL,
  name_zh TEXT NOT NULL,
  name_en TEXT NOT NULL DEFAULT '',
  data_type TEXT NOT NULL DEFAULT 'text',
  description TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  source_type TEXT NOT NULL DEFAULT 'physical_column',
  source_table TEXT NOT NULL DEFAULT '',
  source_column TEXT NOT NULL DEFAULT '',
  is_required INTEGER NOT NULL DEFAULT 0,
  is_multiple INTEGER NOT NULL DEFAULT 0,
  is_unique INTEGER NOT NULL DEFAULT 0,
  is_relation_field INTEGER NOT NULL DEFAULT 0,
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  data_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(entity_id, code),
  FOREIGN KEY(entity_id) REFERENCES ontology_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ontology_relation_definitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name_zh TEXT NOT NULL,
  name_en TEXT NOT NULL DEFAULT '',
  source_entity_id INTEGER NOT NULL,
  target_entity_id INTEGER NOT NULL,
  relationship_type_id INTEGER,
  relation_kind TEXT NOT NULL DEFAULT 'foreign_key',
  synonyms_json TEXT NOT NULL DEFAULT '[]',
  business_types_json TEXT NOT NULL DEFAULT '[]',
  master_slave_type TEXT NOT NULL DEFAULT 'peer',
  query_path TEXT NOT NULL DEFAULT '',
  traversal_depth INTEGER NOT NULL DEFAULT 1,
  execution_mode TEXT NOT NULL DEFAULT 'conceptual',
  cardinality TEXT NOT NULL DEFAULT '待核实',
  direction TEXT NOT NULL DEFAULT '待核实',
  physical_table TEXT NOT NULL DEFAULT '',
  source_column TEXT NOT NULL DEFAULT '',
  target_column TEXT NOT NULL DEFAULT '',
  constraint_description TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  data_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(source_entity_id) REFERENCES ontology_entities(id) ON DELETE RESTRICT,
  FOREIGN KEY(target_entity_id) REFERENCES ontology_entities(id) ON DELETE RESTRICT,
  FOREIGN KEY(relationship_type_id) REFERENCES relationship_types(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ontology_business_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name_zh TEXT NOT NULL,
  name_en TEXT NOT NULL DEFAULT '',
  rule_type TEXT NOT NULL DEFAULT 'constraint',
  layer TEXT NOT NULL DEFAULT 'business_ontology',
  subject_domain_id INTEGER,
  subject_entity_id INTEGER,
  expression_json TEXT NOT NULL DEFAULT '{}',
  action_json TEXT NOT NULL DEFAULT '{}',
  synonyms_json TEXT NOT NULL DEFAULT '[]',
  business_types_json TEXT NOT NULL DEFAULT '[]',
  scenario TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'warning',
  violation_message TEXT NOT NULL DEFAULT '',
  semantic_boundary TEXT NOT NULL DEFAULT '',
  dependencies_json TEXT NOT NULL DEFAULT '[]',
  priority INTEGER NOT NULL DEFAULT 50,
  effective_at TEXT,
  source_table TEXT NOT NULL DEFAULT '',
  source_ref TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  data_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(subject_entity_id) REFERENCES ontology_entities(id) ON DELETE SET NULL
  ,FOREIGN KEY(subject_domain_id) REFERENCES ontology_domains(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ontology_semantic_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL,
  source_key TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_code TEXT NOT NULL,
  mapping_type TEXT NOT NULL DEFAULT 'term_to_entity',
  term_type TEXT NOT NULL DEFAULT 'standard',
  domain_id INTEGER,
  business_types_json TEXT NOT NULL DEFAULT '[]',
  context_json TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 50,
  examples_json TEXT NOT NULL DEFAULT '[]',
  owner TEXT NOT NULL DEFAULT '',
  confidence INTEGER NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 100),
  status TEXT NOT NULL DEFAULT '待核实',
  evidence TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '0.1',
  development_status TEXT NOT NULL DEFAULT '待核实',
  maturity TEXT NOT NULL DEFAULT '待核实',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_change_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  object_type TEXT NOT NULL,
  object_code TEXT NOT NULL,
  action TEXT NOT NULL,
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  actor TEXT NOT NULL DEFAULT 'system',
  source TEXT NOT NULL DEFAULT 'system',
  version TEXT NOT NULL DEFAULT '',
  change_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ontology_entities_domain
  ON ontology_entities(domain_id, status, code);
CREATE INDEX IF NOT EXISTS idx_ontology_attributes_entity
  ON ontology_attributes(entity_id, status, code);
CREATE INDEX IF NOT EXISTS idx_ontology_relations_entities
  ON ontology_relation_definitions(source_entity_id, target_entity_id, status);
CREATE INDEX IF NOT EXISTS idx_ontology_rules_layer
  ON ontology_business_rules(layer, status, code);
CREATE INDEX IF NOT EXISTS idx_ontology_mappings_target
  ON ontology_semantic_mappings(target_type, target_code, status);
CREATE INDEX IF NOT EXISTS idx_ontology_change_logs_object
  ON ontology_change_logs(object_type, object_code, created_at DESC);
"""


DOMAIN_SEEDS = [
    (
        "customer",
        "客户",
        "Customer",
        "业务本体",
        "客户、客户组织、关键人及客户经营关系。",
        "0.1",
        "部分实现",
        "MVP",
        "customers; organizations; customer_organizations; persons",
    ),
    (
        "project",
        "项目",
        "Project",
        "业务本体",
        "工程项目、项目阶段、项目标段及项目参与方。",
        "0.1",
        "部分实现",
        "MVP",
        "projects; project_sections; project_phases; project_lots; project_parties",
    ),
    (
        "opportunity",
        "商机",
        "Opportunity",
        "业务本体",
        "商机及其客户、项目、关键人和推进状态。",
        "0.1",
        "部分实现",
        "MVP",
        "opportunities; opportunity_persons; stage_definitions",
    ),
    (
        "customer_profile",
        "客户画像",
        "Customer Profile",
        "业务本体",
        "客户画像快照、事实、评分、摘要和证据。",
        "0.1",
        "部分实现",
        "MVP",
        "customer_profiles; customer_profile_facts; customer_profile_scores",
    ),
    (
        "partner",
        "伙伴",
        "Partner",
        "业务本体",
        "项目伙伴及生态关系。当前项目存在项目参与方和伙伴关系类型，但独立伙伴主数据仍待核实。",
        "0.1",
        "待核实",
        "待核实",
        "project_parties; relationship_types",
    ),
]


ENTITY_SEEDS = [
    ("customer", "Customer", "客户", "Customer", "客户主实体。", "business_table", "customers", "已确认", "MVP", "server.py: customers"),
    ("customer", "Organization", "组织", "Organization", "客户和销售组织的组织结构实体。", "business_table", "organizations", "已确认", "MVP", "server.py: organizations"),
    ("customer", "CustomerOrganization", "客户组织", "Customer Organization", "客户内部组织树节点。", "business_table", "customer_organizations", "已确认", "MVP", "server.py: customer_organizations"),
    ("customer", "Person", "关键人", "Person", "客户、项目和商机相关人员。", "business_table", "persons", "已确认", "MVP", "server.py: persons"),
    ("project", "Project", "项目", "Project", "工程项目主实体。", "business_table", "projects", "已确认", "MVP", "server.py: projects"),
    ("project", "ProjectSection", "项目标段（旧）", "Project Section", "旧版项目分段实体，当前用于兼容和映射。", "business_table", "project_sections", "已确认", "MVP", "server.py: project_sections"),
    ("project", "ProjectPhase", "项目阶段", "Project Phase", "项目阶段实体。", "business_table", "project_phases", "已确认", "MVP", "server.py: project_phases"),
    ("project", "ProjectLot", "项目标段", "Project Lot", "项目阶段下的标段实体。", "business_table", "project_lots", "已确认", "MVP", "server.py: project_lots"),
    ("project", "ProjectParty", "项目参与方", "Project Party", "项目参与方记录；是否作为独立伙伴主实体仍待核实。", "business_table", "project_parties", "待核实", "待核实", "server.py: project_parties"),
    ("opportunity", "Opportunity", "商机", "Opportunity", "销售商机主实体。", "business_table", "opportunities", "已确认", "MVP", "server.py: opportunities"),
    ("customer", "CustomerDevelopment", "客户开发", "Customer Development", "客户经营开发主实体。", "business_table", "customer_developments", "已确认", "MVP", "server.py: customer_developments"),
    ("customer_profile", "CustomerProfile", "客户画像", "Customer Profile", "客户画像版本快照，不等同于 Customer 主数据。", "business_table", "customer_profiles", "已确认", "MVP", "server.py: customer_profiles"),
]


ATTRIBUTE_SEEDS = [
    ("Customer", "id", "客户 ID", "ID", "integer", "customers", "id", 1, 0, "客户主表主键。"),
    ("Customer", "name", "客户名称", "Name", "text", "customers", "name", 1, 0, "客户名称。"),
    ("Customer", "customer_type", "客户类型", "Customer Type", "text", "customers", "customer_type", 1, 0, "客户类型。"),
    ("Customer", "industry", "行业", "Industry", "text", "customers", "industry", 1, 0, "所属行业。"),
    ("Customer", "status", "状态", "Status", "text", "customers", "status", 1, 0, "客户业务状态。"),
    ("Customer", "customer_serial_no", "客户流水号", "Customer Serial No", "text", "customers", "customer_serial_no", 1, 0, "客户创建时生成的唯一业务标识；不等同于终端客户编码。"),
    ("Customer", "terminal_customer_code", "终端客户编码", "Terminal Customer Code", "text", "customers", "terminal_customer_code", 0, 1, "客户开发成功并通过既有审批后分配；可为空且全局唯一。"),
    ("Customer", "terminal_code_status", "终端客户编码状态", "Terminal Code Status", "text", "customers", "terminal_code_status", 1, 0, "终端客户编码申请/分配状态。"),
    ("Customer", "organization_id", "组织 ID", "Organization ID", "integer", "customers", "organization_id", 0, 0, "关联客户组织根节点。"),
    ("Organization", "id", "组织 ID", "ID", "integer", "organizations", "id", 1, 0, "组织主表主键。"),
    ("Organization", "parent_id", "上级组织 ID", "Parent ID", "integer", "organizations", "parent_id", 0, 0, "组织树父节点。"),
    ("Organization", "code", "组织编码", "Code", "text", "organizations", "code", 1, 0, "组织编码。"),
    ("Organization", "name", "组织名称", "Name", "text", "organizations", "name", 1, 0, "组织名称。"),
    ("CustomerOrganization", "customer_id", "客户 ID", "Customer ID", "integer", "customer_organizations", "customer_id", 1, 0, "所属客户。"),
    ("CustomerOrganization", "parent_id", "上级客户组织 ID", "Parent ID", "integer", "customer_organizations", "parent_id", 0, 0, "客户组织树父节点。"),
    ("CustomerOrganization", "name", "客户组织名称", "Name", "text", "customer_organizations", "name", 1, 0, "客户组织名称。"),
    ("CustomerOrganization", "organization_type", "组织类型", "Organization Type", "text", "customer_organizations", "organization_type", 1, 0, "客户组织类型。"),
    ("Person", "id", "人员 ID", "ID", "integer", "persons", "id", 1, 0, "人员主表主键。"),
    ("Person", "name", "姓名", "Name", "text", "persons", "name", 1, 0, "人员姓名。"),
    ("Person", "organization", "所属组织文本", "Organization", "text", "persons", "organization", 0, 0, "人员所属组织文本。"),
    ("Person", "title", "职位", "Title", "text", "persons", "title", 0, 0, "职位。"),
    ("Person", "role", "业务角色", "Role", "text", "persons", "role", 0, 0, "由增量字段补齐的业务角色。"),
    ("Project", "id", "项目 ID", "ID", "integer", "projects", "id", 1, 0, "项目主表主键。"),
    ("Project", "customer_id", "客户 ID", "Customer ID", "integer", "projects", "customer_id", 0, 0, "所属客户。"),
    ("Project", "customer_organization_id", "客户组织 ID", "Customer Organization ID", "integer", "projects", "customer_organization_id", 0, 0, "所属客户组织。"),
    ("Project", "name", "项目名称", "Name", "text", "projects", "name", 1, 0, "项目名称。"),
    ("Project", "project_type", "项目类型", "Project Type", "text", "projects", "project_type", 1, 0, "项目类型。"),
    ("Project", "status", "项目状态", "Status", "text", "projects", "status", 1, 0, "项目生命周期状态。"),
    ("ProjectSection", "project_id", "项目 ID", "Project ID", "integer", "project_sections", "project_id", 1, 0, "所属项目。"),
    ("ProjectSection", "name", "标段名称", "Name", "text", "project_sections", "name", 1, 0, "旧版标段名称。"),
    ("ProjectPhase", "project_id", "项目 ID", "Project ID", "integer", "project_phases", "project_id", 1, 0, "所属项目。"),
    ("ProjectPhase", "phase_name", "阶段名称", "Phase Name", "text", "project_phases", "phase_name", 1, 0, "项目阶段名称。"),
    ("ProjectPhase", "sequence", "阶段顺序", "Sequence", "integer", "project_phases", "sequence", 1, 0, "项目阶段顺序。"),
    ("ProjectLot", "phase_id", "阶段 ID", "Phase ID", "integer", "project_lots", "phase_id", 1, 0, "所属项目阶段。"),
    ("ProjectLot", "lot_name", "标段名称", "Lot Name", "text", "project_lots", "lot_name", 1, 0, "标段名称。"),
    ("ProjectLot", "amount", "金额", "Amount", "real", "project_lots", "amount", 1, 0, "标段金额。"),
    ("Opportunity", "id", "商机 ID", "ID", "integer", "opportunities", "id", 1, 0, "商机主表主键。"),
    ("Opportunity", "name", "商机名称", "Name", "text", "opportunities", "name", 1, 0, "商机名称。"),
    ("Opportunity", "customer_id", "客户 ID", "Customer ID", "integer", "opportunities", "customer_id", 0, 0, "关联客户。"),
    ("Opportunity", "project_id", "项目 ID", "Project ID", "integer", "opportunities", "project_id", 0, 0, "关联项目。"),
    ("Opportunity", "project_lot_id", "项目标段 ID", "Project Lot ID", "integer", "opportunities", "project_lot_id", 0, 0, "关联项目标段。"),
    ("Opportunity", "stage", "商机阶段", "Stage", "text", "opportunities", "stage", 1, 0, "商机当前业务阶段。"),
    ("Opportunity", "amount", "商机金额", "Amount", "integer", "opportunities", "amount", 1, 0, "商机金额。"),
    ("Opportunity", "owner", "负责人", "Owner", "text", "opportunities", "owner", 1, 0, "商机负责人。"),
    ("CustomerDevelopment", "customer_id", "客户 ID", "Customer ID", "integer", "customer_developments", "customer_id", 1, 0, "客户开发所属客户。"),
    ("CustomerDevelopment", "current_stage_code", "当前阶段编码", "Current Stage Code", "text", "customer_developments", "current_stage_code", 1, 0, "客户开发阶段编码。"),
    ("CustomerDevelopment", "status", "状态", "Status", "text", "customer_developments", "status", 1, 0, "客户开发状态。"),
    ("CustomerProfile", "customer_id", "客户 ID", "Customer ID", "integer", "customer_profiles", "customer_id", 1, 0, "画像所属客户。"),
    ("CustomerProfile", "version_no", "画像版本号", "Version", "integer", "customer_profiles", "version_no", 1, 0, "客户画像快照版本。"),
    ("CustomerProfile", "profile_type", "画像类型", "Profile Type", "text", "customer_profiles", "profile_type", 1, 0, "客户画像类型。"),
    ("CustomerProfile", "confidence_score", "置信度", "Confidence Score", "integer", "customer_profiles", "confidence_score", 0, 0, "画像置信度。"),
]


RELATION_SEEDS = [
    ("customer_has_customer_organization", "客户拥有客户组织", "Customer has Customer Organization", "Customer", "CustomerOrganization", "foreign_key", "customer_organizations", "customer_id", "id", "客户与客户组织根节点的一对多关系。", "已确认", "MVP", "customer_organizations.customer_id"),
    ("customer_owns_project", "客户拥有项目", "Customer owns Project", "Customer", "Project", "foreign_key", "projects", "customer_id", "id", "客户与项目的直接外键关系。", "已确认", "MVP", "projects.customer_id"),
    ("customer_has_opportunity", "客户拥有商机", "Customer has Opportunity", "Customer", "Opportunity", "foreign_key", "opportunities", "customer_id", "id", "客户与商机的直接外键关系。", "已确认", "MVP", "opportunities.customer_id"),
    ("project_has_opportunity", "项目包含商机", "Project has Opportunity", "Project", "Opportunity", "foreign_key", "opportunities", "project_id", "id", "项目与商机的直接外键关系。", "已确认", "MVP", "opportunities.project_id"),
    ("project_has_section", "项目包含旧版标段", "Project has Project Section", "Project", "ProjectSection", "foreign_key", "project_sections", "project_id", "id", "项目与旧版项目标段的关系。", "已确认", "MVP", "project_sections.project_id"),
    ("project_has_phase", "项目包含阶段", "Project has Project Phase", "Project", "ProjectPhase", "foreign_key", "project_phases", "project_id", "id", "项目与阶段的关系。", "已确认", "MVP", "project_phases.project_id"),
    ("phase_has_lot", "阶段包含标段", "Project Phase has Project Lot", "ProjectPhase", "ProjectLot", "foreign_key", "project_lots", "phase_id", "id", "项目阶段与标段的关系。", "已确认", "MVP", "project_lots.phase_id"),
    ("project_has_lot", "项目包含标段", "Project has Project Lot", "Project", "ProjectLot", "derived", "project_phases; project_lots", "project_id; phase_id", "id", "项目通过项目阶段传递到项目标段的关系。", "已确认", "MVP", "project_phases.project_id + project_lots.phase_id"),
    ("project_lot_has_opportunity", "标段承载商机", "Project Lot has Opportunity", "ProjectLot", "Opportunity", "foreign_key", "opportunities", "project_lot_id", "id", "项目标段与商机的关联关系。", "已确认", "MVP", "opportunities.project_lot_id"),
    ("person_contacts_customer", "人员关联客户", "Person contacts Customer", "Person", "Customer", "runtime_relationship", "customer_persons", "person_id", "customer_id", "复用 customer_persons 与 relationship_types 的人员客户关系。", "已确认", "MVP", "customer_persons; relationship_types"),
    ("person_contacts_project", "人员关联项目", "Person contacts Project", "Person", "Project", "runtime_relationship", "project_persons", "person_id", "project_id", "复用 project_persons 与 relationship_types 的人员项目关系。", "已确认", "MVP", "project_persons; relationship_types"),
    ("person_contacts_opportunity", "人员关联商机", "Person contacts Opportunity", "Person", "Opportunity", "runtime_relationship", "opportunity_persons", "person_id", "opportunity_id", "复用 opportunity_persons 与 relationship_types 的人员商机关系。", "已确认", "MVP", "opportunity_persons; relationship_types"),
    ("organization_has_parent", "组织隶属组织", "Organization has Parent", "Organization", "Organization", "hierarchy", "organizations", "parent_id", "id", "组织树父子关系。", "已确认", "MVP", "organizations.parent_id"),
    ("customer_profile_describes_customer", "画像描述客户", "Customer Profile describes Customer", "CustomerProfile", "Customer", "foreign_key", "customer_profiles", "customer_id", "id", "客户画像快照与客户的关系。", "已确认", "MVP", "customer_profiles.customer_id"),
]


RELATION_METADATA = {
    "customer_has_customer_organization": ("一对多", "Customer → CustomerOrganization", "每个 CustomerOrganization 必须归属一个 Customer；同一 Customer 可拥有多个客户组织。"),
    "customer_owns_project": ("一对多", "Customer → Project", "Project.customer_id 指向 Customer.id；项目必须归属客户。"),
    "customer_has_opportunity": ("一对多", "Customer → Opportunity", "Opportunity.customer_id 指向 Customer.id；商机至少关联客户。"),
    "project_has_opportunity": ("一对多", "Project → Opportunity", "Opportunity.project_id 指向 Project.id；项目型商机应关联项目。"),
    "project_has_section": ("一对多", "Project → ProjectSection", "旧版 ProjectSection.project_id 指向 Project.id，仅用于兼容映射。"),
    "project_has_phase": ("一对多", "Project → ProjectPhase", "ProjectPhase.project_id 指向 Project.id；阶段属于项目。"),
    "phase_has_lot": ("一对多", "ProjectPhase → ProjectLot", "ProjectLot.phase_id 指向 ProjectPhase.id；标段属于阶段。"),
    "project_has_lot": ("一对多", "Project → ProjectLot", "ProjectLot 通过 ProjectPhase.project_id 间接归属 Project，不新增直接业务外键。"),
    "project_lot_has_opportunity": ("一对多", "ProjectLot → Opportunity", "Opportunity.project_lot_id 记录其所属标段；为空时表示尚未绑定标段。"),
    "person_contacts_customer": ("多对多", "Person ↔ Customer", "通过 customer_persons 与 relationship_types 管理人员与客户关系。"),
    "person_contacts_project": ("多对多", "Person ↔ Project", "通过 project_persons 与 relationship_types 管理人员与项目关系。"),
    "person_contacts_opportunity": ("多对多", "Person ↔ Opportunity", "通过 opportunity_persons 与 relationship_types 管理人员与商机关系。"),
    "organization_has_parent": ("一对多", "Organization → Organization", "Organization.parent_id 指向上级组织；同一组织只能有一个直接上级。"),
    "customer_profile_describes_customer": ("多对一", "CustomerProfile → Customer", "CustomerProfile.customer_id 指向 Customer.id；画像是客户的版本化快照。"),
}


RULE_SEEDS = [
    ("opportunity_stage_engine", "商机阶段引擎", "Opportunity Stage Engine", "stage_engine", "associated_capability", "Opportunity", {"source": "stage_definitions", "object_type": "opportunity"}, {}, "stage_definitions", "stage_definitions", "阶段引擎用于生命周期控制，作为关联能力管理，不计入业务本体数量。", "0.1", "已确认", "MVP", "server.py: stage_definitions"),
    ("customer_profile_scoring", "客户画像评分规则", "Customer Profile Scoring", "scoring", "associated_capability", "CustomerProfile", {"source": "customer_profile_scoring_rules"}, {}, "customer_profile_scoring_rules", "customer_profile_scoring_models", "客户画像评分规则作为画像能力管理，不等同于本体属性定义。", "0.1", "已确认", "MVP", "server.py: customer_profile_scoring_rules"),
    ("relationship_score_engine", "关系评分引擎", "Relationship Score Engine", "scoring", "associated_capability", None, {"source": "relationship_score_*"}, {}, "relationship_score_rules", "relationship_score_models", "关系评分模型作为关系能力管理，不自动计入业务本体规则数量。", "0.1", "部分实现", "待核实", "server.py: relationship_score_*"),
    ("opportunity_reporting_required", "商机报备必填规则", "Opportunity Reporting Required", "stage_gate", "business_ontology", "Opportunity", {"stage": "OPP_REPORTED", "required": ["projectName", "customer", "source"]}, {"result": "允许进入商机报备"}, "stage_definitions", "STAGE_DEFINITIONS.OPP_REPORTED", "商机报备阶段要求项目名称、客户名称和商机来源；这里仅登记规则依据，不在本页面执行。", "0.1", "已确认", "MVP", "server.py: STAGE_DEFINITIONS"),
    ("opportunity_duplicate_check_before_confirmation", "商机确认前查重规则", "Opportunity Duplicate Check Before Confirmation", "stage_gate", "business_ontology", "Opportunity", {"stage": "OPP_CONFIRMED", "required": ["duplicateStatus", "projectType"]}, {"result": "查重完成后才允许确认"}, "discovery_candidates; duplicate_checks", "server.py: duplicate-check and confirmation", "商机确认前必须完成查重；低置信度或疑似重复记录还需要人工复核。", "0.1", "已确认", "MVP", "server.py: 10356-10390"),
    ("project_phase_lot_name_unique", "项目期和标段名称唯一规则", "Project Phase and Lot Name Uniqueness", "constraint", "business_ontology", "Project", {"project_phase": "UNIQUE(project_id, phase_name)", "project_lot": "UNIQUE(phase_id, lot_name)"}, {}, "project_phases; project_lots", "server.py schema", "同一项目内项目期名称唯一，同一项目期内标段名称唯一；复用现有数据库约束，不新增业务字段。", "0.1", "已确认", "MVP", "server.py: project_phases/project_lots schema"),
    ("opportunity_supply_mode_definition", "商机供料模式定义", "Opportunity Supply Mode Definition", "semantic_constraint", "business_ontology", "Opportunity", {"planned_values": ["SINGLE_SUPPLIER", "DUAL_PACKAGE"], "source": "opportunity-revenue-forecast.md"}, {}, "", "opportunity-revenue-forecast.md: supply_mode", "设计资料定义单供料和双包模式，但当前 CRM 业务表与执行接口尚未确认该字段已落地。", "0.1", "待核实", "待核实", "opportunity-revenue-forecast.md"),
    ("dual_package_revenue_allocation", "双包收入分配约束", "Dual Package Revenue Allocation", "constraint", "business_ontology", "Opportunity", {"constraints": ["sum(package_share) <= 1", "sum(package.net_revenue) = potential_revenue"], "source": "opportunity-revenue-forecast.md"}, {}, "", "opportunity-revenue-forecast.md: dual package rules", "双包金额需要按范围或采购包拆分，不能把两个报价直接相加；当前没有对应执行引擎，本条仅作为待核实规则登记。", "0.1", "待核实", "待核实", "opportunity-revenue-forecast.md"),
]


MAPPING_SEEDS = [
    ("term_customer", "business_term", "客户", "entity", "Customer", "term_to_entity", 100, "已确认", "项目业务模型、customers 表及设计资料均使用客户概念。"),
    ("term_project", "business_term", "项目", "entity", "Project", "term_to_entity", 100, "已确认", "projects 表及项目管理页面使用项目概念。"),
    ("term_opportunity", "business_term", "商机", "entity", "Opportunity", "term_to_entity", 100, "已确认", "opportunities 表及商机页面使用商机概念。"),
    ("term_customer_profile", "business_term", "客户画像", "entity", "CustomerProfile", "term_to_entity", 100, "已确认", "customer_profiles 表及客户画像页面使用客户画像概念。"),
    ("table_customers", "physical_table", "customers", "entity", "Customer", "table_to_entity", 100, "已确认", "server.py customers schema。"),
    ("table_projects", "physical_table", "projects", "entity", "Project", "table_to_entity", 100, "已确认", "server.py projects schema。"),
    ("table_opportunities", "physical_table", "opportunities", "entity", "Opportunity", "table_to_entity", 100, "已确认", "server.py opportunities schema。"),
    ("table_customer_profiles", "physical_table", "customer_profiles", "entity", "CustomerProfile", "table_to_entity", 100, "已确认", "server.py customer_profiles schema。"),
    ("capability_agent_action", "agent_infrastructure", "agents; actions", "capability", "AgentActionInfrastructure", "excluded_from_ontology", 100, "已确认", "Agent、Action 属于关联能力，不计入业务本体统计。"),
    ("capability_stage_engine", "stage_engine", "stage_definitions", "capability", "OpportunityStageEngine", "associated_capability", 100, "已确认", "阶段引擎属于生命周期能力，不计入业务本体统计。"),
    ("term_coating_opportunity", "business_term", "涂料商机", "entity", "Opportunity", "term_to_entity", 60, "待核实", "outputs/index.html 的语义资产与 Agent 配置使用涂料商机概念；当前业务表仍使用通用 Opportunity。"),
    ("term_single_supplier", "business_term", "单供料", "capability", "OpportunitySupplyMode.SINGLE_SUPPLIER", "term_to_capability", 60, "待核实", "opportunity-revenue-forecast.md 定义 SINGLE_SUPPLIER；当前业务表和执行接口未确认该枚举已落地。"),
    ("term_dual_package", "business_term", "双包", "capability", "OpportunitySupplyMode.DUAL_PACKAGE", "term_to_capability", 60, "待核实", "opportunity-revenue-forecast.md 定义 DUAL_PACKAGE；当前业务表和执行接口未确认该枚举已落地。"),
    ("term_project_new_build", "business_term", "新建", "attribute", "Project.project_type", "term_to_attribute_value", 50, "待核实", "项目模型存在 project_type 字段，但代码默认值为工程项目，未确认新建枚举。"),
    ("term_project_renovation", "business_term", "旧改", "attribute", "Project.project_type", "term_to_attribute_value", 50, "待核实", "项目模型存在 project_type 字段；设计资料出现旧墙翻新语义，未确认旧改枚举。"),
    ("term_opportunity_reporting", "business_term", "商机报备", "capability", "OpportunityStageEngine", "term_to_stage", 100, "已确认", "server.py 的 STAGE_DEFINITIONS 与阶段接口均登记商机报备。"),
    ("term_opportunity_duplicate_check", "business_term", "商机查重", "capability", "OpportunityDuplicateCheck", "term_to_capability", 100, "已确认", "server.py 提供 duplicate-check 接口，并在确认前阻止未查重记录进入下一步。"),
    ("term_project_phase", "business_term", "项目期数", "entity", "ProjectPhase", "term_to_entity", 100, "已确认", "project_phases 表和初始化迁移逻辑已实现项目阶段实体。"),
    ("term_project_lot", "business_term", "项目标段", "entity", "ProjectLot", "term_to_entity", 100, "已确认", "project_lots 表和项目阶段接口已实现项目标段实体。"),
]


def ensure_ontology_metadata_schema(db):
    """创建本体元数据表；不会修改任何既有业务表结构。"""
    db.executescript(ONTOLOGY_SCHEMA_SQL)
    # 版本化补齐元数据表字段。这里仅迁移 ontology_* 元数据表，绝不触碰业务表。
    columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_attributes)").fetchall()}
    if "is_unique" not in columns:
        db.execute("ALTER TABLE ontology_attributes ADD COLUMN is_unique INTEGER NOT NULL DEFAULT 0")
    if "is_relation_field" not in columns:
        db.execute("ALTER TABLE ontology_attributes ADD COLUMN is_relation_field INTEGER NOT NULL DEFAULT 0")
    relation_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_relation_definitions)").fetchall()}
    if "cardinality" not in relation_columns:
        db.execute("ALTER TABLE ontology_relation_definitions ADD COLUMN cardinality TEXT NOT NULL DEFAULT '待核实'")
    if "direction" not in relation_columns:
        db.execute("ALTER TABLE ontology_relation_definitions ADD COLUMN direction TEXT NOT NULL DEFAULT '待核实'")
    if "constraint_description" not in relation_columns:
        db.execute("ALTER TABLE ontology_relation_definitions ADD COLUMN constraint_description TEXT NOT NULL DEFAULT ''")
    for name, definition in (
        ("synonyms_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("business_types_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("master_slave_type", "TEXT NOT NULL DEFAULT 'peer'"),
        ("query_path", "TEXT NOT NULL DEFAULT ''"),
        ("traversal_depth", "INTEGER NOT NULL DEFAULT 1"),
        ("execution_mode", "TEXT NOT NULL DEFAULT 'conceptual'"),
    ):
        if name not in relation_columns:
            db.execute(f"ALTER TABLE ontology_relation_definitions ADD COLUMN {name} {definition}")
    rule_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_business_rules)").fetchall()}
    if "subject_domain_id" not in rule_columns:
        db.execute("ALTER TABLE ontology_business_rules ADD COLUMN subject_domain_id INTEGER")
    for name, definition in (("synonyms_json", "TEXT NOT NULL DEFAULT '[]'"), ("business_types_json", "TEXT NOT NULL DEFAULT '[]'"), ("scenario", "TEXT NOT NULL DEFAULT ''"), ("severity", "TEXT NOT NULL DEFAULT 'warning'"), ("violation_message", "TEXT NOT NULL DEFAULT ''"), ("semantic_boundary", "TEXT NOT NULL DEFAULT ''"), ("dependencies_json", "TEXT NOT NULL DEFAULT '[]'"), ("priority", "INTEGER NOT NULL DEFAULT 50"), ("effective_at", "TEXT")):
        if name not in rule_columns:
            db.execute(f"ALTER TABLE ontology_business_rules ADD COLUMN {name} {definition}")
    entity_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_entities)").fetchall()}
    if "version" not in entity_columns:
        db.execute("ALTER TABLE ontology_entities ADD COLUMN version TEXT NOT NULL DEFAULT '0.1'")
    attribute_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_attributes)").fetchall()}
    if "version" not in attribute_columns:
        db.execute("ALTER TABLE ontology_attributes ADD COLUMN version TEXT NOT NULL DEFAULT '0.1'")
    relation_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_relation_definitions)").fetchall()}
    if "version" not in relation_columns:
        db.execute("ALTER TABLE ontology_relation_definitions ADD COLUMN version TEXT NOT NULL DEFAULT '0.1'")
    mapping_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_semantic_mappings)").fetchall()}
    for name, definition in (("term_type", "TEXT NOT NULL DEFAULT 'standard'"), ("domain_id", "INTEGER"), ("business_types_json", "TEXT NOT NULL DEFAULT '[]'"), ("context_json", "TEXT NOT NULL DEFAULT '{}'"), ("priority", "INTEGER NOT NULL DEFAULT 50"), ("examples_json", "TEXT NOT NULL DEFAULT '[]'"), ("owner", "TEXT NOT NULL DEFAULT ''")):
        if name not in mapping_columns:
            db.execute(f"ALTER TABLE ontology_semantic_mappings ADD COLUMN {name} {definition}")
    if "development_status" not in mapping_columns:
        db.execute("ALTER TABLE ontology_semantic_mappings ADD COLUMN development_status TEXT NOT NULL DEFAULT '待核实'")
    if "maturity" not in mapping_columns:
        db.execute("ALTER TABLE ontology_semantic_mappings ADD COLUMN maturity TEXT NOT NULL DEFAULT '待核实'")
    change_columns = {row[1] for row in db.execute("PRAGMA table_info(ontology_change_logs)").fetchall()}
    if "version" not in change_columns:
        db.execute("ALTER TABLE ontology_change_logs ADD COLUMN version TEXT NOT NULL DEFAULT ''")
    if "change_summary" not in change_columns:
        db.execute("ALTER TABLE ontology_change_logs ADD COLUMN change_summary TEXT NOT NULL DEFAULT ''")


def _insert_seed(db, sql, values):
    db.execute(sql, values)


def seed_ontology_metadata(db, now):
    """按代码幂等初始化本体目录，保留后续人工编辑的元数据。"""
    ensure_ontology_metadata_schema(db)

    for item in DOMAIN_SEEDS:
        db.execute(
            """INSERT OR IGNORE INTO ontology_domains
               (code, name_zh, name_en, category, description, version,
                development_status, maturity, data_source, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (*item, now, now),
        )

    domain_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM ontology_domains").fetchall()
    }
    for domain_code, code, name_zh, name_en, description, source_type, source_table, development_status, maturity, data_source in ENTITY_SEEDS:
        db.execute(
            """INSERT OR IGNORE INTO ontology_entities
               (domain_id, code, name_zh, name_en, description, source_type,
                source_table, source_pk, development_status, maturity, data_source,
                status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'id', ?, ?, ?, 'active', ?, ?)""",
            (domain_ids[domain_code], code, name_zh, name_en, description, source_type,
             source_table, development_status, maturity, data_source, now, now),
        )

    entity_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM ontology_entities").fetchall()
    }
    for entity_code, code, name_zh, name_en, data_type, source_table, source_column, is_required, is_multiple, description in ATTRIBUTE_SEEDS:
        is_unique = 1 if (entity_code, code) in {("Customer", "id"), ("Customer", "name"), ("Organization", "id"), ("Organization", "code")} else 0
        is_relation_field = 1 if code.endswith("_id") or code == "parent_id" else 0
        db.execute(
            """INSERT OR IGNORE INTO ontology_attributes
               (entity_id, code, name_zh, name_en, data_type, description,
                source_type, source_table, source_column, is_required, is_multiple,
                is_unique, is_relation_field,
                development_status, maturity, data_source, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'physical_column', ?, ?, ?, ?, ?, ?,
                       '已确认', 'MVP', ?, 'active', ?, ?)""",
            (entity_ids[entity_code], code, name_zh, name_en, data_type, description,
             source_table, source_column, is_required, is_multiple, is_unique, is_relation_field,
             f"{source_table}.{source_column}", now, now),
        )
        # INSERT OR IGNORE 会保留人工编辑值；仅为旧记录补齐首次引入的标记。
        db.execute(
            "UPDATE ontology_attributes SET is_unique = ?, is_relation_field = ? WHERE entity_id = ? AND code = ? AND is_unique = 0 AND is_relation_field = 0",
            (is_unique, is_relation_field, entity_ids[entity_code], code),
        )

    relationship_type_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM relationship_types").fetchall()
    }
    relation_type_lookup = {
        "person_contacts_customer": relationship_type_ids.get("person_customer_contact"),
        "person_contacts_project": relationship_type_ids.get("person_project_owner"),
        "person_contacts_opportunity": relationship_type_ids.get("person_opportunity_influencer"),
    }
    for code, name_zh, name_en, source_code, target_code, relation_kind, physical_table, source_column, target_column, description, development_status, maturity, data_source in RELATION_SEEDS:
        cardinality, direction, constraint_description = RELATION_METADATA.get(code, ("待核实", "待核实", ""))
        db.execute(
            """INSERT OR IGNORE INTO ontology_relation_definitions
               (code, name_zh, name_en, source_entity_id, target_entity_id,
                relationship_type_id, relation_kind, cardinality, direction, physical_table, source_column,
                target_column, constraint_description, description, development_status, maturity,
                data_source, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (code, name_zh, name_en, entity_ids[source_code], entity_ids[target_code],
             relation_type_lookup.get(code), relation_kind, cardinality, direction, physical_table, source_column,
             target_column, constraint_description, description, development_status, maturity, data_source, now, now),
        )
        db.execute(
            """UPDATE ontology_relation_definitions
               SET cardinality = CASE WHEN cardinality IN ('', '待核实') THEN ? ELSE cardinality END,
                   direction = CASE WHEN direction IN ('', '待核实') THEN ? ELSE direction END,
                   constraint_description = CASE WHEN constraint_description = '' THEN ? ELSE constraint_description END
               WHERE code = ?""",
            (cardinality, direction, constraint_description, code),
        )

    for code, name_zh, name_en, rule_type, layer, subject_code, expression, action, source_table, source_ref, description, version, development_status, maturity, data_source in RULE_SEEDS:
        db.execute(
            """INSERT OR IGNORE INTO ontology_business_rules
               (code, name_zh, name_en, rule_type, layer, subject_domain_id, subject_entity_id,
                expression_json, action_json, source_table, source_ref, description,
                version, development_status, maturity, data_source, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (code, name_zh, name_en, rule_type, layer,
             next((domain_id for domain_code, domain_id in domain_ids.items()
                   if subject_code and db.execute("SELECT 1 FROM ontology_entities WHERE id = ? AND domain_id = ?", (entity_ids.get(subject_code), domain_id)).fetchone()), None),
             entity_ids.get(subject_code) if subject_code else None,
             json.dumps(expression, ensure_ascii=False), json.dumps(action, ensure_ascii=False),
             source_table, source_ref, description, version, development_status,
             maturity, data_source, now, now),
        )
        if subject_code:
            db.execute(
                """UPDATE ontology_business_rules
                   SET subject_domain_id = COALESCE(subject_domain_id,
                       (SELECT domain_id FROM ontology_entities WHERE id = subject_entity_id))
                   WHERE code = ?""",
                (code,),
            )

    for code, source_type, source_key, target_type, target_code, mapping_type, confidence, status, evidence in MAPPING_SEEDS:
        db.execute(
            """INSERT OR IGNORE INTO ontology_semantic_mappings
               (code, source_type, source_key, target_type, target_code, mapping_type,
                confidence, status, evidence, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '0.1', ?, ?)""",
            (code, source_type, source_key, target_type, target_code, mapping_type,
             confidence, status, evidence, now, now),
        )
    # 关键消歧样例：仅登记标准概念映射，不创建业务实体，也不触发动作。
    term_seeds = [
        ("term_phase_lot_2_1", "二期一标", "entity", "ProjectLot", {"contains_any": ["二期", "一标"]}, 95, "项目标段信息"),
        ("term_reporting_object", "工程报备", "capability", "OpportunityReporting", {"contains_any": ["项目", "商机", "客户"]}, 90, "工程报备业务对象"),
        ("term_reporting_action", "工程报备", "capability", "OpportunityStageEngine", {"contains_any": ["提交", "发起", "报备"]}, 88, "工程报备提交动作"),
        ("term_design_institute_gap", "设计院还没突破", "relation", "person_contacts_customer", {"contains_any": ["设计院", "突破"]}, 96, "客户关系或决策链缺口"),
    ]
    for code, source_key, target_type, target_code, context, confidence, evidence in term_seeds:
        db.execute("""INSERT OR IGNORE INTO ontology_semantic_mappings
          (code,source_type,source_key,target_type,target_code,mapping_type,term_type,business_types_json,context_json,priority,examples_json,owner,confidence,status,evidence,version,development_status,maturity,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (code, "business_term", source_key, target_type, target_code, "term_to_concept", "alias", "[]", json.dumps(context, ensure_ascii=False), 90, json.dumps([source_key], ensure_ascii=False), "语义治理管理员", confidence, "已确认", evidence, "1.0", "已完成", "MVP", now, now))

    # 为每条已登记定义保存首次真实快照，使详情页的历史记录有可追溯起点。
    seed_objects = (
        ("ontology_domains", "domain"),
        ("ontology_entities", "entity"),
        ("ontology_attributes", "attribute"),
        ("ontology_relation_definitions", "relation"),
        ("ontology_business_rules", "rule"),
        ("ontology_semantic_mappings", "mapping"),
    )
    for table, object_type in seed_objects:
        for row in db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall():
            object_code = row["code"]
            if db.execute(
                "SELECT 1 FROM ontology_change_logs WHERE object_type=? AND object_code=? AND action='seed'",
                (object_type, object_code),
            ).fetchone():
                continue
            snapshot = dict(row)
            db.execute(
                """INSERT INTO ontology_change_logs
                   (object_type, object_code, action, before_json, after_json, actor, source, version, change_summary, created_at)
                   VALUES (?, ?, 'seed', '{}', ?, 'system', 'initialization', ?, '初始化定义；保存首次快照', ?)""",
                (object_type, object_code, json.dumps(snapshot, ensure_ascii=False), snapshot.get("version", ""), now),
            )

    if not db.execute(
        """SELECT 1 FROM ontology_change_logs
           WHERE object_type = 'catalog' AND object_code = 'initial' AND action = 'seed'"""
    ).fetchone():
        counts = {}
        for table in (
            "ontology_domains", "ontology_entities", "ontology_attributes",
            "ontology_relation_definitions", "ontology_business_rules",
            "ontology_semantic_mappings",
        ):
            counts[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        db.execute(
            """INSERT INTO ontology_change_logs
               (object_type, object_code, action, before_json, after_json, actor, source, created_at)
               VALUES ('catalog', 'initial', 'seed', '{}', ?, 'system', 'initialization', ?)""",
            (json.dumps(counts, ensure_ascii=False), now),
        )


def _rows(db, table, order_by="id"):
    return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()]


def ontology_catalog(db):
    """返回本体元数据目录，不包含任何业务实例行。"""
    domains = _rows(db, "ontology_domains", "code")
    entities = _rows(db, "ontology_entities", "code")
    attributes = _rows(db, "ontology_attributes", "entity_id, code")
    domain_names = {row["id"]: row for row in domains}
    entity_names = {row["id"]: row for row in entities}
    attr_counts = {}
    for attr in attributes:
        attr_counts[attr["entity_id"]] = attr_counts.get(attr["entity_id"], 0) + (1 if attr.get("status", "active") == "active" else 0)
    for entity in entities:
        domain = domain_names.get(entity["domain_id"], {})
        entity["domain_code"] = domain.get("code", "")
        entity["domain_name_zh"] = domain.get("name_zh", "")
        entity["attribute_count"] = attr_counts.get(entity["id"], 0)
    for attr in attributes:
        entity = entity_names.get(attr["entity_id"], {})
        attr["entity_code"] = entity.get("code", "")
        attr["entity_name_zh"] = entity.get("name_zh", "")
    rules = _rows(db, "ontology_business_rules", "code")
    for rule in rules:
        domain = domain_names.get(rule.get("subject_domain_id"), {})
        entity = entity_names.get(rule.get("subject_entity_id"), {})
        rule["subject_domain_code"] = domain.get("code", "")
        rule["subject_domain_name_zh"] = domain.get("name_zh", "")
        rule["subject_entity_code"] = entity.get("code", "")
        rule["subject_entity_name_zh"] = entity.get("name_zh", "")
    mappings = _rows(db, "ontology_semantic_mappings", "code")
    entities_by_code = {row["code"]: row for row in entities}
    attributes_by_code = {row["code"]: row for row in attributes}
    for mapping in mappings:
        if mapping.get("target_type") == "domain":
            target = next((row for row in domains if row["code"] == mapping.get("target_code")), {})
        elif mapping.get("target_type") == "entity":
            target = entities_by_code.get(mapping.get("target_code"), {})
        elif mapping.get("target_type") == "attribute":
            target = attributes_by_code.get(mapping.get("target_code"), {})
        else:
            target = {}
        mapping["target_name_zh"] = target.get("name_zh", mapping.get("target_code", ""))
    return {
        "domains": domains,
        "entities": entities,
        "attributes": attributes,
        "relations": _rows(db, "ontology_relation_definitions", "code"),
        "rules": rules,
        "mappings": mappings,
        "changeLogs": _rows(db, "ontology_change_logs", "id DESC"),
    }


def ontology_collection(db, collection):
    mapping = {
        "domains": ("ontology_domains", "code"),
        "entities": ("ontology_entities", "code"),
        "attributes": ("ontology_attributes", "entity_id, code"),
        "relations": ("ontology_relation_definitions", "code"),
        "rules": ("ontology_business_rules", "code"),
        "mappings": ("ontology_semantic_mappings", "code"),
        "changes": ("ontology_change_logs", "id DESC"),
    }
    if collection not in mapping:
        raise KeyError(collection)
    table, order_by = mapping[collection]
    return _rows(db, table, order_by)


def ontology_change_history(db, object_type=None, object_code=None, limit=100):
    """返回真实保存的变更快照；before_json/after_json 可用于审计和历史查看。"""
    clauses = []
    values = []
    if object_type:
        clauses.append("object_type = ?")
        values.append(str(object_type))
    if object_code:
        clauses.append("object_code = ?")
        values.append(str(object_code))
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return [
        dict(row)
        for row in db.execute(
            f"SELECT * FROM ontology_change_logs{where} ORDER BY id DESC LIMIT ?",
            (*values, limit),
        ).fetchall()
    ]


def ontology_application_links(db, domain_id):
    """读取本体领域与现有 Agent、阶段工作流配置的只读关联。

    这里不创建新的关联表，也不把 Agent、Action 或阶段引擎计入本体目录。
    Agent 与实体/关系/规则的“已配置”状态只在已有 Agent 技能和语义资产文本中
    找到明确对象引用时成立；仅有阶段配置中的 agent_id 时保留为“待核实”。
    """
    domain = db.execute("SELECT * FROM ontology_domains WHERE id = ?", (int(domain_id),)).fetchone()
    if not domain:
        raise ValueError("ontology domain not found")
    domain = dict(domain)
    entities = [dict(row) for row in db.execute(
        "SELECT * FROM ontology_entities WHERE domain_id = ? ORDER BY code", (domain["id"],)
    ).fetchall()]
    entity_ids = {item["id"] for item in entities}
    relations = [dict(row) for row in db.execute(
        """SELECT r.* FROM ontology_relation_definitions r
           JOIN ontology_entities source_entity ON source_entity.id = r.source_entity_id
           LEFT JOIN ontology_entities target_entity ON target_entity.id = r.target_entity_id
           WHERE source_entity.domain_id = ? OR target_entity.domain_id = ?
           ORDER BY r.code""", (domain["id"], domain["id"])
    ).fetchall()]
    rules = [dict(row) for row in db.execute(
        """SELECT * FROM ontology_business_rules
           WHERE subject_domain_id = ? OR subject_entity_id IN ({})
           ORDER BY code""".format(",".join("?" for _ in entity_ids) or "NULL"),
        (domain["id"], *sorted(entity_ids)),
    ).fetchall()]

    def searchable(*values):
        return " ".join(str(value or "") for value in values).lower()

    def references(text, item, keys):
        hits = []
        for key in keys:
            value = str(item.get(key) or "").strip()
            if value and value.lower() in text and value not in hits:
                hits.append(value)
        return hits

    stages = [dict(row) for row in db.execute(
        "SELECT * FROM stage_definitions ORDER BY sequence, code"
    ).fetchall()]
    agent_rows = [dict(row) for row in db.execute(
        "SELECT * FROM agents ORDER BY scene, id"
    ).fetchall()]
    agent_items = []
    for agent in agent_rows:
        skills = [dict(row) for row in db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (agent["id"],)
        ).fetchall()]
        text = searchable(
            agent.get("id"), agent.get("name"), agent.get("scene"), agent.get("description"),
            *(value for skill in skills for value in (
                skill.get("name"), skill.get("description"), skill.get("linked_assets")
            )),
        )
        entity_refs = []
        for entity in entities:
            hits = references(text, entity, ("code", "name_zh", "name_en"))
            if hits:
                entity_refs.append({"code": entity["code"], "name_zh": entity["name_zh"], "evidence": hits[:3]})
        relation_refs = []
        for relation in relations:
            hits = references(text, relation, ("code", "name_zh", "name_en"))
            if hits:
                relation_refs.append({"code": relation["code"], "name_zh": relation["name_zh"], "evidence": hits[:3]})
        rule_refs = []
        for rule in rules:
            hits = references(text, rule, ("code", "name_zh", "name_en", "source_ref"))
            if hits:
                rule_refs.append({"code": rule["code"], "name_zh": rule["name_zh"], "evidence": hits[:3]})
        stage_refs = [
            {"code": stage["code"], "name": stage["name"]}
            for stage in stages
            if stage.get("agent_id") == agent["id"] and stage.get("object_type") == domain["code"]
        ]
        if entity_refs or relation_refs or rule_refs:
            association_status = "已配置"
            association_note = "来自现有 Agent 技能/语义资产配置；不代表运行时调用成功。"
        elif stage_refs:
            association_status = "待核实"
            association_note = "仅发现阶段工作流的 agent_id 关联，尚未发现明确本体对象引用。"
        else:
            association_status = "未配置"
            association_note = "当前配置中未发现该本体对象的明确引用。"
        agent_items.append({
            "id": agent["id"], "name": agent["name"], "scene": agent["scene"],
            "status": agent.get("status", "已启用"), "association_status": association_status,
            "entities": entity_refs, "relations": relation_refs, "rules": rule_refs,
            "stages": stage_refs, "skills": skills, "source": "agents; agent_skills",
            "note": association_note,
        })

    workflows = []
    agent_ids = {agent["id"] for agent in agent_rows}
    for stage in stages:
        if stage.get("object_type") != domain["code"]:
            continue
        try:
            required = json.loads(stage.get("required_fields_json") or "[]")
        except (TypeError, ValueError):
            required = []
        next_code = stage.get("next_code")
        next_stage = next((item["name"] for item in stages if item.get("code") == next_code), None)
        workflow_status = "已配置" if not stage.get("agent_id") or stage.get("agent_id") in agent_ids else "待核实"
        workflows.append({
            "id": stage["code"], "name": stage["name"], "type": "阶段工作流",
            "status": workflow_status, "agent_id": stage.get("agent_id") or "",
            "inputs": required, "outputs": ([{"key": "next_stage", "value": next_stage, "code": next_code}]
                        if next_code else []),
            "trigger": f"进入阶段：{stage['name']}",
            "source": "stage_definitions",
            "note": ("阶段配置关联，不代表 Agent 运行时调用成功。" if workflow_status == "已配置"
                     else "阶段配置存在，但 agent_id 未在现有 Agent 注册表中找到。"),
        })
    return {
        "domain": domain,
        "agents": agent_items,
        "workflows": workflows,
        "actions": [],
        "action_config": {
            "status": "未配置",
            "source": "actions",
            "message": "当前 actions 表保存运行中的行动记录，未发现独立 Action 定义或本体关联配置；因此不将运行记录当作配置关联。",
            "editable": False,
        },
        "summary": {
            "configured": sum(item["association_status"] == "已配置" for item in agent_items) + sum(item["status"] == "已配置" for item in workflows),
            "pending": sum(item["association_status"] == "待核实" for item in agent_items) + sum(item["status"] == "待核实" for item in workflows),
            "unconfigured": sum(item["association_status"] == "未配置" for item in agent_items) + 1,
        },
        "editable": False,
        "note": "本区域仅展示已有配置关联；Agent、Action、阶段引擎不计入业务本体统计。",
    }


_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, field, required=False, max_length=500):
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValueError(f"{field}不能为空")
    if len(value) > max_length:
        raise ValueError(f"{field}长度不能超过{max_length}个字符")
    return value


def _development_status(value, field="开发状态"):
    value = _text(value, field, True, 40)
    if value not in DEVELOPMENT_STATUS_ALLOWED:
        raise ValueError(f"{field}不在支持范围内：{'、'.join(DEVELOPMENT_STATUS_OPTIONS)}")
    return value


def _maturity(value, field="成熟度"):
    value = _text(value, field, True, 40)
    if value not in MATURITY_ALLOWED:
        raise ValueError(f"{field}不在支持范围内：{'、'.join(MATURITY_OPTIONS)}")
    return value


def _code(value, field="编码"):
    value = _text(value, field, True, 64)
    if not _CODE_RE.fullmatch(value):
        raise ValueError(f"{field}只能包含字母、数字和下划线，且必须以字母开头")
    return value


def _bool(value, field):
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1, "0", "1"):
        return int(value)
    raise ValueError(f"{field}必须是布尔值")


def _physical_column_exists(db, table, column):
    table = _text(table, "物理表", True, 128)
    column = _text(column, "物理字段", True, 128)
    if not _TABLE_RE.fullmatch(table) or not _TABLE_RE.fullmatch(column):
        raise ValueError("物理表和物理字段名称格式不正确")
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise ValueError(f"物理表不存在：{table}")
    if column not in {row[1] for row in rows}:
        raise ValueError(f"物理字段不存在：{table}.{column}")
    return table, column


def validate_metadata_source(db, source_type, source_table="", source_column=""):
    source_type = _text(source_type, "数据来源类型", True, 64)
    if source_type in ("physical_column", "business_table"):
        if source_type == "physical_column":
            return _physical_column_exists(db, source_table, source_column)
        source_table = _text(source_table, "物理表", True, 128)
        if not _TABLE_RE.fullmatch(source_table) or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (source_table,)).fetchone():
            raise ValueError(f"物理表不存在：{source_table}")
    return (source_table or "", source_column or "")


def _row(db, table, object_id):
    return db.execute(f"SELECT * FROM {table} WHERE id = ?", (int(object_id),)).fetchone()


def _change(db, object_type, object_code, action, before, after, actor, source="ontology-management"):
    before = dict(before or {})
    after = dict(after or {})
    changed_fields = [
        key for key in sorted(set(before) | set(after))
        if key not in {"updated_at", "created_at"} and before.get(key) != after.get(key)
    ]
    action_labels = {"create": "创建定义", "update": "更新定义", "deactivate": "停用定义", "seed": "初始化定义"}
    summary = action_labels.get(action, action)
    if changed_fields:
        summary += "；变更字段：" + "、".join(changed_fields)
    version = str(after.get("version") or before.get("version") or "")
    db.execute(
        "INSERT INTO ontology_change_logs (object_type, object_code, action, before_json, after_json, actor, source, version, change_summary, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (object_type, object_code, action, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), str(actor or "system"), source, version, summary, _now()),
    )


def _domain_values(data, current=None):
    current = current or {}
    values = {
        "code": _code(data.get("code", current.get("code")), "本体编码"),
        "name_zh": _text(data.get("name_zh", current.get("name_zh")), "中文名称", True, 120),
        "name_en": _text(data.get("name_en", current.get("name_en", "")), "英文名称", False, 120),
        "category": _text(data.get("category", current.get("category", "")), "所属分类", True, 120),
        "description": _text(data.get("description", current.get("description", "")), "描述", False, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
        "data_source": _text(data.get("data_source", current.get("data_source", "")), "数据来源", False, 500),
        "status": _text(data.get("status", current.get("status", "active")), "状态", True, 20),
    }
    if values["status"] not in ("active", "inactive"):
        raise ValueError("状态只能是 active 或 inactive")
    return values


def _entity_values(db, data, current=None):
    current = current or {}
    domain_id = data.get("domain_id", current.get("domain_id"))
    try:
        domain_id = int(domain_id)
    except (TypeError, ValueError):
        raise ValueError("所属本体不能为空")
    if not _row(db, "ontology_domains", domain_id):
        raise ValueError("所属本体不存在")
    source_type = _text(data.get("source_type", current.get("source_type", "business_table")), "数据来源类型", True, 64)
    source_table = _text(data.get("source_table", current.get("source_table", "")), "关联业务表", False, 128)
    source_pk = _text(data.get("source_pk", current.get("source_pk", "id")), "主键字段", False, 128)
    if source_type == "business_table" and source_table:
        validate_metadata_source(db, source_type, source_table, "")
        if source_pk:
            _physical_column_exists(db, source_table, source_pk)
    return {
        "domain_id": domain_id,
        "code": _code(data.get("code", current.get("code")), "实体编码"),
        "name_zh": _text(data.get("name_zh", current.get("name_zh")), "实体中文名称", True, 120),
        "name_en": _text(data.get("name_en", current.get("name_en", "")), "实体英文名称", False, 120),
        "description": _text(data.get("description", current.get("description", "")), "实体描述", False, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "source_type": source_type,
        "source_table": source_table,
        "source_pk": source_pk,
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
        "data_source": _text(data.get("data_source", current.get("data_source", "")), "数据来源", False, 500),
        "status": _text(data.get("status", current.get("status", "active")), "状态", True, 20),
    }


def _attribute_values(db, data, current=None):
    current = current or {}
    entity_id = data.get("entity_id", current.get("entity_id"))
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        raise ValueError("所属实体不能为空")
    if not _row(db, "ontology_entities", entity_id):
        raise ValueError("所属实体不存在")
    source_type = _text(data.get("source_type", current.get("source_type", "physical_column")), "数据来源类型", True, 64)
    source_table = _text(data.get("source_table", current.get("source_table", "")), "来源表", False, 128)
    source_column = _text(data.get("source_column", current.get("source_column", "")), "来源字段", False, 128)
    if source_type == "physical_column":
        validate_metadata_source(db, source_type, source_table, source_column)
    return {
        "entity_id": entity_id,
        "code": _code(data.get("code", current.get("code")), "属性技术编码"),
        "name_zh": _text(data.get("name_zh", current.get("name_zh")), "属性中文名称", True, 120),
        "name_en": _text(data.get("name_en", current.get("name_en", "")), "属性英文名称", False, 120),
        "data_type": _text(data.get("data_type", current.get("data_type", "text")), "数据类型", True, 40),
        "description": _text(data.get("description", current.get("description", "")), "业务含义", True, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "source_type": source_type,
        "source_table": source_table,
        "source_column": source_column,
        "is_required": _bool(data.get("is_required", current.get("is_required", 0)), "是否必填"),
        "is_multiple": _bool(data.get("is_multiple", current.get("is_multiple", 0)), "是否多值"),
        "is_unique": _bool(data.get("is_unique", current.get("is_unique", 0)), "是否唯一"),
        "is_relation_field": _bool(data.get("is_relation_field", current.get("is_relation_field", 0)), "是否为关联字段"),
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
        "data_source": _text(data.get("data_source", current.get("data_source", "")), "数据来源", False, 500),
        "status": _text(data.get("status", current.get("status", "active")), "状态", True, 20),
    }


def _json_text(value, field, required=False):
    if value is None or value == "":
        if required:
            raise ValueError(f"{field}不能为空")
        return "{}"
    if isinstance(value, (dict, list, int, float, bool)):
        return json.dumps(value, ensure_ascii=False)
    text = _text(value, field, required, 10000)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是有效 JSON")
    return json.dumps(parsed, ensure_ascii=False)


def _rule_values(db, data, current=None):
    current = current or {}
    subject_domain_id = data.get("subject_domain_id", current.get("subject_domain_id"))
    if subject_domain_id in (None, ""):
        subject_domain_id = None
    else:
        try:
            subject_domain_id = int(subject_domain_id)
        except (TypeError, ValueError):
            raise ValueError("适用本体不正确")
        if not _row(db, "ontology_domains", subject_domain_id):
            raise ValueError("适用本体不存在")
    subject_entity_id = data.get("subject_entity_id", current.get("subject_entity_id"))
    if subject_entity_id in (None, ""):
        subject_entity_id = None
    else:
        try:
            subject_entity_id = int(subject_entity_id)
        except (TypeError, ValueError):
            raise ValueError("适用实体不正确")
        entity = _row(db, "ontology_entities", subject_entity_id)
        if not entity:
            raise ValueError("适用实体不存在")
        if subject_domain_id is None:
            subject_domain_id = entity["domain_id"]
        elif int(entity["domain_id"]) != subject_domain_id:
            raise ValueError("适用实体不属于所选本体")
    from semantic_management import validate_rule_ast
    expression_json = _json_text(data.get("expression_json", current.get("expression_json", "{}")), "规则内容或表达式", True)
    validate_rule_ast(json.loads(expression_json))
    status = _text(data.get("status", current.get("status", "active")), "生效状态", True, 20)
    if status not in ("active", "inactive"):
        raise ValueError("生效状态只能是 active 或 inactive")
    return {
        "code": _code(data.get("code", current.get("code")), "规则编码"),
        "name_zh": _text(data.get("name_zh", current.get("name_zh")), "规则名称", True, 120),
        "name_en": _text(data.get("name_en", current.get("name_en", "")), "英文名称", False, 120),
        "rule_type": _text(data.get("rule_type", current.get("rule_type", "constraint")), "规则类型", True, 64),
        "layer": _text(data.get("layer", current.get("layer", "business_ontology")), "规则层级", True, 64),
        "subject_domain_id": subject_domain_id,
        "subject_entity_id": subject_entity_id,
        "expression_json": expression_json,
        "action_json": _json_text(data.get("action_json", current.get("action_json", "{}")), "规则动作", False),
        "synonyms_json": json.dumps(data.get("synonyms", current.get("synonyms_json", [])) if isinstance(data.get("synonyms", current.get("synonyms_json", [])), list) else [x.strip() for x in str(data.get("synonyms", current.get("synonyms_json", ""))).split(",") if x.strip()], ensure_ascii=False),
        "business_types_json": json.dumps(data.get("business_types", current.get("business_types_json", [])) if isinstance(data.get("business_types", current.get("business_types_json", [])), list) else [x.strip() for x in str(data.get("business_types", current.get("business_types_json", ""))).split(",") if x.strip()], ensure_ascii=False),
        "scenario": _text(data.get("scenario", current.get("scenario", "")), "适用场景", False, 500),
        "severity": _text(data.get("severity", current.get("severity", "warning")), "严重级别", True, 40),
        "violation_message": _text(data.get("violation_message", current.get("violation_message", "")), "违反提示", False, 1000),
        "semantic_boundary": _text(data.get("semantic_boundary", current.get("semantic_boundary", "")), "语义边界", False, 2000),
        "dependencies_json": json.dumps(data.get("dependencies", current.get("dependencies_json", [])) if isinstance(data.get("dependencies", current.get("dependencies_json", [])), list) else [], ensure_ascii=False),
        "priority": int(data.get("priority", current.get("priority", 50)) or 50),
        "effective_at": data.get("effective_at", current.get("effective_at")),
        "source_table": _text(data.get("source_table", current.get("source_table", "")), "来源表", False, 128),
        "source_ref": _text(data.get("source_ref", current.get("source_ref", "")), "来源引用", False, 500),
        "description": _text(data.get("description", current.get("description", "")), "业务说明", True, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
        "data_source": _text(data.get("data_source", current.get("data_source", "")), "数据来源", False, 500),
        "status": status,
    }


def _mapping_values(db, data, current=None):
    current = current or {}
    target_type = _text(data.get("target_type", current.get("target_type")), "目标类型", True, 40)
    if target_type not in ("domain", "entity", "attribute", "relation", "action", "event", "rule", "metric", "capability"):
        raise ValueError("目标类型不在支持范围内")
    target_code = _text(data.get("target_code", current.get("target_code")), "标准术语编码", True, 120)
    if target_type == "domain" and not db.execute("SELECT 1 FROM ontology_domains WHERE code=?", (target_code,)).fetchone():
        raise ValueError("目标本体不存在")
    if target_type == "entity" and not db.execute("SELECT 1 FROM ontology_entities WHERE code=?", (target_code,)).fetchone():
        raise ValueError("目标实体不存在")
    if target_type == "attribute":
        if "." in target_code:
            entity_code, attribute_code = target_code.split(".", 1)
            valid = db.execute("""SELECT 1 FROM ontology_attributes a JOIN ontology_entities e ON e.id=a.entity_id
                                WHERE e.code=? AND a.code=?""", (entity_code, attribute_code)).fetchone()
        else:
            valid = db.execute("SELECT 1 FROM ontology_attributes WHERE code=?", (target_code,)).fetchone()
        if not valid:
            raise ValueError("目标属性不存在")
    if target_type == "relation" and not db.execute("SELECT 1 FROM ontology_relation_definitions WHERE code=?", (target_code,)).fetchone():
        raise ValueError("目标关系不存在")
    # 运行时语义资源只允许引用 published 版本；ontology mapping 仍保留为兼容来源。
    if target_type in ("action", "event", "rule", "metric") and not db.execute("SELECT 1 FROM semantic_resources WHERE resource_type=? AND code=? AND status='published'", (target_type, target_code)).fetchone():
        raise ValueError("目标语义资源不存在")
    try:
        confidence = int(data.get("confidence", current.get("confidence", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError("置信度必须是 0 到 100 的整数")
    if confidence < 0 or confidence > 100:
        raise ValueError("置信度必须是 0 到 100 的整数")
    def json_list(value, key):
        value = data.get(key, current.get(key + "_json", "[]"))
        if isinstance(value, str):
            try: value = json.loads(value) if value.strip().startswith("[") else [x.strip() for x in value.split(",") if x.strip()]
            except json.JSONDecodeError: raise ValueError(f"{key}必须是有效数组")
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value): raise ValueError(f"{key}必须是字符串数组")
        return json.dumps(value, ensure_ascii=False)
    def json_object(value, key):
        value = data.get(key, current.get(key + "_json", "{}"))
        if isinstance(value, str):
            try: value = json.loads(value or "{}")
            except json.JSONDecodeError: raise ValueError(f"{key}必须是有效 JSON")
        if not isinstance(value, dict): raise ValueError(f"{key}必须是 JSON 对象")
        return json.dumps(value, ensure_ascii=False)
    try: priority = int(data.get("priority", current.get("priority", 50)) or 0)
    except (TypeError, ValueError): raise ValueError("匹配优先级必须是整数")
    if priority < 0 or priority > 100: raise ValueError("匹配优先级必须在 0 到 100 之间")
    domain_id = data.get("domain_id", current.get("domain_id")) or None
    if domain_id is not None:
        try: domain_id = int(domain_id)
        except (TypeError, ValueError): raise ValueError("语义域不正确")
        if not db.execute("SELECT 1 FROM ontology_domains WHERE id=?", (domain_id,)).fetchone(): raise ValueError("语义域不存在")
    return {
        "code": _code(data.get("code", current.get("code")), "映射编码"),
        "source_type": _text(data.get("source_type", current.get("source_type")), "来源类型", True, 64),
        "source_key": _text(data.get("source_key", current.get("source_key")), "原始业务术语或别名", True, 240),
        "target_type": target_type,
        "target_code": target_code,
        "mapping_type": _text(data.get("mapping_type", current.get("mapping_type", "term_to_entity")), "映射类型", True, 64),
        "term_type": _text(data.get("term_type", current.get("term_type", "standard")), "术语类型", True, 64),
        "domain_id": domain_id,
        "business_types_json": json_list(data.get("business_types", data.get("business_types_json")), "business_types"),
        "context_json": json_object(data.get("context", data.get("context_json")), "context"),
        "priority": priority,
        "examples_json": json_list(data.get("examples", data.get("examples_json")), "examples"),
        "owner": _text(data.get("owner", current.get("owner", "")), "责任人", False, 120),
        "confidence": confidence,
        "status": _text(data.get("status", current.get("status", "待核实")), "状态", True, 40),
        "evidence": _text(data.get("evidence", current.get("evidence", "")), "映射说明", True, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
    }


def create_ontology_domain(db, data, actor="system"):
    values = _domain_values(data)
    now = _now()
    try:
        cur = db.execute("INSERT INTO ontology_domains (code,name_zh,name_en,category,description,version,development_status,maturity,data_source,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*values.values(), now, now))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("本体编码已存在")
        raise
    result = dict(_row(db, "ontology_domains", cur.lastrowid)); _change(db, "domain", result["code"], "create", {}, result, actor); return result


def update_ontology_domain(db, object_id, data, actor="system"):
    current = _row(db, "ontology_domains", object_id)
    if not current: raise LookupError("本体不存在")
    before = dict(current); values = _domain_values(data, before); now = _now()
    try:
        db.execute("UPDATE ontology_domains SET code=?,name_zh=?,name_en=?,category=?,description=?,version=?,development_status=?,maturity=?,data_source=?,status=?,updated_at=? WHERE id=?", (*values.values(), now, object_id))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper(): raise ValueError("本体编码已存在")
        raise
    result = dict(_row(db, "ontology_domains", object_id)); _change(db, "domain", result["code"], "update", before, result, actor); return result


def create_ontology_entity(db, data, actor="system"):
    values = _entity_values(db, data); now = _now()
    try:
        cur = db.execute("INSERT INTO ontology_entities (domain_id,code,name_zh,name_en,description,version,source_type,source_table,source_pk,development_status,maturity,data_source,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*values.values(), now, now))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper(): raise ValueError("实体编码已存在")
        raise
    result = dict(_row(db, "ontology_entities", cur.lastrowid)); _change(db, "entity", result["code"], "create", {}, result, actor); return result


def update_ontology_entity(db, object_id, data, actor="system"):
    current = _row(db, "ontology_entities", object_id)
    if not current: raise LookupError("实体不存在")
    before = dict(current); values = _entity_values(db, data, before); now = _now()
    try:
        db.execute("UPDATE ontology_entities SET domain_id=?,code=?,name_zh=?,name_en=?,description=?,version=?,source_type=?,source_table=?,source_pk=?,development_status=?,maturity=?,data_source=?,status=?,updated_at=? WHERE id=?", (*values.values(), now, object_id))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper(): raise ValueError("实体编码已存在")
        raise
    result = dict(_row(db, "ontology_entities", object_id)); _change(db, "entity", result["code"], "update", before, result, actor); return result


def create_ontology_attribute(db, data, actor="system"):
    values = _attribute_values(db, data); now = _now()
    try:
        cur = db.execute("INSERT INTO ontology_attributes (entity_id,code,name_zh,name_en,data_type,description,version,source_type,source_table,source_column,is_required,is_multiple,is_unique,is_relation_field,development_status,maturity,data_source,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*values.values(), now, now))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper(): raise ValueError("同一实体下的属性编码已存在")
        raise
    result = dict(_row(db, "ontology_attributes", cur.lastrowid)); _change(db, "attribute", result["code"], "create", {}, result, actor); return result


def update_ontology_attribute(db, object_id, data, actor="system"):
    current = _row(db, "ontology_attributes", object_id)
    if not current: raise LookupError("属性不存在")
    before = dict(current); values = _attribute_values(db, data, before); now = _now()
    try:
        db.execute("UPDATE ontology_attributes SET entity_id=?,code=?,name_zh=?,name_en=?,data_type=?,description=?,version=?,source_type=?,source_table=?,source_column=?,is_required=?,is_multiple=?,is_unique=?,is_relation_field=?,development_status=?,maturity=?,data_source=?,status=?,updated_at=? WHERE id=?", (*values.values(), now, object_id))
    except Exception as exc:
        if "UNIQUE" in str(exc).upper(): raise ValueError("同一实体下的属性编码已存在")
        raise
    result = dict(_row(db, "ontology_attributes", object_id)); _change(db, "attribute", result["code"], "update", before, result, actor); return result


def _relation_values(db, data, current=None):
    current = current or {}
    try:
        source_entity_id = int(data.get("source_entity_id", current.get("source_entity_id")))
        target_entity_id = int(data.get("target_entity_id", current.get("target_entity_id")))
    except (TypeError, ValueError):
        raise ValueError("起始实体和目标实体不能为空")
    if not _row(db, "ontology_entities", source_entity_id) or not _row(db, "ontology_entities", target_entity_id):
        raise ValueError("起始实体或目标实体不存在")
    relation_kind = _text(data.get("relation_kind", current.get("relation_kind", "semantic")), "关系类型", True, 64)
    cardinality = _text(data.get("cardinality", current.get("cardinality", "待核实")), "基数", True, 40)
    cardinality = {"1:1": "一对一", "1:N": "一对多", "N:1": "多对一", "N:M": "多对多"}.get(cardinality, cardinality)
    direction = _text(data.get("direction", current.get("direction", "待核实")), "关系方向", True, 160)
    if cardinality not in ("一对一", "一对多", "多对一", "多对多", "待核实"):
        raise ValueError("基数不在支持范围内")
    physical_table = _text(data.get("physical_table", current.get("physical_table", "")), "关联表", False, 240)
    source_column = _text(data.get("source_column", current.get("source_column", "")), "起始字段", False, 240)
    target_column = _text(data.get("target_column", current.get("target_column", "")), "目标字段", False, 240)
    def _json_list(value, label):
        if value is None: value = current.get(label, "[]")
        if isinstance(value, str):
            try: value = json.loads(value) if value.strip().startswith("[") else [x.strip() for x in value.split(",") if x.strip()]
            except json.JSONDecodeError: raise ValueError(f"{label}必须是逗号分隔文本或 JSON 数组")
        if not isinstance(value, list) or any(not isinstance(x, str) or len(x) > 120 for x in value): raise ValueError(f"{label}格式不正确")
        return json.dumps(value, ensure_ascii=False)
    synonyms_json = _json_list(data.get("synonyms", data.get("synonyms_json")), "同义词/触发词")
    business_types_json = _json_list(data.get("business_types", data.get("business_types_json")), "适用业务类型")
    master_slave_type = _text(data.get("master_slave_type", current.get("master_slave_type", "peer")), "主从类型", True, 40)
    query_path = _text(data.get("query_path", current.get("query_path", "")), "查询路径", False, 500)
    try: traversal_depth = int(data.get("traversal_depth", current.get("traversal_depth", 1)))
    except (TypeError, ValueError): raise ValueError("可遍历深度必须是整数")
    if traversal_depth < 1 or traversal_depth > 5: raise ValueError("可遍历深度必须在 1 到 5 之间")
    execution_mode = _text(data.get("execution_mode", current.get("execution_mode", "conceptual")), "关系执行模式", True, 20)
    if execution_mode not in ("conceptual", "executable"): raise ValueError("关系执行模式不正确")
    if relation_kind == "foreign_key" and physical_table and ";" not in physical_table:
        if source_column and target_column:
            _physical_column_exists(db, physical_table, source_column)
            _physical_column_exists(db, physical_table, target_column)
        else:
            raise ValueError("外键关系需要填写起始字段和目标字段")
    if execution_mode == "executable" and not (query_path or (physical_table and source_column and target_column)):
        raise ValueError("可执行关系需要查询路径或关联表及字段")
    relationship_type_id = data.get("relationship_type_id", current.get("relationship_type_id"))
    if relationship_type_id in ("", None):
        relationship_type_id = None
    else:
        try:
            relationship_type_id = int(relationship_type_id)
        except (TypeError, ValueError):
            raise ValueError("关系类型 ID 不正确")
        if not db.execute("SELECT 1 FROM relationship_types WHERE id=?", (relationship_type_id,)).fetchone():
            raise ValueError("关系类型不存在")
    return {
        "code": _code(data.get("code", current.get("code")), "关系编码"),
        "name_zh": _text(data.get("name_zh", current.get("name_zh")), "关系名称", True, 120),
        "name_en": _text(data.get("name_en", current.get("name_en", "")), "英文名称", False, 120),
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "relationship_type_id": relationship_type_id,
        "relation_kind": relation_kind,
        "synonyms_json": synonyms_json,
        "business_types_json": business_types_json,
        "master_slave_type": master_slave_type,
        "query_path": query_path,
        "traversal_depth": traversal_depth,
        "execution_mode": execution_mode,
        "cardinality": cardinality,
        "direction": direction,
        "physical_table": physical_table,
        "source_column": source_column,
        "target_column": target_column,
        "constraint_description": _text(data.get("constraint_description", current.get("constraint_description", "")), "关联约束", False, 2000),
        "description": _text(data.get("description", current.get("description", "")), "业务含义", True, 2000),
        "version": _text(data.get("version", current.get("version", "0.1")), "版本", True, 40),
        "development_status": _development_status(data.get("development_status", current.get("development_status", "待核实"))),
        "maturity": _maturity(data.get("maturity", current.get("maturity", "待核实"))),
        "data_source": _text(data.get("data_source", current.get("data_source", "")), "数据来源", False, 500),
        "status": _text(data.get("status", current.get("status", "active")), "状态", True, 20),
    }


def create_ontology_relation(db, data, actor="system"):
    values = _relation_values(db, data); now = _now()
    try:
        cur = db.execute(
            """INSERT INTO ontology_relation_definitions
               (code,name_zh,name_en,source_entity_id,target_entity_id,relationship_type_id,
                relation_kind,synonyms_json,business_types_json,master_slave_type,query_path,traversal_depth,execution_mode,cardinality,direction,physical_table,source_column,target_column,
                constraint_description,description,version,development_status,maturity,data_source,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*values.values(), now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("关系编码已存在")
        raise
    result = dict(_row(db, "ontology_relation_definitions", cur.lastrowid)); _change(db, "relation", result["code"], "create", {}, result, actor); return result


def update_ontology_relation(db, object_id, data, actor="system"):
    current = _row(db, "ontology_relation_definitions", object_id)
    if not current:
        raise LookupError("关系不存在")
    before = dict(current); values = _relation_values(db, data, before); now = _now()
    try:
        db.execute(
            """UPDATE ontology_relation_definitions SET code=?,name_zh=?,name_en=?,source_entity_id=?,target_entity_id=?,relationship_type_id=?,relation_kind=?,synonyms_json=?,business_types_json=?,master_slave_type=?,query_path=?,traversal_depth=?,execution_mode=?,cardinality=?,direction=?,physical_table=?,source_column=?,target_column=?,constraint_description=?,description=?,version=?,development_status=?,maturity=?,data_source=?,status=?,updated_at=? WHERE id=?""",
            (*values.values(), now, object_id),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("关系编码已存在")
        raise
    result = dict(_row(db, "ontology_relation_definitions", object_id)); _change(db, "relation", result["code"], "update", before, result, actor); return result


def validate_ontology_relation(db, object_id):
    """发布前的只读校验；只验证已登记的实体、字段和白名单 API 路径。"""
    row = db.execute("SELECT r.*, se.code AS source_code, te.code AS target_code FROM ontology_relation_definitions r JOIN ontology_entities se ON se.id=r.source_entity_id JOIN ontology_entities te ON te.id=r.target_entity_id WHERE r.id=?", (object_id,)).fetchone()
    if not row: raise LookupError("关系不存在")
    item = dict(row); errors = []; warnings = []
    if int(item.get("traversal_depth") or 0) < 1: errors.append("可遍历深度必须大于 0")
    if item.get("execution_mode") == "executable":
        path = (item.get("query_path") or "").strip()
        allowed = ("/api/customers", "/api/projects", "/api/opportunities", "/api/people", "/api/actions", "/api/organizations", "/api/ontology/")
        if path and not path.startswith(allowed): errors.append("查询路径不在受控业务 API 白名单内")
        if not path and not (item.get("physical_table") and item.get("source_column") and item.get("target_column")): errors.append("可执行关系缺少查询路径或关联字段")
    # 对当前有向图做环检测；环不会篡改数据，但发布时必须有深度上限。
    edges = db.execute("SELECT source_entity_id,target_entity_id,traversal_depth FROM ontology_relation_definitions WHERE status='active'").fetchall()
    graph = {}
    for edge in edges: graph.setdefault(edge[0], []).append(edge[1])
    visiting, visited = set(), set()
    def dfs(node):
        if node in visiting: return True
        if node in visited: return False
        visiting.add(node)
        if any(dfs(child) for child in graph.get(node, [])): return True
        visiting.remove(node); visited.add(node); return False
    if any(dfs(node) for node in list(graph)):
        warnings.append("关系图存在循环，运行时必须遵守可遍历深度限制")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "relation": item}


def create_ontology_rule(db, data, actor="system"):
    values = _rule_values(db, data); now = _now()
    try:
        cur = db.execute(
            """INSERT INTO ontology_business_rules
               (code,name_zh,name_en,rule_type,layer,subject_domain_id,subject_entity_id,
                expression_json,action_json,synonyms_json,business_types_json,scenario,severity,violation_message,semantic_boundary,dependencies_json,priority,effective_at,source_table,source_ref,description,version,
                development_status,maturity,data_source,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*values.values(), now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("规则编码已存在")
        raise
    result = dict(_row(db, "ontology_business_rules", cur.lastrowid)); _change(db, "rule", result["code"], "create", {}, result, actor); return result


def update_ontology_rule(db, object_id, data, actor="system"):
    current = _row(db, "ontology_business_rules", object_id)
    if not current:
        raise LookupError("业务规则不存在")
    before = dict(current); values = _rule_values(db, data, before); now = _now()
    try:
        db.execute(
            """UPDATE ontology_business_rules SET
               code=?,name_zh=?,name_en=?,rule_type=?,layer=?,subject_domain_id=?,subject_entity_id=?,
               expression_json=?,action_json=?,synonyms_json=?,business_types_json=?,scenario=?,severity=?,violation_message=?,semantic_boundary=?,dependencies_json=?,priority=?,effective_at=?,source_table=?,source_ref=?,description=?,version=?,
               development_status=?,maturity=?,data_source=?,status=?,updated_at=? WHERE id=?""",
            (*values.values(), now, object_id),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("规则编码已存在")
        raise
    result = dict(_row(db, "ontology_business_rules", object_id)); _change(db, "rule", result["code"], "update", before, result, actor); return result


def create_ontology_mapping(db, data, actor="system"):
    values = _mapping_values(db, data); now = _now()
    try:
        cur = db.execute(
            """INSERT INTO ontology_semantic_mappings
               (code,source_type,source_key,target_type,target_code,mapping_type,term_type,domain_id,
                business_types_json,context_json,priority,examples_json,owner,confidence,status,evidence,
                version,development_status,maturity,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*values.values(), now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("映射编码已存在")
        raise
    result = dict(_row(db, "ontology_semantic_mappings", cur.lastrowid)); _change(db, "mapping", result["code"], "create", {}, result, actor); return result


def update_ontology_mapping(db, object_id, data, actor="system"):
    current = _row(db, "ontology_semantic_mappings", object_id)
    if not current:
        raise LookupError("语义映射不存在")
    before = dict(current); values = _mapping_values(db, data, before); now = _now()
    try:
        db.execute(
            """UPDATE ontology_semantic_mappings SET
               code=?,source_type=?,source_key=?,target_type=?,target_code=?,mapping_type=?,term_type=?,domain_id=?,
               business_types_json=?,context_json=?,priority=?,examples_json=?,owner=?,confidence=?,status=?,evidence=?,
               version=?,development_status=?,maturity=?,updated_at=? WHERE id=?""",
            (*values.values(), now, object_id),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("映射编码已存在")
        raise
    result = dict(_row(db, "ontology_semantic_mappings", object_id)); _change(db, "mapping", result["code"], "update", before, result, actor); return result


def parse_semantic_terms(db, text, context=None):
    """只做语义理解：按词面、优先级和上下文条件返回候选概念，不执行任何动作。"""
    text = str(text or "").strip()
    if not text: return {"text": text, "candidates": [], "ambiguous": False}
    context = context or {}
    rows = db.execute("SELECT m.*, d.code AS domain_code, d.name_zh AS domain_name_zh FROM ontology_semantic_mappings m LEFT JOIN ontology_domains d ON d.id=m.domain_id WHERE m.status NOT IN ('inactive','停用') ORDER BY m.priority DESC, m.confidence DESC, m.id").fetchall()
    candidates = []
    for row in rows:
        item = dict(row); term = item.get("source_key", "")
        if term and term not in text: continue
        try: business = json.loads(item.get("business_types_json") or "[]"); conditions = json.loads(item.get("context_json") or "{}"); examples = json.loads(item.get("examples_json") or "[]")
        except json.JSONDecodeError: business, conditions, examples = [], {}, []
        score = int(item.get("priority") or 0) + int(item.get("confidence") or 0)
        if item.get("domain_code") and context.get("domain") == item["domain_code"]: score += 60
        if context.get("business_type") in business: score += 40
        required = conditions.get("contains_any", []) if isinstance(conditions, dict) else []
        excluded = conditions.get("excludes_any", []) if isinstance(conditions, dict) else []
        if required and not any(str(x) in text for x in required): continue
        if excluded and any(str(x) in text for x in excluded): continue
        if examples and any(str(x) in text for x in examples): score += 20
        item.update({"business_types": business, "context": conditions, "examples": examples, "score": score, "standard_concept": {"type": item.get("target_type"), "code": item.get("target_code")}})
        candidates.append(item)
    candidates.sort(key=lambda x: (-x["score"], x["id"]))
    return {"text": text, "candidates": candidates, "ambiguous": len(candidates) > 1 and (candidates[0]["score"] - candidates[1]["score"] < 25), "safe_to_execute": False}


def validate_semantic_term(db, object_id):
    row = db.execute("SELECT * FROM ontology_semantic_mappings WHERE id=?", (object_id,)).fetchone()
    if not row: raise LookupError("术语不存在")
    item = dict(row); errors = []; warnings = []
    peers = db.execute("SELECT * FROM ontology_semantic_mappings WHERE source_key=? AND id<>? AND status!='inactive'", (item["source_key"], object_id)).fetchall()
    try: ctx = json.loads(item.get("context_json") or "{}")
    except json.JSONDecodeError: ctx = {}
    if peers and not ctx and any(not json.loads(p["context_json"] or "{}") for p in peers): errors.append("同一词语存在多个无上下文条件的标准概念")
    if peers: warnings.append(f"发现 {len(peers)} 个同词候选，解析时将根据语义域、业务类型和上下文消歧")
    if item.get("priority") is None or not 0 <= int(item.get("priority") or 0) <= 100: errors.append("匹配优先级必须在 0 到 100 之间")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "term": item}


def deactivate_ontology_object(db, object_type, object_id, actor="system"):
    table = {"domain": "ontology_domains", "entity": "ontology_entities", "attribute": "ontology_attributes", "relation": "ontology_relation_definitions", "rule": "ontology_business_rules", "mapping": "ontology_semantic_mappings"}.get(object_type)
    if not table: raise ValueError("不支持停用该本体对象")
    current = _row(db, table, object_id)
    if not current: raise LookupError("本体对象不存在")
    before = dict(current); dependencies = []
    if object_type == "domain":
        dependencies.append({"type": "entities", "count": db.execute("SELECT COUNT(*) FROM ontology_entities WHERE domain_id=? AND status='active'", (object_id,)).fetchone()[0]})
        dependencies.append({"type": "rules", "count": db.execute("SELECT COUNT(*) FROM ontology_business_rules WHERE subject_domain_id=? AND status='active'", (object_id,)).fetchone()[0]})
        domain_code = current["code"]
        dependencies.append({"type": "mappings", "count": db.execute("SELECT COUNT(*) FROM ontology_semantic_mappings WHERE target_type='domain' AND target_code=? AND status != 'inactive'", (domain_code,)).fetchone()[0]})
    elif object_type == "entity":
        for label, sql in (("attributes", "SELECT COUNT(*) FROM ontology_attributes WHERE entity_id=? AND status='active'"), ("relations", "SELECT COUNT(*) FROM ontology_relation_definitions WHERE (source_entity_id=? OR target_entity_id=?) AND status='active'"), ("rules", "SELECT COUNT(*) FROM ontology_business_rules WHERE subject_entity_id=? AND status='active'")):
            count = db.execute(sql, (object_id, object_id) if label == "relations" else (object_id,)).fetchone()[0]
            dependencies.append({"type": label, "count": count})
        dependencies.append({"type": "mappings", "count": db.execute(
            "SELECT COUNT(*) FROM ontology_semantic_mappings WHERE target_type='entity' AND target_code=? AND status != 'inactive'",
            (current["code"],),
        ).fetchone()[0]})
    elif object_type == "attribute":
        entity = _row(db, "ontology_entities", current["entity_id"])
        target_codes = (current["code"], f"{entity['code']}.{current['code']}" if entity else current["code"])
        dependencies.append({"type": "mappings", "count": db.execute(
            "SELECT COUNT(*) FROM ontology_semantic_mappings WHERE target_type='attribute' AND target_code IN (?,?) AND status != 'inactive'",
            target_codes,
        ).fetchone()[0]})
    now = _now(); db.execute(f"UPDATE {table} SET status='inactive', development_status='已停用', updated_at=? WHERE id=?", (now, object_id))
    result = dict(_row(db, table, object_id)); _change(db, object_type, result.get("code", str(object_id)), "deactivate", before, result, actor)
    result["dependencies"] = dependencies
    active_dependencies = [item for item in dependencies if item["count"]]
    result["dependency_check"] = {
        "has_active_dependencies": bool(active_dependencies),
        "message": "；".join(f"{item['type']} {item['count']} 条" for item in active_dependencies) if active_dependencies else "未发现活动依赖",
    }
    return result
