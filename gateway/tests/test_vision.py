"""이미지 입력은 로컬 비전 별칭으로만 보냅니다(#261, 계약 #263)."""

import base64
import hashlib
import json
import struct
import zlib

import pytest

from gateway.egress import load_model_info

from .conftest import ROOT
from .test_egress import _agent_ids, _audit, token_for  # noqa: F401  (픽스처)


def _png(w: int = 2, h: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


def _url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _msg(url: str) -> list[dict]:
    return [{"role": "user", "content": [{"type": "text", "text": "영수증 금액을 읽어 줘"},
                                         {"type": "image_url", "image_url": {"url": url}}]}]


@pytest.fixture
def external_ok(app):
    return _agent_ids(app)[1]


def test_config_has_local_vision_alias():
    from gateway.profiles import load_model_profiles

    profiles = load_model_profiles(ROOT / "gateway/litellm/config.yaml")
    assert [p["alias"] for p in profiles if p["profile"]["vision"]] == ["local-vision"]
    assert next(p for p in profiles if p["alias"] == "local-vision")["location"] == "local"


@pytest.mark.parametrize("requested", ["external", "local", "local-gguf"])
def test_image_goes_to_local_vision_even_when_external_is_allowed(client, app, token_for, litellm, external_ok,
                                                                  requested):
    png = _png()
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": requested, "messages": _msg(_url(png))})
    assert r.status_code == 200, r.text
    assert r.headers["x-egress-model"] == "local-vision" and r.headers["x-egress-location"] == "local"
    assert [json.loads(q.content)["model"] for q in litellm.requests] == ["local-vision"]
    assert litellm.last_body()["messages"] == _msg(_url(png))  # 로컬로는 이미지를 그대로 넘깁니다
    assert app.state.audit.egress.read_all() == []  # 외부 전송 기록 없음
    ev = _audit(app)[-1]
    assert ev["result"] == "ok" and ev["model"]["name"] == "local-vision" and ev["model"]["externalSent"] is False
    # 감사에는 이미지 본문 대신 형식·크기·해시만
    assert hashlib.sha256(png).hexdigest() in ev["detail"] and f"{len(png)}" in ev["detail"]
    assert base64.b64encode(png).decode() not in json.dumps(_audit(app), ensure_ascii=False)


def test_image_without_token_also_goes_local(client, litellm):
    r = client.post("/v1/chat/completions", json={"model": "external", "messages": _msg(_url(JPEG, "image/jpeg"))})
    assert r.status_code == 200 and litellm.last_body()["model"] == "local-vision"


def test_external_failure_never_falls_through_with_image(client, app, token_for, litellm, external_ok):
    """외부 장애 폴백 경로와 섞이지 않습니다: 처음부터 외부로 보내지 않습니다."""
    litellm.external_mode = "down"
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": _msg(_url(_png()))})
    assert r.status_code == 200
    assert all(json.loads(q.content)["model"] == "local-vision" for q in litellm.requests)


@pytest.mark.parametrize("url,status,code", [
    (_url(b"GIF89a" + b"\x00" * 20, "image/gif"), 415, "unsupported-media-type"),
    (_url(JPEG, "image/png"), 415, "unsupported-media-type"),   # 선언한 형식과 실제 바이트가 다름
    (_url(b"not an image", "image/png"), 415, "unsupported-media-type"),
    ("https://example.com/r.png", 422, "validation"),
    ("data:image/png;base64,@@@", 422, "validation"),
    ("data:image/png,raw", 422, "validation"),
])
def test_bad_images_are_rejected_before_sending(client, app, litellm, url, status, code):
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": _msg(url)})
    assert r.status_code == status, r.text
    assert r.json()["type"] == f"urn:problem:{code}"
    assert litellm.requests == []
    ev = _audit(app)[-1]
    assert ev["result"] == "denied" and ev["problemType"] == f"urn:problem:{code}"
    assert "base64," not in (ev.get("detail") or "")


def test_too_large_image_is_413(client, app, litellm):
    big = _png() + b"\x00" * (5 * 1024 * 1024)
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": _msg(_url(big))})
    assert r.status_code == 413 and r.json()["type"] == "urn:problem:payload-too-large"
    assert litellm.requests == []


def test_malformed_image_part_is_422(client, litellm):
    bad = [{"role": "user", "content": [{"type": "image_url", "image_url": "data:image/png;base64,AAAA"}]}]
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": bad})
    assert r.status_code == 422 and litellm.requests == []


def test_text_only_requests_are_unchanged(client, litellm):
    parts = [{"role": "user", "content": [{"type": "text", "text": "안녕"}]}]
    assert client.post("/v1/chat/completions", json={"model": "local", "messages": parts}).status_code == 200
    assert litellm.last_body()["model"] == "local"


def test_image_is_refused_without_local_vision_alias(client, app, litellm):
    app.state.egress.vision_alias = None
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": _msg(_url(_png()))})
    assert r.status_code == 400 and r.json()["type"] == "urn:problem:unsupported-parameter"
    assert litellm.requests == []


@pytest.mark.parametrize("part", [
    {"type": "file", "file": {"file_data": "data:image/png;base64,iVBORw0KGgo="}},
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
    {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "wav"}},
    "그냥 문자열",
])
def test_other_part_types_are_rejected(client, app, token_for, litellm, external_ok, part):
    """file·공급자 고유 블록은 이미지를 실어 외부로 나갈 수 있어 받지 않습니다."""
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": [part]}]})
    assert r.status_code == 422, r.text
    assert litellm.requests == [] and app.state.audit.egress.read_all() == []
    assert "iVBOR" not in json.dumps(_audit(app), ensure_ascii=False)


def test_inline_data_url_in_text_never_goes_external(client, app, token_for, litellm, external_ok):
    text = "이거 읽어 줘 " + _url(_png())
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": text}]})
    assert r.status_code == 422 and litellm.requests == []
    assert app.state.audit.egress.read_all() == []
    assert base64.b64encode(_png()).decode() not in json.dumps(_audit(app), ensure_ascii=False)
    # 로컬로 가는 요청은 사내에서 돌아 그대로 받습니다
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": [{"role": "user", "content": text}]})
    assert r.status_code == 200


def test_stream_image_goes_to_local_vision(client, app, token_for, litellm, external_ok):
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "stream": True, "messages": _msg(_url(_png()))})
    assert r.status_code == 200 and "안녕" in r.text
    assert litellm.last_body()["model"] == "local-vision" and app.state.audit.egress.read_all() == []


@pytest.mark.parametrize("condition", ["no_guard", "baseline_tools"])
def test_image_stays_local_when_eval_condition_turns_guards_off(client, app, token_for, litellm, external_ok,
                                                                condition):
    """로컬 강제를 끄는 평가 조건에서도 이미지는 외부로 보내지 않습니다(정책 판단 전에 별칭을 바꿈)."""
    app.state.egress.condition_of = lambda _cid: condition
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": _msg(_url(_png()))})
    assert r.status_code == 200 and litellm.last_body()["model"] == "local-vision"
