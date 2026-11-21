"""incident /analyze: 위임 토큰(aud incident, scope), erp로 권한·티켓 확인, LLM 후보와 기준선 대체."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from incident.app import TokenVerifier, create_app
from incident.logs import Line

KEY = ec.generate_private_key(ec.SECP256R1())
AT = datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc)
TICKET = {"id": "tkt_1", "title": "회의실 예약이 멈춥니다", "description": "예약 버튼이 오래 걸립니다",
          "createdAt": AT.isoformat()}


def token(scopes=("incident:read", "ticket:read"), aud=("erp", "incident"), **extra) -> str:
    t = int(time.time())
    return jwt.encode({"iss": "gateway", "aud": list(aud), "sub": "E0058", "scopes": list(scopes), "iat": t,
                       "exp": t + 600, **extra}, KEY, algorithm="ES256")


class Logs:
    def __init__(self) -> None:
        self.asked: list[tuple[datetime, datetime]] = []

    def lines(self, start, end):
        self.asked.append((start, end))
        lines = [Line(AT - timedelta(seconds=s), "gateway", "heartbeat", "GET /health") for s in range(0, 600, 5)]
        lines += [Line(AT - timedelta(seconds=s), "postgres", "warn", "still waiting for AccessShareLock after 1000 ms")
                  for s in range(10, 200, 7)]
        return lines


def erp(handler: bool = True):
    def h(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        if request.url.path == "/api/v1/tickets":
            return httpx.Response(200 if handler else 403, json={"items": []})
        if request.url.path == "/api/v1/tickets/tkt_1":
            return httpx.Response(200, json=TICKET)
        return httpx.Response(404, json={})
    return httpx.MockTransport(h)


def llm(content: str | None):
    def h(request: httpx.Request) -> httpx.Response:
        if content is None:
            return httpx.Response(504)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.MockTransport(h)


def client(handler=True, answer='{"candidates":[{"service":"postgres","kind":"lock_contention","reason":"잠금 대기",'
                                 '"evidence":["still waiting"]}]}', logs=None):
    app = create_app(logs or Logs(), TokenVerifier(key=KEY.public_key()), "http://erp/api/v1", "http://gw",
                     erp_transport=erp(handler), llm_transport=llm(answer))
    return TestClient(app)


def post(c, body, tok=None):
    headers = {} if tok == "" else {"X-Delegation-Token": tok or token()}
    return c.post("/analyze", json=body, headers=headers)


def test_analyze_ticket_with_llm() -> None:
    logs = Logs()
    r = post(client(logs=logs), {"ticketId": "tkt_1", "windowSeconds": 120})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "llm" and d["ticketId"] == "tkt_1"
    assert d["candidates"][0] == {"service": "postgres", "kind": "lock_contention", "reason": "잠금 대기",
                                  "evidence": ["still waiting"]}
    assert d["baseline"][0]["service"] == "postgres"
    # 티켓 작성 시각을 기준으로 직전 120초를 분석하고, 그 앞 120초를 기준 구간으로 읽습니다
    assert d["window"] == {"start": (AT - timedelta(seconds=120)).isoformat(), "end": AT.isoformat()}
    assert logs.asked == [(AT - timedelta(seconds=240), AT)]


def test_falls_back_to_baseline_when_model_fails() -> None:
    for answer in (None, "답을 못 했습니다"):
        d = post(client(answer=answer), {"at": AT.isoformat()}).json()
        assert d["method"] == "baseline"
        assert d["candidates"][0]["service"] == "postgres" and d["candidates"][0]["evidence"]


@pytest.mark.parametrize("tok,status,code", [
    ("", 401, "unauthorized"),
    (token(aud=("erp", "rag")), 401, "unauthorized"),
    (token(scopes=("ticket:read",)), 403, "scope-missing"),
])
def test_token_rules(tok, status, code) -> None:
    r = post(client(), {"at": AT.isoformat()}, tok)
    assert r.status_code == status and r.json()["type"] == f"urn:problem:{code}"


def test_only_ticket_handlers_and_known_tickets() -> None:
    r = post(client(handler=False), {"at": AT.isoformat()})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:forbidden"
    r = post(client(), {"ticketId": "tkt_none"})
    assert r.status_code == 404


@pytest.mark.parametrize("body", [{"windowSeconds": 10}, {"windowSeconds": "60"}, {"at": "어제"},
                                  {"at": "2026-11-21T01:00:00"}, {"extra": 1}])
def test_validation(body) -> None:
    assert post(client(), body).status_code == 422
