"""2단계 에이전트(재무·구매자재)와 도구(경비 정산·구매 요청). 팩 단계를 2로 켜서 시험합니다."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from agent_runtime.mcp_server.catalog import Catalog
from agent_runtime.mcp_server.service import CallMeta
from agent_runtime.registry import Registry, Requester
from tests.conftest import CONTRACTS, PACK_DIR
from tests.mcp_support import Harness, make_harness, mint
from tests.run_support import RunHarness, call, make_run_harness, say

ME = Requester("E0016", "finance", "staff", ("employee",))
TOOLS_JSON = {t["name"]: t for t in json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))["tools"]}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def reg2() -> Registry:
    return Registry.load(PACK_DIR, stage=2)


def test_stage_override(reg2: Registry) -> None:
    stage1 = Registry.load(PACK_DIR, stage=1)
    assert not stage1.has("finance") and not stage1.has("procurement")
    assert reg2.has("finance") and reg2.has("procurement")
    assert reg2.get("finance").model_policy == "local_only"
    assert reg2.get("procurement").model_policy == "external_allowed"


def test_stage2_catalog_exposes_new_tools_verbatim(reg2: Registry) -> None:
    from agent_runtime.mcp_server.server import tool_descriptor

    cat = Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", reg2)
    for name in ("expense_request", "purchase_request"):
        d = tool_descriptor(cat.get(name)).model_dump(by_alias=True, exclude_none=True, mode="json")
        assert d["inputSchema"] == TOOLS_JSON[name]["inputSchema"]
        assert d["description"] == TOOLS_JSON[name]["description"]
        assert d["_meta"]["risk"] == "reversible_write" and d["_meta"]["trustRequired"] == "user_direct"
    stage1 = Catalog.load(CONTRACTS / "mcp" / "tools.json", CONTRACTS / "openapi", Registry.load(PACK_DIR, stage=1))
    assert stage1.get("expense_request") is None


# ---- MCP 도구: 가짜 erp ----


@pytest.fixture
def h2(tmp_path: Path) -> Harness:
    return make_harness(tmp_path, stage=2)


def execute() -> CallMeta:
    return CallMeta(trust_level="user_direct", idempotency_key=f"idem-{uuid.uuid4().hex}")


EXPENSE = {"amount": 42000, "spent_on": "2027-01-11", "merchant": "가나식당", "business_no": "123-45-67890",
           "purpose": "거래처 점심"}
PURCHASE = {"item_code": "BRG-6204", "quantity": 200, "unit_price": 3500, "total_amount": 700000,
            "reason": "생산 라인 교체"}


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "agent", "args", "form"),
                         [("expense_request", "finance", EXPENSE, "expense"),
                          ("purchase_request", "procurement", PURCHASE, "purchase")])
async def test_new_request_tools_preview_and_execute(h2: Harness, tool: str, agent: str, args: dict,
                                                     form: str) -> None:
    token = mint(agent=agent, scopes=["approval:read", f"approval:request:{form}", "approval:withdraw"])
    preview = await h2.service.call(tool, args, token, CallMeta(trust_level="user_direct", dry_run=True))
    assert preview.ok, preview.problem
    done = await h2.service.call(tool, args, token, execute())
    assert done.ok, done.problem
    doc = done.data["resource"]
    assert doc["formId"] == form and doc["fields"] == args
    assert done.data["undoable"] is True


@pytest.mark.anyio
async def test_form_scope_is_narrow(h2: Harness) -> None:
    token = mint(agent="finance", scopes=["approval:request:leave"])
    r = await h2.service.call("expense_request", EXPENSE, token, execute())
    assert r.problem["type"] == "urn:problem:scope-missing"


@pytest.mark.anyio
async def test_business_no_pattern_is_enforced(h2: Harness) -> None:
    r = await h2.service.call("expense_request", {**EXPENSE, "business_no": "1234567890"}, mint(agent="finance"),
                              CallMeta(trust_level="user_direct", dry_run=True))
    assert r.problem["type"] == "urn:problem:validation"


@pytest.mark.anyio
async def test_finance_agent_cannot_call_purchase(h2: Harness) -> None:
    r = await h2.service.call("purchase_request", PURCHASE, mint(agent="finance", tools=["purchase_request"]),
                              execute())
    assert r.problem["type"] == "urn:problem:tool-not-allowed"


# ---- 업무 실행 ----


@pytest.fixture
def r2(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path, stage=2)


async def _run(r: RunHarness, agent: str, message: str) -> dict:
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    return await r.runner.run(mint(agent=agent, cid=conv), conv, agent, message, ME)


@pytest.mark.anyio
@pytest.mark.parametrize(("agent", "tool", "args", "policy"),
                         [("finance", "expense_request", EXPENSE, "local_only"),
                          ("procurement", "purchase_request", PURCHASE, "external_allowed")])
async def test_new_agents_run_with_undo_guidance(r2: RunHarness, agent: str, tool: str, args: dict,
                                                 policy: str) -> None:
    r2.llm.script = [call(tool, args), say("올렸습니다.")]
    s = await _run(r2, agent, "올려 줘")
    assert s["status"] == "completed"
    assert s["actions"][0]["tool"] == tool and s["actions"][0]["undoable"]
    assert "되돌릴 수 있습니다" in s["messages"][0]["content"]
    assert r2.llm.requests[0]["model_policy"] == policy
    names = {t["function"]["name"] for t in r2.llm.requests[0]["tools"]}
    assert tool in names and "leave_request" not in names


@pytest.mark.anyio
async def test_withdraw_from_finance_needs_approval(r2: RunHarness) -> None:
    token = mint(agent="finance")
    created = await r2.h.service.call("expense_request", EXPENSE, token, execute())
    r2.llm.script = [call("approval_withdraw", {"documentId": created.data["resource"]["id"]})]
    s = await _run(r2, "finance", "그 경비 정산 회수해 줘")
    assert s["status"] == "awaiting_approval"
