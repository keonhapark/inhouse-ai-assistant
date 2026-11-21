"""업종 팩을 스키마와 참조 규칙으로 검사합니다.

실행: uv run --project contracts python -m tools.check_packs   (contracts/에서)
실패하면 문제를 모두 출력하고 1로 끝납니다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.common import CONTRACTS, PACKS, load, openapi_operations

FILE_DEFS = {
    "pack.yaml": "pack",
    "org.yaml": "org",
    "agents.yaml": "agents",
    "forms.yaml": "forms",
    "docs.yaml": "docs",
    "fixtures/employees.json": "fixtures_employees",
    "fixtures/rooms.json": "fixtures_rooms",
    "fixtures/leave_balances.json": "fixtures_leave_balances",
}


def check_pack(pack_dir: Path) -> list[str]:
    errors: list[str] = []
    schema = load(CONTRACTS / "pack/pack.schema.json")
    data: dict[str, object] = {}
    for rel, def_name in FILE_DEFS.items():
        f = pack_dir / rel
        if not f.exists():
            errors.append(f"{pack_dir.name}/{rel}: 파일이 없습니다")
            continue
        doc = load(f)
        data[rel] = doc
        sub = {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]}
        for e in Draft202012Validator(sub).iter_errors(doc):
            loc = "/".join(str(p) for p in e.absolute_path)
            errors.append(f"{pack_dir.name}/{rel}:{loc}: {e.message}")
    for optional, def_name in (("glossary.yaml", "glossary"), ("budgets.yaml", "budgets"),  # 선택 파일
                               ("fixtures/tickets.json", "fixtures_tickets"), ("fixtures/items.json", "fixtures_items"),
                               ("fixtures/customers.json", "fixtures_customers"),
                               ("fixtures/defect_reports.json", "fixtures_defect_reports")):
        f = pack_dir / optional
        if not f.exists():
            continue
        doc = load(f)
        data[optional] = doc
        sub = {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]}
        for e in Draft202012Validator(sub).iter_errors(doc):
            loc = "/".join(str(p) for p in e.absolute_path)
            errors.append(f"{pack_dir.name}/{optional}:{loc}: {e.message}")
    if errors:
        return errors

    p = f"{pack_dir.name}/"
    org = data["org.yaml"]
    agents = data["agents.yaml"]
    forms = data["forms.yaml"]
    docs = data["docs.yaml"]
    employees = data["fixtures/employees.json"]["employees"]
    balances = data["fixtures/leave_balances.json"]["balances"]

    tools = {t["name"]: t for t in load(CONTRACTS / "mcp/tools.json")["tools"]}
    unit_ids = {u["id"] for u in org["units"]}
    grade_ids = {g["id"] for g in org["grades"]}
    role_ids = {r["id"] for r in org["roles"]}
    tag_ids = {t["id"] for t in org["access_tags"]}
    form_ids = {f["id"] for f in forms["forms"]}

    def check_grant(where: str, grant: object) -> None:
        if grant == "all":
            return
        assert isinstance(grant, dict)
        for key, known in (("units", unit_ids), ("roles", role_ids), ("grades", grade_ids)):
            for v in grant.get(key, []):
                if v not in known:
                    errors.append(f"{where}: 없는 {key[:-1]} '{v}'")

    for u in org["units"]:
        if "parent" in u and u["parent"] not in unit_ids:
            errors.append(f"{p}org.yaml: {u['id']}의 parent '{u['parent']}'가 없습니다")
    for r in org["roles"]:
        check_grant(f"{p}org.yaml roles.{r['id']}", r["grant"])
    for t in org["access_tags"]:
        check_grant(f"{p}org.yaml access_tags.{t['id']}", t["grant"])
    for key, v in org.get("erp_roles", {}).items():
        if v not in role_ids:
            errors.append(f"{p}org.yaml erp_roles.{key}: 없는 역할 '{v}'")
    for v in org["delegation_policy"]["registrable_by"]:
        if v != "self" and v not in role_ids:
            errors.append(f"{p}org.yaml delegation_policy.registrable_by: 없는 역할 '{v}'")

    agent_ids = [a["id"] for a in agents["agents"]]
    for dup, n in Counter(agent_ids).items():
        if n > 1:
            errors.append(f"{p}agents.yaml: 에이전트 ID 중복 '{dup}'")
    if agents["fallback_agent"] not in agent_ids:
        errors.append(f"{p}agents.yaml: fallback_agent '{agents['fallback_agent']}'가 없습니다")
    budgets = data.get("budgets.yaml") or {}
    for a in budgets.get("agents", {}):
        if a not in agent_ids:
            errors.append(f"{p}budgets.yaml agents: 없는 에이전트 '{a}'")
    for u in budgets.get("units", {}):
        if u not in unit_ids:
            errors.append(f"{p}budgets.yaml units: 없는 부서 '{u}'")
    topics = (data.get("glossary.yaml") or {}).get("topics", [])
    for dup, n in Counter(t["id"] for t in topics).items():
        if n > 1:
            errors.append(f"{p}glossary.yaml topics: 주제 ID 중복 '{dup}'")
    for t in topics:
        for pat in t["patterns"]:
            try:
                re.compile(pat)
            except re.error as e:
                errors.append(f"{p}glossary.yaml topics {t['id']}: 정규식 '{pat}'이 올바르지 않습니다({e})")
    for a in agents["agents"]:
        w = f"{p}agents.yaml {a['id']}"
        if a["owner_unit"] not in unit_ids:
            errors.append(f"{w}: owner_unit '{a['owner_unit']}'가 org.yaml에 없습니다")
        check_grant(f"{w} callable_by", a["callable_by"])
        for tag in a["doc_scopes"]:
            if tag not in tag_ids:
                errors.append(f"{w}: doc_scopes '{tag}'가 org.yaml access_tags에 없습니다")
        for name in a["tools"]:
            t = tools.get(name)
            if t is None:
                errors.append(f"{w}: 도구 '{name}'가 contracts/mcp/tools.json에 없습니다")
                continue
            if t["risk"] not in a["allowed_risk"]:
                errors.append(f"{w}: 도구 '{name}'의 위험 등급 {t['risk']}가 allowed_risk 밖입니다")
            if a["risk_policy"][t["risk"]] == "deny":
                errors.append(f"{w}: 도구 '{name}'의 위험 등급 {t['risk']}가 risk_policy에서 deny입니다")
            if t["stage"] > a["stage"]:
                errors.append(f"{w}: 도구 '{name}'(stage {t['stage']})가 에이전트 stage {a['stage']}보다 늦습니다")
        ir = a.get("image_reading") or {}
        if ir.get("draft_tool") and ir["draft_tool"] not in a["tools"]:
            errors.append(f"{w}: image_reading.draft_tool '{ir['draft_tool']}'가 tools에 없습니다")
        names = [f["name"] for f in ir.get("fields", [])]
        for dup, n in Counter(names).items():
            if n > 1:
                errors.append(f"{w}: image_reading 항목 이름 중복 '{dup}'")
        for f in ir.get("fields", []):
            if "pattern" in f:
                try:
                    re.compile(f["pattern"])
                except re.error as e:
                    errors.append(f"{w}: image_reading {f['name']} 정규식이 올바르지 않습니다({e})")
            if ("pattern" in f or "enum" in f) and f["type"] != "string":
                errors.append(f"{w}: image_reading {f['name']}: pattern·enum은 string 항목에만 씁니다")
        for o in a["risk_policy"].get("overrides", []):
            if o["tool"] not in a["tools"]:
                errors.append(f"{w}: risk_policy override 도구 '{o['tool']}'가 tools에 없습니다")

    for f in forms["forms"]:
        uses_amount = any(r["when"] for r in f["approval_line"])
        if uses_amount and "amount_field" not in f:
            errors.append(f"{p}forms.yaml {f['id']}: 금액 조건이 있는데 amount_field가 없습니다")
        if "amount_field" in f and f["amount_field"] not in f["fields"].get("properties", {}):
            errors.append(f"{p}forms.yaml {f['id']}: amount_field '{f['amount_field']}'가 fields에 없습니다")
        if "amount_product_of" in f:
            props = f["fields"].get("properties", {})
            if "amount_field" not in f:
                errors.append(f"{p}forms.yaml {f['id']}: amount_product_of가 있는데 amount_field가 없습니다")
            for name in f["amount_product_of"]:
                if props.get(name, {}).get("type") != "integer" or name not in f["fields"].get("required", []):
                    errors.append(f"{p}forms.yaml {f['id']}: amount_product_of '{name}'는 필수 정수 필드여야 합니다")

    doc_ids = [d["id"] for d in docs["documents"]]
    for dup, n in Counter(doc_ids).items():
        if n > 1:
            errors.append(f"{p}docs.yaml: 문서 ID 중복 '{dup}'")
    for d in docs["documents"]:
        for tag in d["acl_tags"]:
            if tag not in tag_ids:
                errors.append(f"{p}docs.yaml {d['id']}: ACL 태그 '{tag}'가 org.yaml에 없습니다")

    emp_ids = {e["id"] for e in employees}
    for e in employees:
        if e["unit_id"] not in unit_ids:
            errors.append(f"{p}fixtures/employees.json {e['id']}: 없는 unit '{e['unit_id']}'")
        if e["grade"] not in grade_ids:
            errors.append(f"{p}fixtures/employees.json {e['id']}: 없는 grade '{e['grade']}'")
    heads = Counter((e["unit_id"], e["grade"]) for e in employees)
    for u in org["units"]:
        want = "team_leader" if u["kind"] == "team" else ("ceo" if "parent" not in u else "division_head")
        if heads[(u["id"], want)] != 1:
            errors.append(f"{p}fixtures/employees.json: {u['id']}의 {want}가 1명이 아닙니다({heads[(u['id'], want)]})")
    for b in balances:
        if b["employee_id"] not in emp_ids:
            errors.append(f"{p}fixtures/leave_balances.json: 없는 직원 '{b['employee_id']}'")
    item_codes = [i["code"] for i in (data.get("fixtures/items.json") or {}).get("items", [])]
    for dup, n in Counter(item_codes).items():
        if n > 1:
            errors.append(f"{p}fixtures/items.json: 품목 코드 중복 '{dup}'")
    for d in (data.get("fixtures/defect_reports.json") or {}).get("defect_reports", []):
        if d["item_code"] not in item_codes:
            errors.append(f"{p}fixtures/defect_reports.json {d['id']}: 없는 품목 '{d['item_code']}'")
        for who in [d["created_by"], d.get("confirmed_by")]:
            if who is not None and who not in emp_ids:
                errors.append(f"{p}fixtures/defect_reports.json {d['id']}: 없는 직원 '{who}'")
    for t in (data.get("fixtures/tickets.json") or {}).get("tickets", []):
        for who in [t["requester_id"], *(c["author_id"] for c in t.get("comments", []))]:
            if who not in emp_ids:
                errors.append(f"{p}fixtures/tickets.json {t['id']}: 없는 직원 '{who}'")
    _ = form_ids
    return errors


def check_tools() -> list[str]:
    errors: list[str] = []
    tools_doc = load(CONTRACTS / "mcp/tools.json")
    schema = load(CONTRACTS / "mcp/tools.schema.json")
    for e in Draft202012Validator(schema).iter_errors(tools_doc):
        errors.append(f"contracts/mcp/tools.json:{'/'.join(map(str, e.absolute_path))}: {e.message}")
    scopes = {s["id"]: s for s in load(CONTRACTS / "auth/scopes.json")["scopes"]}
    specs = {
        "erp": openapi_operations(load(CONTRACTS / "openapi/erp.yaml")),
        "rag": openapi_operations(load(CONTRACTS / "openapi/rag.yaml")),
        "incident": openapi_operations(load(CONTRACTS / "openapi/incident.yaml")),
    }
    names = Counter(t["name"] for t in tools_doc["tools"])
    for n, c in names.items():
        if c > 1:
            errors.append(f"contracts/mcp/tools.json: 도구 이름 중복 '{n}'")
    for t in tools_doc["tools"]:
        w = f"contracts/mcp/tools.json {t['name']}"
        base_scope = t["required_scope"]
        if base_scope.startswith("approval:request:"):
            base_scope = "approval:request"
        if base_scope not in scopes:
            errors.append(f"{w}: scope '{t['required_scope']}'가 contracts/auth/scopes.json에 없습니다")
        elif scopes[base_scope].get("human_only"):
            errors.append(f"{w}: 사람 화면 전용 scope '{base_scope}'는 도구에 쓸 수 없습니다")
        op = specs[t["backend"]["service"]].get(t["backend"]["operationId"])
        if op is None:
            errors.append(f"{w}: operationId '{t['backend']['operationId']}'가 {t['backend']['service']} 계약에 없습니다")
            continue
        if op.get("x-human-only"):
            errors.append(f"{w}: '{t['backend']['operationId']}'는 x-human-only라 도구로 노출할 수 없습니다")
        is_write = bool(op.get("x-write"))
        if is_write and t["risk"] == "read":
            errors.append(f"{w}: 쓰기 operation인데 risk가 read입니다")
        if not is_write and t["risk"] != "read":
            errors.append(f"{w}: 읽기 operation인데 risk가 {t['risk']}입니다")
        if t["backend"]["service"] == "erp" and t["risk"] != "read":
            req = op.get("x-required-scope")
            if req and not t["required_scope"].startswith(req):
                errors.append(f"{w}: required_scope '{t['required_scope']}'가 operation scope '{req}'와 맞지 않습니다")
    return errors


def main() -> int:
    errors = check_tools()
    packs = sorted(d for d in PACKS.iterdir() if d.is_dir() and (d / "pack.yaml").exists())
    for d in packs:
        errors += check_pack(d)
    for e in errors:
        print(e)
    print(f"팩 {len(packs)}개, 문제 {len(errors)}개")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
