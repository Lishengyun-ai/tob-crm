# RelationshipScoreModel 主对象

## 设计结论

`RelationshipScoreModel` 只负责评分模型主对象的生命周期管理，暂不承载版本、维度和规则。它与现有 `relationships`、`relationship_scores`、`relationship_score_configs` 表保持独立，因此不会改变已有 Relationship 结构或 Score Engine 的计算行为。

`model_id` 采用业务主键，避免后续引用依赖数据库自增 ID；`status` 使用大写枚举，便于 API、数据库约束和前端状态展示保持一致。

## 数据库设计

表名：`relationship_score_models`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `model_id` | `TEXT` | `PRIMARY KEY` | 评分模型业务 ID |
| `model_name` | `TEXT` | `NOT NULL` | 模型名称 |
| `description` | `TEXT` | `NOT NULL DEFAULT ''` | 模型描述 |
| `status` | `TEXT` | `NOT NULL DEFAULT 'DRAFT'` | `DRAFT`、`TESTING`、`PUBLISHED`、`DISABLED` |
| `created_by` | `TEXT` | `NOT NULL` | 创建人 |
| `created_time` | `TEXT` | `NOT NULL` | ISO 8601 时间 |
| `updated_time` | `TEXT` | `NOT NULL` | ISO 8601 时间 |

数据库通过 `CHECK` 约束限制状态值，并建立 `status + updated_time` 索引支持列表查询。

## CRUD API

### 创建

`POST /api/relationship-score-models`

```json
{
  "model_id": "relationship-score-v2",
  "model_name": "关系评分模型 V2",
  "description": "测试中的主模型",
  "status": "DRAFT",
  "created_by": "Lisa"
}
```

返回 `201` 和完整主对象。`model_id` 重复或字段校验失败返回 `400`。

### 列表

`GET /api/relationship-score-models`

可选过滤：`GET /api/relationship-score-models?status=TESTING`

按 `updated_time DESC, model_id DESC` 返回主对象数组。

### 详情

`GET /api/relationship-score-models/{model_id}`

返回单个主对象；不存在返回 `404`。

### 编辑

`PUT /api/relationship-score-models/{model_id}`

支持更新 `model_name`、`description`、`status`、`created_by`。`model_id` 不能修改；未提供的字段保持原值。不存在返回 `404`。

## 状态说明

- `DRAFT`：草稿
- `TESTING`：测试中
- `PUBLISHED`：已发布
- `DISABLED`：停用

本任务只做状态存储和校验，不实现发布前置条件、版本切换、维度规则校验或 Score Engine 自动切换。

## RelationshipScoreModelVersion

### 数据库设计

表名：`relationship_score_model_versions`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `version_id` | `TEXT` | `PRIMARY KEY` | 版本业务 ID |
| `model_id` | `TEXT` | `NOT NULL`, 外键 | 所属 `RelationshipScoreModel` |
| `version_no` | `TEXT` | `NOT NULL` | 版本号 |
| `status` | `TEXT` | `NOT NULL DEFAULT 'DRAFT'` | `DRAFT`、`TESTING`、`PUBLISHED`、`DISABLED` |
| `created_by` | `TEXT` | `NOT NULL` | 创建人 |
| `created_time` | `TEXT` | `NOT NULL` | ISO 8601 创建时间 |
| `published_time` | `TEXT` | 可空 | 首次发布或最近一次发布的时间 |

约束：

- `UNIQUE(model_id, version_no)`：同一主模型下版本号不能重复。
- `FOREIGN KEY(model_id)`：不能为不存在的主模型创建版本。
- 部分唯一索引 `model_id WHERE status = 'PUBLISHED'`：同一主模型最多一个已发布版本。
- 删除主模型时级联删除版本；当前任务不提供删除 API。

### API 设计

创建版本：

`POST /api/relationship-score-models/{model_id}/versions`

```json
{
  "version_id": "relationship-score-v1-001",
  "model_id": "relationship-score-v1",
  "version_no": "1.0.0",
  "status": "DRAFT",
  "created_by": "Lisa"
}
```

编辑版本：

`PUT /api/relationship-score-models/{model_id}/versions/{version_id}`

可编辑 `version_no`、`status`、`created_by`。`version_id` 和 `model_id` 不可修改。已发布版本返回 `400`，要求创建新版本。

查看历史版本：

- `GET /api/relationship-score-models/{model_id}/versions`
- `GET /api/relationship-score-models/{model_id}/versions/{version_id}`

列表支持 `status` 查询参数，并按版本号、创建时间倒序返回。

发布版本：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/publish`

发布时自动完成：

1. 将同一模型当前的 `PUBLISHED` 版本改为 `DISABLED`；
2. 将目标版本改为 `PUBLISHED`；
3. 写入 `published_time`。

普通创建和编辑接口不能直接写入 `PUBLISHED`，必须通过发布 API，避免绕过发布审计时间和唯一发布约束。

### 状态流转

```text
DRAFT ──────> TESTING ──────> PUBLISHED
  │              │               │
  └──────────────┴──────> DISABLED
                                  │
                         新版本发布后旧版本进入此状态
```

规则：

- 新版本默认 `DRAFT`。
- `DRAFT` 和 `TESTING` 版本可以编辑。
- `PUBLISHED` 版本不可直接编辑。
- 已发布版本如需修改，必须创建新的 `DRAFT` 版本。
- 发布新版本会将旧的 `PUBLISHED` 版本变为 `DISABLED`。
- `PUBLISHED` 只能通过发布 API 进入，不能通过普通编辑接口设置。

### 测试案例

- 主模型不存在时创建版本失败。
- 同一主模型重复 `version_no` 创建失败。
- 不同主模型可以使用相同 `version_no`。
- 草稿版本可以编辑名称、状态和创建人。
- 已发布版本编辑失败。
- 已发布版本不能通过普通更新接口伪造进入 `PUBLISHED`。
- 发布版本写入 `published_time`。
- 同一主模型发布第二个版本后，第一个版本变为 `DISABLED`。
- 同一主模型查询 `PUBLISHED` 版本最多返回一个版本。

## RelationshipScoreDimension

### 数据库设计

表名：`relationship_score_dimensions`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `dimension_id` | `TEXT` | `PRIMARY KEY` | 维度业务 ID |
| `version_id` | `TEXT` | `NOT NULL`, 外键 | 所属评分模型版本 |
| `dimension_code` | `TEXT` | `NOT NULL` | 维度编码 |
| `dimension_name` | `TEXT` | `NOT NULL` | 维度名称 |
| `weight` | `REAL` | `NOT NULL DEFAULT 0`, `>= 0` | 维度权重 |
| `enabled` | `INTEGER` | `NOT NULL DEFAULT 1` | 是否启用，API 返回布尔值 |
| `description` | `TEXT` | `NOT NULL DEFAULT ''` | 维度说明 |

约束：

- `FOREIGN KEY(version_id)`：维度必须属于已存在的 `RelationshipScoreModelVersion`。
- `UNIQUE(version_id, dimension_code)`：同一版本内维度编码不能重复。
- 删除版本时级联删除维度。
- 已发布版本的维度不可新增、编辑或删除；需要先创建新版本。

新建版本时自动创建五个默认维度：

| 编码 | 名称 | 默认权重 |
| --- | --- | --- |
| `interaction_frequency` | 互动频率 | 0.25 |
| `recency` | 最近联系时间 | 0.25 |
| `influence` | 职位影响力 | 0.20 |
| `history` | 历史合作 | 0.15 |
| `duration` | 关系持续时间 | 0.15 |

### CRUD 接口

新增维度：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions`

```json
{
  "dimension_id": "relationship-score-v1-custom",
  "version_id": "relationship-score-v1-001",
  "dimension_code": "custom",
  "dimension_name": "自定义维度",
  "weight": 0.1,
  "enabled": true,
  "description": "自定义关系维度"
}
```

查询维度列表：

`GET /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions`

查询维度详情：

`GET /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}`

编辑维度：

`PUT /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}`

可编辑 `dimension_code`、`dimension_name`、`weight`、`enabled`、`description`；`dimension_id` 和 `version_id` 不可修改。

删除维度：

`DELETE /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}`

启用或停用维度通过编辑接口完成：

```json
{
  "enabled": false
}
```

### 测试案例

- 新建版本自动生成五个默认维度。
- 维度必须引用已存在的版本。
- 同一版本内重复 `dimension_code` 创建失败。
- 不同版本可以使用相同 `dimension_code`。
- 可以新增自定义维度。
- 可以编辑维度名称、权重、说明。
- 可以启用和停用维度。
- 可以删除草稿或测试中版本的维度。
- 已发布版本的维度新增、编辑、删除均失败。
- 查询维度详情只返回当前版本下的维度，不能跨版本读取。

## RelationshipScoreRule

### 数据模型

表名：`relationship_score_rules`

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `rule_id` | `TEXT` | 与 `dimension_id` 组成联合主键 | 规则业务 ID，在维度范围内唯一 |
| `dimension_id` | `TEXT` | `NOT NULL`, 外键 | 所属评分维度 |
| `rule_type` | `TEXT` | `NOT NULL` | `RANGE`、`TIME`、`ENUM` |
| `condition_json` | `TEXT` | `NOT NULL DEFAULT '{}'` | 结构化条件 JSON |
| `score` | `REAL` | `NOT NULL DEFAULT 0` | 命中后的规则得分 |
| `priority` | `INTEGER` | `NOT NULL DEFAULT 0` | 排序值，越小越优先 |
| `enabled` | `INTEGER` | `NOT NULL DEFAULT 1` | 是否启用，API 返回布尔值 |

规则通过 `dimension_id` 绑定到维度，再间接绑定到版本。主键为 `(rule_id, dimension_id)`，因此不同版本可以复用相同的 `rule_id`，规则数据仍然隔离。已发布版本的规则不可新增、编辑、删除或排序，需要创建新版本。

### 规则解析设计

规则条件采用统一 JSON 结构：

区间规则 `RANGE`：

```json
{
  "field": "interaction_count",
  "operator": ">=",
  "value": 5
}
```

时间规则 `TIME`：

```json
{
  "field": "last_contact_at",
  "withinDays": 7
}
```

枚举规则 `ENUM`：

```json
{
  "field": "role",
  "operator": "=",
  "value": "decision_maker"
}
```

解析器 `evaluate_relationship_score_rule(rule, context, now)`：

1. 校验 `rule_type` 和 `condition` 结构；
2. 从 `context[field]` 读取实际值；
3. `RANGE` 执行数值比较；
4. `TIME` 将 ISO 时间与 `now` 比较是否在指定天数内；
5. `ENUM` 执行等值、集合包含或字符串包含判断；
6. 返回布尔命中结果，具体得分由规则的 `score` 字段提供。

解析器只负责单条规则判断，不在本任务中改变 Score Engine 的现有五项计算逻辑。

### API 设计

新增规则：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules`

```json
{
  "rule_id": "interaction-frequency-5",
  "dimension_id": "relationship-score-v1-001-interaction_frequency",
  "rule_type": "RANGE",
  "condition": {
    "field": "interaction_count",
    "operator": ">=",
    "value": 5
  },
  "score": 80,
  "priority": 1,
  "enabled": true
}
```

查询规则列表：

`GET /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules`

查询规则详情：

`GET /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules/{rule_id}`

编辑规则：

`PUT /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules/{rule_id}`

可编辑 `rule_type`、`condition`、`score`、`priority`、`enabled`；`rule_id` 和 `dimension_id` 不可修改。

批量排序：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules/reorder`

```json
{
  "ruleIds": [
    "interaction-frequency-5",
    "interaction-frequency-10"
  ]
}
```

接口会按数组顺序重新写入 `priority`。

删除规则：

`DELETE /api/relationship-score-models/{model_id}/versions/{version_id}/dimensions/{dimension_id}/rules/{rule_id}`

启用或停用规则通过编辑接口完成：

```json
{
  "enabled": false
}
```

### 测试案例

- `RANGE` 支持 `>=`、`>`、`<=`、`<`、`=`、`!=`。
- `TIME` 能判断最近 N 天联系。
- `ENUM` 能判断角色等枚举值。
- 非法规则类型、字段、操作符、阈值会被拒绝。
- 规则必须属于已存在的评分维度。
- 规则只能通过当前版本下的维度访问。
- 可以新增、编辑、启停和删除规则。
- 可以按 `ruleIds` 批量重排。
- 重排必须包含该维度全部规则且不能重复。
- 不同版本允许使用相同 `rule_id`。
- 已发布版本的规则不能修改或排序。

## RelationshipScoreModel 发布校验

### 校验服务

校验入口：

`validate_relationship_score_model_version(db, model_id, version_id)`

返回结构：

```json
{
  "valid": false,
  "modelId": "relationship-score-v1",
  "versionId": "relationship-score-v1-001",
  "versionNo": "1.0.0",
  "errors": [
    {
      "code": "NO_ENABLED_RULE",
      "message": "维度“互动频率”至少需要一条启用规则。",
      "dimensionId": "relationship-score-v1-001-interaction_frequency"
    }
  ],
  "summary": {
    "dimensionCount": 5,
    "enabledDimensionCount": 5,
    "enabledWeight": 1.0
  }
}
```

校验项目：

- `NO_ENABLED_DIMENSION`：没有启用的评分维度。
- `INVALID_WEIGHT_SUM`：启用维度权重总和不等于 100%。
- `NO_ENABLED_RULE`：启用维度没有启用规则。
- `INVALID_RULE`：规则结构或条件不合法。
- `CONFLICTING_RULES`：同一维度内启用规则的条件存在重叠冲突。
- `INVALID_STATUS`：版本不是 `TESTING` 状态。

冲突判断采用保守策略：同一字段的不同规则如果可能命中同一个上下文，则判定为冲突；不同字段之间不冲突。规则优先级不用于绕过冲突校验。

### 发布接口

发布前校验：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/validate`

校验失败仍返回 `200`，通过 `valid=false` 和 `errors` 告知前端，便于页面展示完整错误列表。

正式发布：

`POST /api/relationship-score-models/{model_id}/versions/{version_id}/publish`

发布流程：

```text
DRAFT -> TESTING -> 校验 -> PUBLISHED
                           |
                    旧版本 -> DISABLED
```

只有 `TESTING` 状态版本可以发布。校验失败返回 `409`：

```json
{
  "error": "version publish validation failed",
  "validation": {
    "valid": false,
    "errors": [
      {
        "code": "INVALID_WEIGHT_SUM",
        "message": "启用维度权重总和必须等于100%，当前为90%。"
      }
    ]
  }
}
```

发布成功后：

- 当前版本状态变为 `PUBLISHED`；
- 同一评分模型原有 `PUBLISHED` 版本变为 `DISABLED`；
- 写入 `published_time`；
- 主模型状态更新为 `PUBLISHED`；
- Score Engine 的 `get_relationship_score_config` 优先读取当前已发布版本的启用维度权重，不再读取旧的模型配置作为当前版本来源。系统尚未存在已发布版本时，保留旧配置作为初始化兼容路径。

### 测试案例

- 没有评分维度时发布失败。
- 没有启用维度时发布失败。
- 启用维度权重总和不是 100% 时发布失败。
- 启用维度没有规则时发布失败。
- 存在非法规则结构时发布失败。
- 存在冲突规则时发布失败。
- `DRAFT` 版本不能直接发布。
- `TESTING` 状态且校验通过的版本可以发布。
- 发布新版本后旧版本自动停用。
- 发布后 Score Engine 返回当前已发布版本的 `versionId` 和维度权重。
