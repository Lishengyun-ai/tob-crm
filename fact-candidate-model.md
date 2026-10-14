# FactCandidate 数据模型与 ER 关系说明

## 1. 设计结论

`FactCandidate` 是独立于已确认事实的新增对象，用来保存 AI 从录音、聊天或文档中抽取出的候选业务事实。候选事实只有在审核后，才允许由后续流程写入对应本体或已确认事实表。

本次只新增 `fact_candidates` 表和相关索引，不修改 `Customer`、`Person`、`Opportunity`、`Project` 或 `Semantic Layer` 的已有表结构。

`confidence` 统一使用 `0-100` 的整数，与当前 CRM 事实模型的置信度口径保持一致。

## 2. 表结构

```sql
CREATE TABLE fact_candidates (
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
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'MODIFIED')),
  created_by TEXT NOT NULL DEFAULT 'system',
  created_time TEXT NOT NULL,
  review_user TEXT,
  review_time TEXT
);
```

| 字段 | 含义 | 约束 |
| --- | --- | --- |
| `id` | 候选事实 ID | 主键 |
| `fact_type` | 事实类型 | 必填，版本化的业务事实分类 |
| `subject_type` | 主体类型 | `Customer` / `Person` / `Opportunity` / `Project` |
| `subject_id` | 主体 ID | 与 `subject_type` 配对使用 |
| `predicate` | 关系 | 例如 `hasBudget`、`influences`、`belongsTo` |
| `object_value` | 候选值 | AI 抽取出的值 |
| `object_type` | 候选值类型 | 例如 `text`、`number`、`date`、`boolean`、`reference` |
| `source_type` | 来源类型 | `recording` / `chat` / `document` |
| `source_id` | 来源 ID | 对应录音、聊天或文档记录 |
| `confidence` | AI 置信度 | `0-100` |
| `status` | 审核状态 | `PENDING` / `APPROVED` / `REJECTED` / `MODIFIED` |
| `created_by` | 创建者 | 通常为 Agent 或系统用户 |
| `created_time` | 创建时间 | 必填 |
| `review_user` | 审核人 | 未审核时为空 |
| `review_time` | 审核时间 | 未审核时为空 |

## 3. ER 关系

```text
Customer      1 ───────< N FactCandidate
Person        1 ───────< N FactCandidate
Opportunity   1 ───────< N FactCandidate
Project       1 ───────< N FactCandidate
Semantic Layer 1 ─────< N FactCandidate（定义 fact_type / predicate / object_type 的语义）
```

关系落库规则：

- `Customer -- hasFact --> FactCandidate`：`subject_type = 'Customer'`，`subject_id = customers.id`。
- `Person -- hasFact --> FactCandidate`：`subject_type = 'Person'`，`subject_id = persons.id`。
- `Opportunity -- hasFact --> FactCandidate`：`subject_type = 'Opportunity'`，`subject_id = opportunities.id`。
- `Project -- hasFact --> FactCandidate`：`subject_type = 'Project'`，`subject_id = projects.id`。
- `Semantic Layer` 不作为业务主体 ID 写入 `subject_id`，而是通过语义定义校验 `fact_type`、`predicate` 和 `object_type`。

这是一个多态关系，因此数据库不能在同一列上同时声明四个外键。本次使用 `subject_type + subject_id` 的逻辑外键，并用 `subject_type, subject_id, status` 索引支持主体查询。审核服务写入时必须先校验对应主体确实存在；后续若需要数据库级强约束，再拆分为四张关系表或引入统一本体对象表。

## 4. 审核队列行为

- `PENDING`：进入审核队列，允许人工确认或修改。
- `APPROVED`：候选事实按原值确认，可进入事实落库流程。
- `MODIFIED`：审核人修改后确认，必须保留审核人和审核时间。
- `REJECTED`：候选事实被拒绝，不得写入已确认事实。

审核队列默认按 `status = 'PENDING'` 查询，并按 `fact_quality_score` 降序、AI 置信度和创建时间倒序展示；对应索引为 `idx_fact_candidates_quality_queue`。

## 5. Fact Extraction Service

`FactExtractionService` 接收 `content`、`source_type`、`source_id`，调用注入的 LLM client，并只输出或写入 `FactCandidate`。支持的 `fact_type` 为：

- `CustomerProfile`：主体默认为 `Customer`。
- `PersonRole`：主体默认为 `Person`。
- `PersonRelation`：主体默认为 `Person`。
- `OpportunityStatus`：主体默认为 `Opportunity`。
- `ProjectInformation`：主体默认为 `Project`。
- `Competitor`：必须由 LLM 或主体解析器提供主体类型。

LLM 返回的 `confidence` 使用 `0-1` 小数，服务转换为表中的 `0-100` 整数。例如 `0.86` 转换为 `86`。低可信规则为 `confidence < 60`，候选仍保持 `PENDING`，通过 `status = 'PENDING' AND confidence < 60` 进入低可信队列，不自动写入任何业务对象。

由于输入只包含来源内容，不一定能得到主体 ID，服务支持注入 `subject_resolver(subject_type, subject)` 解析主体。无法解析时拒绝入队，避免产生没有有效主体的候选记录。

## 6. Fact Candidate Review API

| 接口 | 作用 |
| --- | --- |
| `GET /api/facts/pending` | 查询 `PENDING` 候选，按置信度和创建时间排序 |
| `GET /api/facts/{id}` | 查看候选详情及审核日志 |
| `POST /api/facts/{id}/approve` | 审核通过并调用 Ontology Service |
| `POST /api/facts/{id}/reject` | 拒绝候选，不写入本体 |
| `POST /api/facts/{id}/modify` | 修改 `predicate`、`object_value` 或 `object_type` 后写入本体 |

审核接口要求 `reviewUser`。审核通过或修改时，事务内先写入 `ontology_fact_values`，再更新候选状态并写入 `fact_candidate_review_logs`。任一环节失败都会回滚，避免出现审核状态与本体状态不一致。

## 7. Fact Conflict Detection

当两个候选事实满足 `subject_type + subject_id + predicate` 相同、但 `object_value` 不同，系统会新增 `fact_conflicts` 记录。存在 `OPEN` 冲突时，审核通过或修改写入本体会被阻止，不会自动覆盖已有事实。拒绝其中一个候选后，对应冲突标记为 `RESOLVED`。

## 8. Fact Approval Ontology Sync

`APPROVED` 或 `MODIFIED` 的候选由 `Fact Approval Ontology Sync` 写入 `ontology_fact_values`，并按事实类型同步到业务本体字段：

| 事实类型 | 本体对象 | 同步字段 |
| --- | --- | --- |
| `CustomerProfile` | Customer | `customers.customer_level` |
| `PersonRole` | Person | `persons.role` |
| `OpportunityStatus` | Opportunity | `opportunities.stage` |
| `ProjectInformation` | Project | `projects.status` |

Customer 和 Person 的目标字段通过幂等迁移以可空方式追加，不删除或重命名已有字段。

每次同步尝试写入 `fact_ontology_sync_logs`，记录尝试次数、目标对象、原值、新值、成功/失败状态和错误信息。同步失败会回滚本体写入，但保留 `FAILED` 日志；可通过 `POST /api/facts/{id}/sync/retry` 重试已审核事实。同步按主体、关系和值执行冲突检查，不会静默覆盖已有事实。

## 9. Fact Quality Score

每条候选事实持久化 `fact_quality_score`（0-100）和 `fact_quality_level`（A/B/C），由四个可解释维度加权得到：

| 维度 | 权重 | 计算规则 |
| --- | ---: | --- |
| 来源可靠性 | 30% | `document=90`、`recording=85`、`chat=80` |
| AI 置信度 | 30% | 使用 `confidence` 的 0-100 值 |
| 历史一致性 | 20% | 已确认事实同值 `100`，有冲突 `0`，无历史 `70` |
| 人工确认次数 | 20% | 每次 `APPROVE/MODIFY` 增加 25 分，最高 100 |

总分按权重计算并四舍五入：`round(来源×30% + AI×30% + 历史×20% + 人工×20%)`。等级边界为 `A >= 90`、`B >= 70 且 < 90`、`C < 70`。评分只用于审核队列排序和解释，不会绕过人工审核，也不会自动覆盖已有本体事实。历史数据在首次进入待审核队列时惰性补分，保证新增字段的迁移兼容性。

## 10. CRM Agent 事实接入

通过 `fact_agent_service.py` 统一向 CRM Agent 提供事实上下文，并使用以下边界：

| Agent | 查询范围 | 可作为业务依据 | 仅作提示 |
| --- | --- | --- | --- |
| 客户洞察 Agent | 指定客户的最新事实 | `APPROVED` / `MODIFIED` | 不返回 `PENDING` |
| 商机分析 Agent | 指定商机的相关事实 | `APPROVED` / `MODIFIED` | 不返回 `PENDING` |
| 拜访助手 Agent | 指定客户或商机的候选信息 | 不使用未确认信息作为依据 | `PENDING` |

事实查询接口为 `GET /api/agents/{agent_id}/facts?customerId=&opportunityId=`，运行接口 `/api/agents/{agent_id}/run` 也会返回 `factContext`。每条事实都带有：

- `[已确认事实]`：已审核通过或修改通过，可进入 Agent 的业务依据。
- `[AI推测]`：尚未审核，只能作为待核对提示。

`REJECTED` 事实不会进入任何 Agent 上下文。该约束放在服务端执行，避免仅依赖页面展示或提示词控制。
