"""LLM 출구의 이미지 입력을 확인합니다(#261, contracts/openapi/gateway.yaml 머리말 LLM 출구).

이미지는 OpenAI 호환 `image_url` 부분의 data URL(jpeg·png)만 받습니다. 원격 URL은 받지 않습니다: 모델 서버가
밖에서 내려받게 되고, 무엇을 읽었는지 gateway가 확인할 수 없습니다. 기록에는 이미지 본문 대신 형식·크기·해시만 남깁니다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from gateway.problems import ProblemError

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 한 장의 디코딩 크기 상한
_DATA_URL = re.compile(r"data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>.*)", re.S)
_MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}


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
            if isinstance(part, dict) and part.get("type") == "image_url":
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
        m = _DATA_URL.fullmatch(url)
        if m is None:
            raise ProblemError(422, "validation", "이미지는 base64 data URL만 받습니다", f"{i}번째 이미지")
        mime = m["mime"].lower()
        if mime not in _MAGIC:
            raise ProblemError(415, "unsupported-media-type", "이미지는 jpeg·png만 받습니다", f"{i}번째 이미지: {mime}")
        # 디코딩 전에 크기를 어림해 큰 본문을 메모리에 풀지 않습니다(base64 4글자 = 3바이트)
        if len(m["data"]) * 3 // 4 > MAX_IMAGE_BYTES + 3:
            raise ProblemError(413, "payload-too-large", f"이미지 한 장은 {MAX_IMAGE_BYTES // (1024 * 1024)}MB까지 받습니다",
                               f"{i}번째 이미지")
        try:
            data = base64.b64decode(m["data"], validate=True)
        except (binascii.Error, ValueError):
            raise ProblemError(422, "validation", "이미지 base64가 올바르지 않습니다", f"{i}번째 이미지")
        if len(data) > MAX_IMAGE_BYTES:
            raise ProblemError(413, "payload-too-large", f"이미지 한 장은 {MAX_IMAGE_BYTES // (1024 * 1024)}MB까지 받습니다",
                               f"{i}번째 이미지: {len(data)}B")
        if not data.startswith(_MAGIC[mime]):
            raise ProblemError(415, "unsupported-media-type", "이미지 내용이 선언한 형식과 맞지 않습니다",
                               f"{i}번째 이미지: {mime}")
        out.append(ImageInfo(mime, len(data), hashlib.sha256(data).hexdigest()))
    return out
