"""직원에게 보이는 gateway 문구(#577, ux/copy-guide.md·ux/copy-audit/gateway-erp.md).

화면은 problem+json을 `title + " " + detail`로 이어 보여 줍니다. 코드 값(에이전트 id, 필드 이름)이 나오지 않고,
무슨 일이 났는지와 할 일이 함께 나오는지 봅니다.
"""

import pytest

from gateway.chat import agent_label

from .test_chat import _new, agent, chat, h  # noqa: F401  (픽스처)


def _shown(r) -> str:
    p = r.json()
    return f"{p['title']} {p.get('detail') or ''}".strip()


@pytest.mark.parametrize("name,label", [("인사", "인사 담당 AI"), ("재무", "재무 담당 AI"), ("사내 비서", "사내 비서"),
                                        ("규정 AI", "규정 AI")])
def test_agent_label(name, label):
    assert agent_label(name) == label


def test_unknown_agent_shows_no_code_id(chat, h):
    r = chat.post("/api/conversations", headers=h, json={"agentId": "no_such_agent_x1"})
    assert r.status_code == 403
    assert "no_such_agent_x1" not in r.text
    assert _shown(r) == "이 AI 에이전트를 사용할 권한이 없습니다. 다른 AI 에이전트를 고르세요."


@pytest.mark.parametrize("body,shown", [
    ({"content": "가" * 4001}, "메시지는 4,000자까지 보낼 수 있습니다. 줄여서 다시 보내세요."),
    ({"content": "  "}, "보낼 메시지가 없습니다. 내용을 쓰고 다시 보내세요."),
])
def test_message_errors_say_what_to_do(chat, h, body, shown):
    cid = _new(chat, h)
    r = chat.post(f"/api/conversations/{cid}/messages", headers=h, json=body)
    assert r.status_code == 422 and _shown(r) == shown
    assert "content" not in _shown(r)


def test_long_comment_is_named_as_opinion(chat, h):
    r = chat.post("/api/execution-approvals/ap_x", headers=h, json={"decision": "approve", "comment": "가" * 201})
    assert r.status_code == 422 and _shown(r) == "의견은 200자까지 쓸 수 있습니다."


def test_too_many_attachments_uses_photo(chat, h):
    from .test_vision import _png, _url

    cid = _new(chat, h)
    r = chat.post(f"/api/conversations/{cid}/messages", headers=h,
                  json={"content": "정산해 줘", "attachments": [{"kind": "image", "dataUrl": _url(_png())}] * 4})
    assert r.status_code == 422 and _shown(r) == "사진은 한 번에 3장까지 첨부할 수 있습니다."
