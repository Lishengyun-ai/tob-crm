# Customer Profile Fact 与画像生成闭环

## 设计结论

客户画像采用“事实驱动”：

```text
客户、项目、商机、关键人、关系事件
              ↓
       CustomerProfileFact
              ↓
       事实抽取与证据留痕
              ↓
       已发布客户画像评分模型
              ↓
       CustomerProfileScore
              ↓
       CustomerProfileSummary
```

事实是可审计输入，评分和摘要是可重新生成的派生结果。重新生成不会覆盖历史评分和摘要，而是新增结果，并将上一份已发布摘要标记为 `stale`。

## 数据模型

现有 `customer_profile_facts` 作为事实主表：

| 字段 | 说明 |
| --- | --- |
| `profile_id` | 所属客户画像 |
| `fact_code` | 事实编码 |
| `fact_name` | 事实名称 |
| `category` | 事实分类 |
| `value_type` | 值类型 |
| `value_json` | 事实值 |
| `confidence` | 置信度 |
| `source_type` | 来源类型 |
| `source_id` | 来源 ID |
| `observed_at` | 观察时间 |
| `valid_from` / `valid_to` | 有效时间范围 |
| `status` | 当前状态 |

事实通过 `UNIQUE(profile_id, fact_code)` 做当前画像内的幂等更新。抽取过程另外写入：

- `customer_fact_extraction_runs`
- `customer_fact_extraction_candidates`
- `customer_profile_evidences`

这样可以区分“候选事实”“已采纳事实”和“事实证据”。

## 事实 API

新增或覆盖事实：

`POST /api/customer-profiles/{profile_id}/facts`

编辑事实：

`PUT /api/customer-profiles/{profile_id}/facts/{fact_id}`

删除事实：

`DELETE /api/customer-profiles/{profile_id}/facts/{fact_id}`

事实示例：

```json
{
  "factCode": "business_model",
  "value": "工程项目型客户",
  "confidence": 90,
  "sourceType": "manual",
  "sourceId": "sales-review-001",
  "observedAt": "2026-10-12T00:00:00+00:00"
}
```

人工事实更新只修改事实和画像更新时间，不自动覆盖评分历史；需要通过刷新接口重新计算派生结果。

## 画像刷新服务

服务入口：

`refresh_customer_profile(db, profile_id, source_types, dry_run, trigger_type, now)`

正式刷新按以下顺序执行：

1. 同步客户关联的项目、商机、关键人和客户开发关系；
2. 从指定来源抽取事实候选；
3. 按置信度和规则阈值自动采纳事实；
4. 写入事实证据和抽取运行记录；
5. 使用当前有效客户画像评分模型重算评分；
6. 将旧的 `published` 摘要标记为 `stale`；
7. 生成新的客户画像摘要；
8. 返回事实抽取、评分、摘要和完整画像。

## 刷新 API

`POST /api/customer-profiles/{profile_id}/refresh`

请求：

```json
{
  "sourceTypes": ["project", "opportunity", "person"],
  "triggerType": "manual"
}
```

预览模式：

```json
{
  "sourceTypes": ["project"],
  "dryRun": true
}
```

预览只生成事实候选，不写入评分和摘要。

返回：

```json
{
  "profileId": 1,
  "dryRun": false,
  "extraction": {
    "status": "completed",
    "candidate_count": 3,
    "accepted_count": 2,
    "review_count": 1
  },
  "scores": [],
  "summary": {},
  "profile": {}
}
```

## 一致性规则

- 所有事实必须归属于一个客户画像。
- 事实来源和证据来源必须保留。
- 抽取失败时，画像刷新不会伪造新的评分或摘要。
- 评分使用当前已发布/启用的客户画像评分模型；不存在可用模型时使用系统初始化的默认模型。
- 每次正式刷新都会生成新的评分时间点。
- 每次正式刷新都会生成新的摘要，并将上一份已发布摘要标记为 `stale`。
- 事件驱动的画像更新继续复用同一套抽取、评分和摘要逻辑，避免手工刷新与事件刷新产生两套口径。

## 现有事件闭环

以下事件可以触发画像刷新：

- `project_created`
- `opportunity_created`
- `opportunity_stage_changed`
- `person_changed`
- `action_completed`

事件入口：

`POST /api/customer-profile-events`

事件处理会执行事实抽取、关系同步、评分重算，并将摘要标记为 `stale`。手工刷新接口进一步补上摘要自动重建能力。

## 事实候选审核 API

查询某次抽取运行的候选：

`GET /api/customer-fact-extraction-runs/{run_id}/candidates`

支持按状态过滤：

`GET /api/customer-fact-extraction-runs/{run_id}/candidates?status=needs_review`

审核候选：

`POST /api/customer-fact-extraction-candidates/{candidate_id}/review`

接受候选：

```json
{
  "decision": "accept",
  "value": "集团工程客户",
  "factName": "业务模式",
  "confidence": 95
}
```

接受时可以人工修正 `value`、`factName` 和 `confidence`，然后写入或更新 `customer_profile_facts`，并记录 `applied_fact_id`。

驳回候选：

```json
{
  "decision": "reject"
}
```

驳回只更新候选状态，不写入事实表。

审核规则：

- `needs_review` 候选可以接受或驳回；
- `accepted` 重复接受是幂等操作；
- `rejected` 重复驳回是幂等操作；
- `supporting` 和 `preview` 候选不能直接审核；
- 审核接受后，抽取运行的 `accepted_count`、`review_count` 会重新统计；
- 接受事实后，旧的已发布画像摘要会标记为 `stale`；
- 审核本身不直接重算评分和生成摘要，审核完成后调用 `refresh` API 生成一致的派生结果。
