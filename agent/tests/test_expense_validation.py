"""#426: 슬랙 경비 정산이 MCP 입력 검증에 막히던 경우. 인자 정리, 실패 사유 감사 detail, 프롬프트(날짜·선택 항목)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from agent_runtime.registry import Registry, Requester
from agent_runtime.run.args import normalize_args, optional_args
from agent_runtime.run.graph import system_prompt
from tests.conftest import PACK_DIR
from tests.mcp_support import mint
from tests.run_support import RunHarness, call, make_run_harness, say

ME = Requester("E0016", "finance", "staff", ("employee",))
SCHEMA = {"type": "object", "required": ["amount", "spent_on", "merchant", "purpose"],
          "properties": {"amount": {"type": "integer", "minimum": 1}, "spent_on": {"type": "string", "format": "date"},
                         "merchant": {"type": "string"}, "business_no": {"type": "string", "pattern": "^x$"},
                         "purpose": {"type": "string"}}}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def r2(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path, stage=2)


@pytest.mark.parametrize(("raw", "expected"), [
    ({"amount": 1, "business_no": ""}, {"amount": 1}),
    ({"amount": 1, "business_no": "  "}, {"amount": 1}),
    ({"amount": 1, "business_no": None}, {"amount": 1}),
    ({"amount": "15,000"}, {"amount": 15000}),
    ({"amount": "15000원"}, {"amount": 15000}),
    ({"amount": "15,00"}, {"amount": "15,00"}),        # 숫자 모양이 아니면 그대로(MCP 검증이 잡음)
    ({"amount": "약 만오천"}, {"amount": "약 만오천"}),
    ({"merchant": ""}, {"merchant": ""}),               # 필수 항목은 빼지 않음(검증이 묻게)
])
def test_normalize_args(raw: dict, expected: dict) -> None:
    assert normalize_args(raw, SCHEMA) == expected


def test_optional_args() -> None:
    assert optional_args(SCHEMA) == ["business_no"]


async def _run(r: RunHarness, message: str, conv: str | None = None) -> dict:
    conv = conv or f"cnv_{uuid.uuid4().hex[:8]}"
    return await r.runner.run(mint(agent="finance", cid=conv), conv, "finance", message, ME)


@pytest.mark.anyio
async def test_slack_sentence_with_empty_optional_and_comma_amount_goes_through(r2: RunHarness) -> None:
    """슬랙에서 쓴 문장: 모델이 business_no를 ""로, 금액을 "15,000"으로 채워도 정산이 올라갑니다."""
    args = {"amount": "15,000", "spent_on": "2027-03-01", "merchant": "카카오택시", "business_no": "",
            "purpose": "고객사 미팅 이동"}
    r2.llm.script = [call("expense_request", args), say("올렸습니다.")]
    s = await _run(r2, "어제 택시비 15,000원 정산해 줘. 카카오택시, 고객사 미팅 이동")
    assert s["status"] == "completed", s
    assert "expense_request: business_no" in r2.llm.requests[0]["messages"][0]["content"]
    executed = [c for c in r2.caller.calls if c[0] == "expense_request" and not c[2].get("dryRun")]
    assert executed[0][1] == {"amount": 15000, "spent_on": "2027-03-01", "merchant": "카카오택시",
                              "purpose": "고객사 미팅 이동"}


@pytest.mark.anyio
async def test_unresolved_date_is_reported_to_model_and_audited_without_value(r2: RunHarness) -> None:
    args = {"amount": 15000, "spent_on": "어제", "merchant": "카카오택시", "purpose": "고객사 미팅 이동"}
    r2.llm.script = [call("expense_request", args), say("날짜를 다시 알려 주세요.")]
    await _run(r2, "어제 택시비 15,000원 정산해 줘. 카카오택시, 고객사 미팅 이동")
    tool_msg = json.loads(r2.llm.requests[1]["messages"][-1]["content"])
    assert tool_msg["problem"]["type"] == "urn:problem:validation"
    assert {"field": "spent_on", "rule": "format"} in tool_msg["problem"]["errors"]
    [event] = [e for e in r2.h.events() if e["kind"] == "tool.blocked" and e["operation"] == "expense_request"]
    assert event["detail"] == "입력 검증 실패: spent_on(format)"
    assert "어제" not in json.dumps(event, ensure_ascii=False)


@pytest.mark.anyio
async def test_missing_and_extra_fields_are_named(r2: RunHarness) -> None:
    from agent_runtime.mcp_server.service import CallMeta

    out = await r2.h.service.call("expense_request", {"amount": 1, "memo": "x"}, mint(agent="finance"),
                                  CallMeta(trust_level="user_direct"))
    fields = {(e["field"], e["rule"]) for e in out.problem["errors"]}
    assert ("spent_on,merchant,purpose", "required") in fields and ("memo", "additionalProperties") in fields


def test_prompt_lists_optional_write_args_and_date_rule() -> None:
    reg = Registry.load(PACK_DIR, stage=2)
    text = system_prompt(reg.get("finance"), "full", datetime(2027, 3, 2, 9), True, ["expense_request"],
                         {"expense_request": ["business_no"]})
    assert "YYYY-MM-DD로 풀어 씁니다" in text and "expense_request: business_no" in text
