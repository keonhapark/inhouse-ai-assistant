"""장애 원인 분석 서비스(contracts/openapi/incident.yaml). compose에 넣지 않는 호스트 로컬 도구입니다.

    cd incident && uv run uvicorn --factory incident.app:from_env --host 0.0.0.0 --port 8170   # 세션 1(PORT_BASE + 70)

환경 변수
- INCIDENT_SESSION: 로그를 읽을 세션 스택 번호(iaa-s<번호>, 기본 1). 호스트의 docker CLI로 읽습니다
- INCIDENT_ERP_URL(기본 세션 erp), INCIDENT_GATEWAY_URL(기본 세션 gateway): 권한·티켓 확인과 LLM 출구
- DELEGATION_TOKEN_PUBLIC_KEY 또는 DELEGATION_JWKS_URL(기본 세션 gateway JWKS): 위임 토큰 확인
- INCIDENT_HISTORY_DIR: 원인이 밝혀진 과거 장애 묶음(truth.json) 폴더. 비슷한 과거 티켓에 씁니다(없으면 안 씀)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from incident.baseline import PastTicket, rank
from incident.llm import analyze as llm_analyze
from incident.llm import diagnostics
from incident.logs import Line, read_service
from incident.stack import ROOT, SERVICES, Stack

log = logging.getLogger("incident")
SCOPE = "incident:read"
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss", "scopes"]


class ProblemError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.status, self.code, self.detail = status, code, detail


class LogSource(Protocol):
    def lines(self, start: datetime, end: datetime) -> list[Line]: ...


class DockerLogs:
    """세션 스택 컨테이너 로그를 호스트 docker CLI로 읽습니다."""

    def __init__(self, stack: Stack, tmp: Path):
        self.stack, self.tmp = stack, tmp

    def lines(self, start: datetime, end: datetime) -> list[Line]:
        out: list[Line] = []
        self.tmp.mkdir(parents=True, exist_ok=True)
        for svc in SERVICES:
            text = self.stack.logs(svc, start.isoformat(), end.isoformat())
            path = self.tmp / f"{svc}.log"
            path.write_text(text, encoding="utf-8")
            out += read_service(path, svc)
        if not out:
            raise ProblemError(503, "logs-unavailable", f"{self.stack.project} 로그를 읽지 못했습니다")
        return sorted(out, key=lambda x: x.at)


class TokenVerifier:
    def __init__(self, key: Any = None, jwks_url: str | None = None):
        self._key = key
        self._jwks = jwt.PyJWKClient(jwks_url) if jwks_url else None

    def verify(self, token: str | None) -> dict[str, Any]:
        if not token:
            raise ProblemError(401, "unauthorized", "위임 토큰이 없습니다")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key if self._jwks else self._key
            claims = jwt.decode(token, key, algorithms=["ES256"], audience="incident", issuer="gateway",
                                leeway=5, options={"require": REQUIRED_CLAIMS})
        except jwt.PyJWTError as e:
            raise ProblemError(401, "unauthorized", f"위임 토큰이 올바르지 않습니다({type(e).__name__})") from e
        if SCOPE not in (claims.get("scopes") or []):
            raise ProblemError(403, "scope-missing", f"필요한 scope: {SCOPE}")
        return claims


def history(path: Path | None) -> list[PastTicket]:
    if path is None or not path.exists():
        return []
    out = []
    for t in sorted(path.rglob("truth.json")):
        d = json.loads(t.read_text(encoding="utf-8"))
        out.append(PastTicket(d["ticket"]["id"], f"{d['ticket']['title']} {d['ticket']['description']}",
                              d["rootService"], d["kind"]))
    return out


def create_app(source: LogSource, verifier: TokenVerifier, erp_url: str, gateway_url: str,
               past: list[PastTicket] | None = None, erp_transport: httpx.BaseTransport | None = None,
               llm_transport: httpx.BaseTransport | None = None) -> FastAPI:
    app = FastAPI(title="incident", version="0.1.0")

    @app.exception_handler(ProblemError)
    async def _problem(_: Request, e: ProblemError) -> JSONResponse:
        body = {"type": f"urn:problem:{e.code}", "title": e.code, "status": e.status}
        if e.detail:
            body["detail"] = e.detail
        return JSONResponse(body, status_code=e.status, media_type="application/problem+json")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    def erp(token: str, path: str, **params: Any) -> httpx.Response:
        try:
            with httpx.Client(base_url=erp_url, timeout=10, transport=erp_transport) as c:
                return c.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise ProblemError(503, "erp-unavailable", f"erp에 닿지 못했습니다({type(e).__name__})") from e

    @app.post("/analyze")
    async def analyze(request: Request) -> dict:
        token = request.headers.get("x-delegation-token")
        verifier.verify(token)
        try:
            body = await request.json()
        except ValueError as e:
            raise ProblemError(422, "validation", "JSON 본문이 아닙니다") from e
        if not isinstance(body, dict) or set(body) - {"ticketId", "at", "windowSeconds"}:
            raise ProblemError(422, "validation", "ticketId, at, windowSeconds만 받습니다")
        seconds = body.get("windowSeconds", 300)
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 30 <= seconds <= 3600:
            raise ProblemError(422, "validation", "windowSeconds는 30~3600 정수입니다")
        # 권한: 티켓 담당만(전체 티켓을 볼 수 있는 사람)
        if erp(token, "/tickets", box="all", limit=1).status_code != 200:
            raise ProblemError(403, "forbidden", "티켓 담당만 장애를 분석합니다")
        ticket = None
        if body.get("ticketId") is not None:
            r = erp(token, f"/tickets/{body['ticketId']}")
            if r.status_code != 200:
                raise ProblemError(404, "not-found", "티켓이 없습니다")
            ticket = r.json()
        at = _at(body.get("at"), ticket)
        length = timedelta(seconds=seconds)
        lines = source.lines(at - 2 * length, at)
        text = f"{ticket['title']} {ticket['description']}" if ticket else None
        base = rank(lines, at, length, text, past or None)
        result: dict[str, Any] = {"ticketId": ticket["id"] if ticket else None,
                                  "window": {"start": (at - length).isoformat(), "end": at.isoformat()},
                                  "baseline": [{"service": s, "score": v} for s, v in base.ranking]}
        try:
            out = llm_analyze(gateway_url, diagnostics(base, text), transport=llm_transport)
            if not out.candidates:
                raise ValueError("후보 없음")
            result["method"] = "llm"
            result["candidates"] = [asdict(c) for c in out.candidates]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            log.warning("LLM 분석 실패, 기준선으로 답함: %s", type(e).__name__)
            result["method"] = "baseline"
            result["candidates"] = [{"service": s, "kind": None, "reason": "기준선 순위(로그 변화·유사 티켓)",
                                     "evidence": [c.example[:300] for c in base.changes if c.service == s][:3]}
                                    for s, _ in base.ranking[:3]]
        return result

    return app


def _at(value: Any, ticket: dict[str, Any] | None) -> datetime:
    if value is not None:
        try:
            at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as e:
            raise ProblemError(422, "validation", "at은 RFC 3339 시각입니다") from e
        if at.tzinfo is None:
            raise ProblemError(422, "validation", "at에 시간대가 필요합니다")
        return at
    if ticket is not None:
        return datetime.fromisoformat(ticket["createdAt"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def from_env() -> FastAPI:
    session = int(os.environ.get("INCIDENT_SESSION", "1"))
    base = 8000 + 100 * session
    if path := os.environ.get("DELEGATION_TOKEN_PUBLIC_KEY"):
        p = Path(path)
        verifier = TokenVerifier(key=(p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8"))
    else:
        verifier = TokenVerifier(jwks_url=os.environ.get("DELEGATION_JWKS_URL")
                                 or f"http://localhost:{base + 10}/api/.well-known/jwks.json")
    hist = os.environ.get("INCIDENT_HISTORY_DIR")
    return create_app(DockerLogs(Stack(session), Path(os.environ.get("INCIDENT_TMP", "/tmp/incident-logs"))),
                      verifier, os.environ.get("INCIDENT_ERP_URL", f"http://localhost:{base + 40}/api/v1"),
                      os.environ.get("INCIDENT_GATEWAY_URL", f"http://localhost:{base + 10}"),
                      history(Path(hist) if hist else None))
