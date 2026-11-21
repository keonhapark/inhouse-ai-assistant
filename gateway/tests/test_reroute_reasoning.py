"""외부 별칭 요청을 로컬로 돌릴 때 생각 단계를 끕니다(#427).

로컬 qwen3.5:9b는 생각 모드가 기본이라, 외부 모델을 기대한 호출을 로컬로 돌리면 길게 생각하다 시간 제한을 넘깁니다.
gateway가 로컬로 돌린 호출에 reasoning_effort·think가 없으면 reasoning_effort(기본 none)를 채우고 감사 detail에 적습니다.
"""

import json

import pytest

from .test_egress import _agent_ids, _llm_events, ledger, token_for  # noqa: F401  (픽스처)
from .test_pack_local import _external_ok_in_pack, _token, local_pack, lp  # noqa: F401  (픽스처)
from .test_vision import _msg, _png, _url

NOTE = "생각 단계 끔(reasoning_effort=none)"
HR = [{"role": "user", "content": "2027년 3월 11일 병가 하루 신청해 줘."}]   # 업무 주제 hr-attendance → 로컬
MSG = [{"role": "user", "content": "안녕"}]


def _bodies(litellm) -> list[dict]:
    return [json.loads(q.content) for q in litellm.requests]


def _last_event(app) -> dict:
    return _llm_events(app)[-1]


def _post(client, app, token_for, body):
    _, external_ok = _agent_ids(app)
    return client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)}, json=body)


def test_confidential_reroute_turns_thinking_off(client, app, token_for, litellm):
    r = _post(client, app, token_for, {"model": "external", "messages": HR})
    assert r.status_code == 200, r.text
    (sent,) = _bodies(litellm)
    assert sent["model"] == "local" and sent["reasoning_effort"] == "none"
    assert _last_event(app)["detail"] == NOTE


def test_external_and_direct_local_requests_are_left_alone(client, app, token_for, litellm):
    assert _post(client, app, token_for, {"model": "external", "messages": MSG}).status_code == 200
    assert _post(client, app, token_for, {"model": "local", "messages": MSG}).status_code == 200
    assert [("reasoning_effort" in b, b["model"]) for b in _bodies(litellm)] == [(False, "external"), (False, "local")]
    assert _last_event(app).get("detail") is None


@pytest.mark.parametrize("field,value", [("reasoning_effort", "high"), ("think", True)])
def test_caller_choice_is_kept(client, app, token_for, litellm, field, value):
    r = _post(client, app, token_for, {"model": "external", "messages": HR, field: value})
    assert r.status_code == 200
    (sent,) = _bodies(litellm)
    assert sent["model"] == "local" and sent[field] == value
    assert "reasoning_effort" not in sent or field == "reasoning_effort"
    assert NOTE not in (_last_event(app).get("detail") or "")


def test_setting_can_turn_it_off(client, app, token_for, litellm):
    app.state.egress.local_reasoning_effort = None
    assert _post(client, app, token_for, {"model": "external", "messages": HR}).status_code == 200
    assert "reasoning_effort" not in _bodies(litellm)[0]


def test_alias_that_drops_reasoning_effort_gets_none(client, app, token_for, litellm):
    app.state.egress.drop_params = {**app.state.egress.drop_params, "local": frozenset({"reasoning_effort"})}
    assert _post(client, app, token_for, {"model": "external", "messages": HR}).status_code == 200
    assert "reasoning_effort" not in _bodies(litellm)[0]
    assert NOTE not in (_last_event(app).get("detail") or "")


@pytest.mark.parametrize("stream", [False, True])
def test_fallback_turns_thinking_off_only_on_the_local_retry(client, app, token_for, litellm, stream):
    litellm.external_mode = "500"
    r = _post(client, app, token_for, {"model": "external", "messages": MSG, "stream": stream})
    assert r.status_code == 200
    first, retry = _bodies(litellm)
    assert first["model"] == "external" and "reasoning_effort" not in first
    assert retry["model"] == "local" and retry["reasoning_effort"] == "none"
    assert _last_event(app)["detail"] == f"외부 장애(llm-upstream-error)로 로컬 폴백; {NOTE}"


def test_over_budget_reroute_turns_thinking_off(client, app, token_for, litellm, ledger):
    _, external_ok = _agent_ids(app)
    ledger.agent_limits = {external_ok: 0.1}
    litellm.cost = "0.25"
    assert _post(client, app, token_for, {"model": "external", "messages": MSG}).status_code == 200
    assert _post(client, app, token_for, {"model": "external", "messages": MSG}).status_code == 200
    assert litellm.last_body()["model"] == "local" and litellm.last_body()["reasoning_effort"] == "none"
    assert _last_event(app)["detail"].endswith(f"로컬 모델로 내림; {NOTE}")


def test_image_sent_to_external_alias_turns_thinking_off(client, app, token_for, litellm):
    r = _post(client, app, token_for, {"model": "external", "messages": _msg(_url(_png()))})
    assert r.status_code == 200, r.text
    assert litellm.last_body()["model"] == "local-vision" and litellm.last_body()["reasoning_effort"] == "none"
    assert _last_event(app)["detail"].endswith(f"; {NOTE}")


def test_image_sent_to_local_alias_is_left_alone(client, app, token_for, litellm):
    assert _post(client, app, token_for, {"model": "local", "messages": _msg(_url(_png()))}).status_code == 200
    assert "reasoning_effort" not in litellm.last_body()


def test_pack_local_only_reroute_turns_thinking_off(lp):
    tok = _token(lp, _external_ok_in_pack())
    r = lp.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 200
    body = json.loads(lp.llm.requests[-1].content)
    assert body["model"] == "local" and body["reasoning_effort"] == "none"
    ev = lp.app_ref.state.audit.events.read_all()[-1]
    assert ev["detail"].endswith(f"; {NOTE}") and "팩 외부 LLM 금지" in ev["detail"]
