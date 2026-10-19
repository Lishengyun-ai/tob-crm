import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "outputs";
const outputPath = `${outputDir}/AI商机CRM_V2.1本体数据库对齐补充清单.xlsx`;
const previewDir = "outputs/alignment_preview";
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const workbook = Workbook.create();
const overview = workbook.worksheets.add("总览");
const objects = workbook.worksheets.add("对象映射");
const fields = workbook.worksheets.add("字段补充");
const relations = workbook.worksheets.add("关系补充");
const lifecycle = workbook.worksheets.add("状态生命周期");
const backlog = workbook.worksheets.add("开发清单");

const font = "Aptos";
const navy = "#17365D";
const blue = "#D9EAF7";
const lightBlue = "#EEF5FB";
const amber = "#FFF2CC";
const green = "#E2F0D9";
const red = "#FCE4D6";
const gray = "#F3F6F9";
const border = "#D9E2F3";

function setupSheet(sheet, widths) {
  sheet.showGridLines = false;
  sheet.getRange("A1:Z200").format.font = { name: font, size: 10, color: "#1F2937" };
  Object.entries(widths).forEach(([col, width]) => {
    sheet.getRange(`${col}:${col}`).format.columnWidth = width;
  });
}

function title(sheet, text, subtitle, endCol) {
  sheet.getRange(`A1:${endCol}1`).merge();
  sheet.getRange("A1").values = [[text]];
  sheet.getRange(`A1:${endCol}1`).format = {
    font: { name: font, size: 16, bold: true, color: "#000000" },
    verticalAlignment: "center",
  };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endCol}2`).merge();
  sheet.getRange(`A2:${endCol}2`).format = {
    font: { name: font, size: 10, italic: true, color: "#667085" },
    wrapText: true,
  };
  sheet.getRange(`A3:${endCol}3`).format.borders = {
    bottom: { style: "thin", color: navy },
  };
}

function header(sheet, range) {
  sheet.getRange(range).format = {
    fill: navy,
    font: { name: font, size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "all", style: "thin", color: border },
  };
}

function body(sheet, range) {
  sheet.getRange(range).format = {
    verticalAlignment: "center",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: border },
      bottom: { style: "thin", color: border },
    },
  };
}

function statusFormat(sheet, range) {
  sheet.getRange(range).conditionalFormats.add("containsText", {
    text: "已实现",
    format: { fill: green, font: { color: "#26733A", bold: true } },
  });
  sheet.getRange(range).conditionalFormats.add("containsText", {
    text: "需新增",
    format: { fill: red, font: { color: "#9C0006", bold: true } },
  });
  sheet.getRange(range).conditionalFormats.add("containsText", {
    text: "需拆分",
    format: { fill: amber, font: { color: "#7F6000", bold: true } },
  });
}

setupSheet(overview, { A: 20, B: 18, C: 18, D: 18, E: 58 });
title(overview, "AI商机CRM V2.1 本体数据库对齐补充清单", "基于三份 V1 / V2.1 文档和当前代码状态整理。标记为“需补充”的内容，是下一轮本体开发前建议冻结的对象、字段、关系或生命周期。", "E");
overview.getRange("A5:E5").values = [["判断", "对象概念层", "数据库层", "当前代码层", "直接建议"]];
header(overview, "A5:E5");
overview.getRange("A6:E11").values = [
  ["总体结论", "可以开始本体开发", "不能直接按文档原样建表", "已有 MVP 骨架", "先完成对象、关系、字段和状态四张对齐清单，再进入本体管理页面"],
  ["已具备", "Account / Project / Opportunity / Person / Event", "customers / projects / opportunities / persons / business_events", "已落地并有接口", "继续复用，补充语义和外键"],
  ["已实现兼容层", "Project → Phase → Lot", "project_phases / project_lots + project_sections", "已落地并有迁移映射", "继续保留 project_sections，逐步让新 API 使用 phase / lot"],
  ["部分实现", "CustomerProfile / CustomerDevelopmentOpportunity", "customer_profiles / customer_development_opportunities", "客户画像已存在；客户开发机会已补客户级字段", "继续补字段字典、状态和 Agent 读写"],
  ["需要升级", "Role / Relationship / Insight / Action", "当前只有局部字段或事件记录", "未形成独立对象", "建立独立表和关联关系，保留事实与 AI 推理分离"],
  ["暂不开发", "合同 / 订单 / 回款 / 交付", "文档明确属于 V2/V3", "暂无", "不纳入本轮本体 MVP，避免范围扩张"],
];
body(overview, "A6:E11");
overview.getRange("A13:E13").values = [["本轮优先级", "P0", "P1", "P2", "说明"]];
header(overview, "A13:E13");
overview.getRange("A14:E16").values = [
  ["P0", "对象映射", "关系定义", "生命周期", "不完成这三项，不建议继续扩展本体页面"],
  ["P1", "字段补充", "Event / Insight / Action", "Role / Relationship", "完成后可支撑 Agent 读写本体"],
  ["P2", "页面管理", "本体检索", "治理审计", "建立在 P0/P1 冻结之后"],
];
body(overview, "A14:E16");
overview.getRange("A18:E18").values = [["来源文档", "AI商机CRM V1开发需求说明书_基于V2.1本体.docx", "AI商机领域模型_V2.1_ER关系图说明.docx", "AI商机领域模型_V2.1_数据库表结构设计.docx", "当前代码：server.py / data/crm.sqlite3"]];
overview.getRange("A18:E18").format = { fill: gray, font: { size: 9, italic: true, color: "#667085" }, wrapText: true };

setupSheet(objects, { A: 25, B: 28, C: 28, D: 22, E: 32, F: 34, G: 20, H: 48 });
title(objects, "本体对象与数据库表映射", "直接告诉开发：哪些对象可以复用现有表，哪些需要新增，哪些现有表需要拆分或改名。", "H");
objects.getRange("A5:H5").values = [["本体对象", "中文定义", "建议数据库表", "当前代码表", "状态", "当前问题", "建议动作", "补充说明"]];
header(objects, "A5:H5");
objects.getRange("A6:H20").values = [
  ["Organization", "组织 / 集团 / 区域公司 / 项目公司", "organizations", "organizations + customer_organizations", "已实现", "通用组织与客户内部组织并存", "保留并统一语义", "parent_id、组织类型、行业、区域"],
  ["Account", "客户主体", "customers（语义映射为 Account）", "customers", "已实现", "表名与文档不同，但核心对象可复用", "保留并统一语义", "后续 API 可逐步使用 account 术语"],
  ["CustomerProfile", "客户画像", "customer_profiles", "无", "需新增", "客户事实和 AI 画像尚未分离", "P1 新增", "价值评分、经营面积、客户分层等"],
  ["AccountAssignment", "客户归属", "account_assignments", "无", "需新增", "客户负责人和组织归属未结构化", "P1 新增", "员工、区域、事业部、部门"],
  ["CustomerDevelopmentOpportunity", "客户开发机会", "customer_development_opportunities", "customer_development_opportunities", "已实现兼容层", "保留旧关联字段，同时支持客户级机会", "继续补状态与校验", "集采突破、战略客户开发、增购机会"],
  ["Project", "工程项目", "projects", "projects", "已实现", "字段仍较少", "补充字段", "开发商、设计单位、总包可通过关系对象表达"],
  ["ProjectPhase", "项目期", "project_phases", "project_phases", "已实现", "由旧 project_sections 映射生成", "继续补状态和日期字段", "一期、二期、三期"],
  ["ProjectLot", "项目标段", "project_lots", "project_lots + project_sections", "已实现兼容层", "通过 legacy_section_id 兼容旧标段", "逐步迁移商机外键", "保留 project_sections 做迁移兼容"],
  ["Opportunity", "项目商机", "opportunities", "opportunities", "已实现", "AI字段和事实字段混在表内", "补充外键和拆分 AI 字段", "关联 account、project_lot、person"],
  ["Person", "人员 / 联系人", "persons", "persons", "已实现", "缺少统一组织归属和去重策略", "补充唯一识别", "手机号、邮箱、组织、来源"],
  ["Role", "业务角色", "roles", "无", "需新增", "当前 role 只是关系表文本", "P1 新增", "决策人、采购、设计院、总包等"],
  ["Relationship", "人员与对象关系", "relationships", "customer_persons / project_persons / opportunity_persons", "需升级", "关系按对象拆散，无法统一表达", "P1 统一关系模型", "保留兼容视图或关联表"],
  ["Event", "业务事件", "events", "business_events", "需升级", "只挂 opportunity，related_object 不通用", "P1 扩展", "支持文本、语音、图片、拜访记录"],
  ["Insight", "AI洞察", "insights", "agent_runs 部分承载", "需新增", "AI输出没有独立生命周期", "P1 新增", "风险、评分、建议、依据、有效期"],
  ["Action", "行动任务", "actions", "无", "需新增", "下一步行动只是文本", "P1 新增", "负责人、截止时间、状态、来源洞察"],
];
body(objects, "A6:H20");
statusFormat(objects, "E6:E20");
objects.freezePanes.freezeRows(5);

setupSheet(fields, { A: 25, B: 25, C: 24, D: 25, E: 28, F: 34, G: 42, H: 18 });
title(fields, "字段补充清单", "只列出需要补充或重新归类的关键字段。现有字段不代表已经满足本体要求。", "H");
fields.getRange("A5:H5").values = [["对象", "数据库表", "字段", "字段类型", "来源性质", "当前状态", "为什么要补充", "优先级"]];
header(fields, "A5:H5");
fields.getRange("A6:H28").values = [
  ["Organization", "organizations", "parent_id", "外键", "业务事实", "需新增", "支持集团、区域公司、项目公司的组织层级", "P0"],
  ["Organization", "organizations", "type / industry / region", "枚举 / 文本", "业务事实", "需新增", "支持客户组织分类和区域管理", "P0"],
  ["Account", "customers", "organization_id", "外键", "业务事实", "需新增", "客户需要归属到组织体系", "P0"],
  ["Account", "customers", "market_segment / category / level / source", "枚举 / 文本", "业务事实", "需新增", "补齐客户分类和客户分层", "P1"],
  ["CustomerProfile", "customer_profiles", "construction_area / land_reserve_area", "数值", "业务事实", "需新增", "支撑涂料行业客户画像", "P1"],
  ["CustomerProfile", "customer_profiles", "value_score / growth_potential", "数值", "AI洞察", "需新增", "客户评分不能和客户主数据混存", "P1"],
  ["CustomerDevelopmentOpportunity", "customer_development_opportunities", "account_id / target / type", "外键 / 文本", "业务事实", "需新增", "表达客户级长期开发目标", "P0"],
  ["CustomerDevelopmentOpportunity", "customer_development_opportunities", "stage / owner / probability", "枚举 / 外键 / 数值", "业务事实", "需新增", "支持客户开发阶段和预测", "P0"],
  ["Project", "projects", "developer / design_company / contractor", "文本或外键", "业务事实", "部分已有", "文档明确项目参与方", "P1"],
  ["ProjectPhase", "project_phases", "project_id / phase_name / status", "外键 / 文本 / 枚举", "业务事实", "需新增", "项目期需要独立生命周期", "P0"],
  ["ProjectLot", "project_lots", "phase_id / lot_name / scope / amount", "外键 / 文本 / 数值", "业务事实", "需新增", "标段是商机归属的直接载体", "P0"],
  ["Opportunity", "opportunities", "account_id / project_lot_id", "外键", "业务事实", "部分已有", "当前 project_id 不能表达期和标段", "P0"],
  ["Opportunity", "opportunities", "probability / competitor", "数值 / 文本", "业务事实", "需新增", "文档要求赢率和竞争信息", "P1"],
  ["Opportunity", "opportunities", "risk / next_action", "文本", "AI洞察", "需迁移", "不应和商机事实混存", "P1"],
  ["Person", "persons", "organization_id / source", "外键 / 文本", "业务事实", "需新增", "关键人需要组织归属和来源追踪", "P1"],
  ["Role", "roles", "role_name / decision_power / influence_level", "文本 / 数值", "业务事实", "需新增", "角色定义需要独立维护", "P1"],
  ["Relationship", "relationships", "from_entity / to_entity / type", "多态关系", "业务事实", "需新增", "统一表达人与客户、项目、商机的关系", "P1"],
  ["Relationship", "relationships", "strength_score / relationship_status / last_interaction_at", "数值 / 枚举 / 日期", "业务事实", "需新增", "支持关系强度和关系新鲜度分析", "P1"],
  ["Event", "events", "type / source / content / related_object", "文本 / 多态关系", "业务事实", "需升级", "Event 必须成为 AI 统一输入入口", "P0"],
  ["Event", "events", "extracted_json / extraction_confidence", "JSON / 数值", "AI生成", "需新增", "保存 AI 抽取结果及置信度", "P1"],
  ["Insight", "insights", "object_type / object_id / score / risk", "多态关系 / 数值 / 文本", "AI生成", "需新增", "独立保存 AI 推理结果", "P1"],
  ["Insight", "insights", "recommendation / evidence_json / expires_at", "文本 / JSON / 日期", "AI生成", "需新增", "支持解释、证据和有效期", "P1"],
  ["Action", "actions", "task / owner / deadline / status", "文本 / 外键 / 日期 / 枚举", "业务事实", "需新增", "把建议变成可执行任务", "P1"],
];
body(fields, "A6:H28");
statusFormat(fields, "F6:F28");
fields.freezePanes.freezeRows(5);

setupSheet(relations, { A: 28, B: 28, C: 24, D: 18, E: 18, F: 45, G: 18 });
title(relations, "关系补充清单", "本表用于冻结 ER 关系。关系没有明确前，不建议继续扩展页面和 Agent。", "G");
relations.getRange("A5:G5").values = [["起点对象", "关系", "终点对象", "基数", "当前代码", "需要补充的约束", "优先级"]];
header(relations, "A5:G5");
relations.getRange("A6:G20").values = [
  ["Organization", "拥有 / 管理", "Account", "1:N", "无", "Account.organization_id；支持集团和区域公司", "P0"],
  ["Account", "拥有画像", "CustomerProfile", "1:1", "无", "customer_profiles.account_id 唯一", "P1"],
  ["Account", "发起", "CustomerDevelopmentOpportunity", "1:N", "无", "客户级开发机会与项目商机分离", "P0"],
  ["Account", "拥有", "Project", "1:N", "已实现", "projects.customer_id 改名或语义映射为 account_id", "P0"],
  ["Project", "包含", "ProjectPhase", "1:N", "无", "project_phases.project_id", "P0"],
  ["ProjectPhase", "包含", "ProjectLot", "1:N", "需拆分", "project_lots.phase_id", "P0"],
  ["ProjectLot", "承载", "Opportunity", "1:1", "部分实现", "opportunities.project_lot_id 唯一", "P0"],
  ["Account", "关联", "Person", "N:N", "已实现", "统一 customer_persons 和 relationships 语义", "P1"],
  ["Project", "关联", "Person", "N:N", "已实现", "关系角色和来源统一", "P1"],
  ["Opportunity", "关联", "Person", "N:N", "已实现", "角色改为 role_id，补充影响力和关系状态", "P1"],
  ["Person", "承担", "Role", "N:N", "文本字段", "新增 person_roles 或统一 relationships", "P1"],
  ["Person", "影响 / 支持", "Person", "N:N", "无", "需要表达人员之间的影响关系", "P2"],
  ["Event", "产生", "Insight", "1:N", "部分实现", "insights.event_id，保留来源 Agent", "P1"],
  ["Insight", "生成", "Action", "1:N", "无", "actions.insight_id，支持采纳和完成状态", "P1"],
  ["Event", "关联", "业务对象", "N:1", "仅 opportunity", "related_object_type + related_object_id 或拆分关联表", "P0"],
];
body(relations, "A6:G20");
relations.freezePanes.freezeRows(5);

setupSheet(lifecycle, { A: 25, B: 26, C: 24, D: 25, E: 34, F: 42, G: 18 });
title(lifecycle, "状态与生命周期对齐", "状态必须属于对象本身，不能把客户开发阶段、销售机会阶段、项目状态混在一个字段里。", "G");
lifecycle.getRange("A5:G5").values = [["对象", "状态字段", "建议状态值", "当前实现", "是否需要拆分", "补充要求", "优先级"]];
header(lifecycle, "A5:G5");
lifecycle.getRange("A6:G16").values = [
  ["Account", "status", "active / inactive / archived", "customers.status", "否", "保留客户主体生命周期", "P1"],
  ["CustomerDevelopmentOpportunity", "stage", "目标定义 / 关系建立 / 方案植入 / 集采推进 / 复盘", "无", "是", "不能复用 opportunities.stage", "P0"],
  ["Project", "status", "discovered / planned / under_construction / completed / archived", "projects.status", "否", "补齐项目状态枚举", "P1"],
  ["ProjectPhase", "status", "planned / active / completed / cancelled", "无", "是", "单独维护项目期状态", "P0"],
  ["ProjectLot", "status", "planned / bidding / awarded / active / completed / lost", "project_sections.status", "是", "标段状态独立于项目状态", "P0"],
  ["Opportunity", "sales_stage", "商机报备 / 商机确认 / 商机跟踪 / 标前引导 / 招投标 / 签约", "已实现 6 阶段", "否", "保留 StageDefinition", "已完成"],
  ["Opportunity", "result_status", "open / won / lost / abandoned", "无", "是", "失败不能只靠 stage 表达", "P1"],
  ["Relationship", "relationship_status", "待建立 / 跟进中 / 已建立 / 已失联 / 已结束", "已实现文本字段", "否", "补充更新时间和来源", "P1"],
  ["Event", "status", "recorded / processed / rejected", "business_events 无", "是", "支持 AI 处理闭环", "P1"],
  ["Insight", "status", "draft / active / accepted / dismissed / expired", "无", "是", "支持 AI 建议生命周期", "P1"],
  ["Action", "status", "pending / in_progress / completed / overdue / cancelled", "无", "是", "支持任务执行和逾期管理", "P1"],
];
body(lifecycle, "A6:G16");
statusFormat(lifecycle, "D6:D16");

setupSheet(backlog, { A: 8, B: 28, C: 42, D: 24, E: 42, F: 18, G: 18 });
title(backlog, "本体开发补充清单", "按开发顺序执行。完成 P0 后，再进入本体管理页面和 Agent 深化。", "G");
backlog.getRange("A5:G5").values = [["序号", "工作项", "具体补充内容", "涉及表", "完成标准", "优先级", "状态"]];
header(backlog, "A5:G5");
backlog.getRange("A6:G18").values = [
  [1, "冻结对象命名", "明确 Account、ProjectPhase、ProjectLot、Opportunity、CustomerDevelopmentOpportunity 的中文和英文术语", "对象注册表", "产品、开发、Agent 使用同一套名称", "P0", "已完成"],
  [2, "新增组织模型", "新增 organizations，补客户组织归属和父子组织", "organizations / customers", "客户可归属集团或区域公司", "P0", "已完成"],
  [3, "拆分项目期和标段", "新增 project_phases、project_lots，迁移 project_sections", "projects / project_phases / project_lots", "一个标段明确归属一个项目期", "P0", "已完成"],
  [4, "补客户开发机会", "新增客户级长期开发机会，与项目商机分离", "customer_development_opportunities", "一个客户开发机会可关联多个项目商机", "P0", "已完成"],
  [5, "补商机外键", "Opportunity 增加 account_id、project_lot_id，并建立唯一约束", "opportunities", "商机可追溯到客户和标段", "P0", "已完成兼容字段"],
  [6, "补客户画像", "拆分客户事实与画像评分", "customer_profiles", "AI画像不覆盖客户主数据", "P1", "待开始"],
  [7, "统一关系模型", "新增 roles、relationships 或兼容迁移层", "roles / relationships", "关键人角色、影响力、关系强度可追踪", "P1", "待开始"],
  [8, "升级事件模型", "事件支持多对象、输入来源、AI抽取结果", "events", "文字、语音、图片、拜访记录均可进入 Event", "P0", "部分完成"],
  [9, "新增洞察模型", "独立保存评分、风险、建议、证据和有效期", "insights", "AI结果可追溯、可过期、可复盘", "P1", "待开始"],
  [10, "新增行动模型", "行动任务支持负责人、截止日期、状态、来源洞察", "actions", "洞察可以转成可执行任务", "P1", "待开始"],
  [11, "补字段定义", "为对象建立字段字典、必填、枚举、来源和权限", "field_definitions", "本体、页面和 Agent 共用字段定义", "P1", "待开始"],
  [12, "建立本体管理页", "对象、字段、关系、事件、洞察、行动管理页面", "前端", "可查看和维护本体定义", "P2", "待开始"],
  [13, "建立一致性校验", "检查孤儿外键、重复标段、无效角色和缺失生命周期", "audit / API", "迁移和新增数据可自动校验", "P1", "待开始"],
];
body(backlog, "A6:G18");
statusFormat(backlog, "G6:G18");
backlog.freezePanes.freezeRows(5);

for (const sheet of [overview, objects, fields, relations, lifecycle, backlog]) {
  sheet.getUsedRange().format.autofitRows();
}

workbook.recalculate();

for (const [sheet, name, range] of [
  [overview, "overview", "A1:E18"],
  [objects, "objects", "A1:H20"],
  [fields, "fields", "A1:H28"],
  [relations, "relations", "A1:G20"],
  [lifecycle, "lifecycle", "A1:G16"],
  [backlog, "backlog", "A1:G18"],
]) {
  const preview = await workbook.render({ sheetName: sheet.name, range, scale: 1, format: "png" });
  await fs.writeFile(`${previewDir}/${name}.png`, new Uint8Array(await preview.arrayBuffer()));
}

const check = await workbook.inspect({
  kind: "sheet,table",
  maxChars: 6000,
  tableMaxRows: 5,
  tableMaxCols: 8,
});
console.log(check.ndjson);

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`saved ${outputPath}`);
