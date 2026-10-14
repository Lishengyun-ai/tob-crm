# Opportunity Revenue Forecast

## 1. 目标与边界

本能力预测一个商机在当前范围和成交概率下可以形成的收入金额，服务于销售排期、经营预测和收入汇总。

输入只使用：

- `Opportunity`：商机当前金额、阶段、赢单概率和范围状态；
- `Project`：项目预算、范围、时间线和可实现规模；
- `Product`：产品组合、数量、价格、折扣和供料角色。

输出写入 Intelligence 扩展层，不修改已有 `Opportunity Ontology` 的金额字段。

## 2. 业务口径

### 2.1 两种金额必须分开

| 金额 | 公式 | 用途 |
| --- | --- | --- |
| `potential_revenue` | 预计可实现范围 × 产品净价 | 商机赢单后的潜在收入 |
| `forecast_revenue` | `potential_revenue × win_probability` | 按赢单概率加权的预测收入 |

用户要求的“预测金额”默认返回 `forecast_revenue`，同时返回 `potential_revenue`，避免把“项目全量价值”和“当前可计入收入”混为一谈。

### 2.2 供料模式

| 模式 | 定义 | 收入计算 |
| --- | --- | --- |
| `SINGLE_SUPPLIER` | 本商机由一个供料商提供全部预测产品 | 汇总该供料商产品净收入 |
| `DUAL_PACKAGE` | 同一项目存在两个独立包，分别由两个供料商或产品包承接 | 分别计算包收入，再汇总；不能把两个包的金额重复计算 |

`DUAL_PACKAGE` 必须保存包级明细，至少包括 `package_id`、`supplier_id`、`product_ids`、`package_share` 和 `package_revenue`。

## 3. 输出 Entity

新增 `OpportunityRevenueForecast`，一份快照代表一个预测时点和模型版本。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `revenue_forecast_id` | ID | 是 | 收入预测快照 ID |
| `opportunity_id` | ID | 是 | 引用 `Opportunity` |
| `project_id` | ID | 否 | 引用 `Project` |
| `model_version_id` | ID | 是 | 收入模型版本 |
| `as_of_time` | DateTime | 是 | 预测截面时间 |
| `supply_mode` | Enum | 是 | `SINGLE_SUPPLIER`、`DUAL_PACKAGE` |
| `potential_revenue` | Decimal | 是 | 赢单后预计可实现收入 |
| `forecast_revenue` | Decimal | 是 | 概率加权预测收入 |
| `revenue_low` | Decimal | 是 | 保守金额 |
| `revenue_high` | Decimal | 是 | 乐观金额 |
| `currency` | String | 是 | 币种 |
| `win_probability` | Decimal(0,1) | 是 | 使用的赢单概率 |
| `scope_coverage_ratio` | Decimal(0,1) | 是 | 项目范围可覆盖比例 |
| `discount_rate` | Decimal(0,1) | 是 | 预计综合折扣率 |
| `confidence` | Decimal(0,1) | 是 | 金额预测置信度 |
| `calculation_status` | Enum | 是 | `READY`、`PARTIAL`、`INSUFFICIENT_DATA`、`STALE` |
| `created_at` | DateTime | 是 | 创建时间 |

### 3.1 Revenue Forecast Package

双包商机增加 `RevenueForecastPackage` 明细：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `package_id` | ID | 是 | 包 ID |
| `revenue_forecast_id` | ID | 是 | 所属预测 |
| `package_name` | String | 是 | 包名称 |
| `supplier_id` | ID | 否 | 供料商或责任主体 |
| `product_ids` | Array<ID> | 是 | 包内产品 |
| `scope_quantity` | Decimal | 是 | 包覆盖数量 |
| `gross_revenue` | Decimal | 是 | 折扣前金额 |
| `discount_rate` | Decimal(0,1) | 是 | 包级折扣 |
| `net_revenue` | Decimal | 是 | 折扣后金额 |
| `package_share` | Decimal(0,1) | 是 | 在项目可实现收入中的占比 |
| `confidence` | Decimal(0,1) | 是 | 包级置信度 |

双包规则：

```text
sum(package_share) <= 1
sum(package.net_revenue) = potential_revenue
```

如果两个包覆盖同一产品或同一项目范围，必须先按范围归属拆分，禁止直接把两个报价相加。

## 4. 输入特征

### 4.1 Opportunity

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `opportunity.amount_current` | 当前申报金额 | 金额基线 |
| `opportunity.amount_revision_volatility` | 近 90 天金额变动 | 范围稳定性 |
| `opportunity.win_probability` | Win Probability Prediction 输出 | 概率加权 |
| `opportunity.scope_confirmed_ratio` | 已确认范围 / 预计范围 | 可实现程度 |
| `opportunity.discount_signal` | 已确认折扣或报价信号 | 净收入调整 |

### 4.2 Project

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `project.budget_estimate` | 项目预算或预算区间 | 金额上限 |
| `project.scope_quantity` | 项目可销售范围数量 | 可售规模 |
| `project.section_coverage_ratio` | 已覆盖项目分区 / 总分区 | 范围实现率 |
| `project.scope_change_rate` | 近 90 天范围变更频率 | 金额不确定性 |
| `project.procurement_package_count` | 项目采购包数量 | 单包/双包识别 |
| `project.supplier_allocation` | 项目对供料商的分配 | 包级归属 |

### 4.3 Product

| Feature Code | 计算口径 | 作用 |
| --- | --- | --- |
| `product.list_price_total` | 产品数量 × 牌价 | 毛收入基线 |
| `product.net_price_total` | 牌价扣除已知折扣 | 净收入 |
| `product.quantity_coverage_ratio` | 已确认数量 / 项目需求数量 | 范围覆盖 |
| `product.mix_discount_rate` | 产品组合加权折扣 | 折扣侵蚀 |
| `product.package_overlap_ratio` | 双包产品或范围重叠比例 | 防止重复计算 |
| `product.price_confidence` | 价格已确认、估算或缺失 | 置信度 |

## 5. 计算方法

### 5.1 单供料商机

```text
potential_revenue
  = sum(product.quantity × product.list_price × (1 - discount_rate))
    × scope_coverage_ratio

forecast_revenue
  = potential_revenue × opportunity.win_probability
```

若 `Opportunity.amount_current` 已被确认且产品明细完整，以产品明细计算结果为主；若产品明细不完整，以商机金额为基线，并降低 `confidence`。

### 5.2 双包商机

```text
package_net_revenue_i
  = package_scope_quantity_i
  × package_product_net_price_i
  × package_scope_coverage_i

potential_revenue
  = sum(package_net_revenue_i)

forecast_revenue
  = sum(package_net_revenue_i × package_win_probability_i)
```

如果没有包级赢单概率，先使用商机级 `win_probability`；如果两个包的风险和推进阶段显著不同，必须分别预测并返回包级概率。

### 5.3 金额区间

```text
revenue_low
  = potential_revenue_low × win_probability_low

revenue_high
  = potential_revenue_high × win_probability_high
```

金额区间至少考虑：范围覆盖率、产品数量、折扣、双包分配和赢单概率的不确定性。

## 6. 业务规则与异常处理

- 币种缺失时不生成正式金额预测，返回 `INSUFFICIENT_DATA`。
- 单供料模式只有一个有效供料归属；多个供料商但没有包边界时，标记 `PACKAGE_ALLOCATION_MISSING`。
- 双包金额必须通过项目范围或采购包拆分，不能按两个报价简单叠加。
- 产品数量缺失时允许基于 `Opportunity.amount_current` 估算，但必须降低 `confidence`。
- 预计收入不能高于项目预算上限，除非存在已确认的预算扩展证据。
- 折扣超过审批阈值时，金额可以计算，但需产生价格风险并降低置信度。
- 产品组合或项目范围变更时，旧预测保留为历史快照，新预测追加生成。

## 7. Agent 接口

```http
POST /api/opportunity-intelligence/revenue:forecast
```

请求：

```json
{
  "opportunityId": "opp-1001",
  "asOfTime": "2026-10-14T09:00:00+08:00",
  "modelVersionId": "revenue-forecast-v1",
  "includePackages": true,
  "includeProductBreakdown": true,
  "idempotencyKey": "revenue-opp-1001-20261014"
}
```

响应：

```json
{
  "revenueForecastId": "revenue-8001",
  "opportunityId": "opp-1001",
  "supplyMode": "DUAL_PACKAGE",
  "forecast": {
    "potentialRevenue": 2400000,
    "forecastRevenue": 1728000,
    "revenueLow": 1350000,
    "revenueHigh": 2100000,
    "currency": "CNY",
    "winProbability": 0.72,
    "scopeCoverageRatio": 0.90,
    "discountRate": 0.12,
    "confidence": 0.81,
    "calculationStatus": "READY"
  },
  "packages": [
    {
      "packageId": "package-a",
      "packageName": "主体包",
      "supplierId": "supplier-1",
      "netRevenue": 1500000,
      "packageShare": 0.63,
      "confidence": 0.86
    },
    {
      "packageId": "package-b",
      "packageName": "配套包",
      "supplierId": "supplier-2",
      "netRevenue": 900000,
      "packageShare": 0.37,
      "confidence": 0.74
    }
  ],
  "dataQuality": {
    "status": "PARTIAL",
    "missingInputs": ["package-b.confirmed_quantity"]
  }
}
```

## 8. 验收标准

- [ ] 输出 `forecast_revenue`，同时保留 `potential_revenue`。
- [ ] 支持 `SINGLE_SUPPLIER` 和 `DUAL_PACKAGE`。
- [ ] 双包商机有包级金额和范围归属，不能重复计算。
- [ ] 金额均带 `currency`。
- [ ] 预测绑定赢单概率、模型版本和截面时间。
- [ ] 产品明细不足时降低置信度并说明缺失数据。
- [ ] 历史预测不可覆盖，只能追加新快照。
- [ ] 不修改已有 `Opportunity Ontology`。

