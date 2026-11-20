"""LLM 출구 실패 알림. 오류 로그를 남기고, ALERT_WEBHOOK_URL이 있으면 `{"text": ...}`로 보냅니다(슬랙 수신 웹훅 형식).

알림 전송이 실패해도 원래 요청 처리에는 영향을 주지 않습니다.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class Alerter:
    def __init__(self, webhook_url: str | None, transport: httpx.AsyncBaseTransport | None = None):
        self.webhook_url = webhook_url
        self._transport = transport
        self.sent: list[str] = []  # 보낸 알림 문장(시험·운영 화면에서 확인용, 최근 100개)

    async def alert(self, text: str) -> None:
        log.error("LLM 출구 알림: %s", text)
        self.sent = (self.sent + [text])[-100:]
        if not self.webhook_url:
            return
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=3.0) as c:
                await c.post(self.webhook_url, json={"text": f"[gateway] {text}"})
        except httpx.HTTPError as e:
            log.warning("알림 웹훅 전송 실패: %s", type(e).__name__)
