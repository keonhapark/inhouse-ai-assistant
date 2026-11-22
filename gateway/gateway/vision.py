"""LLM 출구의 이미지 입력을 확인합니다(#261, contracts/openapi/gateway.yaml 머리말 LLM 출구).

이미지는 OpenAI 호환 `image_url` 부분의 data URL(jpeg·png)만 받습니다. 원격 URL은 받지 않습니다: 모델 서버가
밖에서 내려받게 되고, 무엇을 읽었는지 gateway가 확인할 수 없습니다. 기록에는 이미지 본문 대신 형식·크기·해시만 남깁니다.
대화 첨부(#288)는 agent에 넘기기 전에 다시 인코딩해 EXIF 같은 메타데이터(위치·기기·촬영 시각)를 지웁니다(#458).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

from gateway.problems import ProblemError

# 받는 content 부분 종류. file·input_audio나 공급자 고유 블록(image·document)은 이미지·문서를 실어 외부로 내보낼 수
# 있는데 여기서 확인하지 못하므로 422로 거절합니다.
PART_TYPES = frozenset({"text", "image_url", "refusal"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 한 장의 디코딩 크기 상한
_DATA_URL = re.compile(r"data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>.*)", re.S)
_MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
_FORMAT = {"image/png": "PNG", "image/jpeg": "JPEG"}
# 다시 인코딩할 때 풀 수 있는 픽셀 수 상한. 5MB 안에서도 압축이 잘 되는 PNG는 수억 픽셀로 풀려 메모리를 다 쓸 수 있습니다.
# 4800만 화소 휴대폰 사진(8064x6048)은 받습니다.
MAX_PIXELS = 50_000_000
JPEG_QUALITY = 95


@dataclass(frozen=True)
class ImageInfo:
    mime: str
    size: int
    sha256: str

    def describe(self) -> str:
        return f"{self.mime.split('/')[1]} {self.size}B sha256={self.sha256}"


def _image_urls(body: dict[str, Any]) -> list[Any]:
    urls = []
    for m in body["messages"]:
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind not in PART_TYPES:
                raise ProblemError(422, "validation", "받지 않는 content 부분입니다",
                                   f"{str(kind)[:40]}. 받는 것: {', '.join(sorted(PART_TYPES))}")
            if kind == "image_url":
                iu = part.get("image_url")
                urls.append(iu.get("url") if isinstance(iu, dict) else None)
    return urls


def inspect_images(body: dict[str, Any]) -> list[ImageInfo]:
    """본문의 이미지를 확인하고 형식·크기·해시를 돌려줍니다. 이미지가 없으면 빈 목록입니다.

    오류 설명에는 이미지 본문을 넣지 않습니다(감사 detail로 남으므로).
    """
    out = []
    for i, url in enumerate(_image_urls(body), 1):
        if not isinstance(url, str):
            raise ProblemError(422, "validation", "image_url은 {url: 문자열} 모양이어야 합니다", f"{i}번째 이미지")
        out.append(inspect_data_url(url, i))
    return out


def inspect_data_url(url: str, i: int = 1) -> ImageInfo:
    """data URL 한 장을 확인합니다(jpeg·png, 5MB). 대화 첨부(#288)도 같은 규칙을 씁니다."""
    mime, data = _decode(url, i)
    return ImageInfo(mime, len(data), hashlib.sha256(data).hexdigest())


def clean_data_url(url: str, i: int = 1) -> tuple[str, ImageInfo]:
    """data URL 한 장을 확인하고 메타데이터를 지운 data URL과 그 형식·크기·해시를 돌려줍니다(#458)."""
    mime, data = _decode(url, i)
    clean = strip_metadata(data, mime, i)
    return (f"data:{mime};base64,{base64.b64encode(clean).decode('ascii')}",
            ImageInfo(mime, len(clean), hashlib.sha256(clean).hexdigest()))


def strip_metadata(data: bytes, mime: str, i: int = 1) -> bytes:
    """픽셀만 남기고 같은 형식으로 다시 인코딩합니다(EXIF·XMP·ICC·PNG 글 조각 등은 남지 않음).

    EXIF 방향(Orientation)은 지우기 전에 픽셀에 적용해, 돌려 찍은 사진이 눕지 않게 합니다(이때 가로·세로가 바뀜).
    PNG 팔레트의 투명색은 메타데이터가 아니라 그림의 일부라 남깁니다. JPEG는 품질 95로 다시 압축합니다.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[_FORMAT[mime]]) as im:
                if im.width * im.height > MAX_PIXELS:
                    raise ProblemError(413, "payload-too-large", f"사진은 {MAX_PIXELS:,}화소까지 올릴 수 있습니다.",
                                       f"{i}번째 사진({im.width}×{im.height}). 크기를 줄여 다시 올리세요.")
                im.load()
                upright = ImageOps.exif_transpose(im)
    except ProblemError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ProblemError(422, "validation", "사진을 열 수 없습니다.", f"{i}번째 사진. 다른 사진을 올리세요.")
    upright.info = {k: v for k, v in upright.info.items() if k == "transparency"}
    out = io.BytesIO()
    if mime == "image/jpeg":
        upright.save(out, "JPEG", quality=JPEG_QUALITY)
    else:
        upright.save(out, "PNG")
    return out.getvalue()


def _decode(url: str, i: int) -> tuple[str, bytes]:
    m = _DATA_URL.fullmatch(url)
    if m is None:
        raise ProblemError(422, "validation", "사진을 읽지 못했습니다.", f"{i}번째 사진. 다시 올리세요.")
    mime = m["mime"].lower()
    if mime not in _MAGIC:
        raise ProblemError(415, "unsupported-media-type", "JPG나 PNG 사진만 올릴 수 있습니다.", f"{i}번째 사진")
    # 디코딩 전에 크기를 어림해 큰 본문을 메모리에 풀지 않습니다(base64 4글자 = 3바이트)
    if len(m["data"]) * 3 // 4 > MAX_IMAGE_BYTES + 3:
        raise ProblemError(413, "payload-too-large", f"사진 한 장은 {MAX_IMAGE_BYTES // (1024 * 1024)}MB까지 올릴 수 있습니다.",
                           f"{i}번째 사진. 크기를 줄여 다시 올리세요.")
    try:
        data = base64.b64decode(m["data"], validate=True)
    except (binascii.Error, ValueError):
        raise ProblemError(422, "validation", "사진을 읽지 못했습니다.", f"{i}번째 사진. 다시 올리세요.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ProblemError(413, "payload-too-large", f"사진 한 장은 {MAX_IMAGE_BYTES // (1024 * 1024)}MB까지 올릴 수 있습니다.",
                           f"{i}번째 사진({len(data) / (1024 * 1024):.1f}MB). 크기를 줄여 다시 올리세요.")
    if not data.startswith(_MAGIC[mime]):
        raise ProblemError(415, "unsupported-media-type", "사진 파일이 손상됐거나 형식이 맞지 않습니다.",
                           f"{i}번째 사진. JPG나 PNG로 다시 저장해 올리세요.")
    return mime, data


def has_inline_image(body: dict[str, Any]) -> bool:
    """image_url 부분 밖(글 속)에 붙여 넣은 이미지 data URL이 있는지. 외부로 가는 본문에 씁니다."""
    return "data:image/" in json.dumps(body, ensure_ascii=False).lower()
