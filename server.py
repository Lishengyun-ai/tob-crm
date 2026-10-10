import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB_DIR = ROOT / "data"
DB_PATH = DB_DIR / "crm.sqlite3"
OUTPUTS = ROOT / "outputs"

SEED_OPPORTUNITIES = [
    ("华东区域数字化营销项目", "华东建材集团", "方案与报价", "1280000", "制造业", "李盛云", "客户已确认营销自动化与渠道协同需求，等待最终方案评审。", "预算审批节点尚未确认", "准备方案评审会议", "交易数据,CRM通用"),
    ("星河零售会员运营平台", "星河商业集团", "需求确认", "860000", "零售行业", "王敏", "已完成业务访谈，客户关注会员分层、复购预测与活动归因。", "关键用户尚未全部参与", "补充客户成功案例", "客户洞察,行业语义"),
    ("南方能源供应链协同", "南方能源", "初步接触", "2400000", "CRM通用", "赵一", "来自伙伴推荐的集团级线索，正在确认采购范围与决策链。", "决策链不完整", "识别经济买家", "伙伴引荐,集团客户"),
    ("远景科技售后服务升级", "远景科技", "商务谈判", "620000", "高科技", "陈晨", "技术方案和报价已通过，正在确认合同条款与交付周期。", "交付资源需要锁定", "发起合同审批", "服务管理,项目型"),
    ("海岳地产客户经营平台", "海岳地产", "赢单", "1050000", "地产行业", "李盛云", "合同已签署，进入首期交付准备阶段。", "", "创建项目与交付计划", "赢单,交付准备"),
]

SEED_AGENTS = [
    ("customer-insight", "客户洞察 Agent", "客户开发", "从客户、商机、关系和经营指标生成画像、评分、机会与风险洞察。", "客户画像生成,客户评分计算,机会识别,风险扫描", "客户画像,涂料客户增长潜力模型,采购金额增长归因"),
    ("development-strategy", "客户开发策略 Agent", "客户开发", "结合客户 AT 阶段和涂料行业策略，生成突破路径、关键人策略与 30/60/90 天计划。", "开发目标拆解,工程入口识别,设计突破,方案植入,样板验证,关键人地图,30/60/90行动计划", "客户出货目标达成阈值,高潜工程客户增购策略,工程涂料项目推进 SOP"),
    ("visit-script", "拜访话术 Agent", "销售执行", "根据客户角色、当前 AT 阶段和商机风险，生成开场、提问与价值表达。", "开场话术,需求提问,价值表达,异议回应", "客户画像,涂料行业术语,商机关系图谱"),
    ("solution", "方案 Agent", "销售执行", "基于基材、应用场景、产品体系和客户目标推荐涂料解决方案与案例。", "场景分析,产品体系匹配,解决方案推荐,案例匹配,用量测算", "涂料产品,涂布率,工程涂料项目推进 SOP"),
    ("presentation", "PPT Agent", "销售执行", "将客户画像、方案、价值测算和竞争信息组织成客户交流材料与汇报大纲。", "客户交流材料,汇报方案,价值测算,一页纸摘要", "客户画像,采购金额,高潜工程客户增购策略"),
    ("competition", "竞争策略 Agent", "销售执行", "识别竞品、价格、关系和供应商准入风险，给出涂料商机突破打法。", "竞品分析,竞争位势,价格策略,突破打法", "商机关系图谱,涂料报价审批规则,采购金额增长归因"),
    ("opportunity-progress", "商机推进 Agent", "商机诊断", "识别商机所处 AT 阶段、缺失条件和下一步动作，推动商机形成可验证的业务事件。", "AT阶段判断,阶段准入校验,下一步动作,风险提示,业务事件记录", "推进涂料商机,样板验证完成,工程涂料项目推进 SOP"),
    ("win-loss-review", "赢单/输单复盘 Agent", "商机诊断", "复盘赢单、输单和样板验证结果，将经验沉淀为可复用的策略与知识。", "赢单复盘,输单归因,最佳实践提炼,知识库沉淀", "采购金额增长归因,商机关系图谱,高潜工程客户增购策略"),
]

def connect():
    DB_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          customer TEXT NOT NULL,
          stage TEXT NOT NULL,
          amount INTEGER NOT NULL DEFAULT 0,
          business_type TEXT NOT NULL,
          owner TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          risk TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          source_category TEXT NOT NULL DEFAULT '内部信息',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_fields (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          field_name TEXT NOT NULL,
          field_type TEXT NOT NULL,
          field_value TEXT NOT NULL,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS business_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          opportunity_id INTEGER NOT NULL,
          event_type TEXT NOT NULL,
          message TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_assets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          category TEXT NOT NULL,
          asset_type TEXT NOT NULL,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          badges TEXT NOT NULL DEFAULT '',
          fields_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agents (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          scene TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '已启用',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_skills (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT NOT NULL,
          name TEXT NOT NULL,
          skill_type TEXT NOT NULL DEFAULT 'Skill',
          description TEXT NOT NULL DEFAULT '',
          linked_assets TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          agent_id TEXT NOT NULL,
          opportunity_id INTEGER,
          input_json TEXT NOT NULL DEFAULT '{}',
          result TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'completed',
          created_at TEXT NOT NULL,
          FOREIGN KEY(agent_id) REFERENCES agents(id),
          FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
        );
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(opportunities)").fetchall()}
        if "source_category" not in columns:
            db.execute("ALTER TABLE opportunities ADD COLUMN source_category TEXT NOT NULL DEFAULT '内部信息'")
        now = datetime.now(timezone.utc).isoformat()
        count = db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        if count == 0:
            for row in SEED_OPPORTUNITIES:
                name, customer, stage, amount, business_type, owner, description, risk, next_action, tags = row
                cur = db.execute("""INSERT INTO opportunities
                    (name, customer, stage, amount, business_type, owner, description, risk, next_action, source_category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, customer, stage, int(amount), business_type, owner, description, risk, next_action, "内部信息", now, now))
                oid = cur.lastrowid
                for tag in tags.split(','):
                    db.execute("INSERT INTO semantic_fields (opportunity_id, field_name, field_type, field_value) VALUES (?, ?, ?, ?)", (oid, "业务标签", "semantic_tag", tag))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, "created", "商机对象已初始化", now))
        agent_count = db.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        if agent_count == 0:
            for agent_id, name, scene, description, skills, assets in SEED_AGENTS:
                db.execute("INSERT INTO agents (id, name, scene, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (agent_id, name, scene, description, now, now))
                for skill in skills.split(','):
                    db.execute("INSERT INTO agent_skills (agent_id, name, description, linked_assets) VALUES (?, ?, ?, ?)", (agent_id, skill, f"{skill}：读取客户、商机与涂料行业语义后生成可解释结果。", assets))

def serialize(row):
    return {
        "id": row["id"], "name": row["name"], "customer": row["customer"], "stage": row["stage"],
        "amount": row["amount"], "businessType": row["business_type"], "owner": row["owner"],
        "description": row["description"], "risk": row["risk"], "nextAction": row["next_action"], "sourceCategory": row["source_category"],
        "tags": [x["field_value"] for x in row.get("tags", [])] if isinstance(row, dict) else [],
    }

def get_opportunity(db, oid):
    row = db.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["tags"] = [dict(x) for x in db.execute("SELECT * FROM semantic_fields WHERE opportunity_id = ?", (oid,)).fetchall()]
    return item

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        with connect() as db:
            if path == "/api/health":
                return self.send_json({"status": "ok", "database": str(DB_PATH)})
            if path == "/api/opportunities":
                rows = db.execute("SELECT * FROM opportunities ORDER BY updated_at DESC, id DESC").fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    item["tags"] = [x["field_value"] for x in db.execute("SELECT field_value FROM semantic_fields WHERE opportunity_id = ?", (row["id"],)).fetchall()]
                    result.append(item)
                return self.send_json(result)
            if path.startswith("/api/opportunities/"):
                parts = path.strip("/").split("/")
                try:
                    oid = int(parts[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if len(parts) == 4 and parts[3] == "events":
                    events = db.execute("SELECT * FROM business_events WHERE opportunity_id = ? ORDER BY created_at DESC", (oid,)).fetchall()
                    return self.send_json([dict(x) for x in events])
                item = get_opportunity(db, oid)
                return self.send_json(item or {"error": "opportunity not found"}, 200 if item else 404)
            if path == "/api/semantic-assets":
                rows = db.execute("SELECT * FROM semantic_assets ORDER BY updated_at DESC, id DESC").fetchall()
                return self.send_json([{**dict(row), "badges": json.loads(row["badges"] or "[]"), "fields": json.loads(row["fields_json"] or "[]")} for row in rows])
            if path == "/api/agents":
                agents = []
                for row in db.execute("SELECT * FROM agents ORDER BY scene, id").fetchall():
                    item = dict(row)
                    item["skills"] = [dict(x) for x in db.execute("SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (row["id"],)).fetchall()]
                    agents.append(item)
                return self.send_json(agents)
            if path.startswith("/api/agents/"):
                agent_id = path.strip("/").split("/")[2]
                row = db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
                if not row:
                    return self.send_json({"error": "agent not found"}, 404)
                item = dict(row)
                item["skills"] = [dict(x) for x in db.execute("SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY id", (agent_id,)).fetchall()]
                return self.send_json(item)
        if path == "/" or path == "/index.html":
            return self.serve_file(OUTPUTS / "index.html", "text/html; charset=utf-8")
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        now = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            if path == "/api/opportunities":
                required = ["name", "customer", "stage"]
                if any(not str(data.get(k, "")).strip() for k in required):
                    return self.send_json({"error": "name, customer and stage are required"}, 400)
                cur = db.execute("""INSERT INTO opportunities
                    (name, customer, stage, amount, business_type, owner, description, risk, next_action, source_category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                        data["name"], data["customer"], data["stage"], int(data.get("amount", 0) or 0), data.get("businessType", "CRM通用"),
                        data.get("owner", "李盛云"), data.get("description", "刚刚创建，等待补充商机背景与业务需求。"), data.get("risk", "待完善业务信息"), data.get("nextAction", "补充商机语义字段"), data.get("sourceCategory", "内部信息"), now, now))
                oid = cur.lastrowid
                tags = data.get("tags", ["新建对象"])
                for tag in tags:
                    db.execute("INSERT INTO semantic_fields (opportunity_id, field_name, field_type, field_value) VALUES (?, ?, ?, ?)", (oid, "业务标签", "semantic_tag", tag))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, "created", "商机对象已创建，已生成语义字段", now))
                return self.send_json(get_opportunity(db, oid), 201)
            if path.startswith("/api/opportunities/") and path.endswith("/events"):
                try:
                    oid = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                if not db.execute("SELECT 1 FROM opportunities WHERE id = ?", (oid,)).fetchone():
                    return self.send_json({"error": "opportunity not found"}, 404)
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, data.get("eventType", "action"), data.get("message", "业务动作已记录"), now))
                db.execute("UPDATE opportunities SET updated_at = ? WHERE id = ?", (now, oid))
                return self.send_json({"status": "recorded"}, 201)
            if path == "/api/semantic-assets":
                required = ["category", "name", "description"]
                if any(not str(data.get(k, "")).strip() for k in required):
                    return self.send_json({"error": "category, name and description are required"}, 400)
                cur = db.execute("""INSERT INTO semantic_assets
                    (category, asset_type, name, description, badges, fields_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                        data["category"], data.get("assetType", data["category"]), data["name"], data["description"],
                        json.dumps(data.get("badges", ["新增资产"]), ensure_ascii=False), json.dumps(data.get("fields", []), ensure_ascii=False), now, now))
                return self.send_json({"id": cur.lastrowid, **data, "badges": data.get("badges", ["新增资产"]), "fields": data.get("fields", [])}, 201)
            if path.startswith("/api/opportunities/") and path.endswith("/stage"):
                try:
                    oid = int(path.strip("/").split("/")[2])
                except (IndexError, ValueError):
                    return self.send_json({"error": "invalid opportunity id"}, 400)
                row = db.execute("SELECT stage FROM opportunities WHERE id = ?", (oid,)).fetchone()
                if not row:
                    return self.send_json({"error": "opportunity not found"}, 404)
                required = data.get("required", {})
                missing = [key for key, value in required.items() if not str(value).strip()]
                if missing:
                    return self.send_json({"error": "stage fields required", "missing": missing}, 400)
                new_stage = data.get("stage", row["stage"])
                db.execute("UPDATE opportunities SET stage = ?, updated_at = ? WHERE id = ?", (new_stage, now, oid))
                db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (oid, "stage_changed", f"商机阶段由 {row['stage']} 转换为 {new_stage}，阶段字段已校验", now))
                return self.send_json({"status": "converted", "stage": new_stage, "missing": []}, 200)
            if path.startswith("/api/agents/") and path.endswith("/run"):
                agent_id = path.strip("/").split("/")[2]
                if not db.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone():
                    return self.send_json({"error": "agent not found"}, 404)
                opportunity_id = data.get("opportunityId")
                result = data.get("result") or "已完成语义分析，生成待确认的客户开发建议。"
                cur = db.execute("INSERT INTO agent_runs (agent_id, opportunity_id, input_json, result, created_at) VALUES (?, ?, ?, ?, ?)", (agent_id, opportunity_id, json.dumps(data, ensure_ascii=False), result, now))
                if opportunity_id:
                    db.execute("INSERT INTO business_events (opportunity_id, event_type, message, created_at) VALUES (?, ?, ?, ?)", (opportunity_id, "agent_run", f"{agent_id} 已运行：{result}", now))
                return self.send_json({"id": cur.lastrowid, "agentId": agent_id, "result": result, "status": "completed"}, 201)
        return self.send_json({"error": "not found"}, 404)

    def serve_file(self, path, content_type):
        if not path.exists():
            return self.send_json({"error": "file not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_db()

    import os
    port = int(os.environ.get("PORT", 8765))

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        Handler
    )

    print(f"CRM backend running on port {port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()