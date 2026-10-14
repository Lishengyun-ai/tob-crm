# Forecast Engine Core

## 1. 目标与边界

`Forecast Engine Core` 是 Customer Growth Intelligence 和 Opportunity Intelligence 共用的预测底座，统一管理：

- 预测任务和预测对象；
- 算法输入特征；
- 模型和特征版本；
- 预测结果；
- 置信度、数据完整性和新鲜度；
- 预测快照、回放、校准和反馈。

业务域仍然拥有自己的语义和预测目标：

| 业务域 | 典型预测 |
| --- | --- |
| `Customer Growth Intelligence` | 客户增长潜力、客户价值、流失或扩展机会 |
| `Opportunity Intelligence` | 赢单概率、成交日期、收入、风险和下一步行动 |

底座不把客户增长字段和商机字段混成一套业务本体，而是通过 `subject_type`、`target_type` 和域适配器承载差异。

### 1.1 设计原因

- 如果每个 Agent 单独保存预测、特征和模型版本，无法统一回放、比较和治理；
- 如果把预测结果写回业务事实，会覆盖人工判断，也无法保留历史变化；
- 共享底座应该统一生命周期和审计，不应该统一所有业务指标的含义。

### 1.2 统一置信度口径

Forecast Engine 内部统一使用 `Decimal(0,1)`：

```text
0.00 = 没有可信依据
1.00 = 高度可信
```

现有使用 `0-100` 整数的客户事实或前端展示，通过适配层转换：

```text
display_confidence = round(engine_confidence × 100)
```

不允许同一预测链路混用 `0-1` 和 `0-100` 而不声明单位。

## 2. 核心 Entity

### 2.1 Forecast

`Forecast` 表示一次预测任务和预测快照的元数据，不直接承载不同业务域的具体预测值。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `forecast_id` | ID | 是 | 预测 ID |
| `domain` | Enum | 是 | `CUSTOMER_GROWTH`、`OPPORTUNITY` |
| `subject_type` | String | 是 | 预测主体类型，如 `Customer`、`Opportunity` |
| `subject_id` | ID | 是 | 预测主体 ID |
| `target_type` | String | 是 | 如 `GROWTH_POTENTIAL`、`WIN_PROBABILITY`、`CLOSE_DATE`、`REVENUE` |
| `as_of_time` | DateTime | 是 | 预测截面 |
| `model_version_id` | ID | 是 | 使用的模型版本 |
| `feature_set_version` | String | 是 | 特征集合版本 |
| `status` | Enum | 是 | `DRAFT`、`RUNNING`、`READY`、`PARTIAL`、`STALE`、`FAILED`、`RETIRED` |
| `data_completeness` | Decimal(0,1) | 是 | 输入数据完整度 |
| `freshness_score` | Decimal(0,1) | 是 | 输入数据新鲜度 |
| `overall_confidence` | Decimal(0,1) | 是 | 综合置信度 |
| `trigger_type` | Enum | 是 | `EVENT`、`SCHEDULED`、`MANUAL`、`AGENT`、`BATCH` |
| `parent_forecast_id` | ID | 否 | 情景模拟或派生预测的父预测 |
| `created_at` | DateTime | 是 | 创建时间 |
| `completed_at` | DateTime | 否 | 完成时间 |

### 2.2 ForecastFeature

`ForecastFeature` 保存模型实际使用的输入，而不是只保存当前业务表的字段名。它支持回放、解释和数据泄漏检查。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `feature_id` | ID | 是 | 特征 ID |
| `forecast_id` | ID | 是 | 所属预测 |
| `feature_code` | String | 是 | 稳定特征编码 |
| `feature_group` | String | 是 | 业务、行为、关系、时间或质量分组 |
| `value_type` | Enum | 是 | `NUMBER`、`BOOLEAN`、`CATEGORY`、`DATE`、`TEXT_VECTOR`、`JSON` |
| `value_json` | JSON | 是 | 标准化后的特征值 |
| `unit` | String | 否 | 天、金额、比例等单位 |
| `normalized_value` | Decimal | 否 | 供模型使用的标准值 |
| `missing_flag` | Boolean | 是 | 是否缺失 |
| `stale_flag` | Boolean | 是 | 是否过期 |
| `feature_as_of_time` | DateTime | 是 | 特征有效截面 |
| `source_entity_type` | String | 否 | 来源实体类型 |
| `source_entity_id` | ID | 否 | 来源实体 ID |
| `source_field` | String | 否 | 来源字段 |
| `source_event_id` | ID | 否 | 来源事件 |
| `quality_score` | Decimal(0,1) | 是 | 特征质量 |

约束：同一 `forecast_id + feature_code` 只能有一份有效特征值；特征值必须早于或等于预测的 `as_of_time`。

### 2.3 PredictionResult

`PredictionResult` 保存业务域无关的结果容器，具体业务值存放在类型化字段或 `value_json` 中。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `prediction_result_id` | ID | 是 | 预测结果 ID |
| `forecast_id` | ID | 是 | 所属预测 |
| `target_type` | String | 是 | 预测目标 |
| `value_type` | Enum | 是 | `PROBABILITY`、`AMOUNT`、`DATE`、`COUNT`、`CATEGORY`、`JSON` |
| `value_json` | JSON | 是 | 预测值 |
| `lower_bound_json` | JSON | 否 | 区间下界 |
| `upper_bound_json` | JSON | 否 | 区间上界 |
| `unit` | String | 否 | 币种、天或比例单位 |
| `confidence` | Decimal(0,1) | 是 | 该结果置信度 |
| `calibration_status` | Enum | 是 | `CALIBRATED`、`UNCALIBRATED`、`INSUFFICIENT_SAMPLE` |
| `result_status` | Enum | 是 | `PUBLISHED`、`SIMULATION`、`SUPERSEDED`、`INVALID` |
| `created_at` | DateTime | 是 | 创建时间 |

示例：

```json
{
  "targetType": "WIN_PROBABILITY",
  "valueType": "PROBABILITY",
  "value": 0.72,
  "lowerBound": 0.64,
  "upperBound": 0.79,
  "unit": "ratio",
  "confidence": 0.68
}
```

### 2.4 ForecastModelVersion

统一管理算法、规则、特征和标签口径，发布后不可变。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model_version_id` | ID | 是 | 模型版本 ID |
| `model_name` | String | 是 | 模型名称 |
| `version` | String | 是 | 版本号 |
| `domain` | Enum | 是 | 所属业务域 |
| `target_types` | Array<String> | 是 | 支持的预测目标 |
| `model_type` | Enum | 是 | `RULE`、`STATISTICAL`、`ML`、`HYBRID` |
| `feature_set_version` | String | 是 | 特征集合版本 |
| `label_definition` | JSON | 是 | 标签和结果定义 |
| `calibration_method` | String | 否 | 概率或区间校准方法 |
| `training_window` | JSON | 否 | 训练数据时间窗口 |
| `status` | Enum | 是 | `DRAFT`、`TESTING`、`PUBLISHED`、`RETIRED` |
| `metrics_json` | JSON | 否 | 离线评估指标 |
| `approved_by` | ID | 否 | 发布审批人 |
| `published_at` | DateTime | 否 | 发布时间 |

### 2.5 ForecastExplanation

虽然本任务的核心 Entity 是前三个，但统一底座必须保留解释引用，否则不同业务域无法用同一套 Agent 复盘预测。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `explanation_id` | ID | 解释 ID |
| `forecast_id` | ID | 所属预测 |
| `prediction_result_id` | ID | 所属结果 |
| `factor_code` | String | 因素编码 |
| `direction` | Enum | `POSITIVE`、`NEGATIVE`、`NEUTRAL` |
| `contribution` | Decimal | 贡献值 |
| `feature_ids` | Array<ID> | 支撑特征 |
| `evidence_ids` | Array<ID> | 支撑证据 |
| `summary` | Text | 面向用户的解释 |

## 3. Entity 关系

```text
ForecastModelVersion 1 ─────< Forecast >──── 1 Subject
                                      │
                                      ├────< ForecastFeature
                                      ├────< PredictionResult
                                      └────< ForecastExplanation
```

| 主体 | 关系 | 客体 | 基数 | 说明 |
| --- | --- | --- | --- | --- |
| `ForecastModelVersion` | `runs` | `Forecast` | 1:N | 一个模型版本产生多次预测 |
| `Forecast` | `hasFeature` | `ForecastFeature` | 1:N | 预测实际使用的输入 |
| `Forecast` | `hasResult` | `PredictionResult` | 1:N | 一个预测可有多个目标结果 |
| `PredictionResult` | `hasExplanation` | `ForecastExplanation` | 1:N | 结果的因素和证据解释 |
| `Forecast` | `supersedes` | `Forecast` | N:1 | 新预测替代旧当前投影 |
| `Forecast` | `simulates` | `Forecast` | N:1 | 情景模拟关联正式预测 |
| `Forecast` | `targets` | `Customer` / `Opportunity` | N:1 | 由域适配器解析主体 |

## 4. 业务域适配器

### 4.1 Customer Growth Intelligence Adapter

负责：

- 把客户画像、客户事实、项目、关系和历史交易映射为 `ForecastFeature`；
- 将客户增长潜力、客户价值和扩展机会映射为 `PredictionResult`；
- 解释客户事实来源和关系证据；
- 将客户增长预测反馈转成统一结果标签。

示例：

```json
{
  "domain": "CUSTOMER_GROWTH",
  "subjectType": "Customer",
  "targetType": "GROWTH_POTENTIAL",
  "features": [
    "customer.purchase_growth_12m",
    "customer.project_pipeline_value",
    "customer.relationship_coverage",
    "customer.profile_completeness"
  ]
}
```

### 4.2 Opportunity Intelligence Adapter

负责：

- 把 `Opportunity`、`Customer`、`Project`、`Product`、`Person` 和 `Action` 映射为特征；
- 将赢单概率、成交日期、收入和风险结果映射为 `PredictionResult`；
- 复用统一的风险、解释、反馈和快照机制；
- 将领域专用字段转换为统一目标类型和区间表达。

示例：

```json
{
  "domain": "OPPORTUNITY",
  "subjectType": "Opportunity",
  "targetTypes": [
    "WIN_PROBABILITY",
    "CLOSE_DATE",
    "FORECAST_REVENUE",
    "RISK_LEVEL"
  ]
}
```

## 5. 预测生命周期

```text
Created
  -> FeatureAssembled
  -> Running
  -> Calculated
  -> Validated
  -> Published
  -> Superseded
```

异常路径：

```text
Running -> Partial -> Published with low confidence
Running -> Failed
Published -> Stale
```

### 5.1 生命周期规则

- `Forecast` 是追加记录，不原地改写历史预测；
- 只有 `PUBLISHED` 结果可以成为当前业务投影；
- `SIMULATION` 结果不能替代正式预测；
- 输入数据过期时，当前预测标记 `STALE`，不静默清零；
- 模型版本退休后，历史预测仍可读取，但不能产生新的正式预测；
- 部分结果可发布，但必须标记缺失目标和低置信度。

## 6. 统一置信度计算

### 6.1 总体置信度

```text
overall_confidence
  = model_reliability
  × data_completeness
  × freshness_score
  × sample_support
  × definition_consistency
```

结果级置信度可以在总体置信度基础上叠加目标专属因素：

```text
result_confidence
  = overall_confidence
  × target_data_support
  × calibration_quality
```

### 6.2 置信度分段

| 区间 | 状态 | Agent 行为 |
| --- | --- | --- |
| `0.80 - 1.00` | `HIGH_CONFIDENCE` | 可直接用于常规决策 |
| `0.60 - 0.79` | `MEDIUM_CONFIDENCE` | 展示预测和主要假设 |
| `0.40 - 0.59` | `LOW_CONFIDENCE` | 优先提示补齐数据或人工复核 |
| `< 0.40` | `INSUFFICIENT_CONFIDENCE` | 不提供确定性结论，只返回区间和缺失项 |

置信度不能用来掩盖模型错误，也不能等同于业务成功概率。

## 7. 统一运行接口

### 7.1 创建预测

```http
POST /api/forecast-engine/forecasts:run
```

请求：

```json
{
  "domain": "OPPORTUNITY",
  "subjectType": "Opportunity",
  "subjectId": "opp-1001",
  "targetTypes": ["WIN_PROBABILITY", "CLOSE_DATE", "FORECAST_REVENUE"],
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "opportunity-intelligence-v1",
  "mode": "PUBLISHED",
  "idempotencyKey": "forecast-opp-1001-20261014"
}
```

响应：

```json
{
  "forecastId": "forecast-10001",
  "status": "READY",
  "domain": "OPPORTUNITY",
  "subjectId": "opp-1001",
  "overallConfidence": 0.68,
  "results": [
    {
      "targetType": "WIN_PROBABILITY",
      "value": 0.72,
      "confidence": 0.68
    },
    {
      "targetType": "CLOSE_DATE",
      "value": "2026-12-18",
      "lowerBound": "2026-12-05",
      "upperBound": "2027-01-09",
      "confidence": 0.64
    }
  ],
  "missingFeatures": [],
  "modelVersionId": "opportunity-intelligence-v1"
}
```

### 7.2 查询预测

```http
GET /api/forecast-engine/forecasts/{forecastId}
GET /api/forecast-engine/subjects/{subjectType}/{subjectId}/forecasts
```

支持按域、目标、模型版本、时间截面和状态查询。

### 7.3 回放预测

```http
POST /api/forecast-engine/forecasts/{forecastId}:replay
```

回放必须使用当时保存的 `ForecastFeature` 和 `ForecastModelVersion`，不能直接读取当前业务字段替代历史输入。

### 7.4 反馈与校准

```http
POST /api/forecast-engine/forecasts/{forecastId}:feedback
POST /api/forecast-engine/models/{modelVersionId}:calibrate
```

实际结果、人工修正和误差反馈进入统一评估链路，不删除原始预测。

## 8. 模型版本治理

### 8.1 发布条件

模型版本必须具备：

- 明确的 `label_definition`；
- 特征集合版本；
- 训练或规则生效时间；
- 离线评估指标；
- 置信度和校准方法；
- 权限、审批和回滚信息。

### 8.2 不同目标使用不同评估指标

| 目标 | 主要指标 |
| --- | --- |
| 概率 | Brier Score、Calibration Error、AUC/排序质量 |
| 日期 | MAE、P50 覆盖率、P80 覆盖率、系统性提前/滞后 |
| 金额 | MAE、MAPE、区间覆盖率 |
| 分类风险 | Precision、Recall、严重风险漏报率 |
| 推荐动作 | 接受率、完成率、目标改善率 |

不能用单一准确率评价所有预测目标。

### 8.3 灰度与回滚

- 新模型先以 `TESTING` 运行，不替代当前 `PUBLISHED` 结果；
- 通过领域和主体分组进行灰度；
- 监测置信度下降、数据漂移和预测偏差；
- 出现严重问题时停止新模型并恢复上一已发布版本；
- 历史预测仍绑定原模型版本，不随回滚重写。

## 9. 事件与调度

统一引擎接收两类触发：

### 9.1 业务事件

| 事件 | 可能触发的域 |
| --- | --- |
| `CustomerFactUpdated` | 客户增长 |
| `CustomerProfileChanged` | 客户增长、商机 |
| `OpportunityStageChanged` | 商机 |
| `ActionCompleted` | 客户增长、商机 |
| `ProjectMilestoneChanged` | 商机 |
| `OpportunityClosed` | 商机模型反馈 |
| `CustomerPurchaseRecorded` | 客户增长、商机模型反馈 |

### 9.2 调度规则

- 高影响事件即时运行；
- 普通事件按主体进入去重批处理；
- 无事件主体按域配置每日或每周刷新；
- 同一 `subject + target + model_version` 在运行中只保留一个任务；
- 数据源不可用时保留上一结果并标记 `STALE`。

## 10. 权限、审计和数据质量

### 10.1 权限

- 预测引擎使用调用者和域服务的最小权限；
- 特征快照可能包含客户、人员和敏感业务数据，读取需单独授权；
- 聚合预测不能泄露用户无权查看的主体；
- 模型发布、校准和退休需要模型治理权限。

### 10.2 审计链

```text
Forecast
  -> ForecastFeature
  -> ForecastModelVersion
  -> PredictionResult
  -> ForecastExplanation
  -> Feedback / Actual Outcome
```

每次运行还应记录触发来源、运行耗时、数据读取范围、错误、缺失特征和发布决定。

### 10.3 数据质量规则

- 缺少关键特征时返回 `PARTIAL` 或 `INSUFFICIENT_DATA`；
- 发现未来时间戳时阻断该特征，防止数据泄漏；
- 来源冲突时保留冲突信息，降低 `quality_score`；
- 金额必须带币种，日期必须带时区或统一时间语义；
- 特征值、预测值和置信度必须通过类型及范围校验。

## 11. 迁移与落地顺序

1. 先落地 `Forecast`、`ForecastFeature`、`PredictionResult` 和 `ForecastModelVersion`；
2. 将 Opportunity 的赢单概率、成交日期和收入预测适配到统一结果；
3. 将 Customer Growth 的客户价值和增长潜力适配到统一结果；
4. 统一置信度、快照、解释和反馈接口；
5. 增加模型校准、数据漂移和跨域预测质量看板。

已有领域文档中的专用 Entity 可以继续作为业务读模型或兼容接口，但底层预测运行记录应逐步指向共享 `Forecast`。

## 12. 验收标准

- [ ] 创建 `Forecast`、`ForecastFeature`、`PredictionResult`。
- [ ] 支持 `Customer Growth Intelligence` 和 `Opportunity Intelligence`。
- [ ] 统一管理预测结果、算法输入、模型版本和置信度。
- [ ] 特征快照可以按预测时点回放。
- [ ] 预测结果支持点值、区间、单位和结果状态。
- [ ] 置信度统一使用 `0-1`，并能适配已有 `0-100` 展示口径。
- [ ] 支持正式预测、情景模拟、过期和失败状态。
- [ ] 模型版本发布后不可变，历史预测不被新模型覆盖。
- [ ] 缺失、过期、冲突和未来时间戳会被识别并影响置信度。
- [ ] 预测运行、解释、反馈和实际结果可审计。
- [ ] 不修改已有 `Opportunity Ontology`。

