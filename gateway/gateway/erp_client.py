"""erp 호출. 직원 JWT를 그대로 실어 보내고, erp 응답(오류 포함)은 상태 코드와 본문을 그대로 돌려줍니다."""

from __future__ import annotations

from typing import Any

import httpx

from gateway.problems import ProblemError


class ErpClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0):
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, *, bearer: str | None = None,
                      json: Any = None, params: dict[str, Any] | None = None,
                      headers: dict[str, str] | None = None) -> httpx.Response:
        h = dict(headers or {})
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        try:
            return await self._http.request(method, path, json=json, params=params, headers=h)
        except httpx.TimeoutException:
            raise ProblemError(504, "upstream-timeout", "erp가 제때 답하지 않았습니다")
        except httpx.HTTPError:
            raise ProblemError(502, "upstream-unavailable", "erp에 연결하지 못했습니다")

    async def get_json(self, path: str, bearer: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """성공하면 JSON을, 실패하면 erp 상태 코드로 ProblemError를 냅니다."""
        r = await self.request("GET", path, bearer=bearer, params=params)
        if r.status_code >= 400:
            raise as_problem(r)
        return r.json()


def as_problem(r: httpx.Response) -> ProblemError:
    try:
        body = r.json()
    except ValueError:
        body = {}
    code = str(body.get("type", "urn:problem:upstream-error")).removeprefix("urn:problem:")
    return ProblemError(r.status_code, code, body.get("title", "erp 오류"), body.get("detail", ""))
