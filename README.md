# 立邦 ToB CRM 原型

面向涂料行业的 ToB CRM 原型，包含商机工作台、客户360、客户开发 AT 阶段、语义管理、Agent Studio 和 SQLite 后台。

## 本地运行

```powershell
python server.py
```

打开 <http://127.0.0.1:8765/>

## 目录说明

- `outputs/index.html`：CRM 原型界面
- `server.py`：Python 标准库后台和 SQLite 接口
- `ai-native-crm-architecture.svg`：AI 原生 CRM 架构图
- `ai-native-crm-design-notes.md`：架构设计说明

## 部署说明

GitHub Pages 适合托管静态原型页面；`server.py` 和 SQLite 需要部署到支持 Python 的服务环境，才能启用数据持久化和 Agent 接口。
