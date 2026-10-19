"""语义管理中心后端基础设施。

语义资源保存定义与治理元数据，不复制 CRM 业务实例。实体、关系、属性和规则
优先引用已有 ontology_* 目录；其余语义配置以 resource_type 区分，统一走版本
和发布流程，避免为每一种配置重复建设一套 CRUD。
"""

import json
import re
import csv
import hashlib
import io
from datetime import datetime, timezone


RESOURCE_TYPES = {
    "entity", "relation", "term", "action", "event", "rule", "process",
    "metric", "dimension", "target", "analysis_model", "attribution_model", "strategy",
}
RESOURCE_STATUSES = {"draft", "validated", "published", "inactive", "retired"}
PACKAGE_STATUSES = {"draft", "active", "inactive"}
VERSION_STATUSES = {"draft", "validated", "published", "retired"}
DSL_OPERATORS = {
    "eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "is_null",
    "contains", "starts_with", "between", "and", "or", "not", "count", "sum", "avg",
    "days_since",
}
DSL_ACTIONS = {"return_value", "return_warning", "create_recommendation", "create_action_draft", "request_review", "route_to_agent", "emit_event"}
RULE_FIELDS = {"stage", "business_type", "opportunity.stage", "opportunity.project_id", "opportunity.project_section_id", "opportunity.business_type", "duplicate.status", "duplicate.probability", "required", "required.projectName", "required.customer", "required.source", "required.duplicateStatus", "required.projectType", "customer_id", "project_id", "key_contacts", "relationship_roles", "relationship_roles.design_institute", "relationship_roles.budget_approver", "relationship_roles.technical_spec_influencer", "need_themes", "evidence"}
METRIC_FIELDS = {"amount", "stage", "stage_sequence", "days_in_stage", "due_at", "completed_at", "task_status", "person_role", "person_influence", "person_support", "opportunity_id", "project_id"}
METRIC_OPS = {"sum", "count", "avg", "min", "max", "add", "sub", "mul", "div", "if", "field", "literal"}
# 语义编码与本体编码保持一致：允许大小写字母开头，兼容企业级大写编码。
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,100}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_semantic_management_schema(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS semantic_domains (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL UNIQUE,
          name_zh TEXT NOT NULL,
          parent_id INTEGER,
          scope_type TEXT NOT NULL DEFAULT 'global',
          owner_role TEXT NOT NULL DEFAULT 'semantic_admin',
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(parent_id) REFERENCES semantic_domains(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS semantic_packages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          domain_id INTEGER NOT NULL,
          code TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          current_version_id INTEGER,
          status TEXT NOT NULL DEFAULT 'draft',
          owner_role TEXT NOT NULL DEFAULT 'semantic_editor',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(domain_id) REFERENCES semantic_domains(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS semantic_package_versions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          package_id INTEGER NOT NULL,
          version TEXT NOT NULL,
          base_version_id INTEGER,
          status TEXT NOT NULL DEFAULT 'draft',
          change_summary TEXT NOT NULL DEFAULT '',
          created_by TEXT NOT NULL,
          validated_by TEXT,
          published_by TEXT,
          published_at TEXT,
          created_at TEXT NOT NULL,
          UNIQUE(package_id, version),
          FOREIGN KEY(package_id) REFERENCES semantic_packages(id) ON DELETE CASCADE,
          FOREIGN KEY(base_version_id) REFERENCES semantic_package_versions(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_resources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          domain_id INTEGER NOT NULL,
          package_id INTEGER,
          resource_type TEXT NOT NULL,
          code TEXT NOT NULL,
          name_zh TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          payload_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'draft',
          version TEXT NOT NULL DEFAULT '0.1.0',
          source_ref TEXT NOT NULL DEFAULT '',
          override_of_id INTEGER,
          created_by TEXT NOT NULL,
          updated_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(domain_id, resource_type, code, version),
          FOREIGN KEY(domain_id) REFERENCES semantic_domains(id) ON DELETE RESTRICT,
          FOREIGN KEY(package_id) REFERENCES semantic_packages(id) ON DELETE SET NULL,
          FOREIGN KEY(override_of_id) REFERENCES semantic_resources(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_package_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          version_id INTEGER NOT NULL,
          resource_id INTEGER NOT NULL,
          operation TEXT NOT NULL DEFAULT 'add',
          checksum TEXT NOT NULL DEFAULT '',
          UNIQUE(version_id, resource_id),
          FOREIGN KEY(version_id) REFERENCES semantic_package_versions(id) ON DELETE CASCADE,
          FOREIGN KEY(resource_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_asset_references (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_asset_id INTEGER NOT NULL,
          target_asset_id INTEGER NOT NULL,
          reference_type TEXT NOT NULL,
          required INTEGER NOT NULL DEFAULT 0,
          version TEXT NOT NULL DEFAULT '1.0.0',
          source_version TEXT NOT NULL DEFAULT '',
          target_version TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(source_asset_id, target_asset_id, reference_type, version),
          FOREIGN KEY(source_asset_id) REFERENCES semantic_resources(id) ON DELETE CASCADE,
          FOREIGN KEY(target_asset_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_asset_refs_source ON semantic_asset_references(source_asset_id, status);
        CREATE INDEX IF NOT EXISTS idx_semantic_asset_refs_target ON semantic_asset_references(target_asset_id, status);
        CREATE TABLE IF NOT EXISTS semantic_release_records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          version_id INTEGER NOT NULL,
          action TEXT NOT NULL,
          actor TEXT NOT NULL,
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          FOREIGN KEY(version_id) REFERENCES semantic_package_versions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_object_mappings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          semantic_resource_id INTEGER NOT NULL,
          target_type TEXT NOT NULL,
          target_ref TEXT NOT NULL,
          source_table TEXT NOT NULL DEFAULT '',
          source_pk TEXT NOT NULL DEFAULT 'id',
          attribute_mapping_json TEXT NOT NULL DEFAULT '{}',
          permission_json TEXT NOT NULL DEFAULT '{}',
          filter_json TEXT NOT NULL DEFAULT '{}',
          validation_status TEXT NOT NULL DEFAULT 'pending',
          validation_errors_json TEXT NOT NULL DEFAULT '[]',
          runtime_usable INTEGER NOT NULL DEFAULT 0,
          version TEXT NOT NULL DEFAULT '0.1.0',
          status TEXT NOT NULL DEFAULT 'draft',
          created_by TEXT NOT NULL,
          updated_by TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(semantic_resource_id, version),
          FOREIGN KEY(semantic_resource_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_process_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          resource_id INTEGER NOT NULL,
          subject_type TEXT NOT NULL,
          subject_id INTEGER NOT NULL,
          mode TEXT NOT NULL DEFAULT 'recommendation',
          status TEXT NOT NULL DEFAULT 'in_progress',
          results_json TEXT NOT NULL DEFAULT '{}',
          evidence_json TEXT NOT NULL DEFAULT '[]',
          actor TEXT NOT NULL,
          created_at TEXT NOT NULL,
          completed_at TEXT,
          FOREIGN KEY(resource_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS semantic_strategy_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          resource_id INTEGER NOT NULL,
          subject_type TEXT NOT NULL,
          subject_id INTEGER NOT NULL,
          adoption_status TEXT NOT NULL DEFAULT 'recommended',
          execution_status TEXT NOT NULL DEFAULT 'not_started',
          result_json TEXT NOT NULL DEFAULT '{}',
          evidence_json TEXT NOT NULL DEFAULT '[]',
          confidence REAL NOT NULL DEFAULT 0,
          actor TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(resource_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_resources_lookup ON semantic_resources(domain_id, resource_type, status, code);
        CREATE INDEX IF NOT EXISTS idx_semantic_resources_package ON semantic_resources(package_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_semantic_versions_package ON semantic_package_versions(package_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_semantic_object_mappings_resource ON semantic_object_mappings(semantic_resource_id, status, runtime_usable);
        CREATE TABLE IF NOT EXISTS semantic_import_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, file_type TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'preview', mapping_json TEXT NOT NULL DEFAULT '{}',
          source_hash TEXT NOT NULL, preview_json TEXT NOT NULL DEFAULT '{}', errors_json TEXT NOT NULL DEFAULT '[]',
          stats_json TEXT NOT NULL DEFAULT '{}', actor TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS semantic_search_indexes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_code TEXT NOT NULL DEFAULT '', resource_type TEXT NOT NULL DEFAULT '',
          version_from TEXT NOT NULL DEFAULT '', version_to TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
          object_count INTEGER NOT NULL DEFAULT 0, last_built_at TEXT, error_message TEXT NOT NULL DEFAULT '',
          last_mode TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS semantic_search_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT, index_id INTEGER NOT NULL, resource_id INTEGER NOT NULL,
          resource_version TEXT NOT NULL, domain_code TEXT NOT NULL, resource_type TEXT NOT NULL,
          fields_json TEXT NOT NULL DEFAULT '{}', text_content TEXT NOT NULL DEFAULT '', indexed_at TEXT NOT NULL,
          UNIQUE(index_id, resource_id, resource_version),
          FOREIGN KEY(index_id) REFERENCES semantic_search_indexes(id) ON DELETE CASCADE,
          FOREIGN KEY(resource_id) REFERENCES semantic_resources(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_search_documents_text ON semantic_search_documents(index_id, text_content);
        """
    )
    # 统一 SemanticAsset 契约需要显式保存主体/对象引用；保留旧表并以迁移方式补列。
    resource_columns = {row[1] for row in db.execute("PRAGMA table_info(semantic_resources)").fetchall()}
    for name in ("subject_refs_json", "object_refs_json"):
        if name not in resource_columns:
            db.execute(f"ALTER TABLE semantic_resources ADD COLUMN {name} TEXT NOT NULL DEFAULT '[]'")
    t = now_iso()
    for code, name, parent in (("CRM_COMMON", "CRM 通用语义域", None), ("TUB_PAINT", "涂料行业语义域", "CRM_COMMON"), ("NIPPON_ENTERPRISE", "立邦企业语义域", "TUB_PAINT")):
        parent_id = db.execute("SELECT id FROM semantic_domains WHERE code=?", (parent,)).fetchone()[0] if parent else None
        db.execute("INSERT OR IGNORE INTO semantic_domains(code,name_zh,parent_id,scope_type,created_at,updated_at) VALUES(?,?,?,?,?,?)", (code, name, parent_id, "global" if not parent else "industry" if code == "TUB_PAINT" else "enterprise", t, t))
    # 补齐幂等种子之间的父子引用。
    db.execute("UPDATE semantic_domains SET parent_id=(SELECT id FROM semantic_domains WHERE code='CRM_COMMON') WHERE code='TUB_PAINT' AND parent_id IS NULL")
    db.execute("UPDATE semantic_domains SET parent_id=(SELECT id FROM semantic_domains WHERE code='TUB_PAINT') WHERE code='NIPPON_ENTERPRISE' AND parent_id IS NULL")


def _json(value, field="payload"):
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field}必须是有效 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field}必须是 JSON 对象")
    return value


def _validate_dsl(node, path="$"):
    if isinstance(node, list):
        if len(node) > 100:
            raise ValueError("DSL 数组长度不能超过 100")
        for i, item in enumerate(node):
            _validate_dsl(item, f"{path}[{i}]")
        return
    if not isinstance(node, dict):
        return
    if any(key in node for key in ("eval", "exec", "sql", "query", "python")):
        raise ValueError(f"{path}包含禁止的执行字段")
    if "op" in node and node["op"] not in DSL_OPERATORS:
        raise ValueError(f"不支持 DSL 操作符: {node['op']}")
    if node.get("type") == "sql" or node.get("action") in {"write_sql", "execute_sql"}:
        raise ValueError("DSL 不允许 SQL 或任意写入动作")
    for key, value in node.items():
        _validate_dsl(value, f"{path}.{key}")


def validate_rule_ast(ast):
    """校验规则 AST，只允许已登记业务字段和白名单操作符。"""
    ast = _json(ast, "expression")
    _validate_dsl(ast, "$")
    def walk(node):
        if isinstance(node, list):
            for item in node: walk(item)
        elif isinstance(node, dict):
            if "field" in node and node["field"] not in RULE_FIELDS: raise ValueError(f"不允许的规则字段: {node['field']}")
            for value in node.values(): walk(value)
    walk(ast)
    return ast


def evaluate_rule_ast(ast, context):
    """解释执行结构化 AST；不使用 eval、SQL 或动态代码。"""
    ast = validate_rule_ast(ast)
    def value(field):
        if field == "required": return context.get("required", {})
        current = context
        for part in field.split("."):
            if isinstance(current, dict): current = current.get(part)
            else: return None
        return current
    def run(node):
        if not isinstance(node, dict): return bool(node)
        op = node.get("op")
        if op in ("and", "or"): 
            vals = [run(x) for x in node.get("args", [])]
            return all(vals) if op == "and" else any(vals)
        if op == "not": return not run(node.get("arg"))
        if op == "exists": return value(node.get("field", "")) is not None
        left = value(node.get("field", "")); right = node.get("value")
        if op == "eq": return left == right
        if op == "neq": return left != right
        if op == "in": return left in (right or [])
        if op == "not_in": return left not in (right or [])
        if op in ("gt", "gte", "lt", "lte"):
            try: return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
            except TypeError: return False
        if op == "contains": return right in (left or []) or str(right) in str(left or "")
        if op == "is_null": return left is None
        # 兼容现有规则种子中的 stage/required/duplicateStatus 结构。
        if "stage" in node:
            stage_ok = value("stage") == node["stage"]
            required_ok = all(str(value(f"required.{key}") or "").strip() for key in node.get("required", []))
            return stage_ok and required_ok
        if "required" in node: return all(str(value(f"required.{key}") or "").strip() for key in node["required"])
        if "duplicateStatus" in node: return value("duplicate.status") == node["duplicateStatus"]
        return False
    return bool(run(ast))


def evaluate_business_rules(db, context, rule_codes=None):
    clauses = "status='active'"; args = []
    if rule_codes:
        placeholders = ",".join("?" for _ in rule_codes); clauses += f" AND code IN ({placeholders})"; args.extend(rule_codes)
    rows = db.execute(f"SELECT * FROM ontology_business_rules WHERE {clauses} ORDER BY priority DESC, id" if False else f"SELECT * FROM ontology_business_rules WHERE {clauses} ORDER BY id", args).fetchall()
    results = []
    for row in rows:
        try: ast = json.loads(row["expression_json"] or "{}")
        except json.JSONDecodeError: results.append({"code": row["code"], "valid": False, "error": "规则 AST 无效"}); continue
        try: matched = evaluate_rule_ast(ast, context)
        except ValueError as exc: results.append({"code": row["code"], "valid": False, "error": str(exc)}); continue
        results.append({"code": row["code"], "name": row["name_zh"], "ruleType": row["rule_type"], "matched": matched, "action": json.loads(row["action_json"] or "{}"), "description": row["description"]})
    return results


def validate_resource_payload(resource_type, payload):
    payload = _json(payload)
    if resource_type == "rule":
        _validate_dsl(payload.get("expression", payload.get("expression_json", {})), "$.expression")
        action = payload.get("action", payload.get("action_json", {}))
        _validate_dsl(action, "$.action")
        if isinstance(action, dict) and action.get("type") not in (None, *DSL_ACTIONS):
            raise ValueError("规则动作不在白名单中")
    if resource_type in {"action", "event"}:
        if not isinstance(payload, dict): raise ValueError("动作或事件 payload 必须是 JSON 对象")
        allowed_services = {"/api/actions", "create_action_record"}
        if resource_type == "action":
            service = payload.get("service") or payload.get("api")
            if service not in allowed_services: raise ValueError("动作只能绑定已登记的任务服务或 /api/actions")
            for key in ("parameters_schema", "output_schema"):
                if key in payload and not isinstance(payload[key], dict): raise ValueError(f"{key} 必须是 JSON Schema 对象")
            if payload.get("high_risk") and not payload.get("requires_confirmation", True): raise ValueError("高风险动作必须要求人工确认")
            if payload.get("idempotency") not in (None, "dedupe_key", "request_id", "none"): raise ValueError("不支持的幂等策略")
        else:
            if not payload.get("source"): raise ValueError("事件来源不能为空")
            if not isinstance(payload.get("payload_schema", {}), dict): raise ValueError("事件 Payload Schema 必须是对象")
            if payload.get("mode") not in (None, "sync", "async"): raise ValueError("事件模式只能是 sync 或 async")
    if resource_type in {"entity", "relation", "term", "metric", "dimension", "target", "analysis_model", "attribution_model", "strategy"}:
        refs = payload.get("references", [])
        if refs is not None and not isinstance(refs, list):
            raise ValueError("references 必须是数组")
    if resource_type == "process":
        steps = payload.get("steps", [])
        if not isinstance(steps, list) or not steps: raise ValueError("SOP 至少需要一个步骤")
        ids = [str(step.get("id", "")) for step in steps]
        if any(not step.get("id") or not step.get("name") for step in steps): raise ValueError("每个 SOP 步骤必须包含 id 和 name")
        if len(set(ids)) != len(ids): raise ValueError("SOP 步骤 id 不能重复")
        graph = {item: [] for item in ids}
        for step in steps:
            for nxt in step.get("next", []) or []:
                if nxt not in graph: raise ValueError(f"SOP 引用了不存在的后续步骤: {nxt}")
                graph[step["id"]].append(nxt)
        seen = set()
        def visit(node, stack=None):
            stack = stack or set()
            if node in stack: raise ValueError("SOP 步骤存在循环")
            if node in seen: return
            stack.add(node)
            for child in graph[node]: visit(child, stack.copy())
            seen.add(node)
        visit(ids[0])
        unreachable = set(ids) - seen
        if unreachable: raise ValueError(f"SOP 存在不可到达步骤: {','.join(sorted(unreachable))}")
        for step in steps:
            for key in ("goal", "description", "completion", "evidence_refs"):
                if key not in step: raise ValueError(f"步骤 {step['id']} 缺少字段 {key}")
        for ref in payload.get("references", []):
            if not isinstance(ref, dict) or ref.get("type") not in {"rule", "term", "action", "metric"} or not ref.get("code"):
                raise ValueError("SOP 引用必须是 rule、term、action 或 metric 且包含 code")
    if resource_type == "metric":
        formula = payload.get("formula", {})
        if not isinstance(formula, dict): raise ValueError("指标公式必须是 JSON AST")
        def check(node):
            if isinstance(node, list):
                for item in node: check(item)
            elif isinstance(node, dict):
                op = node.get("op")
                if op and op not in METRIC_OPS: raise ValueError(f"不支持的指标操作符: {op}")
                if "field" in node and node["field"] not in METRIC_FIELDS: raise ValueError(f"不允许的指标字段: {node['field']}")
                if any(key in node for key in ("eval", "sql", "query", "python")): raise ValueError("指标公式禁止动态执行字段")
                for value in node.values(): check(value)
        check(formula)
        if payload.get("zero_denominator") not in (None, "N/A"): raise ValueError("分母为零处理必须为 N/A")
        if payload.get("min_sample") is not None and int(payload.get("min_sample")) < 0: raise ValueError("最小样本量不能为负数")
    if resource_type == "dimension":
        if not payload.get("source_entity"): raise ValueError("维度必须映射来源实体")
        if not payload.get("source_attribute") and not payload.get("query_mapping"): raise ValueError("维度必须配置来源属性或查询映射")
    if resource_type == "target":
        if not payload.get("metric_code"): raise ValueError("目标必须关联指标")
        direction = payload.get("direction", "higher_better")
        try: target, warn, critical = float(payload.get("target_value")), float(payload.get("warning_threshold")), float(payload.get("critical_threshold"))
        except (TypeError, ValueError): raise ValueError("目标值和阈值必须是数字")
        if direction == "higher_better" and not (critical <= warn <= target): raise ValueError("正向指标阈值应满足 严重阈值 ≤ 预警阈值 ≤ 目标值")
        if direction == "lower_better" and not (target <= warn <= critical): raise ValueError("逆向指标阈值应满足 目标值 ≤ 预警阈值 ≤ 严重阈值")
    if resource_type == "analysis_model":
        if not isinstance(payload.get("input_features", []), list) or not payload.get("input_features"): raise ValueError("分析模型必须配置输入特征")
        if not isinstance(payload.get("output_schema"), dict): raise ValueError("分析模型必须配置输出 Schema")
        if payload.get("confidence_threshold") is not None and not 0 <= float(payload["confidence_threshold"]) <= 1: raise ValueError("置信度阈值必须在 0 到 1 之间")
        if payload.get("invocation") not in (None, "agent", "service", "manual"): raise ValueError("不支持的模型调用方式")
    if resource_type == "attribution_model":
        factors = payload.get("factors", [])
        if not isinstance(factors, list) or not factors: raise ValueError("归因图谱至少需要一个影响因素")
        for factor in factors:
            relation_type = factor.get("relation_type")
            if relation_type not in {"correlation", "hypothesis", "causal_evidence"}: raise ValueError("归因关系类型不正确")
            if relation_type == "causal_evidence" and not factor.get("evidence"): raise ValueError("因果关系必须提供证据")
            if "weight" in factor and relation_type != "causal_evidence" and factor.get("weight") not in (None, ""): raise ValueError("没有证据时不得填写影响权重")
    if resource_type == "strategy":
        for key in ("rationale", "evidence", "recommended_steps", "risk_boundary"):
            if not payload.get(key): raise ValueError(f"业务策略缺少 {key}")
        if not isinstance(payload.get("recommended_steps"), list): raise ValueError("推荐步骤必须是数组")
    return payload


def _domain(db, domain_id):
    row = db.execute("SELECT * FROM semantic_domains WHERE id=? AND status='active'", (domain_id,)).fetchone()
    if not row:
        raise LookupError("semantic domain not found")
    return row


def _package(db, package_id):
    row = db.execute("SELECT * FROM semantic_packages WHERE id=?", (package_id,)).fetchone()
    if not row:
        raise LookupError("semantic package not found")
    return row


def _resource_dict(row):
    item = dict(row)
    item["payload"] = _json(item.pop("payload_json"), "payload")
    for column, key in (("subject_refs_json", "subjectRefs"), ("object_refs_json", "objectRefs")):
        raw = item.pop(column, "[]")
        try:
            item[key] = json.loads(raw or "[]")
        except json.JSONDecodeError:
            item[key] = []
    # 统一契约字段；保留原 snake_case 字段以兼容旧调用方。
    item["assetType"] = item.get("resource_type")
    item["scope"] = {"domainId": item.get("domain_id")}
    item["version"] = item.get("version", "")
    item["status"] = item.get("status", "draft")
    item["sourceRef"] = item.get("source_ref", "")
    item["createdBy"] = item.get("created_by", "")
    item["updatedBy"] = item.get("updated_by", "")
    return item


def _mapping_dict(row):
    item = dict(row)
    for key in ("attribute_mapping_json", "permission_json", "filter_json", "validation_errors_json"):
        value = item.pop(key, "{}")
        try: item[key.replace("_json", "")] = json.loads(value or ("[]" if "errors" in key else "{}"))
        except json.JSONDecodeError: item[key.replace("_json", "")] = [] if "errors" in key else {}
    item["runtimeUsable"] = bool(item.pop("runtime_usable", 0))
    return item


def list_mappings(db, resource_id=None):
    sql = "SELECT * FROM semantic_object_mappings"; args = []
    if resource_id is not None:
        sql += " WHERE semantic_resource_id=?"; args.append(int(resource_id))
    sql += " ORDER BY id DESC"
    return [_mapping_dict(row) for row in db.execute(sql, args).fetchall()]


REFERENCE_TYPES = {"depends_on", "subject", "precondition", "uses", "derived_from", "triggers"}
REFERENCE_SOURCE_TYPES = {"rule", "term", "process", "metric", "event", "strategy", "action", "entity", "attribute", "relation"}


def _asset_scope(db, resource_id):
    row = db.execute("SELECT r.*, d.scope_type FROM semantic_resources r JOIN semantic_domains d ON d.id=r.domain_id WHERE r.id=?", (resource_id,)).fetchone()
    if not row: raise LookupError("semantic asset not found")
    return row


def _scope_allowed(source, target):
    return source["domain_id"] == target["domain_id"] or target["scope_type"] == "global"


def _reference_graph(db, include_draft=False):
    status_clause = "" if include_draft else " AND ar.status='published'"
    rows = db.execute("SELECT ar.source_asset_id, ar.target_asset_id FROM semantic_asset_references ar WHERE 1=1" + status_clause).fetchall()
    graph = {}
    for row in rows: graph.setdefault(row["source_asset_id"], set()).add(row["target_asset_id"])
    return graph


def _would_cycle(db, source_id, target_id):
    graph = _reference_graph(db, include_draft=True)
    graph.setdefault(source_id, set()).add(target_id)
    seen, stack = set(), {source_id}
    while stack:
        node = stack.pop()
        if node == source_id and node in seen: return True
        if node in seen: continue
        seen.add(node); stack.update(graph.get(node, set()))
    return source_id in graph.get(target_id, set()) or target_id == source_id


def create_asset_reference(db, data):
    source_id, target_id = int(data.get("sourceAssetId")), int(data.get("targetAssetId"))
    source, target = _asset_scope(db, source_id), _asset_scope(db, target_id)
    if source["resource_type"] not in REFERENCE_SOURCE_TYPES: raise ValueError("来源资产类型不支持引用")
    if target["status"] == "retired": raise ValueError("目标资产已退役")
    reference_type = str(data.get("referenceType") or "depends_on").strip()
    if reference_type not in REFERENCE_TYPES: raise ValueError("referenceType 不合法")
    if not _scope_allowed(source, target): raise ValueError("来源与目标资产作用域不兼容")
    if _would_cycle(db, source_id, target_id): raise ValueError("资产引用存在循环依赖")
    now = now_iso(); version = str(data.get("version") or "1.0.0")
    cur = db.execute("INSERT INTO semantic_asset_references(source_asset_id,target_asset_id,reference_type,required,version,source_version,target_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (source_id, target_id, reference_type, int(bool(data.get("required", False))), version, str(data.get("sourceVersion") or source["version"]), str(data.get("targetVersion") or target["version"]), str(data.get("status") or "draft"), now, now))
    return get_asset_reference(db, cur.lastrowid)


def get_asset_reference(db, reference_id):
    row = db.execute("SELECT * FROM semantic_asset_references WHERE id=?", (reference_id,)).fetchone()
    if not row: raise LookupError("semantic asset reference not found")
    item = dict(row); item["required"] = bool(item["required"]); item["sourceAssetId"] = item.pop("source_asset_id"); item["targetAssetId"] = item.pop("target_asset_id"); item["referenceType"] = item.pop("reference_type"); item["sourceVersion"] = item.pop("source_version"); item["targetVersion"] = item.pop("target_version"); return item


def list_asset_references(db, source_id=None, target_id=None, status=None):
    where, args = [], []
    if source_id is not None: where.append("source_asset_id=?"); args.append(int(source_id))
    if target_id is not None: where.append("target_asset_id=?"); args.append(int(target_id))
    if status: where.append("status=?"); args.append(status)
    sql = "SELECT * FROM semantic_asset_references" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC"
    return [get_asset_reference(db, row["id"]) for row in db.execute(sql, args).fetchall()]


def validate_asset_references(db, asset_id=None):
    rows = db.execute("SELECT * FROM semantic_asset_references" + (" WHERE source_asset_id=? OR target_asset_id=?" if asset_id else ""), (int(asset_id), int(asset_id)) if asset_id else ()).fetchall()
    errors = []
    for row in rows:
        try: source, target = _asset_scope(db, row["source_asset_id"]), _asset_scope(db, row["target_asset_id"])
        except LookupError: errors.append({"referenceId": row["id"], "error": "引用对象不存在"}); continue
        if row["status"] != "published": errors.append({"referenceId": row["id"], "error": "引用关系未发布"})
        if source["status"] != "published" or target["status"] != "published": errors.append({"referenceId": row["id"], "error": "引用存在未发布版本"})
        if not _scope_allowed(source, target): errors.append({"referenceId": row["id"], "error": "跨作用域非法引用"})
    try:
        graph = _reference_graph(db, include_draft=True); visiting, visited = set(), set()
        def visit(node):
            if node in visiting: raise ValueError("资产引用存在循环依赖")
            if node in visited: return
            visiting.add(node)
            for child in graph.get(node, set()): visit(child)
            visiting.remove(node); visited.add(node)
        for node in graph: visit(node)
    except ValueError as exc: errors.append({"error": str(exc)})
    return {"valid": not errors, "errors": errors, "references": [get_asset_reference(db, row["id"]) for row in rows]}


def _mapping_payload(data, current=None):
    current = current or {}
    target_type = str(data.get("targetType", current.get("target_type", ""))).strip()
    if target_type not in {"ontology_entity", "database_object", "business_api"}:
        raise ValueError("targetType 必须是 ontology_entity、database_object 或 business_api")
    target_ref = str(data.get("targetRef", current.get("target_ref", ""))).strip()
    if not target_ref: raise ValueError("targetRef is required")
    def obj(name, default):
        value = data.get(name, current.get(name + "_json", default))
        if isinstance(value, str):
            try: value = json.loads(value or json.dumps(default, ensure_ascii=False))
            except json.JSONDecodeError as exc: raise ValueError(f"{name}必须是有效 JSON") from exc
        if not isinstance(value, dict): raise ValueError(f"{name}必须是 JSON 对象")
        return value
    attrs = obj("attributeMapping", {})
    permission = obj("permission", {})
    filters = obj("filter", {})
    return target_type, target_ref, str(data.get("sourceTable", current.get("source_table", ""))).strip(), str(data.get("sourcePk", current.get("source_pk", "id"))).strip(), attrs, permission, filters


def _table_column_exists(db, table, column):
    if not table or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", column): return False
    return any(row[1] == column for row in db.execute(f"PRAGMA table_info({table})").fetchall())


def validate_mapping(db, mapping_id):
    row = db.execute("SELECT * FROM semantic_object_mappings WHERE id=?", (mapping_id,)).fetchone()
    if not row: raise LookupError("semantic mapping not found")
    resource = db.execute("SELECT * FROM semantic_resources WHERE id=? AND resource_type='entity'", (row["semantic_resource_id"],)).fetchone()
    errors = []
    if not resource: errors.append("映射目标必须关联 resource_type=entity 的语义实体")
    if row["target_type"] == "ontology_entity":
        if not db.execute("SELECT 1 FROM ontology_entities WHERE code=? AND status='active'", (row["target_ref"],)).fetchone(): errors.append("目标本体实体不存在或已停用")
    elif row["target_type"] == "database_object":
        if not _table_column_exists(db, row["source_table"], row["source_pk"]): errors.append("数据库对象或主键字段不存在")
    elif row["target_type"] == "business_api":
        allowed = {"/api/customers", "/api/projects", "/api/opportunities", "/api/people", "/api/actions", "/api/organizations", "/api/ontology/catalog"}
        if row["target_ref"] not in allowed: errors.append("业务 API 不在允许的只读映射清单中")
    try: attrs = json.loads(row["attribute_mapping_json"] or "{}")
    except json.JSONDecodeError: attrs = {}; errors.append("属性映射不是有效 JSON")
    if not isinstance(attrs, dict) or not attrs: errors.append("至少需要一条属性映射")
    if row["target_type"] == "database_object" and isinstance(attrs, dict):
        for source_column in attrs.values():
            if isinstance(source_column, str) and not _table_column_exists(db, row["source_table"], source_column): errors.append(f"数据库字段不存在: {source_column}")
    runtime = not errors and bool(resource and resource["status"] == "published")
    now = now_iso(); db.execute("UPDATE semantic_object_mappings SET validation_status=?,validation_errors_json=?,runtime_usable=?,updated_at=? WHERE id=?", ("passed" if not errors else "failed", json.dumps(errors, ensure_ascii=False), int(runtime), now, mapping_id))
    return _mapping_dict(db.execute("SELECT * FROM semantic_object_mappings WHERE id=?", (mapping_id,)).fetchone())


def create_mapping(db, data, actor):
    resource_id = int(data.get("semanticResourceId")); resource = db.execute("SELECT * FROM semantic_resources WHERE id=? AND resource_type='entity'", (resource_id,)).fetchone()
    if not resource: raise ValueError("semanticResourceId 必须引用实体资源")
    target_type, target_ref, table, pk, attrs, permission, filters = _mapping_payload(data)
    version = str(data.get("version") or "0.1.0"); now = now_iso(); actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    if db.execute("SELECT 1 FROM semantic_object_mappings WHERE semantic_resource_id=? AND version=?", (resource_id, version)).fetchone(): raise ValueError("该实体映射版本已存在")
    cur = db.execute("""INSERT INTO semantic_object_mappings(semantic_resource_id,target_type,target_ref,source_table,source_pk,attribute_mapping_json,permission_json,filter_json,version,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (resource_id, target_type, target_ref, table, pk, json.dumps(attrs, ensure_ascii=False), json.dumps(permission, ensure_ascii=False), json.dumps(filters, ensure_ascii=False), version, actor_id, actor_id, now, now))
    return validate_mapping(db, cur.lastrowid)


def update_mapping(db, mapping_id, data, actor):
    row = db.execute("SELECT * FROM semantic_object_mappings WHERE id=?", (mapping_id,)).fetchone()
    if not row: raise LookupError("semantic mapping not found")
    if row["status"] == "published": raise ValueError("已发布映射不可原地修改，请创建新版本")
    target_type, target_ref, table, pk, attrs, permission, filters = _mapping_payload(data, row)
    actor_id = actor if isinstance(actor, str) else actor.get("userId", "system"); now = now_iso()
    db.execute("UPDATE semantic_object_mappings SET target_type=?,target_ref=?,source_table=?,source_pk=?,attribute_mapping_json=?,permission_json=?,filter_json=?,updated_by=?,updated_at=? WHERE id=?", (target_type, target_ref, table, pk, json.dumps(attrs, ensure_ascii=False), json.dumps(permission, ensure_ascii=False), json.dumps(filters, ensure_ascii=False), actor_id, now, mapping_id))
    return validate_mapping(db, mapping_id)


def list_resources(db, resource_type=None, domain_id=None, package_id=None, status=None, search=None):
    where, args = [], []
    if resource_type:
        if resource_type not in RESOURCE_TYPES:
            raise ValueError("invalid resource type")
        where.append("resource_type=?"); args.append(resource_type)
    for column, value in (("domain_id", domain_id), ("package_id", package_id), ("status", status)):
        if value is not None and value != "":
            where.append(f"{column}=?"); args.append(value)
    if search:
        where.append("(code LIKE ? OR name_zh LIKE ? OR description LIKE ? OR payload_json LIKE ?)")
        token = f"%{search}%"; args.extend([token] * 4)
    sql = "SELECT * FROM semantic_resources" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at DESC, id DESC"
    return [_resource_dict(row) for row in db.execute(sql, args).fetchall()]


def parse_semantic_import(content, file_name):
    """仅支持 JSON/CSV，返回规范化行和逐行错误；不引入第三方解析器。"""
    suffix = str(file_name or '').lower().rsplit('.', 1)[-1] if '.' in str(file_name) else ''
    rows = []
    if suffix == 'json':
        try: raw = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc: return [], [{'row': 0, 'error': f'JSON 解析失败: {exc}'}]
        raw = raw.get('resources', raw) if isinstance(raw, dict) else raw
        if not isinstance(raw, list): return [], [{'row': 0, 'error': 'JSON 必须是数组或 resources 数组'}]
        rows = [(i + 1, item) for i, item in enumerate(raw)]
    elif suffix == 'csv':
        try: rows = [(i + 2, row) for i, row in enumerate(csv.DictReader(io.StringIO(content)))]
        except csv.Error as exc: return [], [{'row': 0, 'error': f'CSV 解析失败: {exc}'}]
    else:
        return [], [{'row': 0, 'error': '仅支持 .json 和 .csv'}]
    return rows, []


def preview_semantic_import(db, content, file_name, mapping=None, actor='system'):
    mapping = mapping or {}; rows, errors = parse_semantic_import(content, file_name)
    normalized, seen = [], set(); stats = {'total': len(rows), 'valid': 0, 'invalid': 0, 'conflicts': 0}
    canonical = {'resourceType': 'resourceType', 'resource_type': 'resourceType', 'code': 'code', 'nameZh': 'nameZh', 'name_zh': 'nameZh', 'description': 'description', 'domainCode': 'domainCode', 'domain_code': 'domainCode', 'version': 'version', 'payload': 'payload', 'payload_json': 'payload'}
    for row_no, raw in rows:
        if not isinstance(raw, dict): errors.append({'row': row_no, 'error': '每行必须是对象'}); stats['invalid'] += 1; continue
        item = {}
        for key, value in raw.items():
            target = mapping.get(key) or canonical.get(key) or key
            item[target] = value
        item['resourceType'] = str(item.get('resourceType') or '').strip(); item['code'] = str(item.get('code') or '').strip(); item['nameZh'] = str(item.get('nameZh') or '').strip(); item['domainCode'] = str(item.get('domainCode') or '').strip(); item['version'] = str(item.get('version') or '0.1.0')
        payload = item.get('payload', {})
        if isinstance(payload, str):
            try: payload = json.loads(payload or '{}')
            except json.JSONDecodeError: errors.append({'row': row_no, 'error': 'payload 不是有效 JSON'}); stats['invalid'] += 1; continue
        item['payload'] = payload
        row_errors = []
        if item['resourceType'] not in RESOURCE_TYPES: row_errors.append('resourceType 不合法')
        if not item['code']: row_errors.append('缺少 code')
        if not item['nameZh']: row_errors.append('缺少 nameZh')
        domain = db.execute('SELECT id FROM semantic_domains WHERE code=? AND status="active"', (item['domainCode'],)).fetchone() if item['domainCode'] else None
        if not domain: row_errors.append('语义域不存在或已停用')
        try: validate_resource_payload(item['resourceType'], payload)
        except (ValueError, TypeError) as exc: row_errors.append(str(exc))
        key = (item['domainCode'], item['resourceType'], item['code'], item['version'])
        if key in seen: row_errors.append('导入文件内重复对象')
        seen.add(key)
        existing = db.execute('SELECT status FROM semantic_resources WHERE domain_id=? AND resource_type=? AND code=? AND version=?', (domain['id'], item['resourceType'], item['code'], item['version'])).fetchone() if domain and item['resourceType'] in RESOURCE_TYPES and item['code'] else None
        if existing:
            row_errors.append('published_conflict' if existing['status'] == 'published' else 'draft_conflict'); stats['conflicts'] += 1
        if row_errors: errors.append({'row': row_no, 'code': item['code'], 'error': '; '.join(row_errors)}); stats['invalid'] += 1
        else: normalized.append(item); stats['valid'] += 1
    return {'fileName': file_name, 'sourceHash': hashlib.sha256(str(content).encode('utf-8')).hexdigest(), 'mapping': mapping, 'preview': normalized, 'errors': errors, 'stats': stats, 'actor': actor}


def confirm_semantic_import(db, preview, actor):
    if preview.get('errors'): raise ValueError('预览存在错误，不能确认导入')
    created = []
    for item in preview.get('preview', []):
        domain = db.execute('SELECT id FROM semantic_domains WHERE code=? AND status="active"', (item['domainCode'],)).fetchone()
        created.append(create_resource(db, {'domainId': domain['id'], 'resourceType': item['resourceType'], 'code': item['code'], 'nameZh': item['nameZh'], 'description': item.get('description', ''), 'payload': item.get('payload', {}), 'version': item.get('version', '0.1.0')}, actor))
    return {'created': created, 'stats': {'created': len(created), 'status': 'draft'}}


def _index_matches(row, query):
    q = str(query or '').lower(); fields = json.loads(row['fields_json'] or '{}'); matched = [k for k, v in fields.items() if q and q in str(v).lower()]
    return matched


def build_semantic_index(db, index_id, mode='full', actor='system'):
    index = db.execute('SELECT * FROM semantic_search_indexes WHERE id=?', (index_id,)).fetchone()
    if not index: raise LookupError('语义索引不存在')
    now = now_iso()
    try:
        if mode == 'full': db.execute('DELETE FROM semantic_search_documents WHERE index_id=?', (index_id,))
        clauses = ["r.status='published'"]; args = []
        if index['domain_code']: clauses.append('d.code=?'); args.append(index['domain_code'])
        if isinstance(actor, dict) and actor.get('allowedSemanticDomainCodes') is not None:
            allowed_domains = [str(x) for x in actor.get('allowedSemanticDomainCodes', [])]
            if not allowed_domains:
                db.execute('UPDATE semantic_search_indexes SET status="completed",object_count=0,last_built_at=?,error_message="",last_mode=?,updated_at=? WHERE id=?', (now, mode, now, index_id))
                return {'indexId': index_id, 'status': 'completed', 'objectCount': 0, 'mode': mode}
            clauses.append('d.code IN (' + ','.join('?' for _ in allowed_domains) + ')'); args.extend(allowed_domains)
        if index['resource_type']: clauses.append('r.resource_type=?'); args.append(index['resource_type'])
        if index['version_from']: clauses.append('r.version>=?'); args.append(index['version_from'])
        if index['version_to']: clauses.append('r.version<=?'); args.append(index['version_to'])
        rows = db.execute(f"SELECT r.*, d.code domain_code FROM semantic_resources r JOIN semantic_domains d ON d.id=r.domain_id WHERE {' AND '.join(clauses)}", args).fetchall()
        for row in rows:
            payload = json.loads(row['payload_json'] or '{}'); fields = {'code': row['code'], 'nameZh': row['name_zh'], 'description': row['description'], 'payload': json.dumps(payload, ensure_ascii=False)}
            db.execute('INSERT OR REPLACE INTO semantic_search_documents(index_id,resource_id,resource_version,domain_code,resource_type,fields_json,text_content,indexed_at) VALUES(?,?,?,?,?,?,?,?)', (index_id, row['id'], row['version'], row['domain_code'], row['resource_type'], json.dumps(fields, ensure_ascii=False), ' '.join(map(str, fields.values())), now))
        db.execute('UPDATE semantic_search_indexes SET status="completed",object_count=?,last_built_at=?,error_message="",last_mode=?,updated_at=? WHERE id=?', (len(rows), now, mode, now, index_id)); return {'indexId': index_id, 'status': 'completed', 'objectCount': len(rows), 'mode': mode}
    except Exception as exc:
        db.execute('UPDATE semantic_search_indexes SET status="failed",error_message=?,last_mode=?,updated_at=? WHERE id=?', (str(exc), mode, now, index_id)); return {'indexId': index_id, 'status': 'failed', 'error': str(exc)}


def search_semantic_index(db, index_id, query):
    index = db.execute('SELECT status FROM semantic_search_indexes WHERE id=?', (index_id,)).fetchone()
    if not index: raise LookupError('语义索引不存在')
    if index['status'] != 'completed': return []
    rows = db.execute('SELECT d.*, r.code, r.name_zh, r.version FROM semantic_search_documents d JOIN semantic_resources r ON r.id=d.resource_id AND r.status="published" WHERE d.index_id=? AND d.text_content LIKE ?', (index_id, f'%{query}%')).fetchall()
    return [{'resourceId': r['resource_id'], 'code': r['code'], 'nameZh': r['name_zh'], 'version': r['version'], 'domainCode': r['domain_code'], 'resourceType': r['resource_type'], 'matchedFields': _index_matches(r, query), 'reason': '匹配已发布语义资源的编码、名称、说明或结构化定义'} for r in rows]


def get_semantic_call_stats(db, start=None, end=None, agent_id=None, resource_id=None, version=None):
    where, args = [], []
    if start: where.append('created_at>=?'); args.append(start)
    if end: where.append('created_at<=?'); args.append(end)
    if agent_id: where.append('agent_id=?'); args.append(agent_id)
    rows = db.execute('SELECT agent_id,status,input_json,created_at FROM agent_runs' + (' WHERE ' + ' AND '.join(where) if where else ''), args).fetchall()
    groups = {}
    for row in rows:
        try: meta = json.loads(row['input_json'] or '{}')
        except json.JSONDecodeError: meta = {}
        rid, ver = meta.get('semanticResourceId'), meta.get('semanticVersion')
        if resource_id and str(rid) != str(resource_id): continue
        if version and str(ver) != str(version): continue
        key = (row['agent_id'], str(rid or ''), str(ver or '')); g = groups.setdefault(key, {'agentId': row['agent_id'], 'resourceId': rid, 'version': ver, 'callCount': 0, 'successCount': 0, 'latencies': [], 'errors': {}, 'lastCallAt': row['created_at']})
        g['callCount'] += 1; g['successCount'] += 1 if row['status'] == 'completed' else 0; g['lastCallAt'] = max(g['lastCallAt'], row['created_at'])
        if meta.get('latencyMs') is not None: g['latencies'].append(float(meta['latencyMs']))
        if row['status'] != 'completed': cat = meta.get('errorCategory', 'unknown'); g['errors'][cat] = g['errors'].get(cat, 0) + 1
    for g in groups.values():
        g['successRate'] = round(g['successCount'] / g['callCount'] * 100, 2) if g['callCount'] else 0
        latencies = g.pop('latencies', [])
        g['avgLatencyMs'] = round(sum(latencies) / len(latencies), 2) if latencies else None
    return list(groups.values())


def create_resource(db, data, actor):
    resource_type = str(data.get("assetType") or data.get("resourceType") or data.get("resource_type") or "").strip()
    code = str(data.get("code") or "").strip()
    name = str(data.get("nameZh") or data.get("name_zh") or "").strip()
    if resource_type not in RESOURCE_TYPES:
        raise ValueError("invalid resource type")
    if not CODE_RE.match(code):
        raise ValueError("code 格式不合法")
    if not name:
        raise ValueError("nameZh is required")
    domain_value = data.get("domainId") or (data.get("scope") or {}).get("domainId")
    if not domain_value and (data.get("scope") or {}).get("domainCode"):
        domain = db.execute("SELECT id FROM semantic_domains WHERE code=? AND status='active'", (str(data["scope"]["domainCode"]),)).fetchone()
        domain_value = domain["id"] if domain else None
    if domain_value is None:
        raise ValueError("domainId 或 scope.domainCode 是必填项")
    domain_id = int(domain_value)
    _domain(db, domain_id)
    package_id = data.get("packageId")
    if package_id:
        _package(db, int(package_id))
    payload = validate_resource_payload(resource_type, data.get("payload", data.get("payload_json", {})))
    version = str(data.get("version") or "0.1.0")
    subject_refs = data.get("subjectRefs", (data.get("subject") or {}).get("objectRefs", []))
    object_refs = data.get("objectRefs", (data.get("subject") or {}).get("fieldRefs", []))
    if not isinstance(subject_refs, list) or not isinstance(object_refs, list):
        raise ValueError("subjectRefs 和 objectRefs 必须是数组")
    if db.execute("SELECT 1 FROM semantic_resources WHERE domain_id=? AND resource_type=? AND code=? AND version=?", (domain_id, resource_type, code, version)).fetchone():
        raise ValueError("同一语义域内编码和版本已存在")
    now = now_iso()
    actor_id = str(actor if isinstance(actor, str) else actor.get("userId", "system"))
    cur = db.execute("""INSERT INTO semantic_resources(domain_id,package_id,resource_type,code,name_zh,description,payload_json,status,version,source_ref,override_of_id,created_by,updated_by,created_at,updated_at,subject_refs_json,object_refs_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (domain_id, package_id, resource_type, code, name, str(data.get("description") or ""), json.dumps(payload, ensure_ascii=False), "draft", version, str(data.get("sourceRef") or ""), data.get("overrideOfId"), actor_id, actor_id, now, now, json.dumps(subject_refs, ensure_ascii=False), json.dumps(object_refs, ensure_ascii=False)))
    return _resource_dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (cur.lastrowid,)).fetchone())


def update_resource(db, resource_id, data, actor):
    current = db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()
    if not current:
        raise LookupError("semantic resource not found")
    if current["status"] == "published":
        raise ValueError("已发布资源不可原地修改，请创建新版本或新草稿")
    resource_type = data.get("resourceType", current["resource_type"])
    payload = validate_resource_payload(resource_type, data.get("payload", current["payload_json"]))
    name = str(data.get("nameZh", current["name_zh"])).strip()
    if not name:
        raise ValueError("nameZh is required")
    now = now_iso(); actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    subject_refs = data.get("subjectRefs", json.loads(current["subject_refs_json"] or "[]"))
    object_refs = data.get("objectRefs", json.loads(current["object_refs_json"] or "[]"))
    if not isinstance(subject_refs, list) or not isinstance(object_refs, list): raise ValueError("subjectRefs 和 objectRefs 必须是数组")
    db.execute("UPDATE semantic_resources SET name_zh=?,description=?,payload_json=?,source_ref=?,subject_refs_json=?,object_refs_json=?,updated_by=?,updated_at=? WHERE id=?", (name, str(data.get("description", current["description"])), json.dumps(payload, ensure_ascii=False), str(data.get("sourceRef", current["source_ref"])), json.dumps(subject_refs, ensure_ascii=False), json.dumps(object_refs, ensure_ascii=False), actor_id, now, resource_id))
    return _resource_dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone())


def validate_resource(db, resource_id):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()
    if not row:
        raise LookupError("semantic resource not found")
    payload = validate_resource_payload(row["resource_type"], row["payload_json"])
    refs = payload.get("references", [])
    missing = []
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("type") or not ref.get("code"):
            raise ValueError("references 项必须包含 type 和 code")
        table = {"entity": "ontology_entities", "relation": "ontology_relation_definitions", "rule": "ontology_business_rules", "attribute": "ontology_attributes"}.get(ref["type"])
        if table:
            semantic_match = db.execute("SELECT 1 FROM semantic_resources WHERE resource_type=? AND code=? AND status='published'", (ref["type"], ref["code"])).fetchone()
            legacy_match = False
            if not semantic_match:
                try: legacy_match = bool(db.execute(f"SELECT 1 FROM {table} WHERE code=? AND status='active'", (ref["code"],)).fetchone())
                except Exception: legacy_match = False
            if not semantic_match and not legacy_match: missing.append(ref)
        if ref["type"] in {"action", "metric", "process", "strategy", "analysis_model", "attribution_model"} and not db.execute("SELECT 1 FROM semantic_resources WHERE resource_type=? AND code=? AND status='published'", (ref["type"], ref["code"])).fetchone(): missing.append(ref)
    if missing:
        raise ValueError("存在未找到或未启用的引用对象")
    if row["resource_type"] == "dimension":
        source = payload.get("source_entity")
        if source and not db.execute("SELECT 1 FROM ontology_entities WHERE code=? AND status='active'", (source,)).fetchone(): raise ValueError("维度来源实体不存在或已停用")
    if row["resource_type"] == "target":
        metric_code = payload.get("metric_code")
        if metric_code and not db.execute("SELECT 1 FROM semantic_resources WHERE resource_type='metric' AND code=? AND status='published'", (metric_code,)).fetchone(): raise ValueError("目标关联指标不存在或尚未发布")
    return {"valid": True, "resourceId": resource_id, "checkedReferences": len(refs)}


def preview_process(db, resource_id):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=? AND resource_type='process'", (resource_id,)).fetchone()
    if not row: raise LookupError("SOP 不存在")
    payload = _json(row["payload_json"]); validate_resource_payload("process", payload)
    return {"resourceId": resource_id, "code": row["code"], "name": row["name_zh"], "mode": payload.get("mode", "recommendation"), "steps": payload["steps"], "completion": payload.get("completion", {}), "references": payload.get("references", [])}


def check_process_completion(payload, results):
    completion = payload.get("completion", {}) if isinstance(payload, dict) else {}
    required = completion.get("required_steps", [step.get("id") for step in payload.get("steps", [])])
    completed = {str(item.get("step_id")) for item in (results or []) if item.get("status") == "completed"}
    missing = [step for step in required if str(step) not in completed]
    return {"complete": not missing, "missingSteps": missing, "requiredSteps": required}


def calculate_metric(db, resource_id, filters=None):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=? AND resource_type='metric'", (resource_id,)).fetchone()
    if not row: raise LookupError("指标不存在")
    payload = _json(row["payload_json"]); validate_resource_payload("metric", payload)
    code = row["code"]; filters = filters or {}; now = now_iso(); provenance = {"resourceId": resource_id, "metricCode": code, "version": row["version"], "calculatedAt": now, "filters": filters}
    if code == "weighted_opportunity_amount":
        rows = db.execute("SELECT amount, stage FROM opportunities").fetchall(); weights = {"初步接触": .2, "商机确认": .35, "商机跟踪": .5, "标前引导": .65, "招投标": .8, "商务谈判": .9, "赢单": 1.0}
        values = [float(r["amount"] or 0) * weights.get(r["stage"], .2) for r in rows]; sample = len(values); value = sum(values)
    elif code == "task_on_time_completion_rate":
        rows = db.execute("SELECT due_at, completed_at, status FROM actions WHERE status='completed' AND due_at IS NOT NULL").fetchall(); sample = len(rows); value = (sum(1 for r in rows if r["completed_at"] and r["completed_at"][:10] <= r["due_at"][:10]) / sample * 100) if sample else None
    elif code == "opportunity_stage_conversion_rate":
        total = db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]; won = db.execute("SELECT COUNT(*) FROM opportunities WHERE stage='赢单'").fetchone()[0]; sample = total; value = won / total * 100 if total else None
    elif code == "opportunity_stage_dwell_days":
        rows = db.execute("SELECT created_at, updated_at FROM opportunities").fetchall(); sample = len(rows); value = (sum(max(0, (datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00")) - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).total_seconds() / 86400) for r in rows) / sample) if sample else None
    elif code == "decision_role_coverage_rate":
        provenance["status"] = "待映射"; provenance["reason"] = "当前仓库尚未提供统一决策角色枚举和覆盖口径"; return {"value": None, "display": "待映射", "sampleSize": 0, "provenance": provenance}
    else:
        provenance["status"] = "待映射"; provenance["reason"] = "指标编码尚未绑定受控数据服务"; return {"value": None, "display": "待映射", "sampleSize": 0, "provenance": provenance}
    minimum = int(payload.get("min_sample", 1) or 1)
    if sample < minimum: return {"value": None, "display": "样本不足", "sampleSize": sample, "provenance": provenance}
    if value is None: return {"value": None, "display": "N/A", "sampleSize": sample, "provenance": provenance}
    return {"value": value, "display": value, "sampleSize": sample, "provenance": provenance}


def publish_resource(db, resource_id, actor):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()
    if not row: raise LookupError("semantic resource not found")
    validate_resource(db, resource_id)
    if row["status"] == "published": return _resource_dict(row)
    db.execute("UPDATE semantic_resources SET status='published',updated_by=?,updated_at=? WHERE id=?", (actor if isinstance(actor, str) else actor.get("userId", "system"), now_iso(), resource_id))
    return _resource_dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone())


def deactivate_resource(db, resource_id, actor):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()
    if not row:
        raise LookupError("semantic resource not found")
    db.execute("UPDATE semantic_resources SET status='inactive',updated_by=?,updated_at=? WHERE id=?", (actor if isinstance(actor, str) else actor.get("userId", "system"), now_iso(), resource_id))
    return _resource_dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone())


def retire_resource(db, resource_id, actor):
    row = db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()
    if not row:
        raise LookupError("semantic resource not found")
    actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    db.execute("UPDATE semantic_resources SET status='retired',updated_by=?,updated_at=? WHERE id=?", (actor_id, now_iso(), resource_id))
    return _resource_dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (resource_id,)).fetchone())


def validate_version(db, version_id):
    version = db.execute("SELECT * FROM semantic_package_versions WHERE id=?", (version_id,)).fetchone()
    if not version:
        raise LookupError("semantic version not found")
    items = db.execute("SELECT resource_id FROM semantic_package_items WHERE version_id=?", (version_id,)).fetchall()
    results = [validate_resource(db, row["resource_id"]) for row in items]
    resource_codes = {row["resource_id"]: db.execute("SELECT code FROM semantic_resources WHERE id=?", (row["resource_id"],)).fetchone()[0] for row in items}
    graph = {code: set() for code in resource_codes.values()}
    for resource_id, code in resource_codes.items():
        payload = _json(db.execute("SELECT payload_json FROM semantic_resources WHERE id=?", (resource_id,)).fetchone()[0])
        for ref in payload.get("references", []):
            if isinstance(ref, dict) and ref.get("type") == "resource" and ref.get("code") in graph:
                graph[code].add(ref["code"])
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting: raise ValueError("语义资源引用存在循环依赖")
        if node in visited: return
        visiting.add(node)
        for child in graph[node]: visit(child)
        visiting.remove(node); visited.add(node)
    for node in graph: visit(node)
    return {"valid": True, "versionId": version_id, "resourceCount": len(results), "results": results}


def publish_version(db, version_id, actor):
    version = db.execute("SELECT * FROM semantic_package_versions WHERE id=?", (version_id,)).fetchone()
    if not version:
        raise LookupError("semantic version not found")
    if version["status"] == "published":
        return dict(version)
    validation = validate_version(db, version_id)
    if not validation["valid"]:
        raise ValueError("版本校验未通过")
    actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    now = now_iso()
    db.execute("UPDATE semantic_package_versions SET status='published',published_by=?,published_at=? WHERE id=?", (actor_id, now, version_id))
    db.execute("UPDATE semantic_packages SET current_version_id=?,status='active',updated_at=? WHERE id=?", (version_id, now, version["package_id"]))
    db.execute("UPDATE semantic_resources SET status='published',updated_at=? WHERE id IN (SELECT resource_id FROM semantic_package_items WHERE version_id=?)", (now, version_id))
    db.execute("INSERT INTO semantic_release_records(version_id,action,actor,result_json,created_at) VALUES(?,?,?,?,?)", (version_id, "publish", actor_id, json.dumps(validation, ensure_ascii=False), now))
    return dict(db.execute("SELECT * FROM semantic_package_versions WHERE id=?", (version_id,)).fetchone())


def rollback_version(db, version_id, actor):
    """回滚采用重新发布历史版本，不删除任何版本或资源。"""
    version = db.execute("SELECT * FROM semantic_package_versions WHERE id=?", (version_id,)).fetchone()
    if not version:
        raise LookupError("semantic version not found")
    if version["status"] == "retired":
        raise ValueError("已停用版本不可回滚")
    return publish_version(db, version_id, actor)


def create_package(db, data, actor):
    domain_id = int(data.get("domainId")); _domain(db, domain_id)
    code = str(data.get("code") or "").strip()
    if not CODE_RE.match(code): raise ValueError("code 格式不合法")
    if not str(data.get("name") or "").strip(): raise ValueError("name is required")
    if db.execute("SELECT 1 FROM semantic_packages WHERE code=?", (code,)).fetchone(): raise ValueError("语义包编码已存在")
    t = now_iso(); actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    cur = db.execute("INSERT INTO semantic_packages(domain_id,code,name,description,status,owner_role,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (domain_id, code, data["name"].strip(), str(data.get("description") or ""), "draft", data.get("ownerRole", "semantic_editor"), t, t))
    return dict(db.execute("SELECT * FROM semantic_packages WHERE id=?", (cur.lastrowid,)).fetchone())


def create_version(db, package_id, data, actor):
    _package(db, package_id)
    version = str(data.get("version") or "").strip()
    if not re.match(r"^\d+\.\d+\.\d+$", version): raise ValueError("version 必须是 x.y.z")
    if db.execute("SELECT 1 FROM semantic_package_versions WHERE package_id=? AND version=?", (package_id, version)).fetchone(): raise ValueError("版本已存在")
    t = now_iso(); actor_id = actor if isinstance(actor, str) else actor.get("userId", "system")
    cur = db.execute("INSERT INTO semantic_package_versions(package_id,version,base_version_id,status,change_summary,created_by,created_at) VALUES(?,?,?,?,?,?,?)", (package_id, version, data.get("baseVersionId"), "draft", str(data.get("changeSummary") or ""), actor_id, t))
    for resource_id in data.get("resourceIds", []):
        resource = db.execute("SELECT id,package_id FROM semantic_resources WHERE id=?", (int(resource_id),)).fetchone()
        if not resource: raise ValueError("resource not found")
        db.execute("INSERT INTO semantic_package_items(version_id,resource_id,operation,checksum) VALUES(?,?,?,?)", (cur.lastrowid, resource["id"], "add", ""))
    return dict(db.execute("SELECT * FROM semantic_package_versions WHERE id=?", (cur.lastrowid,)).fetchone())


def seed_at2_semantic_assets(db, actor="system"):
    """幂等创建 AT2 第一版语义资产，不创建 CRM 实例数据。"""
    domain = db.execute("SELECT id FROM semantic_domains WHERE code='NIPPON_ENTERPRISE' AND status='active'").fetchone()
    if not domain: return {}
    domain_id = domain["id"]
    definitions = [
        ("term", "at2_need_theme", "AT2 需求主题", {"aliases": ["需求主题", "业务需求", "场景需求"], "contexts": ["客户访谈", "项目立项", "方案共创前"], "targetObjects": ["Customer", "Project", "Opportunity"]}),
        ("term", "at2_key_contact", "AT2 关键联系人", {"aliases": ["关键人", "决策链联系人", "项目关键人"], "contexts": ["客户关系", "项目关系", "商机关系"], "targetObjects": ["Person", "Customer", "Project"]}),
        ("action", "at2_fill_relationship_gap", "AT2 关系补齐 Action", {"service": "/api/actions", "parameters_schema": {"required": ["title", "customer_id", "project_id", "role"]}, "output_schema": {"type": "object"}, "requires_confirmation": False, "idempotency": "dedupe_key"}),
        ("rule", "at2_relationship_coverage", "AT2 关系覆盖规则", {"expression": {"op": "and", "args": [{"op": "exists", "field": "customer_id"}, {"op": "exists", "field": "project_id"}, {"op": "exists", "field": "key_contacts"}, {"op": "exists", "field": "relationship_roles.design_institute"}, {"op": "exists", "field": "relationship_roles.budget_approver"}, {"op": "exists", "field": "relationship_roles.technical_spec_influencer"}]}, "action": {"type": "create_action_draft", "actionCode": "at2_fill_relationship_gap", "whenMissing": ["design_institute", "budget_approver", "technical_spec_influencer"]}, "subject": {"objects": ["Customer", "Project", "Person", "Opportunity"]}, "output": {"requiredRoles": ["design_institute", "budget_approver", "technical_spec_influencer"], "missingRolesPath": "relationship_roles"}}),
        ("process", "at2_need_relationship_sop", "AT2 需求与关系引导 SOP", {"mode": "recommendation", "steps": [{"id": "identify-need-theme", "name": "识别需求主题", "goal": "归纳客户和项目当前需求主题", "description": "从访谈、项目和商机证据中提取需求主题", "completion": "至少形成一个已确认需求主题", "evidence_refs": ["conversation", "project", "opportunity"], "next": ["check-relationship-coverage"]}, {"id": "check-relationship-coverage", "name": "检查关系覆盖", "goal": "检查当前客户和项目的关键联系人覆盖", "description": "按角色检查关系网络是否覆盖", "completion": "完成客户、项目、关键联系人及三类影响角色检查", "evidence_refs": ["relationship"], "next": ["identify-missing-roles"]}, {"id": "identify-missing-roles", "name": "识别缺失角色", "goal": "识别设计院影响人、预算审批人和技术规格影响人缺口", "description": "输出缺失角色清单", "completion": "缺失角色清单已结构化", "evidence_refs": ["relationship", "rule"], "next": ["create-relationship-action"]}, {"id": "create-relationship-action", "name": "生成关系补齐 Action", "goal": "为每个缺失角色生成可追踪 Action 草稿", "description": "调用 AT2 关系补齐 Action 资产", "completion": "Action 草稿已生成并关联客户与项目", "evidence_refs": ["rule", "action"], "next": ["save-evidence"]}, {"id": "save-evidence", "name": "保存证据", "goal": "保存需求主题、关系判断和 Action 依据", "description": "记录来源、版本和证据引用", "completion": "证据记录完成，可回放", "evidence_refs": ["conversation", "relationship", "action"], "next": []}], "completion": {"required_steps": ["identify-need-theme", "check-relationship-coverage", "identify-missing-roles", "create-relationship-action", "save-evidence"]}, "references": [{"type": "rule", "code": "at2_relationship_coverage"}, {"type": "term", "code": "at2_need_theme"}, {"type": "term", "code": "at2_key_contact"}, {"type": "action", "code": "at2_fill_relationship_gap"}]})
    ]
    ids = {}
    for resource_type, code, name, payload in definitions:
        row = db.execute("SELECT id FROM semantic_resources WHERE domain_id=? AND resource_type=? AND code=? AND version='1.0.0'", (domain_id, resource_type, code)).fetchone()
        if not row:
            item = create_resource(db, {"domainId": domain_id, "resourceType": resource_type, "code": code, "nameZh": name, "description": f"NIPPON_ENTERPRISE · AT2 · {name}", "payload": payload, "version": "1.0.0", "sourceRef": "AT2:需求与关系引导", "subjectRefs": ["Customer", "Project", "Person"], "objectRefs": []}, actor)
            ids[code] = item["id"]
        else: ids[code] = row["id"]
    for code in ("at2_need_theme", "at2_key_contact", "at2_fill_relationship_gap", "at2_relationship_coverage", "at2_need_relationship_sop"):
        row = db.execute("SELECT * FROM semantic_resources WHERE id=?", (ids[code],)).fetchone()
        if row and row["status"] != "published":
            try: publish_resource(db, row["id"], actor)
            except (ValueError, LookupError): pass
    for source, target, ref_type in (("at2_relationship_coverage", "at2_need_theme", "uses"), ("at2_relationship_coverage", "at2_key_contact", "uses"), ("at2_need_relationship_sop", "at2_relationship_coverage", "depends_on"), ("at2_need_relationship_sop", "at2_need_theme", "uses"), ("at2_need_relationship_sop", "at2_key_contact", "uses"), ("at2_need_relationship_sop", "at2_fill_relationship_gap", "uses")):
        if not db.execute("SELECT 1 FROM semantic_asset_references WHERE source_asset_id=? AND target_asset_id=? AND reference_type=? AND version='1.0.0'", (ids[source], ids[target], ref_type)).fetchone():
            try: create_asset_reference(db, {"sourceAssetId": ids[source], "targetAssetId": ids[target], "referenceType": ref_type, "required": True, "version": "1.0.0", "status": "published"})
            except (ValueError, LookupError): pass
    return {code: dict(db.execute("SELECT * FROM semantic_resources WHERE id=?", (rid,)).fetchone()) for code, rid in ids.items()}
