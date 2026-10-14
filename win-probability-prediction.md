# Win Probability Prediction

## 1. 目标与边界

本能力只回答一个问题：**当前商机在给定预测时点赢单的概率是多少，为什么，主要风险是什么。**

输入事实来自：

- `Opportunity`
- `Customer`
- `Project`
- `Person`
- `Action`

预测结果写入 `Opportunity Intelligence` 扩展层，不修改已有 `Opportunity Ontology`，也不覆盖
`Opportunity` 上的人工事实字段。

### 1.1 为什么单独建设

- 赢单概率是随时间、动作和项目事实变化的预测结果，不是商机主数据。
- 概率必须能回溯到当时的输入特征，否则销售无法判断“是业务变了，还是模型变了”。
- 影响因素和风险原因需要分开：影响因素解释分数变化，风险原因表达可处理的问题。

### 1.2 用户看到的结果

销售或管理者获得四个直接答案：

1. 当前赢单概率，例如 `72%`；
2. 相比上次预测上升还是下降，以及变化幅度；
3. 哪些事实正在提升或拉低概率；
4. 哪些风险最可能导致输单，以及应该补什么事实或执行什么动作。

## 2. 预测对象与输出契约

### 2.1 预测主体

一个预测主体由以下键确定：

```text
opportunity_id + as_of_time + model_version_id
```

同一商机可以有多次预测，但历史预测只追加保存。当前工作台读取
`OpportunityIntelligenceProfile.current_forecast_snapshot_id`。

### 2.2 最小输出

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| `win_probability` | Decimal(0,1) | 校准后的赢单概率，范围 `[0,1]` |
| `probability_band` | Enum | `VERY_LOW`、`LOW`、`MEDIUM`、`HIGH`、`VERY_HIGH` |
| `probability_delta` | Decimal | 相比上一份有效预测的变化 |
| `confidence` | Decimal(0,1) | 对当前预测可靠性的判断，不等于赢单概率 |
| `top_positive_factors` | Array | 提升概率的主要因素，按贡献排序 |
| `top_negative_factors` | Array | 拉低概率的主要因素，按贡献排序 |
| `risk_reasons` | Array | 可治理的风险原因，按严重度排序 |
| `recommended_actions` | Array | 通过 `Action` 执行的建议动作 |
| `as_of_time` | DateTime | 预测截面时间 |
| `model_version_id` | ID | 模型和特征口径版本 |

### 2.3 概率分段

分段只用于工作台筛选和管理动作，不替代精确概率：

| 区间 | `probability_band` | 经营含义 |
| --- | --- | --- |
| `< 0.20` | `VERY_LOW` | 低优先级，先补齐关键事实或验证是否应继续投入 |
| `0.20 - 0.39` | `LOW` | 存在可推进空间，但输单因素明显 |
| `0.40 - 0.69` | `MEDIUM` | 需要关键动作改变局势 |
| `0.70 - 0.84` | `HIGH` | 进入重点推进和成交保障 |
| `>= 0.85` | `VERY_HIGH` | 重点防止流程、价格或交付因素造成意外丢单 |

边界值采用左闭右开，最后一档包含上限 `1.0`。

## 3. 输入事实与特征映射

### 3.1 Opportunity 特征

| Feature Code | 输入字段/关系 | 计算口径 | 影响方向 |
| --- | --- | --- | --- |
| `opp.stage_baseline` | `Opportunity.stage` | 当前阶段在同细分市场的历史校准胜率 | 基线 |
| `opp.stage_age_ratio` | `Opportunity.stage`, 阶段事件 | 当前阶段停留天数 / 阶段历史 P50 | 超期则负向 |
| `opp.amount_log` | `Opportunity.amount` | `log(1 + amount)` | 非线性影响 |
| `opp.amount_stability_90d` | `Opportunity.amount` 历史快照 | 金额变更次数和变异度 | 稳定正向 |
| `opp.data_completeness` | `Opportunity` 必填字段 | 已填关键字段 / 应填字段 | 完整正向 |
| `opp.competitive_position` | Opportunity 事实或证据 | `WINNING`、`NEUTRAL`、`LOSING`、`UNKNOWN` | 竞争位置 |

### 3.2 Customer 特征

| Feature Code | 输入字段/关系 | 计算口径 | 影响方向 |
| --- | --- | --- | --- |
| `customer_prior_win_rate` | `Customer` 历史 `Opportunity` | 同客户历史赢单数 / 已结案数 | 正向基线 |
| `customer_relationship_age` | `Customer`、关系事件 | 合作关系持续时间 | 稳定关系正向 |
| `customer_open_opp_load` | `Customer` 当前开放商机 | 同客户开放商机数量和金额 | 过高则负向 |
| `customer_budget_fit` | `Customer`、`Opportunity.amount` | 当前金额相对客户历史购买能力 | 超出能力则负向 |
| `customer_engagement_trend` | `Customer`、`Action` | 近 30/90 天互动趋势 | 上升正向，下降负向 |

### 3.3 Project 特征

| Feature Code | 输入字段/关系 | 计算口径 | 影响方向 |
| --- | --- | --- | --- |
| `project_progress_ratio` | `Project` | 已完成里程碑 / 总里程碑 | 正向 |
| `project_schedule_health` | `Project` | 计划与实际进度偏差 | 延误负向 |
| `project_target_date_fit` | `Project.target_date` | 项目目标日期是否落在可交付窗口 | 可实现正向 |
| `project_budget_confirmed` | `Project` | 已确认预算 / 预计预算 | 已确认正向 |
| `project_scope_stability` | `Project` | 近 90 天范围变更次数 | 变更多则负向 |

### 3.4 Person 特征

| Feature Code | 输入字段/关系 | 计算口径 | 影响方向 |
| --- | --- | --- | --- |
| `person_decision_maker_coverage` | `Person` 角色关系 | 已识别关键决策角色数 / 预期角色数 | 正向 |
| `person_influence_strength_max` | `Person` 影响力和关系强度 | 关键人最高有效关系强度 | 正向 |
| `person_multi_thread_coverage` | `Person` | 技术、采购、业务、财务等角色覆盖数 | 多线程正向 |
| `person_response_latency` | `Person`、`Action` | 关键联系人平均响应时间 | 延迟过长负向 |
| `person_champion_signal` | `Person`、`Action` | 是否有客户内部倡导者的有效证据 | 正向 |

### 3.5 Action 特征

| Feature Code | 输入字段/关系 | 计算口径 | 影响方向 |
| --- | --- | --- | --- |
| `action_effective_count_30d` | `Action` | 近 30 天完成且有结果的动作数 | 正向 |
| `action_days_since_last_effective` | `Action` | 当前时间 - 最近有效动作时间 | 过久负向 |
| `action_positive_outcome_rate` | `Action` | 正向结果 / 有结果动作 | 正向 |
| `action_next_step_commitment` | `Action` | 是否存在客户确认的下一步及日期 | 正向 |
| `action_overdue_rate_90d` | `Action` | 逾期动作 / 计划动作 | 负向 |
| `action_proof_progress` | `Action` | 方案、样板、测试、报价等关键动作完成度 | 正向 |

## 4. 计算方法

### 4.1 推荐的第一阶段模型

第一阶段使用“分层基线 + 特征调整 + 风险惩罚 + 概率校准”的混合方法：

```text
raw_score
  = logit(stage_baseline)
  + customer_effect
  + project_effect
  + person_effect
  + action_effect
  + opportunity_effect
  - explicit_risk_penalty

win_probability = calibrate(sigmoid(raw_score))
```

这样设计的原因：

- `stage_baseline` 提供稳定起点，避免新商机因为数据少而被误判为零概率；
- 各实体只贡献本领域特征，便于定位问题和解释结果；
- 风险单独建模，允许销售处理风险后重新计算影响；
- `calibrate` 保证“70%”在长期样本中大致对应 70% 的真实赢单率，而不是只追求排序准确。

### 4.2 评分约束

- 概率必须限制在 `[0,1]`，不能出现大于 100% 或负值。
- 特征必须按 `as_of_time` 截断，禁止使用预测时点之后的事实造成数据泄漏。
- 同一事实有多个来源时，先按来源可靠度和时间有效性选择或合并，再进入模型。
- 缺失值不自动解释为负向事实；缺失会降低 `confidence`，只有明确规则才能生成风险。
- 没有足够历史样本时使用父级分层基线，例如行业、区域、阶段，而不是伪造精确分数。

### 4.3 置信度

`confidence` 不是第二个赢单概率，建议由以下因素组合：

```text
confidence
  = model_reliability
  × data_completeness
  × freshness_score
  × segment_sample_support
```

当 `confidence < 0.50` 时，响应必须明确标记 `LOW_CONFIDENCE`，并优先返回需要补齐的事实。

## 5. 影响因素解释

### 5.1 因素对象

每个影响因素都必须包含数值、方向和证据引用：

| 字段 | 说明 |
| --- | --- |
| `factor_code` | 稳定的特征编码 |
| `factor_name` | 面向用户的名称 |
| `direction` | `POSITIVE`、`NEGATIVE`、`NEUTRAL` |
| `contribution` | 对本次预测的标准化贡献 |
| `current_value` | 当前特征值 |
| `reference_value` | 基线或比较值 |
| `evidence_ids` | 证据 ID 列表 |
| `explanation` | 简短可读说明 |
| `actionable` | 是否可通过动作改变 |

### 5.2 正向因素示例

- `person_decision_maker_coverage`：已覆盖采购、技术和业务三类关键角色。
- `action_next_step_commitment`：客户确认了下一次评审时间和参与人。
- `project_progress_ratio`：项目已经进入采购准备阶段。
- `customer_prior_win_rate`：该客户过去同类项目有稳定成交记录。
- `action_proof_progress`：样板或测试结果已被客户确认。

### 5.3 负向因素示例

- `action_days_since_last_effective`：超过 21 天没有有效客户互动。
- `person_decision_maker_coverage`：尚未识别最终预算决策人。
- `project_schedule_health`：关键里程碑预计延迟，成交窗口可能后移。
- `customer_budget_fit`：当前金额显著高于客户历史同类采购水平。
- `opp.amount_stability_90d`：报价金额在近 90 天多次下调，需求范围尚未稳定。

解释排序采用绝对贡献值，但正负因素分别展示，避免一个正向高分掩盖关键负向风险。

## 6. 风险原因模型

### 6.1 风险原因分类

| `risk_code` | 触发事实 | 严重度建议 | 可治理动作 |
| --- | --- | --- | --- |
| `STALE_ACTIVITY` | 超过阶段阈值无有效 `Action` | 中/高 | 重新确认客户下一步 |
| `DECISION_MAKER_GAP` | 缺少最终决策人或预算负责人 | 高 | 建立多线程并请求引荐 |
| `PROJECT_DELAY` | `Project` 里程碑持续延期 | 中/高 | 对齐新计划和采购窗口 |
| `BUDGET_UNCONFIRMED` | 预算未确认或明显低于金额 | 高 | 验证预算和分阶段方案 |
| `SCOPE_UNSTABLE` | 项目范围或 `ProjectSection` 需求频繁变化 | 中 | 固化需求边界 |
| `PRODUCT_MISMATCH` | `Product` 未覆盖关键项目需求 | 高 | 补充方案或替代产品 |
| `COMPETITOR_PRESSURE` | 有明确竞品、比价或替换信号 | 高 | 获取竞争情报并强化差异化 |
| `PRICE_PRESSURE` | 折扣请求、毛利或价格审批受压 | 中/高 | 走价格审批并量化价值 |
| `CUSTOMER_ENGAGEMENT_DROP` | 客户互动频率和响应明显下降 | 中 | 找到客户内部倡导者 |
| `DATA_QUALITY` | 关键事实缺失、过期或冲突 | 低/中 | 补录、核验并标记来源 |

### 6.2 风险原因与概率的关系

风险原因不能简单等同于“输单概率”。推荐保存三种值：

```text
risk_probability       # 该风险发生或持续的概率
risk_impact             # 该风险对赢单结果的影响强度
estimated_probability_loss # 当前风险预计拉低的赢单概率
```

例如，项目延期概率可能只有 `0.35`，但如果项目日期是客户采购的硬约束，其
`estimated_probability_loss` 仍可能很高。这样销售优先处理“影响大”的风险，而不是只看风险数量。

### 6.3 风险生成规则

- 每个风险至少绑定一个 `OpportunityEvidence`。
- 同一 `risk_code + opportunity_id` 在未关闭时合并更新，不重复创建。
- 风险关闭需要新的正向证据、人工确认或明确的 `FALSE_POSITIVE` 原因。
- 预测下降超过阈值，或出现高严重度风险时，触发 `OpportunityRisk` 更新和通知候选。
- 风险原因不能由生成式文本凭空产生，文本只能把已结构化的触发事实翻译成业务语言。

## 7. Agent 接口

### 7.1 预测接口

```http
POST /api/opportunity-intelligence/win-probability:predict
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "win-probability-v1",
  "includeEvidence": true,
  "includeRecommendedActions": true,
  "idempotencyKey": "win-probability-opp-1001-20261014"
}
```

响应：

```json
{
  "runId": "run-9101",
  "opportunityId": "opp-1001",
  "forecastSnapshotId": "forecast-7101",
  "prediction": {
    "winProbability": 0.72,
    "probabilityBand": "HIGH",
    "probabilityDelta": 0.08,
    "confidence": 0.68,
    "status": "READY",
    "asOfTime": "2026-10-14T09:00:00+08:00"
  },
  "positiveFactors": [
    {
      "factorCode": "person_decision_maker_coverage",
      "direction": "POSITIVE",
      "contribution": 0.14,
      "currentValue": 0.75,
      "referenceValue": 0.50,
      "evidenceIds": ["evidence-101"],
      "explanation": "已覆盖采购、技术和业务三类关键角色。",
      "actionable": true
    }
  ],
  "negativeFactors": [
    {
      "factorCode": "project_schedule_health",
      "direction": "NEGATIVE",
      "contribution": -0.11,
      "currentValue": -21,
      "referenceValue": 0,
      "evidenceIds": ["evidence-102"],
      "explanation": "项目关键里程碑预计延迟 21 天。",
      "actionable": true
    }
  ],
  "riskReasons": [
    {
      "riskCode": "PROJECT_DELAY",
      "severity": "HIGH",
      "riskProbability": 0.65,
      "riskImpact": 0.80,
      "estimatedProbabilityLoss": 0.11,
      "evidenceIds": ["evidence-102"],
      "ownerPersonId": "person-21",
      "recommendedActionIds": ["action-501"]
    }
  ],
  "recommendedActions": ["action-501"],
  "dataQuality": {
    "completeness": 0.86,
    "missingFeatures": ["customer_budget_fit"],
    "status": "PARTIAL"
  }
}
```

### 7.2 解释接口

```http
GET /api/opportunities/{opportunityId}/intelligence/win-probability/explanation
```

支持按 `forecastSnapshotId` 查询，返回当时的特征、贡献和证据，而不是使用当前字段重新解释历史结果。

### 7.3 情景模拟接口

```http
POST /api/opportunity-intelligence/win-probability:simulate
```

用途是回答：“如果本周完成某个 `Action`，赢单概率可能如何变化？”

约束：

- 模拟结果标记为 `SIMULATION`，不写入当前有效预测；
- 只能模拟允许的特征变化，不能直接输入目标概率；
- 返回变化最大的因素、假设条件和不确定性；
- 若模拟会创建真实 `Action`，必须另走审批或确认流程。

## 8. 刷新、反馈与治理

### 8.1 触发刷新

以下事件触发重新计算：

| 事件 | 主要影响 |
| --- | --- |
| `OpportunityStageChanged` | 阶段基线、阶段停留 |
| `OpportunityAmountChanged` | 金额稳定性、预算匹配 |
| `ActionCompleted` | 活跃度、下一步承诺、关系信号 |
| `ActionOverdue` | 失活和执行风险 |
| `ProjectMilestoneChanged` | 项目成熟度和延期风险 |
| `PersonRoleChanged` | 决策链覆盖 |
| `CustomerSignalReceived` | 客户互动趋势和意向 |

高影响事件即时重算；普通事件进入短批处理窗口；无事件商机每日检查一次是否过期。

### 8.2 人工反馈

销售可以：

- 接受或质疑某个影响因素；
- 标记风险为已处理或误报；
- 修正关键事实；
- 在商机结案后确认实际输赢。

这些行为写入 `OpportunityPredictionFeedback`，不能删除或覆盖原始
`OpportunityForecastSnapshot`。

### 8.3 最小验收标准

- [ ] 对给定 `Opportunity` 返回 `[0,1]` 内的赢单概率。
- [ ] 每个概率绑定 `model_version_id`、`as_of_time` 和特征快照。
- [ ] 正向、负向因素均能引用具体 `Evidence`。
- [ ] 风险原因可映射到 `risk_code`、严重度、责任人和建议 `Action`。
- [ ] 缺失数据降低 `confidence`，不被默认为“没有风险”。
- [ ] 历史预测可按快照还原，不能用当前字段替代历史输入。
- [ ] 模拟结果不污染当前生效预测。
- [ ] 不修改已有 `Opportunity Ontology`。

## 9. 落地顺序

1. 先用 `stage_baseline + Opportunity + Action` 实现可解释的基础概率。
2. 接入 `Customer` 和 `Person`，补齐历史关系、决策链和互动信号。
3. 接入 `Project`，处理进度、预算和时间约束。
4. 增加风险原因、证据和 Next Best Action 闭环。
5. 累积足够结案样本后进行概率校准，再评估 ML 模型是否带来真实收益。

核心取舍是：先让销售能理解和纠正预测，再追求模型复杂度。对用户而言，低置信度的“可解释 58%”比没有依据的“精确 61.37%”更可用。
