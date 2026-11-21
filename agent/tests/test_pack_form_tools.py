"""팩 양식 도구(#397): 팩 forms.yaml 양식의 tool로 상신 도구를 만들어 공용 도구처럼 다룹니다.

금융 팩 사본에서 여신 지원(credit) 에이전트에 loan_request를 붙여 봅니다(실제 팩 연결은 agent·gateway 구현 뒤).
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

from agent_runtime.audit import AuditLog
from agent_runtime.mcp_server.catalog import Catalog, CatalogError
from agent_runtime.mcp_server.server import tool_descriptor
from agent_runtime.mcp_server.service import CallMeta, ToolService
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.pack_tools import form_tools, strip_x
from agent_runtime.registry import Registry
from fakes.erp.app import create_app as create_fake_erp
from tests.conftest import CONTRACTS, PACK_DIR
from tests.mcp_support import PRIVATE_KEY, PUBLIC_KEY

FINANCE = PACK_DIR.parent / "finance"
LOAN = {"borrower": "가명차주A", "product": "business_operating", "term_months": 24,
        "collateral": "공장 부지 근저당", "purpose": "원자재 구입"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    dst = tmp_path / "finance"
    shutil.copytree(FINANCE, dst)
    path = dst / "agents.yaml"
    doc = yaml.safe_load(path.read_text("utf-8"))
    credit = next(a for a in doc["agents"] if a["id"] == "credit")
    if "loan_request" not in credit["tools"]:
        credit["tools"].insert(0, "loan_request")
    if "reversible_write" not in credit["allowed_risk"]:
        credit["allowed_risk"].append("reversible_write")
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")
    return dst


def test_form_tools_follow_contract_rule() -> None:
    forms = yaml.safe_load((FINANCE / "forms.yaml").read_text("utf-8"))
    [loan] = form_tools(forms)
    loan_form = next(f for f in forms["forms"] if f["id"] == "loan")
    assert loan["name"] == "loan_request" and loan["required_scope"] == "approval:request:loan"
    assert loan["backend"] == {"service": "erp", "operationId": "createApprovalDocument", "fixed": {"formId": "loan"}}
    assert (loan["risk"], loan["trust_required"], loan["stage"]) == ("reversible_write", "user_direct", 1)
    assert loan["inputSchema"] == strip_x(loan_form["fields"]) and "x-labels" not in json.dumps(loan["inputSchema"])
    assert form_tools(yaml.safe_load((PACK_DIR / "forms.yaml").read_text("utf-8"))) == ()
    assert form_tools(None) == ()


def test_registry_and_catalog_expose_form_tool(pack: Path) -> None:
    reg = Registry.load(pack)
    assert [t["name"] for t in reg.form_tools] == ["loan_request"]
    catalog = Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", reg)
    tool = catalog.get("loan_request")
    assert tool is not None and tool.fixed == {"formId": "loan"} and tool.required_scope == "approval:request:loan"
    assert tool.operation.operation_id == "createApprovalDocument" and tool.operation.write
    d = tool_descriptor(tool)
    assert d.input_schema["required"] == ["borrower", "product", "amount", "term_months", "collateral", "purpose"]
    assert d.meta["risk"] == "reversible_write" and d.meta["trustRequired"] == "user_direct"
    # 공용 도구 뒤에 붙습니다(업무 실행·평가 경로의 도구 순서가 같도록)
    names = [t.name for t in catalog.tools]
    assert names.index("loan_request") == len(names) - 1


def test_form_tool_name_clash_with_public_tool_is_refused(pack: Path) -> None:
    path = pack / "forms.yaml"
    doc = yaml.safe_load(path.read_text("utf-8"))
    next(f for f in doc["forms"] if f["id"] == "loan")["tool"]["name"] = "leave_request"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")
    with pytest.raises(CatalogError, match="겹칩니다"):
        Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", Registry.load(pack))


def test_agent_tool_missing_everywhere_is_refused(pack: Path) -> None:
    path = pack / "forms.yaml"
    doc = yaml.safe_load(path.read_text("utf-8"))
    del next(f for f in doc["forms"] if f["id"] == "loan")["tool"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")
    with pytest.raises(CatalogError, match="팩 양식 도구에 없는 도구"):
        Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", Registry.load(pack))


def _mint(reg: Registry, employee: str) -> str:
    import time

    import jwt

    t = int(time.time())
    return jwt.encode({"iss": "gateway", "aud": ["erp", "mcp"], "sub": employee, "agt": "credit",
                       "cid": f"cnv_{uuid.uuid4().hex[:8]}", "scopes": ["approval:request:loan", "approval:read"],
                       "tools": list(reg.get("credit").tools), "doc_scopes": ["public"], "iat": t, "exp": t + 600,
                       "jti": uuid.uuid4().hex}, PRIVATE_KEY, algorithm="ES256")


@pytest.mark.anyio
@pytest.mark.parametrize(("amount", "steps"), [(50_000_000, 1), (500_000_000, 2), (3_000_000_000, 3)])
async def test_loan_request_goes_to_erp_with_line_by_amount(pack: Path, tmp_path: Path, amount: int,
                                                            steps: int) -> None:
    reg = Registry.load(pack)
    catalog = Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", reg)
    erp = create_fake_erp(pack, delegation_public_key=PUBLIC_KEY)
    backends = {"erp": httpx.AsyncClient(transport=httpx.ASGITransport(app=erp), base_url="http://erp.test")}
    service = ToolService(catalog, reg, TokenVerifier.from_public_key(PUBLIC_KEY), backends, AuditLog(tmp_path / "a"))
    token = _mint(reg, "E0006")  # 여신심사 직원
    out = await service.call("loan_request", {**LOAN, "amount": amount}, token,
                             CallMeta(trust_level="user_direct", idempotency_key=uuid.uuid4().hex))
    assert out.ok, out.problem
    doc_id = out.data["resource"]["id"]
    got = await service.call("approval_get", {"documentId": doc_id}, token, CallMeta())
    assert got.ok, got.problem
    assert got.data["formId"] == "loan" and len(got.data["steps"]) == steps


def test_eval_path_tools_include_form_tools_after_public(pack: Path) -> None:
    from agent_runtime.evaluation.tool_call import load_tools

    reg = Registry.load(pack)
    tools = load_tools(CONTRACTS / "mcp" / "tools.json", reg.form_tools)
    assert list(tools)[-1] == "loan_request" and tools["loan_request"]["required_scope"] == "approval:request:loan"
