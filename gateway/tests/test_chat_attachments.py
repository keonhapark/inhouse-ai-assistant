"""대화 메시지의 이미지 첨부를 agent /run으로 넘깁니다(#288, 계약 #287)."""

import base64
import json
import logging

import pytest

from .test_chat import _new, agent, chat, events, h, schema_check  # noqa: F401  (픽스처)
from .test_vision import JPEG, _png, _url


def _att(url):
    return {"kind": "image", "dataUrl": url}


def _post(chat, h, cid, **body):
    return chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "이 영수증으로 정산해 줘", **body})


def test_attachments_are_passed_to_run_as_is(chat, h, agent):
    cid = _new(chat, h)
    atts = [_att(_url(_png())), _att(_url(JPEG, "image/jpeg"))]
    r = _post(chat, h, cid, attachments=atts)
    assert r.status_code == 200 and events(r)[-1]["type"] == "done"
    path, body, _ = agent.calls[-1]
    assert path == "/run" and body["attachments"] == atts
    for a in body["attachments"]:
        schema_check.validate("openapi/agent.yaml", "Attachment", a)
    route_body = next(b for p, b, _ in agent.calls if p == "/route")
    assert "attachments" not in route_body  # 라우터에는 넘기지 않음


def test_turn_without_attachments_sends_none(chat, h, agent):
    cid = _new(chat, h)
    _post(chat, h, cid)
    assert "attachments" not in agent.calls[-1][1]


def test_images_are_not_kept_in_conversation_or_logs(chat, h, agent, caplog):
    caplog.set_level(logging.DEBUG)
    cid = _new(chat, h)
    png = _png()
    _post(chat, h, cid, attachments=[_att(_url(png))])
    b64 = base64.b64encode(png).decode()
    conv = chat.get(f"/api/conversations/{cid}", headers=h).json()
    schema_check.validate("openapi/gateway.yaml", "Conversation", conv)
    assert b64 not in json.dumps(conv) and b64 not in caplog.text
    assert b64 not in json.dumps(chat.app_ref.state.audit.events.read_all())


@pytest.mark.parametrize("attachments,status,code", [
    ([_att(_url(b"GIF89a" + b"\x00" * 20, "image/gif"))], 415, "unsupported-media-type"),
    ([_att(_url(JPEG, "image/png"))], 415, "unsupported-media-type"),
    ([_att(_url(_png() + b"\x00" * (5 * 1024 * 1024)))], 413, "payload-too-large"),
    ([_att("https://example.com/a.png")], 422, "validation"),
    ([_att("data:image/png;base64,@@@")], 422, "validation"),
    ([_att(_url(_png()))] * 4, 422, "validation"),                       # 최대 3장
    ([{"kind": "file", "dataUrl": _url(_png())}], 422, "validation"),
    ([{"kind": "image", "dataUrl": _url(_png()), "x": 1}], 422, "validation"),
    ([{"kind": "image"}], 422, "validation"),
    ("not a list", 422, "validation"),
    ([], 422, "validation"),
])
def test_bad_attachments_are_rejected_before_agent(chat, h, agent, attachments, status, code):
    cid = _new(chat, h)
    r = _post(chat, h, cid, attachments=attachments)
    assert r.status_code == status, r.text
    assert r.json()["type"] == f"urn:problem:{code}"
    assert [c for c in agent.calls if c[0] in ("/run", "/route")] == []
    assert "base64," not in r.text


def test_user_message_keeps_attachment_meta_only(chat, h, agent):
    """대화 기록의 user_message에 첨부 메타(kind, mediaType, bytes, sha256)만 남깁니다(#395, 계약 #396)."""
    import hashlib

    cid = _new(chat, h)
    png = _png()
    _post(chat, h, cid, attachments=[_att(_url(png)), _att(_url(JPEG, "image/jpeg"))])
    _post(chat, h, cid)  # 첨부 없는 턴
    conv = chat.get(f"/api/conversations/{cid}", headers=h).json()
    schema_check.validate("openapi/gateway.yaml", "Conversation", conv)
    users = [e for e in conv["events"] if e["type"] == "user_message"]
    assert users[0]["attachments"] == [
        {"kind": "image", "mediaType": "image/png", "bytes": len(png), "sha256": hashlib.sha256(png).hexdigest()},
        {"kind": "image", "mediaType": "image/jpeg", "bytes": len(JPEG), "sha256": hashlib.sha256(JPEG).hexdigest()}]
    assert "attachments" not in users[1]
    assert "base64" not in json.dumps(conv)


@pytest.mark.parametrize("extra,expected", [({"fromAttachments": True}, True), ({"fromAttachments": False}, False),
                                            ({}, None)])
def test_approval_carries_from_attachments(chat, h, agent, extra, expected):
    agent.preview_extra = extra
    cid = _new(chat, h)
    ev = events(chat.post(f"/api/conversations/{cid}/messages", headers=h,
                          json={"content": "회의실 예약해 줘", "attachments": [_att(_url(_png()))]}))
    ap = next(e for e in ev if e["type"] == "approval_required")
    schema_check.validate("openapi/gateway.yaml", "ChatEvent", ap)
    assert ap["approval"].get("fromAttachments") is expected
