"""도구 표시 이름(#575): 미리보기·완료한 일의 toolLabel과 표시 이름 우선순위."""

from __future__ import annotations

import dataclasses
import shutil
import uuid
from pathlib import Path

import jsonschema
import pytest
import yaml

from agent_runtime.pack_tools import form_tools, tool_labels
from agent_runtime.registry import Requester
from agent_runtime.run.graph import build_graph
from tests.conftest import CONTRACTS, PACK_DIR
from tests.mcp_support import mint
from tests.run_support import RunHarness, call, make_run_harness, say
from tests.test_plan_reasoning import _deps

ME = Requester("E0016", "finance", "staff", ("employee",))
TOOLS = CONTRACTS / "mcp" / "tools.json"
# 500만 원을 넘는 구매 요청은 구매자재 에이전트에서 미리보기 승인을 받습니다(팩 risk_policy overrides)
BIG = {"item_code": "BRG-6204", "quantity": 2000, "unit_price": 3500, "total_amount": 7000000, "reason": "설비 교체"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_label_precedence(tmp_path: Path) -> None:
    # tools.json displayName
    base = tool_labels(TOOLS, PACK_DIR)
    assert base["room_reserve"] == "회의실 예약" and base["expense_request"] == "경비 정산 상신"
    # 팩 양식 도구: tool.displayName, 없으면 '<양식 이름> 상신'
    fin = PACK_DIR.parent / "finance"
    forms = yaml.safe_load((fin / "forms.yaml").read_text("utf-8"))
    loan = next(f for f in forms["forms"] if f["id"] == "loan")
    assert tool_labels(TOOLS, fin, form_tools(forms))["loan_request"] == (loan["tool"].get("displayName")
                                                                          or f"{loan['name']} 상신")
    # pack.yaml tool_display_names가 가장 앞섬
    dst = tmp_path / "manufacturing"
    shutil.copytree(PACK_DIR, dst)
    pack = yaml.safe_load((dst / "pack.yaml").read_text("utf-8"))
    pack["tool_display_names"] = {"room_reserve": "회의실 잡기"}
    (dst / "pack.yaml").write_text(yaml.safe_dump(pack, allow_unicode=True), "utf-8")
    assert tool_labels(TOOLS, dst)["room_reserve"] == "회의실 잡기"


@pytest.fixture
def r2(tmp_path: Path) -> RunHarness:
    r = make_run_harness(tmp_path, stage=2)
    r.runner.graph = build_graph(dataclasses.replace(_deps(r), tool_labels=tool_labels(TOOLS, PACK_DIR)))
    return r


@pytest.mark.anyio
async def test_preview_and_action_carry_tool_label(r2: RunHarness) -> None:
    spec = yaml.safe_load((CONTRACTS / "openapi" / "agent.yaml").read_text("utf-8"))
    schemas = spec["components"]["schemas"]
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    token = mint(agent="procurement", cid=conv)
    r2.llm.script = [call("purchase_request", BIG), say("올렸습니다.")]
    s = await r2.runner.run(token, conv, "procurement", "BRG-6204 2000개 개당 3,500원 구매 요청해 줘. 설비 교체", ME, "full",
                            None)
    preview = s["pendingApproval"]["toolPreview"]
    assert preview["tool"] == "purchase_request" and preview["toolLabel"] == "구매 요청 상신"
    jsonschema.validate(preview, {**schemas["ToolPreview"], "components": spec["components"]})
    done = await r2.runner.resume(token, conv, s["pendingApproval"]["approvalId"], "approve")
    [action] = done["actions"]
    assert action["toolLabel"] == "구매 요청 상신"
    jsonschema.validate(action, schemas["ExecutedAction"])


@pytest.mark.anyio
async def test_no_label_without_table(tmp_path: Path) -> None:
    r = make_run_harness(tmp_path, stage=2)  # 표시 이름 표 없이 만든 그래프: toolLabel을 넣지 않음(선택 필드)
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    r.llm.script = [call("purchase_request", BIG)]
    s = await r.runner.run(mint(agent="procurement", cid=conv), conv, "procurement", "구매 요청해 줘", ME, "full", None)
    assert "toolLabel" not in s["pendingApproval"]["toolPreview"]
