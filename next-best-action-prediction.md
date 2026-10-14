# Next Best Action Prediction

## 1. 目标与边界

本能力根据商机当前状态，推荐销售下一步最值得执行的动作，回答：

- 现在最应该做什么？
- 为什么这个动作优先？
- 做完后预计改善什么结果？

输入来自：

- `Opportunity`
- `Risk`，包括已有 `OpportunityRisk` 和 `OpportunityRiskPrediction`
- `Person`
- `Action History`

推荐结果写入 Intelligence 扩展层或生成待确认的 `Action` 草稿，不修改已有
`Opportunity Ontology`，不自动替销售对外承诺。

## 2. 输出契约

### 2.1 推荐动作

每条推荐至少包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `recommendation_id` | ID | 推荐记录 ID |
| `opportunity_id` | ID | 商机 ID |
| `action_type` | Enum | 复用已有 `Action` 类型 |
| `action_title` | String | 动作标题 |
| `action_description` | Text | 可执行的动作描述 |
| `priority` | Enum | `P0`、`P1`、`P2`、`P3` |
| `priority_score` | Decimal(0,1) | 排序分数 |
| `expected_impact` | JSON | 预计对赢单、成交时间或收入的影响 |
| `reason` | Text | 推荐原因 |
| `risk_ids` | Array<ID> | 需要处理的风险 |
| `person_ids` | Array<ID> | 建议涉及的客户或内部人员 |
| `evidence_ids` | Array<ID> | 支撑推荐的证据 |
| `due_at` | DateTime | 建议完成时间 |
| `approval_required` | Boolean | 是否需要审批 |
| `status` | Enum | `RECOMMENDED`、`DRAFTED`、`ACCEPTED`、`REJECTED`、`COMPLETED`、`EXPIRED` |
| `confidence` | Decimal(0,1) | 推荐可靠性 |

### 2.2 优先级

| 优先级 | 使用条件 | 用户影响 |
| --- | --- | --- |
| `P0` | 关键风险正在恶化，延迟执行会明显降低赢单概率 | 立即处理或升级 |
| `P1` | 能直接解除阶段阻塞或关键决策缺口 | 本周内完成 |
| `P2` | 能提升关系、证据或方案质量，但不构成立即阻塞 | 纳入近期计划 |
| `P3` | 信息补齐、整理或低影响优化 | 有空处理 |

优先级不是销售人员等级，而是动作对当前商机结果的紧迫度和影响度。

### 2.3 预计影响

`expected_impact` 至少支持以下字段：

| 字段 | 说明 |
| --- | --- |
| `win_probability_delta` | 执行动作后预计赢单概率变化 |
| `delay_probability_delta` | 延期概率预计变化 |
| `expected_revenue_delta` | 概率加权收入预计变化 |
| `risk_reduction` | 目标风险预计降低幅度 |
| `impact_horizon_days` | 预计在多少天内产生影响 |
| `impact_confidence` | 对预计影响的置信度 |

预计影响是情景估计，不是承诺结果。接口必须返回假设和证据。

## 3. 推荐对象 Entity

新增 `OpportunityNextBestActionRecommendation`，保存一次推荐及其依据。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `recommendation_id` | ID | 是 | 推荐 ID |
| `opportunity_id` | ID | 是 | 引用 `Opportunity` |
| `action_type` | String | 是 | 已有 `Action` 类型 |
| `action_template_id` | ID | 否 | 可复用动作模板 |
| `action_title` | String | 是 | 动作名称 |
| `action_description` | Text | 是 | 可执行内容 |
| `priority` | Enum | 是 | `P0` - `P3` |
| `priority_score` | Decimal(0,1) | 是 | 排序分数 |
| `expected_impact` | JSON | 是 | 预计业务影响 |
| `trigger_type` | Enum | 是 | `RISK`、`STAGE`、`STALE_ACTIVITY`、`MISSING_EVIDENCE`、`CUSTOMER_SIGNAL`、`MANUAL_REQUEST` |
| `risk_ids` | Array<ID> | 否 | 触发风险 |
| `person_ids` | Array<ID> | 否 | 涉及人员 |
| `evidence_ids` | Array<ID> | 是 | 推荐依据 |
| `action_history_ids` | Array<ID> | 否 | 相似历史动作 |
| `owner_person_id` | ID | 否 | 建议执行人 |
| `due_at` | DateTime | 否 | 建议截止时间 |
| `approval_required` | Boolean | 是 | 是否需要审批 |
| `status` | Enum | 是 | 推荐生命周期 |
| `confidence` | Decimal(0,1) | 是 | 推荐置信度 |
| `model_version_id` | ID | 是 | 推荐规则或模型版本 |
| `as_of_time` | DateTime | 是 | 推荐截面 |

## 4. 输入特征

### 4.1 Opportunity

| Feature Code | 计算口径 | 推荐意义 |
| --- | --- | --- |
| `opportunity.stage_code` | 当前商机阶段 | 决定阶段动作模板 |
| `opportunity.stage_prerequisite_gap` | 未完成阶段条件数 | 推荐补齐阻塞条件 |
| `opportunity.win_probability` | 当前赢单概率 | 衡量提升空间 |
| `opportunity.days_to_expected_close` | 预计成交日 - 当前日期 | 决定动作时限 |
| `opportunity.amount_at_risk` | 受风险影响的收入金额 | 计算经济优先级 |

### 4.2 Risk

| Feature Code | 计算口径 | 推荐意义 |
| --- | --- | --- |
| `risk.open_high_count` | 未关闭高风险数量 | 提升动作优先级 |
| `risk.top_impact_score` | 最大风险影响分 | 先处理最大影响风险 |
| `risk.days_open` | 风险持续时间 | 判断是否升级 |
| `risk.owner_missing` | 是否没有责任人 | 推荐分派动作 |
| `risk.recommended_action_gap` | 风险是否已有有效动作 | 避免重复推荐 |

### 4.3 Person

| Feature Code | 计算口径 | 推荐意义 |
| --- | --- | --- |
| `person.decision_maker_missing` | 是否缺最终决策人 | 推荐引荐或多线程动作 |
| `person.relationship_strength` | 现有关系强度 | 选择最可能打开关系的人 |
| `person.response_latency` | 联系人平均响应时间 | 选择沟通方式和时机 |
| `person.champion_signal` | 是否有客户内部倡导者 | 推荐让倡导者参与下一步 |
| `person.role_coverage_gap` | 技术、采购、业务、财务角色缺口 | 推荐补齐角色 |

### 4.4 Action History

| Feature Code | 计算口径 | 推荐意义 |
| --- | --- | --- |
| `action.last_effective_days` | 距最近有效动作天数 | 判断是否需要重新激活 |
| `action.overdue_rate_90d` | 近 90 天逾期率 | 避免推荐无法执行的动作 |
| `action.positive_outcome_rate` | 动作正向结果率 | 选择历史有效动作 |
| `action.response_rate_by_type` | 不同动作类型的响应率 | 选择更可能被接受的渠道 |
| `action.unresolved_commitment_count` | 未完成承诺数量 | 优先清理旧承诺 |
| `action.recently_recommended_types` | 近期已推荐动作类型 | 去重和冷却 |

## 5. 推荐算法

### 5.1 候选动作生成

候选动作按四类来源生成：

1. 风险缓解：处理 `HIGH` 或 `CRITICAL` 风险；
2. 阶段推进：补齐当前阶段准入条件；
3. 关系推进：覆盖决策人、采购人或内部倡导者；
4. 证据补齐：完成方案、样板、测试、预算或下一步承诺。

候选动作必须满足：有明确责任人、可观察完成结果、能绑定一个或多个证据或风险。

### 5.2 优先级评分

```text
priority_score
  = 0.30 × expected_win_impact
  + 0.25 × risk_reduction
  + 0.20 × urgency
  + 0.15 × executability
  + 0.10 × historical_effectiveness
  - duplication_penalty
```

其中：

- `expected_win_impact`：预计改善赢单概率；
- `risk_reduction`：预计降低当前风险的程度；
- `urgency`：距离成交或风险恶化的时间压力；
- `executability`：是否有合适人员、渠道和明确期限；
- `historical_effectiveness`：相似商机中该动作的历史有效性；
- `duplication_penalty`：近期已执行或已推荐同类动作的扣分。

排序后通过阈值映射到 `P0` - `P3`。评分权重应进入模型版本，不能散落在 Agent 提示词中。

### 5.3 推荐约束

- 同一商机最多返回 3 条主推荐，避免销售面对过多待办；
- `P0` 和 `P1` 必须有明确风险、阶段缺口或成交时间依据；
- 已完成、已拒绝或冷却期内的同类动作不重复推荐；
- 没有可验证影响的动作只能作为 `P3` 信息补齐动作；
- 推荐动作不得自动修改价格、折扣、合同或对外承诺；
- 推荐的目标必须与当前商机目标一致，不能为了提高活动数量而推荐无效动作。

## 6. 推荐模板

| 触发条件 | 推荐动作 | 预计影响 |
| --- | --- | --- |
| 缺少最终决策人 | 请求现有联系人引荐预算或最终决策人 | 降低 `DECISION_MAKER_GAP`，提高赢单概率 |
| 超过阶段 P80 未推进 | 召开阶段推进评审，确认阻塞条件 | 降低延期概率，推动阶段转换 |
| 项目里程碑延期 | 与项目方重排关键路径和采购窗口 | 降低成交日期后移风险 |
| 客户长期无响应 | 通过已有倡导者或新渠道重新建立联系 | 降低失活风险 |
| 预算未确认 | 核实预算来源、审批状态和范围替代方案 | 降低预算风险，稳定收入预测 |
| 产品需求未覆盖 | 组织方案评审并补充产品映射 | 降低产品匹配风险 |
| 竞品信号出现 | 获取竞品信息并组织差异化价值评审 | 降低竞争风险 |
| 没有客户确认的下一步 | 输出明确日期、参与人和交付物并请求确认 | 提高推进确定性 |
| 历史承诺未完成 | 清理逾期承诺并重新确认责任人和截止时间 | 降低执行信任风险 |

## 7. 预计影响计算

推荐动作的影响采用情景估计：

```text
expected_win_probability_delta
  = historical_action_effect
  × current_context_similarity
  × execution_probability

expected_revenue_delta
  = opportunity_potential_revenue
  × expected_win_probability_delta

expected_delay_probability_delta
  = -delay_risk_reduction
```

当缺少足够历史样本时，返回区间和低置信度，不伪造精确提升值。例如：

```json
{
  "winProbabilityDelta": {
    "low": 0.03,
    "expected": 0.08,
    "high": 0.14
  },
  "executionProbability": 0.72,
  "impactConfidence": 0.54,
  "assumptions": [
    "客户愿意在 7 天内安排预算负责人会议",
    "项目采购窗口不会再次变更"
  ]
}
```

## 8. Agent 接口

### 8.1 推荐接口

```http
POST /api/opportunity-intelligence/next-best-action:recommend
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "objective": "IMPROVE_WIN_PROBABILITY",
  "maxRecommendations": 3,
  "dueWithinDays": 14,
  "includeImpactSimulation": true,
  "createActionDraft": false,
  "idempotencyKey": "nba-opp-1001-20261014"
}
```

响应：

```json
{
  "runId": "run-9401",
  "opportunityId": "opp-1001",
  "recommendations": [
    {
      "recommendationId": "nba-4001",
      "actionType": "STAKEHOLDER_MAPPING",
      "actionTitle": "引荐预算决策人",
      "actionDescription": "请当前技术联系人引荐预算负责人，并确认下次采购评审时间。",
      "priority": "P1",
      "priorityScore": 0.84,
      "reason": "当前决策链覆盖率为 0.50，且预计成交时间已接近客户历史采购 P80。",
      "expectedImpact": {
        "winProbabilityDelta": {
          "low": 0.03,
          "expected": 0.08,
          "high": 0.14
        },
        "delayProbabilityDelta": -0.10,
        "expectedRevenueDelta": 192000,
        "impactConfidence": 0.54
      },
      "riskIds": ["risk-pred-3001"],
      "personIds": ["person-21", "person-22"],
      "evidenceIds": ["evidence-301", "evidence-401"],
      "ownerPersonId": "person-21",
      "dueAt": "2026-10-21T18:00:00+08:00",
      "approvalRequired": false,
      "status": "RECOMMENDED",
      "confidence": 0.79
    }
  ]
}
```

### 8.2 模拟接口

```http
POST /api/opportunity-intelligence/next-best-action:simulate
```

用于比较多个候选动作的预期影响，但模拟结果不创建真实 `Action`，也不改变正式预测快照。

### 8.3 执行接口

```http
POST /api/opportunity-intelligence/recommendations/{recommendationId}:accept
POST /api/opportunity-intelligence/recommendations/{recommendationId}:reject
POST /api/opportunity-intelligence/recommendations/{recommendationId}:create-action
```

`create-action` 只创建待执行或待审批的 `Action`，不会代表销售自动联系客户。

## 9. 生命周期与审计

```text
Recommended
  -> Accepted
  -> Action Drafted
  -> Action Completed
  -> Outcome Observed
```

每次推荐都应记录：

- 当时的商机状态、风险和动作历史摘要；
- 使用的模型版本和特征快照；
- 推荐动作、优先级和影响估计；
- 用户接受、拒绝或修改原因；
- 动作执行结果及对后续预测的实际影响。

这样才能评估“推荐是否真的推动了成交”，而不是只统计 Agent 生成了多少建议。

## 10. 验收标准

- [ ] 输入覆盖 `Opportunity`、`Risk`、`Person`、`Action History`。
- [ ] 输出推荐动作、优先级和预计影响。
- [ ] 推荐动作可映射到已有 `Action` 类型。
- [ ] 每条推荐都有原因、证据和目标风险或阶段缺口。
- [ ] 优先级综合考虑影响、风险、紧迫度、可执行性和历史有效性。
- [ ] 预计影响返回假设和置信度，不伪造精确结果。
- [ ] 同类动作有去重和冷却机制。
- [ ] 推荐最多返回有限数量的主动作，避免行动泛滥。
- [ ] 创建真实 `Action` 前保留确认和审批边界。
- [ ] 推荐、接受、执行和结果均可审计。
- [ ] 不修改已有 `Opportunity Ontology`。

