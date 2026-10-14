# Opportunity Intelligence Ontology

## 1. 设计目标

本体用于回答四个经营问题：

1. 哪些商机最可能赢？
2. 预计什么时候成交？
3. 预计成交金额是多少？
4. 风险在哪里，以及下一步应该做什么？

本设计是一个独立的 `Opportunity Intelligence` 扩展层，不修改已有
`Opportunity Ontology` 的实体、字段和关系。已有业务对象继续作为事实来源；
预测、风险、解释和行动建议以新的 Intelligence Entity 保存。

**边界声明：本设计不修改已有 `Opportunity Ontology`。**

### 1.1 为什么采用扩展层

- `Opportunity` 记录业务事实，不能同时承担模型输出，否则预测值会覆盖人工事实。
- 预测结果会随时间、模型版本和新事件变化，必须保留历史快照，才能解释“为什么变了”。
- 风险和建议不是同一种对象：风险描述不确定性，Action 描述可执行动作，二者需要分别治理。
- Agent 只能基于已发布模型和可追溯特征进行推理，不能绕过权限直接改写原 Opportunity。

### 1.2 对用户的影响

销售看到的不是一个不可解释的总分，而是：

- 赢单概率及其变化；
- 预计成交窗口与置信区间；
- 预计金额、金额区间和金额风险；
- 影响预测的关键事实；
- 风险严重度、证据和建议动作。

管理者可以按区域、客户、项目、产品和阶段比较预测，区分“高价值且高胜率”
与“金额大但风险高”的商机。

## 2. 范围与边界

### 2.1 复用的事实实体

以下实体属于已有业务本体，本设计只引用其稳定业务 ID，不重新定义其主数据：

| Entity | 在预测中的作用 |
| --- | --- |
| `Opportunity` | 预测主体、阶段、金额、状态和销售过程事实 |
| `Customer` | 客户经营关系、历史合作和组织上下文 |
| `Project` | 商机对应项目、项目进度、预算和采购时间 |
| `ProjectSection` | 项目分区或施工/业务标段的细粒度进度与需求 |
| `Product` | 产品组合、需求匹配、价格和毛利上下文 |
| `Person` | 决策人、影响人、联系人和关系覆盖 |
| `Action` | 已完成或计划中的销售动作及其结果 |

`ProjectSection` 在文档中使用无空格的技术名；如果已有系统使用
`Project Section`，通过字段映射层转换，不创建第二个概念。

### 2.2 本设计新增的 Intelligence Entity

| Entity | 作用 | 生命周期 |
| --- | --- | --- |
| `OpportunityIntelligenceProfile` | 某商机当前的智能预测总览 | 随商机和预测刷新更新 |
| `OpportunityForecastSnapshot` | 一次完整预测的不可变快照 | 追加写入 |
| `OpportunityFeatureSnapshot` | 参与预测的特征快照 | 与预测快照绑定 |
| `OpportunityRisk` | 可解释、可治理的商机风险 | 可检测、确认、缓解、关闭 |
| `OpportunityEvidence` | 支撑预测或风险的事实证据 | 追加写入 |
| `OpportunityPredictionExplanation` | 对预测结果的贡献解释 | 与预测快照绑定 |
| `OpportunityModelVersion` | 模型、规则、特征口径的版本 | 发布后不可变 |
| `OpportunityAgentRun` | Agent 一次推理或执行的审计记录 | 追加写入 |
| `OpportunityPredictionFeedback` | 人工修正和实际结果反馈 | 追加写入 |

## 3. Entity 与字段

字段类型为逻辑类型，最终可以映射到关系表、事件流或图数据库。所有时间使用
ISO 8601；金额必须同时保存 `currency`。

### 3.1 OpportunityIntelligenceProfile

表示商机当前可供工作台和 Agent 快速读取的投影，不作为历史事实来源。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `profile_id` | ID | 是 | 智能档案 ID |
| `opportunity_id` | ID | 是 | 引用已有 `Opportunity` |
| `current_forecast_snapshot_id` | ID | 是 | 当前生效预测快照 |
| `win_probability` | Decimal(0,1) | 是 | 当前赢单概率 |
| `win_probability_band` | Enum | 是 | `VERY_LOW`、`LOW`、`MEDIUM`、`HIGH`、`VERY_HIGH` |
| `expected_close_date` | Date | 否 | 预计成交日期 |
| `close_date_start` | Date | 否 | 预计成交窗口起点 |
| `close_date_end` | Date | 否 | 预计成交窗口终点 |
| `expected_amount` | Decimal | 否 | 期望成交金额 |
| `amount_low` | Decimal | 否 | 金额区间下界 |
| `amount_high` | Decimal | 否 | 金额区间上界 |
| `currency` | String | 是 | 金额币种 |
| `risk_level` | Enum | 是 | `LOW`、`MEDIUM`、`HIGH`、`CRITICAL` |
| `open_risk_count` | Integer | 是 | 未关闭风险数 |
| `next_best_action_id` | ID | 否 | 关联建议或计划中的 `Action` |
| `confidence` | Decimal(0,1) | 是 | 对本次综合输出的置信度 |
| `last_scored_at` | DateTime | 是 | 最近评分时间 |
| `forecast_status` | Enum | 是 | `READY`、`STALE`、`INSUFFICIENT_DATA`、`ERROR` |

### 3.2 OpportunityForecastSnapshot

保存某一时刻的完整预测输出。历史快照不可更新，只能新增。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `forecast_snapshot_id` | ID | 是 | 预测快照 ID |
| `opportunity_id` | ID | 是 | 预测主体 |
| `model_version_id` | ID | 是 | 使用的 `OpportunityModelVersion` |
| `as_of_time` | DateTime | 是 | 预测基准时间 |
| `win_probability` | Decimal(0,1) | 是 | 赢单概率 |
| `loss_probability` | Decimal(0,1) | 是 | 输单概率 |
| `no_decision_probability` | Decimal(0,1) | 是 | 延期或无决策概率 |
| `expected_close_date` | Date | 否 | 期望成交日期 |
| `close_date_p50` | Date | 否 | 成交日期中位数 |
| `close_date_p80` | Date | 否 | 80% 覆盖日期 |
| `expected_amount` | Decimal | 否 | 期望金额 |
| `amount_p50` | Decimal | 否 | 金额中位数 |
| `amount_p80` | Decimal | 否 | 80% 覆盖金额 |
| `currency` | String | 是 | 金额币种 |
| `confidence` | Decimal(0,1) | 是 | 综合置信度 |
| `data_completeness` | Decimal(0,1) | 是 | 输入数据完整度 |
| `calculation_status` | Enum | 是 | `CALCULATED`、`PARTIAL`、`FAILED` |
| `created_at` | DateTime | 是 | 创建时间 |

### 3.3 OpportunityFeatureSnapshot

保存“模型当时实际看到的输入”，避免以后因业务数据变化而无法复盘。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `feature_snapshot_id` | ID | 是 | 特征快照 ID |
| `forecast_snapshot_id` | ID | 是 | 所属预测快照 |
| `feature_set_version` | String | 是 | 特征口径版本 |
| `feature_code` | String | 是 | 特征编码 |
| `feature_value` | JSON | 是 | 标准化后的值 |
| `raw_value_reference` | JSON | 否 | 原始字段或事件引用 |
| `missing_flag` | Boolean | 是 | 是否缺失 |
| `as_of_time` | DateTime | 是 | 特征截面时间 |
| `source_entity_type` | String | 否 | 来源实体类型 |
| `source_entity_id` | ID | 否 | 来源实体 ID |

同一 `forecast_snapshot_id + feature_code` 只能有一个有效值。

### 3.4 OpportunityRisk

风险是可以被证据支持、被责任人处理、被结果验证的对象。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `risk_id` | ID | 是 | 风险 ID |
| `opportunity_id` | ID | 是 | 所属商机 |
| `risk_type` | Enum | 是 | `STALE_ACTIVITY`、`DECISION_MAKER_GAP`、`PROJECT_DELAY`、`BUDGET_GAP`、`PRODUCT_MISMATCH`、`COMPETITION`、`PRICE_PRESSURE`、`DATA_QUALITY`、`OTHER` |
| `severity` | Enum | 是 | `LOW`、`MEDIUM`、`HIGH`、`CRITICAL` |
| `probability` | Decimal(0,1) | 是 | 风险发生概率 |
| `impact_amount` | Decimal | 否 | 可能影响的金额 |
| `impact_days` | Integer | 否 | 可能造成的延期天数 |
| `status` | Enum | 是 | `OPEN`、`ACKNOWLEDGED`、`MITIGATING`、`RESOLVED`、`ACCEPTED`、`FALSE_POSITIVE` |
| `owner_person_id` | ID | 否 | 风险责任人，引用 `Person` |
| `detected_at` | DateTime | 是 | 首次检测时间 |
| `last_observed_at` | DateTime | 是 | 最近观察时间 |
| `due_at` | DateTime | 否 | 处理截止时间 |
| `resolution_note` | Text | 否 | 关闭或接受原因 |

### 3.5 OpportunityEvidence

证据可以来自结构化字段、事件、文档抽取结果或人工确认。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `evidence_id` | ID | 是 | 证据 ID |
| `opportunity_id` | ID | 是 | 所属商机 |
| `evidence_type` | Enum | 是 | `FIELD_VALUE`、`ACTION_RESULT`、`PROJECT_EVENT`、`CUSTOMER_SIGNAL`、`PERSON_SIGNAL`、`DOCUMENT`、`MANUAL_ASSERTION` |
| `source_entity_type` | String | 是 | 来源实体类型 |
| `source_entity_id` | ID | 是 | 来源实体 ID |
| `source_field` | String | 否 | 来源字段 |
| `observed_at` | DateTime | 是 | 事实发生或观察时间 |
| `content` | JSON | 是 | 结构化证据内容 |
| `reliability` | Decimal(0,1) | 是 | 来源可靠度 |
| `valid_from` | DateTime | 否 | 证据有效期开始 |
| `valid_to` | DateTime | 否 | 证据有效期结束 |
| `created_by` | String | 是 | `SYSTEM`、Agent ID 或用户 ID |

### 3.6 OpportunityPredictionExplanation

解释必须引用特征或证据，不能只保存一段自然语言。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `explanation_id` | ID | 是 | 解释 ID |
| `forecast_snapshot_id` | ID | 是 | 所属预测快照 |
| `target` | Enum | 是 | `WIN`、`CLOSE_DATE`、`AMOUNT`、`RISK` |
| `direction` | Enum | 是 | `POSITIVE`、`NEGATIVE`、`NEUTRAL` |
| `factor_code` | String | 是 | 因素编码 |
| `contribution` | Decimal | 是 | 对结果的贡献 |
| `rank` | Integer | 是 | 影响排序 |
| `evidence_ids` | Array<ID> | 是 | 支撑证据 |
| `summary` | Text | 是 | 面向用户的简短解释 |

### 3.7 OpportunityModelVersion

用于保证模型、规则和特征口径可复现。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model_version_id` | ID | 是 | 模型版本 ID |
| `model_name` | String | 是 | 模型名称 |
| `version` | String | 是 | 语义化版本 |
| `model_type` | Enum | 是 | `RULE`、`STATISTICAL`、`ML`、`HYBRID` |
| `feature_set_version` | String | 是 | 特征集合版本 |
| `target_definition` | JSON | 是 | 赢单、成交、金额标签定义 |
| `status` | Enum | 是 | `DRAFT`、`TESTING`、`PUBLISHED`、`RETIRED` |
| `published_at` | DateTime | 否 | 发布时间 |
| `created_by` | String | 是 | 创建人或系统 |

### 3.8 OpportunityAgentRun

记录 Agent 如何读取上下文、得出结论和执行动作。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `run_id` | ID | 是 | Agent 调用 ID |
| `opportunity_id` | ID | 是 | 商机 ID |
| `agent_code` | String | 是 | Agent 编码 |
| `intent` | String | 是 | 用户或系统意图 |
| `input_context_hash` | String | 是 | 输入上下文摘要 |
| `forecast_snapshot_id` | ID | 否 | 产生的预测快照 |
| `risk_ids` | Array<ID> | 否 | 产生或更新的风险 |
| `action_ids` | Array<ID> | 否 | 建议或执行的 `Action` |
| `approval_required` | Boolean | 是 | 是否需要审批 |
| `approval_status` | Enum | 是 | `NOT_REQUIRED`、`PENDING`、`APPROVED`、`REJECTED` |
| `result_status` | Enum | 是 | `SUCCESS`、`PARTIAL`、`BLOCKED`、`FAILED` |
| `created_at` | DateTime | 是 | 开始时间 |
| `completed_at` | DateTime | 否 | 完成时间 |

### 3.9 OpportunityPredictionFeedback

把人工判断和实际结果作为学习闭环，但不直接修改历史预测。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `feedback_id` | ID | 是 | 反馈 ID |
| `opportunity_id` | ID | 是 | 商机 ID |
| `forecast_snapshot_id` | ID | 否 | 被反馈的预测 |
| `feedback_type` | Enum | 是 | `ACCEPTED`、`CORRECTED`、`REJECTED`、`OUTCOME_CONFIRMED` |
| `target` | Enum | 是 | `WIN`、`CLOSE_DATE`、`AMOUNT`、`RISK` |
| `previous_value` | JSON | 否 | 原预测值 |
| `corrected_value` | JSON | 否 | 人工修正值 |
| `actual_value` | JSON | 否 | 最终事实结果 |
| `reason_code` | String | 否 | 修正原因 |
| `created_by` | String | 是 | 用户或系统 |
| `created_at` | DateTime | 是 | 创建时间 |

## 4. 关系模型

### 4.1 核心关系

```text
Customer 1 ─────< Opportunity >───── 1 Project
                         │                  │
                         │                  └────< ProjectSection
                         │
                         ├────< OpportunityIntelligenceProfile
                         ├────< OpportunityForecastSnapshot
                         ├────< OpportunityRisk
                         ├────< OpportunityEvidence
                         ├────< OpportunityAgentRun
                         └────< OpportunityPredictionFeedback

Opportunity >────< Product
Opportunity >────< Person
Opportunity >────< Action

OpportunityForecastSnapshot >──── 1 OpportunityModelVersion
OpportunityForecastSnapshot ────< OpportunityFeatureSnapshot
OpportunityForecastSnapshot ────< OpportunityPredictionExplanation
OpportunityRisk ───────────────< OpportunityEvidence
OpportunityAgentRun >──────────< Action
```

### 4.2 关系定义

| 主体 | 关系 | 客体 | 基数 | 语义 |
| --- | --- | --- | --- | --- |
| `Opportunity` | `hasIntelligenceProfile` | `OpportunityIntelligenceProfile` | 1:1 | 商机当前智能投影 |
| `Opportunity` | `hasForecastSnapshot` | `OpportunityForecastSnapshot` | 1:N | 商机的预测历史 |
| `OpportunityForecastSnapshot` | `usesModelVersion` | `OpportunityModelVersion` | N:1 | 预测使用的模型版本 |
| `OpportunityForecastSnapshot` | `hasFeatureSnapshot` | `OpportunityFeatureSnapshot` | 1:N | 预测实际输入 |
| `OpportunityForecastSnapshot` | `hasExplanation` | `OpportunityPredictionExplanation` | 1:N | 预测解释 |
| `Opportunity` | `hasRisk` | `OpportunityRisk` | 1:N | 当前或历史风险 |
| `OpportunityRisk` | `supportedBy` | `OpportunityEvidence` | N:N | 风险证据 |
| `Opportunity` | `hasEvidence` | `OpportunityEvidence` | 1:N | 商机事实证据 |
| `Opportunity` | `hasAgentRun` | `OpportunityAgentRun` | 1:N | Agent 审计记录 |
| `Opportunity` | `hasFeedback` | `OpportunityPredictionFeedback` | 1:N | 预测反馈 |
| `Opportunity` | `relatedToCustomer` | `Customer` | N:1 | 复用已有客户关系 |
| `Opportunity` | `realizesProject` | `Project` | N:1 | 复用已有项目关系 |
| `Project` | `hasSection` | `ProjectSection` | 1:N | 复用已有项目分区关系 |
| `Opportunity` | `requiresProduct` | `Product` | N:N | 产品组合和需求匹配 |
| `Opportunity` | `involvesPerson` | `Person` | N:N | 决策链和关系覆盖 |
| `Opportunity` | `hasAction` | `Action` | 1:N | 销售动作和结果 |

关系语义要点：

- 预测实体只能引用事实实体，不能复制事实字段作为第二份主数据。
- `OpportunityIntelligenceProfile` 是当前投影；历史以 `OpportunityForecastSnapshot` 为准。
- `Action` 仍是业务动作本体，智能层只记录“建议哪个 Action、为什么建议、执行结果如何”。
- `Evidence` 是解释的最小可审计单元；自然语言摘要不能替代证据引用。

## 5. Algorithm Feature 设计

特征命名采用 `subject.signal.window` 形式，示例：
`opportunity.stage_age_days`、`project.milestone_delay_days`。

### 5.1 赢单概率 Features

| Feature Code | 来源 | 计算口径 | 业务含义 |
| --- | --- | --- | --- |
| `opportunity.stage_code` | `Opportunity` | 当前阶段编码 | 阶段基线胜率 |
| `opportunity.stage_age_days` | `Opportunity` | 当前阶段持续天数 | 阶段停滞信号 |
| `opportunity.amount_log` | `Opportunity` | `log(1 + amount)` | 金额规模影响 |
| `opportunity.amount_change_30d` | `Opportunity` | 近 30 天金额变化 | 预算稳定性 |
| `opportunity.activity_count_30d` | `Action` | 近 30 天有效动作数 | 推进活跃度 |
| `opportunity.days_since_last_action` | `Action` | 当前时间减最近完成动作 | 失联风险 |
| `action_outcome_positive_rate_90d` | `Action` | 正向结果 / 有结果动作 | 行动质量 |
| `customer_prior_win_rate` | `Customer`、历史 `Opportunity` | 同客户历史赢单率 | 客户关系基线 |
| `customer_open_opportunity_count` | `Customer`、`Opportunity` | 客户当前开放商机数 | 资源竞争 |
| `project_progress_ratio` | `Project` | 已完成里程碑 / 总里程碑 | 项目成熟度 |
| `project_milestone_delay_days` | `Project` | 实际进度相对计划延误 | 项目延期风险 |
| `project_section_need_coverage` | `ProjectSection`、`Product` | 已覆盖需求 / 总需求 | 方案匹配度 |
| `product_fit_score` | `Product`、`ProjectSection` | 产品与需求规则匹配 | 解决方案适配度 |
| `decision_maker_coverage` | `Person` | 已识别并有效互动的关键角色比例 | 决策链完整度 |
| `relationship_strength_max` | `Person`、关系评分 | 关键联系人最高关系强度 | 进入客户组织能力 |
| `competitor_signal_count_30d` | `Evidence`、`Action` | 竞争信号数 | 竞争压力 |

### 5.2 成交时间 Features

| Feature Code | 来源 | 计算口径 | 业务含义 |
| --- | --- | --- | --- |
| `stage_transition_velocity_90d` | `Opportunity`、事件 | 阶段变化次数 / 天数 | 推进速度 |
| `current_stage_remaining_days_p50` | 历史商机 | 当前阶段历史中位停留天数 | 阶段剩余时间 |
| `project_target_date_gap_days` | `Project` | 项目目标日期与当前日期差 | 外部时间约束 |
| `procurement_window_days` | `Project`、`ProjectSection` | 采购窗口长度 | 可成交时间窗 |
| `next_action_due_gap_days` | `Action` | 下一动作到期时间差 | 近期推进计划 |
| `approval_cycle_days_p50` | `Action`、历史记录 | 审批周期中位数 | 内部流程耗时 |
| `decision_maker_response_latency_days` | `Person`、`Action` | 关键人平均响应时间 | 决策节奏 |
| `stale_days` | `Action` | 最近有效活动距今天数 | 延期风险 |
| `project_delay_probability` | `Project`、风险模型 | 项目延期概率 | 成交日期下移风险 |

### 5.3 成交金额 Features

| Feature Code | 来源 | 计算口径 | 业务含义 |
| --- | --- | --- | --- |
| `opportunity_amount_current` | `Opportunity` | 当前申报金额 | 当前金额基线 |
| `opportunity_amount_revision_count_90d` | `Opportunity` | 近 90 天金额修改次数 | 金额稳定性 |
| `project_budget_estimate` | `Project` | 项目预算或预算区间 | 外部金额上限 |
| `project_section_demand_quantity` | `ProjectSection` | 需求数量汇总 | 可售规模 |
| `product_mix_list_price` | `Product` | 产品组合牌价汇总 | 理论金额 |
| `product_mix_discount_rate` | `Product`、`Action` | 预计折扣率 | 折扣侵蚀 |
| `historical_customer_deal_amount_p50` | `Customer`、历史 `Opportunity` | 客户历史成交金额中位数 | 客户购买能力 |
| `scope_coverage_ratio` | `ProjectSection`、`Product` | 已覆盖范围 / 可销售范围 | 金额实现程度 |
| `amount_change_volatility_180d` | `Opportunity` | 金额变动标准差或变异系数 | 金额不确定性 |

### 5.4 风险 Features

| Feature Code | 来源 | 触发条件 | 风险 |
| --- | --- | --- | --- |
| `risk.no_recent_action` | `Action` | 超过阈值未有有效动作 | 商机失活 |
| `risk.no_decision_maker` | `Person` | 未识别关键决策角色 | 决策链缺口 |
| `risk.project_schedule_slippage` | `Project` | 里程碑延迟超过阈值 | 项目进度风险 |
| `risk.section_need_uncovered` | `ProjectSection`、`Product` | 关键需求未覆盖 | 方案风险 |
| `risk.amount_above_customer_history` | `Customer`、历史 `Opportunity` | 当前金额显著高于历史能力 | 预算风险 |
| `risk.high_discount_pressure` | `Product`、`Action` | 折扣请求超过阈值 | 毛利和赢单风险 |
| `risk.competitor_detected` | `Evidence` | 近期出现明确竞品信号 | 竞争风险 |
| `risk.conflicting_facts` | `Evidence` | 关键字段与新事实冲突 | 数据质量风险 |

### 5.5 算法建议

第一阶段采用可解释的混合模型：

```text
WinProbability
  = calibrated_baseline(stage, segment)
  + evidence_adjustments
  + relationship_adjustments
  - risk_penalties

CloseDate
  = stage_duration_model
  + project_schedule_adjustment
  + action_velocity_adjustment
  + approval_cycle_adjustment

ExpectedAmount
  = opportunity_amount_current
  × scope_coverage_ratio
  × (1 - discount_rate)
  × amount_stability_factor
```

关键取舍：

- 先使用规则、统计基线和校准模型，便于销售解释和快速发现数据问题。
- 有足够历史标签后，再引入 ML 模型；ML 输出必须保留特征快照和解释。
- 预测置信度同时受模型置信度和数据完整度影响，不能只展示一个漂亮分数。
- 缺失数据不默认当作“没有风险”，而是降低 `confidence`，必要时生成
  `DATA_QUALITY` 风险。

## 6. Agent 接口

### 6.1 统一调用约定

接口返回三类结果：

1. `prediction`：结构化预测；
2. `evidence`：证据和解释；
3. `actions`：建议动作或待审批动作。

所有写操作携带 `idempotencyKey`，所有结果产生 `OpportunityAgentRun`。

### 6.2 Opportunity Forecast Agent

用途：回答“能不能赢、何时成交、金额多少”。

```http
POST /api/opportunity-intelligence/forecast
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "targets": ["WIN", "CLOSE_DATE", "AMOUNT"],
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "opp-forecast-v1",
  "includeEvidence": true,
  "includeFeatureSummary": true,
  "idempotencyKey": "forecast-opp-1001-20261014"
}
```

响应：

```json
{
  "runId": "run-9001",
  "opportunityId": "opp-1001",
  "forecastSnapshotId": "forecast-7001",
  "prediction": {
    "winProbability": 0.72,
    "expectedCloseDate": "2026-12-18",
    "closeDateWindow": {
      "start": "2026-12-05",
      "end": "2027-01-09"
    },
    "expectedAmount": 1850000,
    "amountRange": {
      "low": 1500000,
      "high": 2200000
    },
    "currency": "CNY",
    "confidence": 0.68
  },
  "topFactors": [
    {
      "factorCode": "decision_maker_coverage",
      "direction": "POSITIVE",
      "summary": "已识别 3 个关键角色，其中 2 个在近 14 天有有效互动。"
    },
    {
      "factorCode": "project_milestone_delay_days",
      "direction": "NEGATIVE",
      "summary": "项目关键里程碑预计延迟 21 天，成交窗口可能后移。"
    }
  ],
  "risks": ["risk-3001"],
  "recommendedActions": ["action-5001"]
}
```

### 6.3 Opportunity Risk Agent

用途：发现、合并、解释和分派风险。

```http
POST /api/opportunity-intelligence/risks:detect
GET  /api/opportunities/{opportunityId}/intelligence/risks
POST /api/opportunity-intelligence/risks/{riskId}:acknowledge
POST /api/opportunity-intelligence/risks/{riskId}:resolve
```

`detect` 只产生或更新 `OpportunityRisk`，不自动关闭已有风险。风险关闭必须有
状态变化、证据或人工说明。

### 6.4 Next Best Action Agent

用途：根据预测和风险推荐下一步销售动作。

```http
POST /api/opportunity-intelligence/next-best-action
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "objective": "IMPROVE_WIN_PROBABILITY",
  "constraints": {
    "ownerPersonId": "person-21",
    "dueWithinDays": 7,
    "maxActions": 3
  },
  "requireApproval": true
}
```

返回的动作建议必须包含：

| 字段 | 说明 |
| --- | --- |
| `actionType` | 复用已有 `Action` 类型 |
| `reason` | 触发建议的风险或预测因素 |
| `expectedImpact` | 对赢单、时间或金额的预期影响 |
| `ownerPersonId` | 建议责任人 |
| `dueAt` | 建议截止时间 |
| `evidenceIds` | 证据引用 |
| `approvalRequired` | 是否需要确认 |

### 6.5 Forecast Review Agent

用途：帮助销售或管理者复核“为什么系统这样判断”。

```http
GET /api/opportunities/{opportunityId}/intelligence/summary
POST /api/opportunity-intelligence/feedback
```

支持的问题：

- “为什么这个商机只有 42%？”
- “哪些事实让成交日期后移？”
- “如果本周完成这个 Action，预测会怎样变化？”
- “这个风险是否已经被处理？”

Agent 必须返回结构化证据和解释，不得只返回无法验证的自然语言结论。

## 7. 事件与刷新策略

### 7.1 触发事件

以下事件触发增量特征更新，必要时触发重新预测：

| 事件 | 影响 |
| --- | --- |
| `OpportunityStageChanged` | 赢单概率、成交时间 |
| `OpportunityAmountChanged` | 赢单概率、金额、风险 |
| `ActionCompleted` | 活跃度、推进速度、关系信号 |
| `ActionOverdue` | 失活风险、成交时间 |
| `ProjectMilestoneChanged` | 项目成熟度、成交时间 |
| `ProjectSectionRequirementChanged` | 产品匹配、金额 |
| `PersonRoleChanged` | 决策链覆盖 |
| `CustomerSignalReceived` | 客户意向和风险 |
| `ProductMixChanged` | 产品匹配、金额和折扣 |
| `ForecastFeedbackSubmitted` | 反馈闭环和模型评估 |

### 7.2 刷新规则

- 高影响事件：即时重算当前商机。
- 普通事件：进入短批处理窗口，避免同一商机连续重复计算。
- 无事件商机：至少每日检查一次数据新鲜度。
- 数据源不可用：保留上一份预测，标记 `STALE`，不得静默覆盖为零。

## 8. 治理、权限与数据质量

### 8.1 写入边界

- 预测结果写入新的 Intelligence Entity，不写回已有 `Opportunity` 的事实字段。
- Agent 可以创建建议型 `Action` 草稿。
- 对外沟通、价格、折扣、合同承诺和批量更新必须审批。
- 用户人工修正通过 `OpportunityPredictionFeedback` 记录，不直接覆盖历史快照。

### 8.2 解释与审计

每次预测至少可以追溯：

```text
AgentRun
  -> ForecastSnapshot
  -> ModelVersion
  -> FeatureSnapshot
  -> Evidence
  -> Source Entity / Source Field / Source Event
```

禁止以下做法：

- 只保存最终分数，不保存输入特征；
- 用当前字段值回溯替代当时的特征值；
- 用无证据的生成式文本解释风险；
- 用人工修改覆盖系统原始预测；
- 未经审批直接代表销售对外承诺。

### 8.3 数据质量规则

当出现以下情况时，预测可以返回，但必须降低 `confidence` 或标记风险：

- 缺少金额币种；
- 缺少项目或项目目标日期；
- 阶段持续时间异常；
- 关键人未识别；
- 产品组合与项目需求无法匹配；
- 事实时间戳晚于当前时间；
- 同一事实存在互相冲突的来源。

## 9. 最小落地顺序

### Phase 1：可解释预测

先实现：

- `OpportunityForecastSnapshot`
- `OpportunityFeatureSnapshot`
- `OpportunityPredictionExplanation`
- `OpportunityIntelligenceProfile`
- 赢单概率、成交时间、金额区间的规则/统计模型
- Forecast Agent 查询接口

### Phase 2：风险与行动闭环

增加：

- `OpportunityRisk`
- `OpportunityEvidence`
- Risk Agent
- Next Best Action Agent
- 与现有 `Action` 的审批和执行结果联动

### Phase 3：反馈学习

增加：

- `OpportunityModelVersion` 发布流程
- `OpportunityPredictionFeedback`
- 预测校准、模型对比和数据漂移监控
- 基于实际成交结果的模型迭代

## 10. 验证清单

- [ ] 未修改已有 `Opportunity Ontology` 的实体、字段和关系。
- [ ] 每个预测快照都绑定 `OpportunityModelVersion`。
- [ ] 每个关键解释都能回溯到 `FeatureSnapshot` 或 `Evidence`。
- [ ] 预测历史追加保存，不能被当前投影覆盖。
- [ ] 缺失数据会降低置信度或产生数据质量风险。
- [ ] 风险有责任人、状态、截止时间和证据。
- [ ] Agent 的每次调用都有 `OpportunityAgentRun`。
- [ ] 建议 Action 与执行 Action 分离，并保留审批状态。
- [ ] 人工反馈不删除原始预测。
- [ ] 金额均带币种，日期预测同时提供区间和置信度。
