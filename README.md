# 立邦 ToB CRM 原型

面向涂料行业的 ToB CRM 原型，包含商机工作台、客户360、客户开发 AT 阶段、语义管理、Agent Studio 和 SQLite 后台。

## 本地运行

```powershell
python server.py
```

打开 <http://127.0.0.1:8877/>

## Windows 后台服务

如果需要让多位同事访问，建议把后台注册为 Windows Service，使它在未登录时也能启动，并在机器重启后自动恢复。安装和卸载脚本不引入新的第三方依赖，使用当前 Python 环境中的 `pywin32`：

```powershell
# 以管理员身份运行 PowerShell
.\install-crm-service.ps1
```

服务名为 `AICrm8877`，默认监听 `0.0.0.0:8877`。停止或移除服务：

```powershell
.\uninstall-crm-service.ps1
```

安装脚本会创建仅允许 Domain/Private 本地网段访问 8877 的防火墙规则。同事应通过 `http://<CRM主机名或内网IP>:8877/` 访问。正式开放前仍需要配置真实的用户登录和权限控制；当前项目的 `actor` 字段不能替代身份认证。

## 目录说明

- `outputs/index.html`：CRM 原型界面
- `server.py`：Python 标准库后台和 SQLite 接口
- `ai-native-crm-architecture.svg`：AI 原生 CRM 架构图
- `crm-voice-entry-flow.svg`：销售语音录入 CRM 端到端流程图
- `ai-native-crm-design-notes.md`：架构设计说明
- `crm-voice-entry-design.md`：销售语音录入 CRM 能力设计
- `crm-image-opportunity-flow.svg`：图片识别商机报备端到端流程图
- `crm-image-opportunity-design.md`：图片识别商机报备设计
- `ai-crm-er-model.md`：AI CRM 本体、P0 数据模型与兼容迁移说明
- `test_p0_models.py`：P0 数据模型初始化与迁移测试

## 部署说明

GitHub Pages 适合托管静态原型页面；`server.py` 和 SQLite 需要部署到支持 Python 的服务环境，才能启用数据持久化和 Agent 接口。

## P0 数据模型 API

本轮 P0 数据模型在保留旧 API 的基础上增加以下接口：

- `GET/POST /api/organizations`、`GET/PUT /api/organizations/{id}`
- `GET/POST /api/project-phases`、`GET/PUT /api/project-phases/{id}`
- `GET /api/project-phases/{id}/lots`、`GET/POST /api/project-lots`、`PUT /api/project-lots/{id}`
- `GET/POST /api/customer-development-opportunities`、`PUT /api/customer-development-opportunities/{id}`

启动时会自动创建 P0 表和索引，并把旧 `project_sections` 映射到 `project_phases` / `project_lots`。旧字段和旧接口保留，便于渐进迁移。
# 客户画像数据模型补充

客户主数据仍位于 `customers`。`customer_profiles` 是版本化画像快照，保存价值评分、增长潜力、经营面积、客户分层、画像版本与更新时间；事实和预测保持独立追加历史。画像详情会返回低置信度、过期和摘要缺失提示。

常用接口：

- `GET /api/customers/{id}/profile`：读取当前画像；
- `GET /api/customers/{id}/profile-history`：读取全部画像版本；
- `POST /api/customer-profiles/{id}/refresh`：刷新画像并映射最新评分/预测。

统一关系：

- `GET /api/roles`：读取角色字典；
- `GET /api/relationships`：读取 Person 与客户、项目、商机、组织的统一关系；
- `POST /api/relationships`：按关系类型或角色幂等创建/更新关系；
- 旧 `customer_persons`、`project_persons`、`opportunity_persons` API 保持兼容。

## Insight 与 Action

洞察和行动已拆成独立数据对象：`insights` 保存结构化判断、证据、风险、建议、置信度和有效期；`actions` 保存负责人、截止时间、优先级、来源洞察、审批状态及执行结果。AI 推荐动作使用 `action_origin=ai_recommended`，销售确认后再进入 `accepted`、`in_progress` 或 `completed` 等真实执行状态，避免把推荐与承诺混为一谈。

相关接口：

- `GET/POST /api/insights`、`PUT /api/insights/{id}`；
- `GET /api/insights/{id}/actions`、`POST /api/insights/{id}/actions`；
- `GET/POST /api/actions`、`PUT /api/actions/{id}`；
- `GET /api/insights/{id}/audit`、`GET /api/actions/{id}/audit`。

`insight_action_audits` 会记录推荐、采纳、执行、完成、驳回和过期等关键状态变化。Agent 页面优先读取上述真实 API，接口不可用时保留原有演示配置，便于静态部署和渐进迁移。

## Forecast Engine

统一预测底座由 `forecasts`、`forecast_features`、`prediction_results`、`forecast_model_versions` 和 `forecast_explanations` 组成，并保留 `forecast_feedback` 作为实际结果回写入口。第一阶段使用可解释规则，不引入训练框架；每次运行保存特征快照，预测历史只追加不覆盖。

接口：

- `POST /api/forecast-engine/forecasts:run`：创建正式预测或 `SIMULATION` 情景预测；
- `GET /api/forecast-engine/forecasts/{id}`：读取预测、特征、结果和解释；
- `GET /api/forecast-engine/subjects/{subjectType}/{subjectId}/forecasts`：查询主体历史预测；
- `POST /api/forecast-engine/forecasts/{id}:replay`：使用原始特征快照回放；
- `POST /api/forecast-engine/forecasts/{id}:feedback`：追加实际结果或人工反馈。

支持 `CUSTOMER_GROWTH` 和 `OPPORTUNITY` 两个域。缺失、冲突或过期输入会降低数据完整度、新鲜度和置信度；原有 `/api/agents/customer-growth/predict` 等客户预测接口保持兼容。

## Opportunity Intelligence Agent

Opportunity Intelligence Agent 负责统一编排 Forecast Engine、商机风险和下一步行动，不重复实现赢单概率或成交日期算法。入口为 `POST /api/opportunity-intelligence/agent:query`，支持“哪些商机最可能赢”“哪些商机风险最高”“下一步应该做什么”等意图，并返回结构化预测、风险、证据、置信度、数据范围和截面时间。

风险可通过 `POST /api/opportunity-intelligence/risks:detect` 检测，并通过 `GET /api/opportunities/{id}/intelligence/risks` 查询。推荐动作默认只作为建议返回；只有明确确认，并对需要审批的动作提供 `approvalStatus=APPROVED` 时，才会写入 `actions`。每次运行同时写入 `agent_runs` 和 `opportunity_agent_runs`，并保留 Forecast、风险和 Action 的关联。

风险复核接口：`POST /api/opportunity-intelligence/risks/{id}:acknowledge`、`.../{id}:resolve`、`.../{id}:false-positive`。

## 销售语音与图片识别适配层

`media_adapters.py` 提供供应商无关的 `TranscriptionAdapter`、`OCRAdapter` 和 `VisionExtractionAdapter` 接口，并内置可测试的 Mock 实现。请求和响应统一包含超时、尝试次数、错误码、可重试标记、置信度、原始文件引用和适配器版本。

相关接口：

- `POST /api/media/adapters/transcribe`、`/ocr`、`/vision-extraction`；
- `POST /api/voice-recordings`、`POST /api/voice-recordings/{id}/transcribe`、`/extract`；
- `GET /api/media/runs/{id}`、`POST /api/media/runs/{id}/retry`。

语音抽取结果进入 `FactCandidate`，图片识别结果进入现有 `discovery_candidates` 和候选草稿；正式客户、项目和商机仍需人工确认。低置信度、字段冲突、重复商机和适配器失败都会保留原始证据并进入审核或重试路径，不绑定具体第三方服务。
