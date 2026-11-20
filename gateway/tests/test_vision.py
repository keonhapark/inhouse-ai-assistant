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
    info = load_model_info(ROOT / "gateway/litellm/config.yaml")
    assert info["local-vision"]["location"] == "local" and info["local-vision"]["vision"] is True
    assert [a for a, i in info.items() if i.get("vision")] == ["local-vision"]


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
