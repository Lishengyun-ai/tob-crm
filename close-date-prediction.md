# Close Date Prediction

## 1. 目标与边界

本能力预测商机最可能成交的时间，并回答两个经营问题：

- 预计什么时候成交？
- 延期的可能性有多大，主要由什么造成？

输入来自四类事实：

- `Opportunity Stage`
- `Project Timeline`
- `Customer Purchase Cycle`
- `Historical Opportunity`

输出写入 `Opportunity Intelligence` 扩展层，不修改已有 `Opportunity Ontology`，不覆盖
`Opportunity` 中的人工预计日期。

## 2. 输出契约

| 输出 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `expected_close_date` | Date | 是 | 当前最可能成交日期 |
| `close_date_p50` | Date | 是 | 50% 概率覆盖日期，用于中位预测 |
| `close_date_p80` | Date | 是 | 80% 概率覆盖日期，用于保守计划 |
| `delay_probability` | Decimal(0,1) | 是 | 相对基准成交日期发生延期的概率 |
| `expected_delay_days` | Integer | 是 | 期望延期天数，可为 0 |
| `confidence` | Decimal(0,1) | 是 | 对日期预测可靠性的判断 |
| `date_status` | Enum | 是 | `READY`、`PARTIAL`、`INSUFFICIENT_DATA`、`STALE` |
| `as_of_time` | DateTime | 是 | 预测截面时间 |
| `model_version_id` | ID | 是 | 日期模型版本 |
| `delay_reasons` | Array | 是 | 延期原因及证据 |

`expected_close_date` 是行动计划的主日期；`close_date_p80` 用于资源、交付和收入预测，不能把
P80 当成最可能日期。

## 3. 日期语义

### 3.1 四个日期概念

| 概念 | 来源 | 作用 |
| --- | --- | --- |
| `forecast_as_of_date` | 系统时间 | 本次预测的截面 |
| `stage_baseline_date` | 当前阶段 + 历史商机 | 不考虑外部延期时的基准日期 |
| `project_constraint_date` | 项目时间线 | 项目采购、开工或预算窗口形成的外部约束 |
| `expected_close_date` | 模型输出 | 综合阶段、项目、客户周期和历史相似商机后的日期 |

日期计算必须先确定预测事件是“签约/订单确认”，还是“项目开始/交付”。本设计默认预测
`Opportunity` 的赢单或订单确认日期；如果业务使用不同的成交定义，应通过
`model_version.target_definition` 固定口径。

### 3.2 延期定义

```text
baseline_close_date = stage_baseline_date + project_constraint_adjustment
delay_days = max(0, expected_close_date - baseline_close_date)
delay_probability = P(actual_close_date > baseline_close_date)
```

延期不是“距离今天很远”，而是相对当前商机合理基准日期发生后移。这样可以区分正常较长
采购周期和真正的推进失速。

## 4. 输入特征

### 4.1 Opportunity Stage

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `stage.current_code` | 当前阶段 | 确定阶段基线 |
| `stage.age_days` | 当前日期 - 进入阶段日期 | 判断阶段停留 |
| `stage.remaining_days_p50` | 当前阶段历史剩余天数中位数 | 基准剩余时间 |
| `stage.remaining_days_p80` | 当前阶段历史剩余天数 P80 | 保守剩余时间 |
| `stage.transition_velocity_90d` | 近 90 天阶段推进次数 / 天数 | 推进速度 |
| `stage.stall_ratio` | 当前阶段停留 / 阶段 P50 | 停滞程度 |
| `stage.prerequisite_completion` | 当前阶段准入条件完成比例 | 是否具备进入下一阶段条件 |

阶段停留超过 P50 不直接判定延期；只有与项目约束、采购周期或阶段准入缺口同时出现时，才提高
`delay_probability`。

### 4.2 Project Timeline

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `project.target_date_gap_days` | 项目目标日期 - 预测截面日期 | 外部可成交时间窗 |
| `project.milestone_delay_days` | 实际里程碑日期 - 计划日期 | 项目进度偏差 |
| `project.timeline_slippage_ratio` | 延期天数 / 原计划周期 | 延期规模 |
| `project.procurement_window_start` | 采购窗口开始日期 | 最早可成交约束 |
| `project.procurement_window_end` | 采购窗口结束日期 | 最晚可成交约束 |
| `project.next_milestone_gap_days` | 下一关键里程碑距离 | 近期推进锚点 |
| `project.timeline_change_count_90d` | 近 90 天时间线变更次数 | 计划稳定性 |
| `project.critical_path_risk` | 关键路径节点风险汇总 | 项目延期概率 |

项目时间线应形成日期约束：如果采购窗口尚未开启，预测日期不能早于窗口开始；如果窗口已经
关闭且没有新计划，必须生成高严重度延期原因。

### 4.3 Customer Purchase Cycle

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `customer.purchase_cycle_days_p50` | 客户历史从商机确认到成交的中位天数 | 客户基准周期 |
| `customer.purchase_cycle_days_p80` | 客户历史采购周期 P80 | 保守周期 |
| `customer.current_cycle_elapsed_days` | 当前商机已运行采购周期 | 周期进度 |
| `customer.cycle_overrun_ratio` | 已用周期 / 客户 P50 | 周期超限 |
| `customer.approval_steps_p50` | 客户历史审批步骤中位数 | 审批耗时 |
| `customer.response_latency_days_p50` | 客户关键联系人历史响应时间 | 沟通耗时 |
| `customer.procurement_seasonality` | 月度/季度采购季节模式 | 季节性约束 |
| `customer.budget_release_date_gap` | 预算释放日期与当前日期差 | 预算窗口 |

客户周期不足 3 个有效历史样本时，回退到客户细分、区域或行业的分层基线，并降低
`confidence`。

### 4.4 Historical Opportunity

历史商机必须按预测时点可获得的信息构造，不能把结案后的事实泄漏到训练或实时预测中。

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `historical.stage_duration_p50` | 相同阶段历史停留中位数 | 阶段基线 |
| `historical.close_lag_p50` | 预计日期到实际成交日期的中位偏差 | 预测偏差校正 |
| `historical.delay_rate` | 同类商机延期数 / 已结案数 | 延期基线 |
| `historical.similar_project_cycle_p50` | 相似项目成交周期中位数 | 项目相似性基线 |
| `historical.same_customer_cycle_p50` | 同客户已结案商机周期 | 客户个性化基线 |
| `historical.stage_transition_days_p50` | 阶段之间历史转换耗时 | 剩余时间估计 |
| `historical.forecast_bias` | 历史预测日期与实际日期偏差 | 校准修正 |
| `historical.sample_support` | 可用相似样本数量 | 置信度支持 |

相似商机至少考虑客户、项目类型、当前阶段、金额区间和采购模式；不能只按金额相似匹配。

## 5. 预测算法

### 5.1 推荐的可解释混合模型

```text
stage_baseline_date
  = forecast_as_of_date
  + stage.remaining_days_p50

customer_adjustment
  = customer.purchase_cycle_adjustment
  + customer.approval_adjustment
  + customer.seasonality_adjustment

project_adjustment
  = project.milestone_delay_adjustment
  + project.critical_path_adjustment
  + project.procurement_window_adjustment

historical_adjustment
  = similar_opportunity_close_lag
  + historical.forecast_bias

expected_close_date
  = max(
      stage_baseline_date
      + customer_adjustment
      + project_adjustment
      + historical_adjustment,
      project.procurement_window_start
    )
```

`project.procurement_window_end` 之后仍无成交计划时，不强行把日期截断到窗口末日，而是：

1. 将日期推到下一个已确认采购窗口；
2. 提高 `delay_probability`；
3. 生成 `PROCUREMENT_WINDOW_MISSED` 延期原因。

### 5.2 延期概率

```text
delay_probability
  = calibrate(
      P(stage_stall)
      + P(project_slippage)
      + P(customer_cycle_overrun)
      + P(missing_prerequisites)
      - confirmed_next_step_effect
    )
```

实现时应避免简单相加造成超过 1.0；可以在 logit 空间计算，或使用校准后的分类模型。

建议的延期触发权重：

| 信号 | 初始作用 |
| --- | --- |
| 阶段停留超过 P80 | 高 |
| 项目关键路径已经延期 | 高 |
| 客户采购周期超过 P50 且没有下一步承诺 | 高 |
| 采购窗口即将关闭 | 高 |
| 关键阶段准入条件缺失 | 中/高 |
| 客户响应延迟上升 | 中 |
| 存在已确认的下一步日期 | 降低延期概率 |

### 5.3 日期区间与置信度

- `close_date_p50`：日期分布中位数；
- `close_date_p80`：日期分布的 80% 覆盖点；
- `expected_close_date`：结合业务损失函数后的计划日期，通常接近 P50，但允许受项目硬约束调整；
- `confidence`：日期分布稳定性、样本量、数据新鲜度和时间线完整度的综合结果。

推荐：

```text
confidence
  = model_reliability
  × timeline_completeness
  × historical_sample_support
  × freshness_score
  × definition_consistency
```

如果预测日期区间过宽，即使点预测日期存在，也必须降低 `confidence`。

## 6. 延期原因

### 6.1 原因分类

| `delay_code` | 触发条件 | 业务解释 |
| --- | --- | --- |
| `STAGE_STALL` | 当前阶段超过 P80 且无推进证据 | 阶段推进停滞 |
| `MISSING_STAGE_PREREQUISITE` | 阶段准入条件未完成 | 还不具备进入下一阶段的条件 |
| `PROJECT_MILESTONE_SLIPPAGE` | 关键里程碑延期 | 项目进度推迟成交 |
| `PROCUREMENT_WINDOW_NOT_OPEN` | 采购窗口尚未开始 | 正常等待外部窗口 |
| `PROCUREMENT_WINDOW_MISSED` | 采购窗口已关闭且无新计划 | 需要等待下一窗口 |
| `CUSTOMER_CYCLE_OVERRUN` | 已超过客户历史采购 P80 | 客户采购周期异常变长 |
| `CUSTOMER_APPROVAL_DELAY` | 审批步骤或响应耗时上升 | 客户内部决策慢 |
| `TIMELINE_UNSTABLE` | 近 90 天多次变更项目日期 | 项目计划不稳定 |
| `HISTORICAL_BIAS` | 同类商机存在系统性晚于预计日期 | 历史预测偏早 |
| `INSUFFICIENT_DATA` | 缺少阶段、时间线或历史样本 | 无法可靠判断 |

### 6.2 延期原因对象

每条原因至少保存：

| 字段 | 说明 |
| --- | --- |
| `delay_code` | 稳定原因编码 |
| `severity` | `LOW`、`MEDIUM`、`HIGH`、`CRITICAL` |
| `contribution_days` | 对日期后移的预计天数 |
| `reason_probability` | 该原因成立或持续的概率 |
| `evidence_ids` | 项目时间线、阶段事件或历史商机证据 |
| `owner_person_id` | 负责验证或缓解的人 |
| `recommended_action_id` | 关联的 `Action` |
| `explanation` | 面向业务的简短描述 |

自然语言原因只能由已结构化的证据生成。例如不能只返回“客户意愿不强”，必须说明对应的
响应延迟、采购周期超限或缺失下一步承诺。

## 7. Agent 接口

### 7.1 预测接口

```http
POST /api/opportunity-intelligence/close-date:predict
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "close-date-v1",
  "includeDelayReasons": true,
  "includeEvidence": true,
  "idempotencyKey": "close-date-opp-1001-20261014"
}
```

响应：

```json
{
  "runId": "run-9201",
  "opportunityId": "opp-1001",
  "forecastSnapshotId": "forecast-7201",
  "prediction": {
    "expectedCloseDate": "2026-12-18",
    "closeDateP50": "2026-12-18",
    "closeDateP80": "2027-01-15",
    "delayProbability": 0.42,
    "expectedDelayDays": 14,
    "confidence": 0.76,
    "dateStatus": "READY",
    "asOfTime": "2026-10-14T09:00:00+08:00"
  },
  "delayReasons": [
    {
      "delayCode": "PROJECT_MILESTONE_SLIPPAGE",
      "severity": "HIGH",
      "contributionDays": 21,
      "reasonProbability": 0.65,
      "evidenceIds": ["evidence-201"],
      "ownerPersonId": "person-21",
      "recommendedActionId": "action-601",
      "explanation": "项目关键里程碑预计延迟 21 天。"
    }
  ],
  "features": {
    "stageRemainingDaysP50": 28,
    "customerPurchaseCycleDaysP50": 35,
    "projectMilestoneDelayDays": 21,
    "historicalSampleSupport": 18
  },
  "missingInputs": []
}
```

### 7.2 解释接口

```http
GET /api/opportunities/{opportunityId}/intelligence/close-date/explanation
```

支持查询当前或指定 `forecastSnapshotId` 的：

- 日期基准是如何计算的；
- 哪些输入把日期向后推移；
- 延期概率由哪些信号组成；
- 哪些证据仍需销售确认。

### 7.3 情景模拟接口

```http
POST /api/opportunity-intelligence/close-date:simulate
```

示例问题：

> 如果项目里程碑按新日期完成，且客户本周完成审批，预计成交日期会怎样变化？

模拟结果必须：

- 标记 `SIMULATION`，不改变当前正式预测；
- 明确列出假设的时间线和客户周期变化；
- 返回 `expected_close_date`、`delay_probability` 和 `confidence` 的变化；
- 如果假设对应真实业务动作，提供待确认的 `Action` 草稿，而不是自动执行。

## 8. 事件刷新与数据治理

### 8.1 刷新事件

| 事件 | 影响 |
| --- | --- |
| `OpportunityStageChanged` | 阶段基准和剩余时间 |
| `ProjectMilestoneChanged` | 里程碑偏差和关键路径 |
| `ProjectTargetDateChanged` | 项目硬约束 |
| `CustomerPurchaseCycleUpdated` | 客户周期基线 |
| `CustomerApprovalStepCompleted` | 审批剩余时间 |
| `HistoricalOpportunityClosed` | 历史样本和校准 |
| `ActionCompleted` | 下一步承诺和阶段推进 |
| `ActionOverdue` | 延期风险 |

高影响事件立即重算；普通事件进入短批处理窗口。数据源暂时不可用时，保留上一份预测并标记
`STALE`，不得把日期静默置空或改成当前日期。

### 8.2 时间穿越保护

- 训练特征只能使用历史商机在当时已经可见的字段和事件；
- 当前预测只读取 `as_of_time` 之前的项目、客户和阶段事实；
- 结案后的实际成交日期只能作为标签，不能作为同一预测的输入；
- 所有特征保存 `feature_as_of_time` 和来源 ID，支持回放。

### 8.3 不确定性处理

以下情况必须降低 `confidence` 或返回 `INSUFFICIENT_DATA`：

- 当前阶段缺少进入时间；
- 项目没有目标日期、关键里程碑或采购窗口；
- 客户没有足够有效采购历史；
- 历史商机的成交定义不一致；
- 项目时间线存在相互冲突的版本；
- 预测区间超过业务允许的最大宽度。

## 9. 最小验收标准

- [ ] 返回 `expected_close_date`、`delay_probability`、`confidence`。
- [ ] 日期预测绑定 `as_of_time` 和 `model_version_id`。
- [ ] 明确区分 P50、P80 和最可能成交日期。
- [ ] 延期概率定义为相对基准日期的后移概率。
- [ ] 输入覆盖 `Opportunity Stage`、`Project Timeline`、`Customer Purchase Cycle` 和 `Historical Opportunity`。
- [ ] 每个延期原因都能追溯到证据和影响天数。
- [ ] 缺失或冲突数据会降低置信度，不会被默认为正常推进。
- [ ] 历史预测可按快照复盘，不使用当前字段重写过去的输入。
- [ ] 情景模拟不污染正式预测。
- [ ] 不修改已有 `Opportunity Ontology`。

## 10. 落地顺序

1. 使用阶段 P50、项目目标日期和客户采购周期 P50，完成可解释日期基线。
2. 接入历史商机的 P50/P80、成交偏差和延期率，形成日期区间。
3. 增加项目关键路径、采购窗口和客户审批步骤，计算延期概率。
4. 接入延期原因、证据和缓解 `Action`，形成闭环。
5. 用实际成交日期做校准，监测 P50/P80 覆盖率和系统性提前或滞后。

核心取舍是：成交时间预测优先服务排期和风险管理，因此必须同时返回点日期、保守日期、延期概率和置信度；只返回一个日期会让用户无法区分“正常长周期”和“正在延期”。
