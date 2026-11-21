"""시나리오 턴의 이미지 첨부(contracts/eval/scenario.schema.json turns[].attachments)를 gateway 형식으로 바꿉니다.

첨부는 eval 폴더 기준 상대 경로(예: images/drawings/dwg-001.png)로 적습니다. gateway 메시지의 attachments는
agent 계약 Attachment({kind: image, dataUrl})이고 jpeg·png, 한 장 5MB까지입니다.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from harness.paths import EVAL_DIR

MAX_BYTES = 5 * 1024 * 1024
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class AttachmentError(ValueError):
    pass


def load_attachment(path: str, base: Path = EVAL_DIR) -> dict[str, Any]:
    p = (base / path).resolve()
    media = MEDIA.get(p.suffix.lower())
    if media is None:
        raise AttachmentError(f"jpeg·png만 붙일 수 있습니다: {path}")
    if not p.is_file():
        raise AttachmentError(f"첨부 파일이 없습니다: {path}")
    data = p.read_bytes()
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"첨부가 5MB를 넘습니다: {path}")
    return {"kind": "image", "dataUrl": f"data:{media};base64," + base64.b64encode(data).decode("ascii")}


def turn_attachments(turn: dict[str, Any], base: Path = EVAL_DIR) -> list[dict[str, Any]]:
    return [load_attachment(a, base) for a in turn.get("attachments", [])]
