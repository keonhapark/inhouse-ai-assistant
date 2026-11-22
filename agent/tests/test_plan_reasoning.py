"""#423·#535: 로컬로 가는 계획 호출의 생각 단계 설정(기본은 보내지 않음=모델 기본 켬, 결정 0008)과,
시간 초과·출구 장애 때 다시 보내 달라는 안내."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from agent_runtime.llm import ChatClient, LLMError, LLMSettings
from agent_runtime.registry import Requester
from agent_runtime.run.graph import llm_failure_message
from tests.mcp_support import mint
from tests.run_support import RunHarness, make_run_harness, say

ME = Requester("E0016", "finance", "staff", ("employee",))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def r(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path)


async def _run(r: RunHarness, agent: str, route_method: str | None = None) -> dict:
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    return await r.runner.run(mint(agent=agent, cid=conv), conv, agent, "연차 며칠 남았어?", ME, "full", None,
                              route_method)


@pytest.mark.anyio
@pytest.mark.parametrize(("agent", "route"), [("hr", None), ("assistant", None), ("assistant", "fallback")])
async def test_plan_reasoning_is_left_to_model_by_default(r: RunHarness, agent: str, route: str | None) -> None:
    # 결정 0008(#535): 기본은 reasoning_effort를 보내지 않습니다(로컬 qwen3.5:9b는 생각 켬)
    r.llm.script = [say("네.")]
    await _run(r, agent, route)
    assert r.llm.requests[0]["extra"] is None


@pytest.mark.anyio
@pytest.mark.parametrize(("agent", "route", "extra"), [
    ("hr", None, {"reasoning_effort": "none"}),          # local_only
    ("assistant", None, None),                           # external_allowed: 보내지 않음
    ("assistant", "fallback", {"reasoning_effort": "none"}),  # fallback 대화는 로컬(#308)
])
async def test_local_plan_call_can_turn_thinking_off(r: RunHarness, agent: str, route: str | None, extra) -> None:
    import dataclasses

    from agent_runtime.run.graph import build_graph

    r.runner.graph = build_graph(dataclasses.replace(_deps(r), plan_reasoning_effort="none"))
    r.llm.script = [say("네.")]
    await _run(r, agent, route)
    assert r.llm.requests[0]["extra"] == extra


def _deps(r: RunHarness):
    from agent_runtime.audit import AuditLog
    from agent_runtime.run.graph import Deps
    from agent_runtime.run.policy import WideScope
    from agent_runtime.run.trust import trusted_docs
    from tests.conftest import PACK_DIR

    return Deps(llm=r.llm, caller=r.caller, audit=AuditLog(r.audit_path), wide=WideScope.from_pack(PACK_DIR),
                trusted_docs=trusted_docs(PACK_DIR))


@pytest.mark.parametrize(("error", "slow"), [
    (LLMError("LLM 응답 504", 504), True), (LLMError("LLM 응답 502", 502), True),
    (LLMError("LLM 호출 실패: ReadTimeout"), True), (LLMError("LLM 응답 403", 403), False),
])
def test_failure_message(error: LLMError, slow: bool) -> None:
    msg = llm_failure_message(error)
    assert ("다시 보내 주세요" in msg) is slow


@pytest.mark.anyio
async def test_timeout_turn_fails_with_retry_guidance(r: RunHarness) -> None:
    r.llm.script = [LLMError("LLM 응답 504", 504)]
    s = await _run(r, "hr")
    assert s["status"] == "failed" and "다시 보내 주세요" in s["messages"][0]["content"]


def test_chat_client_sends_extra() -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": "네"}}]})

    chat = ChatClient(LLMSettings(base_url="http://gw.invalid/v1", model="local",
                                  policy_aliases={"local_only": "local", "external_allowed": "external"}),
                      transport=httpx.MockTransport(handler))
    chat.chat([{"role": "user", "content": "x"}], None, None, "local_only", {"reasoning_effort": "none"})
    chat.chat([{"role": "user", "content": "x"}], None, None, "external_allowed")
    assert seen[0]["reasoning_effort"] == "none" and seen[0]["model"] == "local"
    assert "reasoning_effort" not in seen[1]
