import asyncio
import json

import jwt
import pytest
from jsonschema import Draft202012Validator

from gateway.problems import ProblemError

from .conftest import ROOT

SCHEMA = json.loads((ROOT / "contracts/auth/delegation-token.schema.json").read_text(encoding="utf-8"))
SCOPES = json.loads((ROOT / "contracts/auth/scopes.json").read_text(encoding="utf-8"))["scopes"]
HUMAN_ONLY = {s["id"] for s in SCOPES if s.get("human_only")}


def test_claims_follow_contract_schema(login, issue, staff_no):
    issued = issue(login(staff_no), "hr", "conv-42")
    Draft202012Validator(SCHEMA).validate(issued.claims)
    c = issued.claims
    assert c["exp"] - c["iat"] == 600
    assert c["agt"] == "hr" and c["cid"] == "conv-42"
    assert set(c["aud"]) == {"erp", "rag", "mcp"}


def test_scopes_are_agent_tool_scopes_without_human_only(app, login, issue, staff_no):
    agent = app.state.registry.get("hr")
    tools = {t["name"]: t for t in json.loads((ROOT / "contracts/mcp/tools.json").read_text())["tools"]}
    issued = issue(login(staff_no), "hr")
    assert issued.claims["tools"] == list(agent.tools)
    assert set(issued.claims["scopes"]) == {tools[t]["required_scope"] for t in agent.tools} - HUMAN_ONLY
    assert not set(issued.claims["scopes"]) & HUMAN_ONLY


def test_doc_scopes_are_requester_tags_intersect_agent(app, login, issue, staff_no, hr_staff_no, erp_http):
    agent = app.state.registry.get("hr")
    for no in (staff_no, hr_staff_no):
        emp_jwt = login(no)
        tags = erp_http.get("/me/access-tags", headers={"Authorization": f"Bearer {emp_jwt}"}).json()["tags"]
        issued = issue(emp_jwt, "hr")
        assert set(issued.claims["doc_scopes"]) == set(tags) & set(agent.doc_scopes)
    # 인사 담당이 아닌 직원은 제한 문서 태그를 받지 못하고, 인사 담당은 받습니다.
    restricted = set(agent.doc_scopes) - set(
        erp_http.get("/me/access-tags", headers={"Authorization": f"Bearer {login(staff_no)}"}).json()["tags"])
    assert restricted
    assert not restricted & set(issue(login(staff_no), "hr").claims["doc_scopes"])
    assert restricted <= set(issue(login(hr_staff_no), "hr").claims["doc_scopes"])


def test_erp_accepts_token_within_scope_and_rejects_outside(login, issue, staff_no, erp_http):
    token = issue(login(staff_no), "hr").token
    auth = {"Authorization": f"Bearer {token}"}
    assert erp_http.get("/me/access-tags", headers=auth).status_code == 200
    # 인사 에이전트 도구에는 회의실 조회가 없으므로 scope가 없습니다.
    r = erp_http.get("/rooms", headers=auth)
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:scope-missing"
    # 결재 승인은 사람 화면 전용이라 위임 토큰으로 부르지 못합니다.
    r = erp_http.post("/approval-documents/any/approve", headers=auth, json={})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:delegation-token-not-allowed"


def test_token_signed_by_other_key_is_rejected_by_erp(login, staff_no, app, erp_http):
    from gateway.tokens import DelegationTokenIssuer

    other = DelegationTokenIssuer.ephemeral()
    who = asyncio.run(_requester(app, login(staff_no)))
    forged = other.issue(who, app.state.registry.get("hr"), "c").token
    assert erp_http.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


async def _requester(app, employee_jwt):
    from gateway.delegation import load_requester
    return await load_requester(app.state.erp, employee_jwt)


def test_unknown_agent_is_404(login, issue, staff_no):
    with pytest.raises(ProblemError) as e:
        issue(login(staff_no), "no-such-agent")
    assert e.value.status == 404


def test_agent_not_callable_is_403(app, login, issue, staff_no, hr_staff_no):
    from gateway.registry import Registry

    agents = {"fallback_agent": "only-staff", "agents": [
        {**app.state.registry.get("hr").raw, "id": "only-staff", "callable_by": {"roles": ["hr_staff"]}}]}
    tools = json.loads((ROOT / "contracts/mcp/tools.json").read_text())
    app.state.delegation.registry = Registry(agents, tools, {"scopes": SCOPES})
    with pytest.raises(ProblemError) as e:
        issue(login(staff_no), "only-staff")
    assert e.value.status == 403
    assert issue(login(hr_staff_no), "only-staff").claims["agt"] == "only-staff"


def test_invalid_employee_jwt_is_401(issue):
    with pytest.raises(ProblemError) as e:
        issue("not-a-jwt", "hr")
    assert e.value.status == 401


def test_expired_token_is_rejected(issuer, app, login, staff_no):
    who = asyncio.run(_requester(app, login(staff_no)))
    old = issuer.issue(who, app.state.registry.get("hr"), "c", now=1_000_000)
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(old.token, issuer.public_pem(), algorithms=["ES256"], audience="erp")
