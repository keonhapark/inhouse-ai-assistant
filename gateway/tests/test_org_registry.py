"""조직도·에이전트 등록부 조회(#222, 계약 #221)."""

import yaml

from gateway.registry import Registry, Requester

from .conftest import PACK, ROOT
from .test_chat import schema_check


def _who(**kw):
    base = dict(id="E1", unit_id="u1", grade="staff", roles=("employee",), access_tags=())
    return Requester(**{**base, **kw})


TOOLS = {"tools": [{"name": "t_read", "required_scope": "x:read", "risk": "read",
                    "description": "목록을 봅니다. 둘째 문장입니다."},
                   {"name": "t_pay", "required_scope": "x:write", "risk": "irreversible",
                    "description": "지급을 요청합니다"}]}
SCOPES = {"scopes": [{"id": "x:read"}, {"id": "x:write"}]}
AGENT = {
    "id": "a", "name": "에이", "version": "0.1.0", "stage": 1, "owner_unit": "u1", "description": "설명",
    "callable_by": {"units": ["u9"]}, "tools": ["t_read", "t_pay"], "allowed_risk": ["read", "irreversible"],
    "doc_scopes": ["public"], "model_policy": {"mode": "local_only", "reason": "이유"},
    "risk_policy": {"read": "auto", "reversible_write": "auto_with_undo", "irreversible": "confirm",
                    "overrides": [{"tool": "t_pay", "when": {"arg": "amount", "gt": 1000000}, "action": "confirm"},
                                  {"tool": "t_read", "when": "always", "action": "auto"}]},
    "routing": {"keywords": ["지급"], "examples": ["백만 원 지급해 줘"]},
}


def test_registry_entry_follows_contract_shape():
    reg = Registry({"fallback_agent": "a", "agents": [AGENT]}, TOOLS, SCOPES, unit_names={"u1": "일팀"})
    e = reg.registry_entry(reg.get("a"), _who())
    schema_check.validate("openapi/gateway.yaml", "AgentRegistryEntry", e)
    assert e["ownerUnitId"] == "u1" and e["ownerUnitName"] == "일팀"
    assert e["callable"] is False and e["callableBy"] == {"units": ["u9"]}
    assert e["tools"] == [{"name": "t_read", "title": "목록을 봅니다.", "risk": "read"},
                          {"name": "t_pay", "title": "지급을 요청합니다", "risk": "irreversible"}]
    assert e["riskPolicy"]["reversibleWrite"] == "auto_with_undo"
    assert e["riskPolicy"]["overrides"] == [
        {"tool": "t_pay", "when": "arg_gt", "arg": "amount", "gt": 1000000, "action": "confirm"},
        {"tool": "t_read", "when": "always", "action": "auto"}]
    assert e["modelPolicy"] == {"mode": "local_only", "reason": "이유"}
    assert e["routingKeywords"] == ["지급"]
    assert "백만 원 지급해 줘" not in str(e)  # 라우팅 예문은 넣지 않습니다
    assert reg.registry_entry(reg.get("a"), _who(unit_id="u9"))["callable"] is True


def test_unknown_owner_unit_name_is_null():
    reg = Registry({"agents": [AGENT]}, TOOLS, SCOPES)
    assert reg.registry_entry(reg.get("a"), _who())["ownerUnitName"] is None


def test_agent_registry_endpoint(client, login, staff_no):
    h = {"Authorization": f"Bearer {login(staff_no)}"}
    r = client.get("/api/agent-registry", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    agents_doc = yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))
    stage = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))["stage"]
    assert body["fallbackAgentId"] == agents_doc["fallback_agent"]
    assert [e["id"] for e in body["items"]] == [a["id"] for a in agents_doc["agents"] if a["stage"] <= stage]
    for e in body["items"]:
        schema_check.validate("openapi/gateway.yaml", "AgentRegistryEntry", e)
        assert e["ownerUnitName"]  # 팩 org.yaml에 있는 부서
    for a in agents_doc["agents"]:  # 팩의 인자 조건은 arg_gt로 옮깁니다
        for o in a.get("risk_policy", {}).get("overrides", []):
            if isinstance(o["when"], dict) and a["stage"] <= stage:
                got = next(e for e in body["items"] if e["id"] == a["id"])["riskPolicy"]["overrides"]
                assert {"tool": o["tool"], "when": "arg_gt", "arg": o["when"]["arg"], "gt": o["when"]["gt"],
                        "action": o["action"]} in got
    assert client.get("/api/agent-registry").status_code == 401


def test_org_units_relays_erp(client, login, staff_no):
    r = client.get("/api/org/units", headers={"Authorization": f"Bearer {login(staff_no)}"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    org = yaml.safe_load((PACK / "org.yaml").read_text(encoding="utf-8"))
    assert {u["id"] for u in items} == {u["id"] for u in org["units"]}
    for u in items:
        schema_check.validate("openapi/erp.yaml", "Unit", u)
    assert client.get("/api/org/units").status_code == 401


def test_registry_load_reads_unit_names():
    reg = Registry.load(PACK, ROOT / "contracts")
    org = yaml.safe_load((PACK / "org.yaml").read_text(encoding="utf-8"))
    assert reg.unit_names == {u["id"]: u["name"] for u in org["units"]}


def test_callable_by_all_and_optional_fields():
    minimal = {"id": "m", "name": "엠", "version": "1.0.0", "owner_unit": "u1", "description": "",
               "callable_by": "all", "tools": ["t_read"], "allowed_risk": ["read"],
               "model_policy": {"mode": "external_allowed"},
               "risk_policy": {"read": "auto", "reversible_write": "deny", "irreversible": "deny"}}
    roles = {**AGENT, "id": "r", "callable_by": {"roles": ["auditor"], "grades": ["ceo"]}}
    reg = Registry({"agents": [minimal, roles]}, TOOLS, SCOPES)
    m = reg.registry_entry(reg.get("m"), _who())
    schema_check.validate("openapi/gateway.yaml", "AgentRegistryEntry", m)
    assert m["callableBy"] == "all" and m["callable"] is True and m["stage"] == 1
    assert "overrides" not in m["riskPolicy"] and "routingKeywords" not in m
    assert m["modelPolicy"] == {"mode": "external_allowed"} and m["docScopes"] == []
    r = reg.registry_entry(reg.get("r"), _who())
    assert r["callableBy"] == {"roles": ["auditor"], "grades": ["ceo"]} and r["callable"] is False
    assert reg.registry_entry(reg.get("r"), _who(grade="ceo"))["callable"] is True


def test_endpoint_keeps_uncallable_agents_and_omits_missing_fallback(app, client, login, staff_no):
    """/agents와 달리 부를 수 없는 에이전트도 callable=false로 남고, fallback_agent가 없으면 키를 뺍니다."""
    agents_doc = yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))
    agents = [dict(a) for a in agents_doc["agents"]]
    agents[0]["callable_by"] = {"units": ["no-such-unit"]}
    full = Registry.load(PACK, ROOT / "contracts")
    reg = Registry({"agents": agents}, {"tools": list(full.tool_meta.values())},
                   {"scopes": [{"id": s} for s in full.wide_scopes]}, stage=full.stage, unit_names=full.unit_names)
    app.state.chat.registry = reg
    body = client.get("/api/agent-registry", headers={"Authorization": f"Bearer {login(staff_no)}"}).json()
    assert "fallbackAgentId" not in body
    by_id = {e["id"]: e for e in body["items"]}
    assert by_id[agents[0]["id"]]["callable"] is False
    assert all(e["callable"] for i, e in by_id.items() if i != agents[0]["id"])
