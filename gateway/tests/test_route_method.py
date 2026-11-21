"""대화를 연 라우팅 방식을 agent /run의 routeMethod로 넘깁니다(#311, 계약 #310, #308)."""

import pytest

from .test_chat import _new, agent, chat, events, h, schema_check  # noqa: F401  (픽스처)


def _runs(agent):
    return [b for p, b, _ in agent.calls if p == "/run"]


@pytest.mark.parametrize("method", ["fallback", "llm", "keyword"])
def test_router_method_is_passed_on_every_run_of_the_conversation(chat, h, agent, method):
    agent.route_method = method
    cid = _new(chat, h)
    for text in ("출장비 규정 알려 줘", "고마워"):
        events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": text}))
    runs = _runs(agent)
    assert len(runs) == 2 and all(r["routeMethod"] == method for r in runs)


def test_explicit_conversation_sends_explicit(chat, h, agent):
    cid = _new(chat, h, agentId="hr")
    events(chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "연차 며칠 남았어?"}))
    assert _runs(agent)[-1]["routeMethod"] == "explicit"
    assert "/route" not in [p for p, _, _ in agent.calls]
