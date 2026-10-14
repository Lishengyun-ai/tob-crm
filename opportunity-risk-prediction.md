# Opportunity Risk Prediction

## 1. 目标与边界

本能力识别商机当前最可能影响赢单、成交时间或收入实现的风险，并输出：

- `risk_level`
- `risk_type`
- `risk_reason`
- `recommended_action`

输入来自：

- `Opportunity`
- `Customer`
- `Project`
- `Action`

风险预测结果通过新增 `OpportunityRiskPrediction` Entity 保存，不修改已有 `Opportunity Ontology`，也不直接覆盖原商机风险字段。

## 2. OpportunityRiskPrediction Entity

一条记录表示某个商机在某个预测时点的一类风险判断。风险历史追加保存，当前风险通过投影读取。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `risk_prediction_id` | ID | 是 | 风险预测 ID |
| `opportunity_id` | ID | 是 | 引用 `Opportunity` |
| `customer_id` | ID | 否 | 引用 `Customer` |
| `project_id` | ID | 否 | 引用 `Project` |
| `as_of_time` | DateTime | 是 | 风险预测截面 |
| `model_version_id` | ID | 是 | 风险规则或模型版本 |
| `risk_level` | Enum | 是 | `LOW`、`MEDIUM`、`HIGH`、`CRITICAL` |
| `risk_type` | Enum | 是 | 风险类型编码 |
| `risk_reason` | Text | 是 | 基于证据生成的风险原因 |
| `risk_probability` | Decimal(0,1) | 是 | 风险成立或持续概率 |
| `impact_scope` | Enum | 是 | `WIN`、`CLOSE_DATE`、`REVENUE`、`DATA_QUALITY` |
| `impact_score` | Decimal(0,1) | 是 | 对业务结果的影响程度 |
| `recommended_action` | Text | 是 | 面向业务的建议动作 |
| `recommended_action_type` | Enum | 是 | 复用 `Action` 类型 |
| `recommended_action_id` | ID | 否 | 已创建的 `Action` 或草稿动作 |
| `owner_person_id` | ID | 否 | 风险责任人，引用 `Person` |
| `evidence_ids` | Array<ID> | 是 | 支撑风险的证据 ID |
| `status` | Enum | 是 | `OPEN`、`ACKNOWLEDGED`、`MITIGATING`、`RESOLVED`、`FALSE_POSITIVE` |
| `confidence` | Decimal(0,1) | 是 | 风险判断置信度 |
| `created_at` | DateTime | 是 | 创建时间 |

### 2.1 风险类型

| `risk_type` | 触发重点 | 典型影响 |
| --- | --- | --- |
| `STALE_ACTIVITY` | 最近长期没有有效 `Action` | 赢单、成交时间 |
| `DECISION_MAKER_GAP` | 客户决策链不完整 | 赢单 |
| `PROJECT_DELAY` | 项目里程碑或目标日期延期 | 成交时间、收入 |
| `BUDGET_UNCONFIRMED` | 客户预算未确认或不足 | 赢单、收入 |
| `CUSTOMER_ENGAGEMENT_DROP` | 客户响应和互动下降 | 赢单、成交时间 |
| `COMPETITION` | 竞品、比价或替换信号 | 赢单、收入 |
| `PRICE_PRESSURE` | 折扣、价格审批或毛利压力 | 赢单、收入 |
| `SCOPE_UNSTABLE` | 项目范围频繁变化 | 成交时间、收入 |
| `PRODUCT_MISMATCH` | 方案不能覆盖项目需求 | 赢单、收入 |
| `NEXT_STEP_MISSING` | 没有客户确认的下一步 | 赢单、成交时间 |
| `DATA_QUALITY` | 关键事实缺失、过期或冲突 | 所有预测 |

## 3. 输入特征

### 3.1 Opportunity

| Feature Code | 计算口径 | 风险信号 |
| --- | --- | --- |
| `opportunity.stage_age_ratio` | 当前阶段停留 / 历史 P50 | 阶段停滞 |
| `opportunity.amount_change_rate` | 近 90 天金额变更次数 | 范围或预算不稳定 |
| `opportunity.stage_prerequisite_gap` | 当前阶段未满足条件数 | 推进阻塞 |
| `opportunity.competitive_signal` | 已确认竞争信号 | 竞争风险 |
| `opportunity.data_completeness` | 关键字段完整比例 | 数据质量风险 |

### 3.2 Customer

| Feature Code | 计算口径 | 风险信号 |
| --- | --- | --- |
| `customer.response_latency_trend` | 客户响应时间趋势 | 互动下降 |
| `customer.purchase_cycle_overrun` | 当前周期 / 客户历史 P50 | 采购延误 |
| `customer.budget_fit` | 商机金额 / 客户历史能力 | 预算风险 |
| `customer.decision_chain_coverage` | 已覆盖关键角色比例 | 决策人缺口 |
| `customer.relationship_strength` | 关键关系有效强度 | 关系脆弱 |

### 3.3 Project

| Feature Code | 计算口径 | 风险信号 |
| --- | --- | --- |
| `project.milestone_delay_days` | 实际进度 - 计划进度 | 项目延期 |
| `project.critical_path_risk` | 关键路径受阻节点数 | 项目延期 |
| `project.scope_change_count_90d` | 近 90 天范围变更次数 | 范围不稳定 |
| `project.budget_confirmation_status` | 预算确认状态 | 预算风险 |
| `project.requirement_coverage` | 已确认需求覆盖比例 | 产品匹配风险 |

### 3.4 Action

| Feature Code | 计算口径 | 风险信号 |
| --- | --- | --- |
| `action.days_since_last_effective` | 距最近有效动作天数 | 商机失活 |
| `action.overdue_rate_90d` | 逾期动作 / 计划动作 | 执行风险 |
| `action.next_step_commitment` | 是否有客户确认的下一步 | 无下一步风险 |
| `action.positive_outcome_rate` | 正向结果 / 有结果动作 | 推进质量 |
| `action.unresolved_objection_count` | 未关闭异议数量 | 赢单风险 |

## 4. 风险计算

### 4.1 风险等级

```text
risk_score
  = risk_probability × impact_score × evidence_reliability

risk_level:
  LOW       if risk_score < 0.20
  MEDIUM    if 0.20 <= risk_score < 0.45
  HIGH      if 0.45 <= risk_score < 0.70
  CRITICAL  if risk_score >= 0.70
```

高影响风险可以直接升级。例如缺少最终决策人通常属于 `HIGH`，即使当前暂时没有明确输单证据，也不能因为风险概率尚未很高而降为低风险。

### 4.2 规则与模型取舍

第一阶段采用规则与统计基线：

- 规则用于明确、可审计的触发条件；
- 历史数据用于估计风险概率和阈值；
- 后续有足够标签后再引入 ML，但必须保留触发特征和证据。

这样销售可以直接看到风险为什么产生，并能通过执行 `recommended_action` 验证风险是否下降。

## 5. 风险原因与建议动作

### 5.1 原因格式

`risk_reason` 必须包含三部分：

```text
事实 + 偏离/阈值 + 可能业务影响
```

示例：

> 过去 28 天没有完成有效客户动作，已超过该阶段历史 P80 的 14 天；商机可能进入失活状态并推迟成交。

不能只返回“客户意向弱”或“存在延期风险”等无法验证的结论。

### 5.2 建议动作映射

| 风险类型 | `recommended_action` | `recommended_action_type` |
| --- | --- | --- |
| `STALE_ACTIVITY` | 与客户确认下一次会议和决策节点 | `CUSTOMER_MEETING` |
| `DECISION_MAKER_GAP` | 请求现有联系人引荐预算或最终决策人 | `STAKEHOLDER_MAPPING` |
| `PROJECT_DELAY` | 与项目方重新确认关键路径和采购窗口 | `PROJECT_REVIEW` |
| `BUDGET_UNCONFIRMED` | 核实预算来源、审批状态和替代范围 | `BUDGET_CONFIRMATION` |
| `COMPETITION` | 获取竞品信息并组织差异化方案评审 | `COMPETITIVE_REVIEW` |
| `PRICE_PRESSURE` | 量化价值并提交价格/折扣审批 | `PRICING_REVIEW` |
| `SCOPE_UNSTABLE` | 固化项目范围和变更边界 | `SCOPE_CONFIRMATION` |
| `PRODUCT_MISMATCH` | 补充或调整产品方案 | `SOLUTION_REVIEW` |
| `NEXT_STEP_MISSING` | 生成并确认下一步日期、参与人和输出物 | `NEXT_STEP_CONFIRMATION` |
| `DATA_QUALITY` | 补齐并核验缺失事实 | `DATA_VERIFICATION` |

建议动作默认创建为待确认的 `Action` 草稿；对外沟通、价格承诺和合同相关动作必须审批。

## 6. Agent 接口

### 6.1 风险预测接口

```http
POST /api/opportunity-intelligence/risk:predict
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "opportunity-risk-v1",
  "includeEvidence": true,
  "createRecommendedActionDraft": true,
  "idempotencyKey": "risk-opp-1001-20261014"
}
```

响应：

```json
{
  "runId": "run-9301",
  "opportunityId": "opp-1001",
  "predictions": [
    {
      "riskPredictionId": "risk-pred-3001",
      "riskLevel": "HIGH",
      "riskType": "DECISION_MAKER_GAP",
      "riskReason": "已识别技术联系人，但未识别预算或最终决策人，当前决策链覆盖率为 0.50。",
      "riskProbability": 0.68,
      "impactScope": "WIN",
      "impactScore": 0.82,
      "recommendedAction": "请求现有联系人引荐预算或最终决策人。",
      "recommendedActionType": "STAKEHOLDER_MAPPING",
      "recommendedActionId": "action-701",
      "evidenceIds": ["evidence-301", "evidence-302"],
      "confidence": 0.79,
      "status": "OPEN"
    }
  ],
  "summary": {
    "riskLevel": "HIGH",
    "openRiskCount": 2,
    "criticalRiskCount": 0
  }
}
```

### 6.2 风险复核接口

```http
GET  /api/opportunities/{opportunityId}/intelligence/risks
POST /api/opportunity-intelligence/risk-predictions/{riskPredictionId}:acknowledge
POST /api/opportunity-intelligence/risk-predictions/{riskPredictionId}:resolve
POST /api/opportunity-intelligence/risk-predictions/{riskPredictionId}:false-positive
```

风险关闭或标记误报必须记录用户、时间、说明和新证据；不能通过重新预测直接删除历史风险。

## 7. 刷新与治理

### 7.1 触发事件

| 事件 | 主要风险 |
| --- | --- |
| `OpportunityStageChanged` | 阶段停滞、准入缺口 |
| `OpportunityAmountChanged` | 预算、价格、范围 |
| `ProjectMilestoneChanged` | 项目延期 |
| `ProjectScopeChanged` | 范围不稳定、产品匹配 |
| `ActionCompleted` | 互动、下一步、异议 |
| `ActionOverdue` | 失活、执行风险 |
| `CustomerSignalReceived` | 客户互动、竞争、预算 |

高影响事件立即更新；普通事件进入短批处理窗口；没有事件时每日检查风险是否过期。

### 7.2 风险合并

同一 `opportunity_id + risk_type` 在未关闭时合并更新，不重复堆积相同风险。只有以下情况才创建新的预测版本：

- 风险原因事实发生变化；
- 风险等级变化；
- 风险责任人或建议动作变化；
- 模型版本变化。

### 7.3 权限与自动化边界

- 查询风险和生成内部建议属于低风险操作；
- 分配责任人、创建内部 `Action` 草稿需要规则校验；
- 对外联系、价格折扣、合同承诺和批量更新必须审批；
- Agent 只能引用有证据的风险，不能用生成式文本凭空制造风险。

## 8. 验收标准

- [ ] 创建 `OpportunityRiskPrediction` Entity。
- [ ] 输入覆盖 `Opportunity`、`Customer`、`Project`、`Action`。
- [ ] 输出 `risk_level`、`risk_type`、`risk_reason`、`recommended_action`。
- [ ] 每个风险都有证据、置信度和影响范围。
- [ ] 风险等级由概率、影响和证据可靠度共同决定。
- [ ] 建议动作可映射到已有 `Action` 类型。
- [ ] 风险支持确认、缓解、关闭和误报状态。
- [ ] 相同风险在未关闭时合并，不重复创建。
- [ ] 历史预测追加保存，不覆盖原始判断。
- [ ] 不修改已有 `Opportunity Ontology`。

