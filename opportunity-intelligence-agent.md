# Opportunity Intelligence Agent

## 1. 目标与边界

`Opportunity Intelligence Agent` 是商机智能预测的统一自然语言入口，负责把已有预测能力组织成可查询、可解释、可行动的回答。

支持四类能力：

1. 查询商机预测；
2. 分析赢单概率；
3. 识别和解释风险；
4. 推荐下一步行动。

Agent 读取 `Opportunity Intelligence` 的结构化预测、风险、证据和推荐结果，不直接凭空推断，也不修改已有 `Opportunity Ontology`。

## 2. 用户问题

### 2.1 最可能赢

```text
哪些商机最可能赢？
```

Agent 返回按 `win_probability` 排序的商机，同时展示金额、预计成交时间、置信度和主要正负因素。

### 2.2 风险最高

```text
哪些商机风险最高？
```

Agent 按风险严重度、风险影响金额、风险概率和风险新鲜度综合排序，不能只按风险数量排序。

### 2.3 下一步做什么

```text
下一步应该做什么？
```

Agent 根据当前商机、开放风险、阶段缺口、人员关系和动作历史，返回有限数量的可执行动作。

## 3. Agent 输入上下文

### 3.1 必要上下文

| 上下文 | 作用 |
| --- | --- |
| 当前用户和组织 | 权限、数据范围和责任区域 |
| 当前商机或筛选条件 | 确定查询对象 |
| `OpportunityIntelligenceProfile` | 当前预测总览 |
| `OpportunityForecastSnapshot` | 历史和当前预测 |
| `OpportunityRiskPrediction` / `OpportunityRisk` | 风险和风险状态 |
| `OpportunityNextBestActionRecommendation` | 推荐动作 |
| `OpportunityEvidence` | 解释和证据追溯 |
| `Action` 历史 | 动作执行情况和反馈 |
| `OpportunityAgentRun` | 本次调用审计 |

### 3.2 查询范围

Agent 必须明确当前查询范围：

- 全部有权限的商机；
- 当前用户负责的商机；
- 指定客户、项目、区域或团队；
- 指定金额、阶段、成交时间或风险等级；
- 指定时间截面的预测。

如果用户没有给出范围，默认使用当前用户有权限查看的开放商机，并在回答中标注范围。

## 4. 意图识别

### 4.1 意图枚举

| `intent` | 典型问题 | 主要工具 |
| --- | --- | --- |
| `RANK_WIN_PROBABILITY` | 哪些商机最可能赢？ | Win Probability Prediction |
| `ANALYZE_WIN_PROBABILITY` | 为什么这个商机只有 40%？ | 预测解释和证据 |
| `RANK_RISK` | 哪些商机风险最高？ | Opportunity Risk Prediction |
| `EXPLAIN_RISK` | 这个商机最大的风险是什么？ | 风险、证据和状态 |
| `RECOMMEND_NEXT_ACTION` | 下一步应该做什么？ | Next Best Action Prediction |
| `QUERY_FORECAST` | 本季度能完成多少收入？ | Revenue、Close Date、Win Probability |
| `COMPARE_OPPORTUNITIES` | A 和 B 哪个更值得投入？ | 多目标排序 |
| `SIMULATE_ACTION` | 做完这个动作会怎样？ | 情景模拟接口 |

### 4.2 参数抽取

Agent 从自然语言中抽取：

| 参数 | 示例 |
| --- | --- |
| `opportunity_id` | “商机 opp-1001” |
| `customer_id` | “某客户的商机” |
| `project_id` | “这个项目相关商机” |
| `owner_person_id` | “我负责的商机” |
| `stage` | “报价阶段” |
| `time_range` | “本季度”“未来 30 天” |
| `amount_range` | “金额超过 100 万” |
| `risk_level` | “高风险” |
| `top_k` | “列出前 5 个” |
| `objective` | “优先提高赢单率/收入/按时成交” |

不能可靠识别的关键范围参数，应使用默认范围并明确告知，而不是假设用户有权查看全部数据。

## 5. 核心回答能力

### 5.1 查询商机预测

回答至少包括：

- 商机名称和客户；
- `win_probability`；
- `expected_close_date`；
- `forecast_revenue`；
- `risk_level`；
- `confidence`；
- 相比上次预测的变化；
- 主要影响因素和证据。

示例结构：

```text
商机：华东园区项目
赢单概率：72%，较上次上升 8 个百分点
预计成交：2026-12-18，置信度 68%
预测收入：172.8 万 CNY
当前风险：高，项目关键里程碑预计延迟 21 天
主要正向因素：决策链覆盖率提升、客户已确认下一步评审
```

### 5.2 分析赢单概率

回答按正负因素分组：

```text
当前赢单概率：42%，置信度：61%

提升概率的因素：
- 客户过去同类项目有成交记录；
- 产品方案已覆盖主要项目需求。

拉低概率的因素：
- 尚未识别最终预算决策人；
- 近 21 天没有有效客户动作；
- 当前金额高于客户历史同类采购 P80。

结论：当前最值得先处理的是决策链缺口，而不是继续调整报价。
```

每个因素必须链接到 `factor_code`、`evidence_id` 或来源字段。

### 5.3 识别风险

风险回答按以下顺序组织：

1. 风险等级；
2. 风险类型；
3. 触发事实；
4. 可能影响；
5. 当前责任人和状态；
6. 建议处理动作。

示例：

```text
最高风险：DECISION_MAKER_GAP，HIGH
原因：已识别技术联系人，但尚未识别预算或最终决策人，决策链覆盖率为 50%。
影响：可能降低赢单概率，并使成交时间后移。
下一步：请现有联系人引荐预算负责人，截止本周五。
证据：evidence-301、evidence-302
```

### 5.4 推荐行动

Agent 最多返回 3 条主动作，每条包含：

- 动作内容；
- 优先级；
- 推荐原因；
- 责任人；
- 截止时间；
- 预计影响；
- 证据和目标风险；
- 是否需要审批。

推荐动作必须可执行、可观察和可复盘，不能只返回“加强跟进”“持续沟通”等空泛建议。

## 6. 工具编排

### 6.1 只读工具

```text
query_opportunity_forecast
explain_win_probability
list_opportunity_risks
explain_risk
list_next_best_actions
get_action_history
get_evidence
```

### 6.2 模拟工具

```text
simulate_win_probability_change
simulate_close_date_change
simulate_revenue_change
simulate_action_impact
```

模拟结果标记为 `SIMULATION`，不改变正式预测和业务对象。

### 6.3 写入工具

```text
create_action_draft
accept_recommendation
acknowledge_risk
resolve_risk
submit_prediction_feedback
```

写入工具必须：

- 记录 `OpportunityAgentRun`；
- 携带 `idempotencyKey`；
- 检查用户权限；
- 对外沟通、价格、折扣、合同和批量操作要求审批；
- 向用户说明将要产生的业务变化。

## 7. 统一 Agent 接口

```http
POST /api/opportunity-intelligence/agent:query
```

请求：

```json
{
  "message": "哪些商机最可能赢？",
  "scope": {
    "ownerPersonId": "person-21",
    "status": "OPEN"
  },
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "maxResults": 5,
  "includeEvidence": true,
  "includeRecommendedActions": false,
  "idempotencyKey": "agent-query-20261014-001"
}
```

响应：

```json
{
  "runId": "run-9501",
  "intent": "RANK_WIN_PROBABILITY",
  "scope": {
    "description": "当前用户负责的开放商机",
    "opportunityCount": 18
  },
  "answer": "当前最可能赢的前三个商机是华东园区项目、南区医院项目和总部改造项目。",
  "results": [
    {
      "opportunityId": "opp-1001",
      "name": "华东园区项目",
      "customerName": "示例客户",
      "winProbability": 0.72,
      "expectedCloseDate": "2026-12-18",
      "forecastRevenue": 1728000,
      "currency": "CNY",
      "riskLevel": "HIGH",
      "confidence": 0.68,
      "topFactors": ["decision_maker_coverage", "project_milestone_delay_days"],
      "evidenceIds": ["evidence-101", "evidence-102"]
    }
  ],
  "dataQuality": {
    "status": "PARTIAL",
    "staleOpportunityCount": 2,
    "missingDataNotice": "2 个商机超过 7 天未刷新预测。"
  },
  "citations": [
    {
      "type": "FORECAST_SNAPSHOT",
      "id": "forecast-7101",
      "asOfTime": "2026-10-14T09:00:00+08:00"
    }
  ]
}
```

## 8. 排序逻辑

### 8.1 最可能赢

默认按：

```text
win_probability
× confidence
× freshness_score
```

排序，并在金额相差较大时同时展示 `forecast_revenue`，避免把小金额高概率商机和大金额中概率商机简单混为一类。

### 8.2 风险最高

默认按：

```text
risk_level_weight
× risk_probability
× impact_score
× affected_revenue
× freshness_score
```

排序。`CRITICAL` 风险始终优先展示，即使其金额不高。

### 8.3 下一步动作

调用 `Next Best Action Prediction` 的优先级排序结果，同时过滤：

- 已完成动作；
- 已拒绝且仍在冷却期的动作；
- 没有责任人或截止时间的不可执行动作；
- 与当前目标不相关的动作。

## 9. 自然语言回答规则

### 9.1 必须做到

- 先给结论，再给关键依据；
- 明确数据截面时间；
- 区分事实、预测、风险和建议；
- 对低置信度和过期预测主动提示；
- 说明排序范围和过滤条件；
- 关键结论引用预测快照、特征或证据。

### 9.2 禁止做到

- 把赢单概率说成确定结果；
- 把建议动作说成已经执行；
- 用当前数据解释过去的预测；
- 没有证据时编造客户意图、预算或竞品信息；
- 隐藏权限范围、缺失数据和预测过期状态；
- 自动替用户发送外部消息或承诺价格、日期和合同条款。

## 10. 记忆与多轮对话

Agent 可以在当前会话内保留查询条件，例如：

```text
用户：哪些商机最可能赢？
用户：只看金额超过 100 万的。
用户：其中风险最高的是哪个？
用户：那下一步应该做什么？
```

每轮请求仍需在审计记录中保存解析后的完整范围，不能只保存“沿用上个条件”这类不可复盘的文本。

跨会话使用的筛选条件必须显式保存并可撤销，不应默认长期记住敏感客户范围。

## 11. 权限、审计与反馈

### 11.1 权限

Agent 的数据权限不高于当前用户：

- 只能查询用户有权限看到的商机和客户；
- 只能查看授权范围内的证据和动作历史；
- 汇总结果不能通过统计反推出无权查看的单个商机；
- 创建动作、更新风险和提交反馈仍要经过业务权限校验。

### 11.2 审计

每次调用写入 `OpportunityAgentRun`，至少记录：

- 原始用户问题；
- 解析出的意图和筛选范围；
- 使用的工具及参数；
- 读取的预测快照、风险和证据；
- 最终结构化结果和自然语言回答；
- 是否产生写入动作；
- 用户对回答或推荐的反馈。

### 11.3 反馈

用户可以标记：

- 结论正确；
- 风险误报；
- 影响因素不准确；
- 推荐动作不可执行；
- 预测已经过期。

反馈写入 `OpportunityPredictionFeedback` 或 Agent 反馈事件，不覆盖原始预测。

## 12. 验收标准

- [ ] 支持查询商机预测。
- [ ] 支持分析赢单概率及其影响因素。
- [ ] 支持识别风险并返回风险原因和证据。
- [ ] 支持推荐下一步行动、优先级和预计影响。
- [ ] 能理解“哪些商机最可能赢？”、“哪些商机风险最高？”、“下一步应该做什么？”。
- [ ] 自然语言回答绑定结构化预测、风险或动作结果。
- [ ] 返回数据范围、截面时间、置信度和数据质量提示。
- [ ] Agent 权限不超过当前用户，写操作可审批和审计。
- [ ] 过期预测、缺失数据和低置信度结果会主动提示。
- [ ] 不修改已有 `Opportunity Ontology`。

