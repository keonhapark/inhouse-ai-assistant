"""로그와 모델 문맥에 토큰 문자열이 남지 않게 가립니다.

JWT 모양(헤더.페이로드.서명, base64url)과 `Bearer <값>`을 찾아 바꿉니다. 로그는 install()로 모든 레코드에 걸고,
모델에 보낼 문자열에는 scrub()을 직접 씁니다.
"""

from __future__ import annotations

import logging
import re

MASK = "[가린 토큰]"
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{16,}")


def scrub(text: str) -> str:
    text = _JWT.sub(MASK, text)
    return _BEARER.sub(lambda m: m.group(1) + MASK, text)


_installed = False


def install() -> None:
    """모든 로그 레코드가 만들어질 때 메시지를 가리도록 레코드 팩토리를 감쌉니다.

    로거·핸들러마다 거름망을 거는 방식은 나중에 생긴 핸들러나 전파 경로를 놓치므로 쓰지 않았습니다.
    여러 번 불러도 한 번만 감쌉니다.
    """
    global _installed
    if _installed:
        return
    base = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = base(*args, **kwargs)
        try:
            msg = record.getMessage()
        except Exception:  # 형식이 틀린 레코드는 logging이 나중에 알아서 보고합니다.
            return record
        clean = scrub(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
