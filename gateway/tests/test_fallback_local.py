"""입구 라우터 fallback 대화는 출구에서도 로컬로만 보냅니다(#308 두 번째 방어선).

#128 실행 중 로컬 모델이 내려가자 라우터의 LLM 호출이 실패해 fallback 에이전트(외부 허용)로 넘어갔고, 인사 요청 원문이
외부 모델로 나갔습니다. agent는 routeMethod=fallback 대화를 로컬로 고정합니다(force_local). gateway는 그 표시를 agent에만
맡기지 않고, 대화의 라우팅 방법을 보고 외부 별칭 요청을 로컬로 돌립니다.
"""

import json

import pytest

from .test_model_override import _conv, _token, ec  # noqa: F401  (픽스처)

MSG = [{"role": "user", "content": "규정 알려 줘"}]


def _fallback_agent(app) -> str:
    agent = app.state.registry.get(app.state.registry.fallback_agent)
    assert agent.model_policy["mode"] == "external_allowed"   # 이 정책대로면 외부로 가던 경로입니다
    return agent.id


def _routed(ec, staff_no, method):
    """채팅 흐름으로 대화를 열어 라우터가 fallback 에이전트를 method로 고른 상태를 만듭니다."""
    ec.agent.route_to, ec.agent.route_method = _fallback_agent(ec.app_ref), method
    r, h = _conv(ec, staff_no)
    cid = r.json()["conversationId"]
    ec.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "출장비 규정 알려 줘"})
    assert ec.app_ref.state.chat.route_method_of(cid) == method
    return cid, _token(ec, staff_no, cid, ec.agent.route_to)


def _send(ec, tok, model="external"):
    return ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": model, "messages": MSG})


def test_fallback_conversation_external_request_goes_local(ec, staff_no):
    cid, tok = _routed(ec, staff_no, "fallback")
    r = _send(ec, tok)
    assert r.status_code == 200 and r.headers["x-egress-location"] == "local"
    assert json.loads(ec.llm.requests[-1].content)["model"] == "local"
    assert ec.app_ref.state.audit.egress.read_all() == []          # 외부 전송 기록 없음
    ev = [e for e in ec.app_ref.state.audit.events.read_all() if e["kind"] == "llm.request"][-1]
    assert ev["model"]["externalSent"] is False and "라우터 fallback 대화" in ev["detail"]


def test_local_failure_in_fallback_conversation_does_not_go_external(ec, staff_no):
    """로컬이 실패하면 오류로 끝나고 외부로 가지 않습니다(이슈 완료 조건)."""
    cid, tok = _routed(ec, staff_no, "fallback")
    ec.llm.mode = "down"
    r = _send(ec, tok)
    assert r.status_code == 502
    assert all(json.loads(q.content)["model"] == "local" for q in ec.llm.requests)
    assert ec.app_ref.state.audit.egress.read_all() == []


@pytest.mark.parametrize("method", ["llm", "keyword"])
def test_chosen_external_agent_keeps_its_policy(ec, staff_no, method):
    cid, tok = _routed(ec, staff_no, method)
    r = _send(ec, tok)
    assert r.status_code == 200 and r.headers["x-egress-location"] == "external"


@pytest.mark.parametrize("condition,location", [("full", "local"), ("write_blocked", "local"), ("approve_all", "local"),
                                                ("no_guard", "external"), ("baseline_tools", "external")])
def test_eval_conditions(ec, staff_no, condition, location):
    """장치를 끄는 평가 조건에서만 외부를 허용합니다(agent model_policy_for와 같음)."""
    cid, tok = _routed(ec, staff_no, "fallback")
    ec.app_ref.state.egress.condition_of = lambda _cid: condition
    assert _send(ec, tok).headers["x-egress-location"] == location
