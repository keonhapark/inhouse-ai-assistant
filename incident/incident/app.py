"""장애 원인 분석 서비스(contracts/openapi/incident.yaml). compose에 넣지 않는 호스트 로컬 도구입니다.

    cd incident && uv run uvicorn --factory incident.app:from_env --host 127.0.0.1 --port 8170   # 세션 1(PORT_BASE + 70)

호스트 로그를 읽는 도구라 기본은 루프백에만 엽니다. agent 컨테이너가 부르게 하려면 도커 브리지 주소(예: 172.17.0.1)에 엽니다.

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
import re
import tempfile
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
import jwt
from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from incident.baseline import PastTicket, rank
from incident.llm import analyze as llm_analyze
from incident.llm import Candidate, diagnostics
from incident.logs import Line, read_service
from incident.stack import ROOT, SERVICES, Stack

log = logging.getLogger("incident")
SCOPE = "incident:read"
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss", "scopes"]
TICKET_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_LOG_BYTES = 5_000_000  # 서비스 하나의 로그 상한(넘으면 앞부분을 버림)
AT_RANGE = timedelta(days=30)
# 근거 줄은 티켓 담당에게 그대로 가므로 토큰·이메일처럼 보이는 값을 가립니다.
SECRETS = (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9._-]+"),
           re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"))


def mask(text: str) -> str:
    for pat in SECRETS:
        text = pat.sub("<가림>", text)
    return text


class ProblemError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.status, self.code, self.detail = status, code, detail


class LogSource(Protocol):
    def lines(self, start: datetime, end: datetime) -> list[Line]: ...


class DockerLogs:
    """세션 스택 컨테이너 로그를 호스트 docker CLI로 읽습니다."""

    def __init__(self, stack: Stack, tmp: Path | None = None):
        self.stack, self.tmp = stack, tmp

    def lines(self, start: datetime, end: datetime) -> list[Line]:
        out: list[Line] = []
        # 요청마다 따로 만든 임시 폴더(공유 경로·고정 이름을 쓰지 않음)
        with tempfile.TemporaryDirectory(prefix="incident-", dir=self.tmp) as d:
            for svc in SERVICES:
                text = self.stack.logs(svc, start.isoformat(), end.isoformat())[-MAX_LOG_BYTES:]
                path = Path(d) / f"{svc}.log"
                path.write_text(text, encoding="utf-8")
                out += read_service(path, svc)
        if not out:
            log.warning("%s 로그를 읽지 못했습니다", self.stack.project)
            raise ProblemError(503, "logs-unavailable", "서비스 로그를 읽지 못했습니다")
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
            log.info("위임 토큰 거절: %s", type(e).__name__)
            raise ProblemError(401, "unauthorized", "위임 토큰이 올바르지 않습니다") from e
        scopes = claims.get("scopes")
        if not isinstance(scopes, list) or SCOPE not in scopes:
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
    # 분석은 docker 로그와 로컬 모델을 오래 쓰므로 한 번에 하나만 돌립니다(동기 핸들러라 /health는 막지 않음).
    busy = threading.Lock()

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
            log.warning("erp 호출 실패: %s", type(e).__name__)
            raise ProblemError(503, "erp-unavailable", "erp에 닿지 못했습니다") from e

    @app.post("/analyze")
    def analyze(request: Request, body: Any = Body(default=None)) -> dict:
        token = request.headers.get("x-delegation-token")
        verifier.verify(token)
        if not busy.acquire(timeout=1):
            raise ProblemError(503, "busy", "다른 분석이 도는 중입니다")
        try:
            return _analyze(token, body)
        finally:
            busy.release()

    def _analyze(token: str, body: Any) -> dict:
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
            tid = body["ticketId"]
            if not isinstance(tid, str) or not TICKET_ID.fullmatch(tid):
                raise ProblemError(422, "validation", "ticketId 형식이 아닙니다")
            r = erp(token, f"/tickets/{tid}")
            ticket = r.json() if r.status_code == 200 else None
            if not isinstance(ticket, dict) or not all(isinstance(ticket.get(k), str)
                                                        for k in ("id", "title", "description", "createdAt")):
                raise ProblemError(404, "not-found", "티켓이 없습니다")
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
            result["candidates"] = [asdict(_masked(c)) for c in out.candidates]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            log.warning("LLM 분석 실패, 기준선으로 답함: %s", type(e).__name__)
            result["method"] = "baseline"
            result["candidates"] = [{"service": s, "kind": None, "reason": "기준선 순위(로그 변화·유사 티켓)",
                                     "evidence": [mask(c.example[:300]) for c in base.changes if c.service == s][:3]}
                                    for s, _ in base.ranking[:3]]
        return result

    return app


def _masked(c: Candidate) -> Candidate:
    return replace(c, reason=mask(c.reason), evidence=[mask(e) for e in c.evidence])


def _at(value: Any, ticket: dict[str, Any] | None) -> datetime:
    now = datetime.now(timezone.utc)
    if value is None and ticket is None:
        return now
    raw = value if value is not None else ticket["createdAt"]  # type: ignore[index]
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as e:
        raise ProblemError(422, "validation", "at은 RFC 3339 시각입니다") from e
    if at.tzinfo is None:
        raise ProblemError(422, "validation", "at에 시간대가 필요합니다")
    if value is not None and abs(at - now) > AT_RANGE:
        raise ProblemError(422, "validation", "at은 지금부터 30일 안이어야 합니다")
    return at


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
    return create_app(DockerLogs(Stack(session), Path(os.environ["INCIDENT_TMP"]) if os.environ.get("INCIDENT_TMP") else None),
                      verifier, os.environ.get("INCIDENT_ERP_URL", f"http://localhost:{base + 40}/api/v1"),
                      os.environ.get("INCIDENT_GATEWAY_URL", f"http://localhost:{base + 10}"),
                      history(Path(hist) if hist else None))
