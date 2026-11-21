"""3단계 품질·영업 에이전트(#382). 가짜 erp와 각본 LLM으로 돌립니다(실제 모델은 GPU 차례에)."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

import pytest

from agent_runtime.registry import Registry, Requester
from agent_runtime.run.graph import UNTRUSTED_NOTE
from agent_runtime.run.image_reading import ImageSpec
from tests.conftest import PACK_DIR
from tests.mcp_support import mint
from tests.run_support import RunHarness, call, make_run_harness, say

STAFF = Requester("E0016", "finance", "staff", ("employee",))
SALES = Requester("E0023", "sales", "staff", ("employee", "sales_staff"))  # gateway가 org.yaml 역할을 넣음
IMAGE = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake defect").decode()
DEFECT = {"itemCode": "HSG-A100", "defectType": "균열", "severity": "major", "quantity": 3,
          "location": "체결부 모서리", "description": "사출 후 체결부 모서리에 균열"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def r3(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path, stage=3)


class StubReader:
    def __init__(self, result: dict | None) -> None:
        self.result = result
        self.specs: list[ImageSpec] = []

    async def read_all(self, data_urls: list[str], token: str, spec: ImageSpec) -> list[dict | None]:
        self.specs.append(spec)
        return [self.result for _ in data_urls]


async def _run(r: RunHarness, agent: str, who: Requester, message: str, attachments: list[str] | None = None,
               conv: str | None = None, token: str | None = None) -> tuple[dict, str, str]:
    conv = conv or f"cnv_{uuid.uuid4().hex[:8]}"
    token = token or mint(employee=who.employee_id, agent=agent, cid=conv)
    s = await r.runner.run(token, conv, agent, message, who, "full", attachments)
    return s, conv, token


def test_stage3_agents_and_policies() -> None:
    reg3 = Registry.load(PACK_DIR, stage=3)
    q, s = reg3.get("quality"), reg3.get("sales")
    assert q.model_policy == "external_allowed" and s.model_policy == "external_allowed"
    assert q.callable_for(STAFF) and not s.callable_for(STAFF) and s.callable_for(SALES)
    assert ImageSpec.from_agent(q).draft_tool == "defect_report_draft"
    assert ImageSpec.from_agent(s) is None
    assert not Registry.load(PACK_DIR, stage=2).has("quality")


@pytest.mark.anyio
async def test_defect_photo_draft_needs_approval_then_undoable(r3: RunHarness) -> None:
    stub = StubReader({"item_code": "HSG-A100", "defect_type": "균열", "location": "체결부 모서리",
                       "severity": "major"})
    r3.runner.images = stub
    r3.llm.script = [call("defect_report_draft", DEFECT), say("초안을 썼습니다.")]
    s, conv, token = await _run(r3, "quality", STAFF, "이 사진 불량 보고서 초안 써 줘. 3개 나왔어", [IMAGE])
    assert stub.specs[0].purpose == "불량 사진"
    note = r3.llm.requests[0]["messages"][-1]["content"]
    assert note.startswith(UNTRUSTED_NOTE) and "균열" in note
    # 사진을 읽은 턴: 초안 도구만 막지 않고 미리보기 승인(결정 0004 덧붙임)
    assert s["status"] == "awaiting_approval" and s["pendingApproval"]["toolPreview"]["tool"] == "defect_report_draft"
    assert r3.llm.requests[0]["model_policy"] == "external_allowed"  # 사진 자체는 gateway가 로컬 비전으로
    done = await r3.runner.resume(token, conv, s["pendingApproval"]["approvalId"], "approve")
    assert done["status"] == "completed" and done["actions"][0]["tool"] == "defect_report_draft"
    assert done["actions"][0]["undoable"] is True


@pytest.mark.anyio
async def test_defect_draft_without_photo_runs_with_undo_guidance(r3: RunHarness) -> None:
    r3.llm.script = [call("defect_report_draft", DEFECT), say("초안을 썼습니다.")]
    s, _, _ = await _run(r3, "quality", STAFF, "HSG-A100 균열 3개 불량 보고서 초안 써 줘")
    assert s["status"] == "completed" and "되돌릴 수 있습니다" in s["messages"][0]["content"]


@pytest.mark.anyio
async def test_sales_quote_draft_and_lookups(r3: RunHarness) -> None:
    quote = {"customerId": "cus_0001", "lines": [{"itemCode": "GR-M2-40", "quantity": 50}]}
    r3.llm.script = [call("customer_search", {"q": "가온테크"}), call("quote_draft", quote), say("견적 초안을 썼습니다.")]
    s, _, _ = await _run(r3, "sales", SALES, "가온테크에 평기어 GR-M2-40 50개 견적 초안 써 줘")
    names = {t["function"]["name"] for t in r3.llm.requests[0]["tools"]}
    assert {"quote_draft", "customer_search", "item_search"} <= names
    assert [c[0] for c in r3.caller.calls] == ["customer_search", "quote_draft"]
    assert s["status"] == "completed" and s["actions"][0]["tool"] == "quote_draft" and s["actions"][0]["undoable"]


@pytest.mark.anyio
async def test_non_sales_staff_gets_no_sales_tools(r3: RunHarness) -> None:
    r3.llm.script = [say("영업 담당자만 쓸 수 있습니다.")]
    await _run(r3, "sales", STAFF, "견적 목록 보여 줘")
    assert r3.llm.requests[0]["tools"] is None
