"""RFC 9457 problem+json 응답. type은 `urn:problem:<코드>`입니다(contracts/openapi/erp.yaml Problem)."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class ProblemError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str = "", headers: dict[str, str] | None = None):
        super().__init__(detail or title)
        self.status, self.code, self.title, self.detail = status, code, title, detail
        self.headers = headers or {}  # 예: 429의 Retry-After


def problem_response(e: ProblemError) -> JSONResponse:
    body: dict[str, Any] = {"type": f"urn:problem:{e.code}", "title": e.title, "status": e.status}
    if e.detail:
        body["detail"] = e.detail
    return JSONResponse(body, status_code=e.status, media_type="application/problem+json", headers=e.headers or None)
