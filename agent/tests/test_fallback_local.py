"""#308: 라우터가 부서를 고르지 못한(fallback) 대화는 fallback 에이전트 정책과 관계없이 로컬로 실행합니다."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from agent_runtime.llm import POLICY_ALIASES, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.router import Router
from tests.conftest import content_response
from tests.mcp_support import mint
from tests.run_support import RunHarness, make_run_harness, say

ME = Requester("E0016", "finance", "staff", ("employee",))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def r(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path)


def _fail(req: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("로컬 모델 없음")


ROUTER_FAILURES = {
    "llm:error": _fail,
    "llm:unparsable": lambda req: content_response("모르겠습니다"),
    "llm:no_choice": lambda req: content_response('{"agentId": "none", "confidence": 0.9, "reason": "없음"}'),
    "llm:low_confidence": lambda req: content_response('{"agentId": "hr", "confidence": 0.1, "reason": "애매"}'),
}


async def _run(r: RunHarness, agent: str, route_method: str | None, conv: str, condition: str = "full") -> dict:
    return await r.runner.run(mint(agent=agent, cid=conv), conv, agent, "연차 며칠 남았어?", ME, condition,
                              None, route_method)


@pytest.mark.anyio
@pytest.mark.parametrize("cause", list(ROUTER_FAILURES))
async def test_fallback_conversation_runs_local(r: RunHarness, registry: Registry, stub_chat, cause: str) -> None:
    d = Router(registry, stub_chat(ROUTER_FAILURES[cause])).route("연차 며칠 남았어?", ME)
    assert d.method == "fallback" and d.audit_reason.startswith(cause)
    fallback = registry.get(d.agent_id)
    assert fallback.model_policy == "external_allowed"  # 이 정책대로면 외부로 가던 경로입니다
    r.llm.script = [say("인사 담당에 문의해 주세요.")]
    await _run(r, d.agent_id, d.method, f"cnv_{uuid.uuid4().hex[:8]}")
    policy = r.llm.requests[0]["model_policy"]
    assert policy == "local_only"
    assert LLMSettings("http://gw.invalid/v1", "local", policy_aliases=dict(POLICY_ALIASES)).model_for(policy) == "local"


@pytest.mark.anyio
async def test_fallback_stays_local_for_later_turns(r: RunHarness) -> None:
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    r.llm.script = [say("네."), say("네.")]
    await _run(r, "assistant", "fallback", conv)
    await _run(r, "assistant", None, conv)  # 뒤 턴에는 routeMethod가 없어도
    assert [q["model_policy"] for q in r.llm.requests] == ["local_only", "local_only"]


@pytest.mark.anyio
@pytest.mark.parametrize("method", [None, "llm", "keyword", "explicit"])
async def test_chosen_assistant_keeps_its_policy(r: RunHarness, method: str | None) -> None:
    r.llm.script = [say("네.")]
    await _run(r, "assistant", method, f"cnv_{uuid.uuid4().hex[:8]}")
    assert r.llm.requests[0]["model_policy"] == "external_allowed"


@pytest.mark.anyio
@pytest.mark.parametrize(("condition", "policy"), [("write_blocked", "local_only"), ("approve_all", "local_only"),
                                                   ("no_guard", "external_allowed"),
                                                   ("baseline_tools", "external_allowed")])
async def test_fallback_by_condition(r: RunHarness, condition: str, policy: str) -> None:
    """장치를 끄는 조건(no_guard·baseline_tools)은 conditions.md대로 모두 외부입니다."""
    r.llm.script = [say("네.")]
    await _run(r, "assistant", "fallback", f"cnv_{uuid.uuid4().hex[:8]}", condition)
    assert r.llm.requests[0]["model_policy"] == policy


def test_run_api_rejects_unknown_route_method(registry: Registry, stub_chat, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from agent_runtime.app import Services, create_app
    from agent_runtime.audit import AuditLog

    svc = Services(registry, Router(registry, stub_chat(_fail)), AuditLog(tmp_path / "a.jsonl"))
    body = {"conversationId": "cnv_x", "agentId": "assistant", "message": "x", "routeMethod": "guess",
            "requester": {"employeeId": "E0016", "unitId": "finance", "grade": "staff", "roles": ["employee"]}}
    assert TestClient(create_app(svc)).post("/run", json=body, headers={"X-Delegation-Token": "t"}).status_code == 422
