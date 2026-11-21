"""팩 양식 도구(#397·#403): forms.yaml 양식의 tool을 공용 도구와 합쳐 등록부·위임 토큰을 계산합니다."""

import importlib.util
import json
import shutil

import pytest
import yaml
from jsonschema import Draft202012Validator

from gateway.registry import Registry, Requester, form_tools
from gateway.tokens import DelegationTokenIssuer

from .conftest import ROOT

FIN = ROOT / "packs/finance"
SCHEMA = json.loads((ROOT / "contracts/auth/delegation-token.schema.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("pack_tools", ROOT / "contracts/tools/pack_tools.py")
pack_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pack_tools)

LOAN_TOOL = {"name": "loan_request", "description": "여신 품의 결재를 올립니다. 결재선은 금액에 따라 erp가 정합니다."}


@pytest.fixture
def fin(tmp_path):
    """금융 팩 사본에 여신 품의 양식 도구를 붙이고 여신 에이전트에 연결합니다."""
    pack = tmp_path / "finance"
    shutil.copytree(FIN, pack)
    forms = yaml.safe_load((pack / "forms.yaml").read_text(encoding="utf-8"))
    for f in forms["forms"]:
        if f["id"] == "loan":
            f["tool"] = dict(LOAN_TOOL)
    (pack / "forms.yaml").write_text(yaml.safe_dump(forms, allow_unicode=True), encoding="utf-8")
    agents = yaml.safe_load((pack / "agents.yaml").read_text(encoding="utf-8"))
    for a in agents["agents"]:
        if a["id"] == "credit":
            a["tools"].append("loan_request")
            a["allowed_risk"] = sorted(set(a["allowed_risk"]) | {"reversible_write"})
    (pack / "agents.yaml").write_text(yaml.safe_dump(agents, allow_unicode=True), encoding="utf-8")
    return pack


def test_form_tools_follow_contract_reference(fin):
    forms = yaml.safe_load((fin / "forms.yaml").read_text(encoding="utf-8"))
    assert form_tools(forms) == pack_tools.form_tools(forms)
    (t,) = form_tools(forms)
    assert t["required_scope"] == "approval:request:loan" and t["backend"]["fixed"] == {"formId": "loan"}
    assert "x-labels" not in json.dumps(t["inputSchema"])


def test_agent_with_form_tool_gets_tool_and_scope_in_token(fin):
    reg = Registry.load(fin, ROOT / "contracts")
    credit = reg.get("credit")
    assert "loan_request" in credit.tools and "approval:request:loan" in credit.scopes
    issued = DelegationTokenIssuer.ephemeral().issue(Requester("E0005", "credit-review", "staff", ("employee",), ()),
                                                     credit, "c")
    Draft202012Validator(SCHEMA).validate(issued.claims)
    assert "loan_request" in issued.claims["tools"] and "approval:request:loan" in issued.claims["scopes"]
    assert "approval:request" in reg.wide_scopes   # 평가 공용 계정 범위는 상위 범위로 양식별 범위를 덮음
    entry = reg.registry_entry(credit, Requester("E0005", "credit-review", "staff", ("credit_officer",), ()))
    assert {"name": "loan_request", "title": "여신 품의 결재를 올립니다.", "risk": "reversible_write"} in entry["tools"]


def test_packs_without_form_tools_are_unchanged():
    reg = Registry.load(ROOT / "packs/manufacturing", ROOT / "contracts")
    tools = json.loads((ROOT / "contracts/mcp/tools.json").read_text(encoding="utf-8"))["tools"]
    assert set(reg.tool_meta) == {t["name"] for t in tools}


def test_form_tool_name_clash_with_shared_tool_fails_fast(fin):
    forms = yaml.safe_load((fin / "forms.yaml").read_text(encoding="utf-8"))
    for f in forms["forms"]:
        if f["id"] == "loan":
            f["tool"]["name"] = "leave_request"
    (fin / "forms.yaml").write_text(yaml.safe_dump(forms, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError):
        Registry.load(fin, ROOT / "contracts")
