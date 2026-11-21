"""대화 메시지의 이미지 첨부를 agent /run으로 넘깁니다(#288, 계약 #287). 메타데이터는 지우고 넘깁니다(#458)."""

import base64
import hashlib
import io
import json
import logging

import pytest
from PIL import Image

from .test_chat import _new, agent, chat, events, h, schema_check  # noqa: F401  (픽스처)
from .test_vision import _png, _url

# GPS IFD(0x8825)와 기기·소프트웨어·촬영 시각. 사진 한 장으로 사는 곳과 휴대폰을 알 수 있는 값들입니다(지어낸 값).
GPS = {1: "N", 2: (37.0, 33.0, 59.0), 3: "E", 4: (126.0, 58.0, 41.0)}
DEVICE = {0x010F: "ExampleMaker", 0x0110: "Phone X1", 0x0131: "CameraApp 9.9", 0x0132: "2027:03:09 14:05:00"}


def _jpeg(w=40, h=30, orientation=None, exif=True) -> bytes:
    im = Image.new("RGB", (w, h), (200, 30, 30))
    im.paste((30, 30, 200), (0, 0, w // 2, h // 2))           # 왼쪽 위만 파랑(방향 확인용)
    ex = Image.Exif()
    if exif:
        ex.update(DEVICE)
        ex.get_ifd(0x8825).update(GPS)
    if orientation:
        ex[0x0112] = orientation
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90, exif=ex.tobytes(), comment=b"secret note")
    return out.getvalue()


def _png_with_meta() -> bytes:
    from PIL.PngImagePlugin import PngInfo

    im = Image.new("RGB", (20, 10), (10, 200, 10))
    info = PngInfo()
    info.add_text("Author", "Kim")
    info.add_itxt("Location", "Seoul office 3F")
    ex = Image.Exif()
    ex.update(DEVICE)
    out = io.BytesIO()
    im.save(out, "PNG", pnginfo=info, exif=ex.tobytes())
    return out.getvalue()


JPEG = _jpeg()


def _decoded(url: str) -> bytes:
    return base64.b64decode(url.split(",", 1)[1])


def _image(url: str) -> Image.Image:
    im = Image.open(io.BytesIO(_decoded(url)))
    im.load()
    return im


def _att(url):
    return {"kind": "image", "dataUrl": url}


def _post(chat, h, cid, **body):
    return chat.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "이 영수증으로 정산해 줘", **body})


def test_attachments_are_passed_to_run_cleaned(chat, h, agent):
    cid = _new(chat, h)
    atts = [_att(_url(_png())), _att(_url(JPEG, "image/jpeg"))]
    r = _post(chat, h, cid, attachments=atts)
    assert r.status_code == 200 and events(r)[-1]["type"] == "done"
    path, body, _ = agent.calls[-1]
    assert path == "/run" and [a["kind"] for a in body["attachments"]] == ["image", "image"]
    assert [a["dataUrl"].split(";")[0] for a in body["attachments"]] == ["data:image/png", "data:image/jpeg"]
    assert [_image(a["dataUrl"]).size for a in body["attachments"]] == [(2, 2), (40, 30)]
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
    cid = _new(chat, h)
    _post(chat, h, cid, attachments=[_att(_url(_png())), _att(_url(JPEG, "image/jpeg"))])
    sent = [_decoded(a["dataUrl"]) for a in agent.calls[-1][1]["attachments"]]
    _post(chat, h, cid)  # 첨부 없는 턴
    conv = chat.get(f"/api/conversations/{cid}", headers=h).json()
    schema_check.validate("openapi/gateway.yaml", "Conversation", conv)
    users = [e for e in conv["events"] if e["type"] == "user_message"]
    # 크기·해시는 agent에 넘긴(메타데이터를 지운) 이미지 기준입니다. 출구 감사의 해시와 같습니다(#458)
    assert users[0]["attachments"] == [
        {"kind": "image", "mediaType": mime, "bytes": len(d), "sha256": hashlib.sha256(d).hexdigest()}
        for mime, d in zip(("image/png", "image/jpeg"), sent)]
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


# ---------- 메타데이터 지우기(#458) ----------
def test_jpeg_exif_and_comment_are_removed_and_size_kept(chat, h, agent):
    src = Image.open(io.BytesIO(JPEG))
    assert src.getexif().get_ifd(0x8825) and src.getexif()[0x010F] == "ExampleMaker" and b"secret" in JPEG
    _post(chat, h, _new(chat, h), attachments=[_att(_url(JPEG, "image/jpeg"))])
    url = agent.calls[-1][1]["attachments"][0]["dataUrl"]
    im, raw = _image(url), _decoded(url)
    assert im.format == "JPEG" and im.size == (40, 30)
    assert dict(im.getexif()) == {} and "exif" not in im.info and "comment" not in im.info
    for needle in (b"Exif", b"ExampleMaker", b"Phone X1", b"CameraApp", b"2027:03:09", b"secret note"):
        assert needle not in raw, needle
    assert im.getpixel((5, 5))[2] > 150 and im.getpixel((35, 25))[0] > 150   # 픽셀은 그대로(파랑·빨강 자리)


def test_png_text_and_exif_chunks_are_removed(chat, h, agent):
    png = _png_with_meta()
    assert b"tEXt" in png and b"iTXt" in png and b"eXIf" in png
    _post(chat, h, _new(chat, h), attachments=[_att(_url(png))])
    raw = _decoded(agent.calls[-1][1]["attachments"][0]["dataUrl"])
    for needle in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"Kim", b"Seoul", b"ExampleMaker"):
        assert needle not in raw, needle
    im = Image.open(io.BytesIO(raw))
    assert im.size == (20, 10) and im.getpixel((0, 0)) == (10, 200, 10)


def test_orientation_is_applied_before_removing_exif(chat, h, agent):
    """방향 6(시계 방향 90도로 봐야 함)인 40x30 사진은 30x40으로 세워서 넘기고, 방향 태그는 남기지 않습니다."""
    _post(chat, h, _new(chat, h), attachments=[_att(_url(_jpeg(orientation=6, exif=False), "image/jpeg"))])
    im = _image(agent.calls[-1][1]["attachments"][0]["dataUrl"])
    assert im.size == (30, 40) and 0x0112 not in im.getexif()
    assert im.getpixel((25, 5))[2] > 150          # 왼쪽 위 파랑이 오른쪽 위로 감


def test_palette_png_keeps_transparency(chat, h, agent):
    im = Image.new("P", (4, 4), 1)
    im.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    out = io.BytesIO()
    im.save(out, "PNG", transparency=1)
    _post(chat, h, _new(chat, h), attachments=[_att(_url(out.getvalue()))])
    got = _image(agent.calls[-1][1]["attachments"][0]["dataUrl"])
    assert got.mode == "P" and got.info.get("transparency") == 1


@pytest.mark.parametrize("data,mime,status", [
    (b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9", "image/jpeg", 422),   # 머리만 맞고 읽을 수 없는 jpeg
    (_png()[:40], "image/png", 422),                                            # 잘린 png
])
def test_unreadable_images_are_rejected(chat, h, agent, data, mime, status):
    r = _post(chat, h, _new(chat, h), attachments=[_att(_url(data, mime))])
    assert r.status_code == status and r.json()["type"] == "urn:problem:validation"
    assert [c for c in agent.calls if c[0] == "/run"] == []


def test_too_many_pixels_is_413_before_decoding(chat, h, agent):
    """5MB 안이라도 풀면 수억 픽셀인 PNG는 픽셀을 풀기 전에 413입니다."""
    from gateway import vision

    big = Image.new("L", (8000, 7000), 255)        # 5,600만 화소, 압축하면 수십 KB
    out = io.BytesIO()
    big.save(out, "PNG")
    assert len(out.getvalue()) < 1024 * 1024 and 8000 * 7000 > vision.MAX_PIXELS
    r = _post(chat, h, _new(chat, h), attachments=[_att(_url(out.getvalue()))])
    assert r.status_code == 413 and r.json()["type"] == "urn:problem:payload-too-large"
    assert "8000x7000" in r.json()["detail"]
