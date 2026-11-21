"""행동 계약 시험의 공통 준비.

기본은 가짜 erp를 프로세스 안에서 띄웁니다. ERP_BASE_URL을 주면 실제 erp(예: http://localhost:8140/api/v1)에
같은 시험을 돌립니다. 실제 erp는 아래 값으로 떠 있어야 합니다.
- ERP_DEMO_PASSWORD: 시험이 쓰는 비밀번호와 같게
- DELEGATION_TOKEN_PUBLIC_KEY: ERP_TEST_DELEGATION_PRIVATE_KEY의 짝(위임 토큰 시험용)
- ERP_SERVICE_LOGIN_SECRET: 시험의 서비스 로그인 비밀값과 같게(없으면 서비스 로그인 시험은 건너뜀)
"""

from __future__ import annotations

import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from tests.schema_check import validate
from tools.common import ROOT, load

KST = ZoneInfo("Asia/Seoul")
PACK = ROOT / "packs/manufacturing"
PASSWORD = os.environ.get("ERP_DEMO_PASSWORD", "demo")
# 실제 erp는 같은 값으로 떠 있어야 합니다(erp/ci/start.sh 기본값과 같음). 시험 전용 값입니다.
SERVICE_LOGIN_SECRET = os.environ.get("ERP_SERVICE_LOGIN_SECRET", "test-only-service-login-secret-32bytes")


def _keys() -> tuple[str, str]:
    path = os.environ.get("ERP_TEST_DELEGATION_PRIVATE_KEY")
    if path:
        priv_pem = Path(path).read_text()
        key = serialization.load_pem_private_key(priv_pem.encode(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        priv_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()).decode()
    pub_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv_pem, pub_pem


PRIV, PUB = _keys()


class Org:
    """팩 고정 데이터에서 시험에 쓸 사람을 고릅니다."""

    def __init__(self) -> None:
        emps = load(PACK / "fixtures/employees.json")["employees"]
        self.by_unit: dict[str, list[dict]] = defaultdict(list)
        for e in emps:
            self.by_unit[e["unit_id"]].append(e)
        self.all = emps

    def leader(self, unit: str) -> str:
        return next(e["id"] for e in self.by_unit[unit] if e["grade"] in ("team_leader", "division_head"))

    def members(self, unit: str) -> list[str]:
        return [e["id"] for e in self.by_unit[unit] if e["grade"] == "staff"]

    def head(self, division: str) -> str:
        return self.leader(division)


@pytest.fixture(scope="session")
def org() -> Org:
    return Org()


@pytest.fixture(scope="session")
def base_client():
    base = os.environ.get("ERP_BASE_URL")
    if base:
        with httpx.Client(base_url=base, timeout=10) as c:
            yield c
        return
    from fastapi.testclient import TestClient

    from fakes.erp.app import create_app

    app = create_app(PACK, demo_password=PASSWORD, delegation_public_key=PUB,
                     service_login_secret=SERVICE_LOGIN_SECRET)
    with TestClient(app, base_url="http://fake/api/v1") as c:
        yield c


class Api:
    def __init__(self, client: httpx.Client) -> None:
        self.c = client
        self._tokens: dict[str, str] = {}

    def token(self, emp: str) -> str:
        if emp not in self._tokens:
            r = self.c.post("/auth/login", json={"employeeNo": emp, "password": PASSWORD})
            assert r.status_code == 200, r.text
            self._tokens[emp] = r.json()["accessToken"]
        return self._tokens[emp]

    def delegation_token(self, emp: str, scopes: list[str], agent: str = "hr", ttl: int = 600) -> str:
        t = int(time.time())
        return jwt.encode({"iss": "gateway", "aud": ["erp", "mcp"], "sub": emp, "agt": agent,
                           "cid": f"cnv_{uuid.uuid4().hex[:8]}", "scopes": scopes, "tools": [],
                           "doc_scopes": ["public"], "iat": t, "exp": t + ttl, "jti": uuid.uuid4().hex},
                          PRIV, algorithm="ES256")

    def req(self, method: str, path: str, emp: str | None = None, *, token: str | None = None,
            json: Any = None, params: dict | None = None, key: str | None | bool = True) -> httpx.Response:
        headers = {}
        if token or emp:
            headers["Authorization"] = f"Bearer {token or self.token(emp)}"
        if key is True and method == "POST" and not (params or {}).get("dryRun"):
            headers["Idempotency-Key"] = uuid.uuid4().hex
        elif isinstance(key, str):
            headers["Idempotency-Key"] = key
        return self.c.request(method, path, headers=headers, json=json, params=params)

    def get(self, path: str, emp: str, **kw: Any) -> httpx.Response:
        return self.req("GET", path, emp, **kw)

    def post(self, path: str, emp: str, **kw: Any) -> httpx.Response:
        return self.req("POST", path, emp, **kw)

    # 자주 쓰는 동작
    def request_leave(self, emp: str, start: str, end: str | None = None, leave_type: str = "annual") -> dict:
        r = self.post("/approval-documents", emp, json={"formId": "leave", "fields": {
            "leave_type": leave_type, "start_date": start, "end_date": end or start, "reason": "개인 사정"}})
        assert r.status_code == 201, r.text
        validate("openapi/erp.yaml", "ActionResult", r.json())
        return r.json()

    def request_expense(self, emp: str, amount: int) -> dict:
        r = self.post("/approval-documents", emp, json={"formId": "expense", "fields": {
            "amount": amount, "spent_on": "2026-11-02", "merchant": "가상상회", "purpose": "출장 교통비"}})
        assert r.status_code == 201, r.text
        return r.json()

    def doc(self, emp: str, doc_id: str) -> dict:
        r = self.get(f"/approval-documents/{doc_id}", emp)
        assert r.status_code == 200, r.text
        validate("openapi/erp.yaml", "ApprovalDocument", r.json())
        return r.json()

    def approve(self, emp: str, doc_id: str, version: int | None = None, **kw: Any) -> httpx.Response:
        if version is None:
            version = self.doc(emp, doc_id)["version"]
        return self.post(f"/approval-documents/{doc_id}/approve", emp, json={"version": version}, **kw)

    def delegate(self, delegator: str, delegate: str, *, start: datetime | None = None, days: float = 3,
                 form_types: list[str] | None = None, max_amount: int | None = None,
                 as_emp: str | None = None) -> httpx.Response:
        start = start or now() - timedelta(minutes=1)
        body = {"delegateId": delegate, "startsAt": start.isoformat(),
                "endsAt": (start + timedelta(days=days)).isoformat(),
                "scope": {"formTypes": form_types or ["leave"], "maxAmount": max_amount}, "reason": "출장"}
        if as_emp and as_emp != delegator:
            body["delegatorId"] = delegator
        return self.post("/delegations", as_emp or delegator, json=body)


def now() -> datetime:
    return datetime.now(KST)


_day = [0]


def future_weekday() -> str:
    """시험마다 다른 미래 평일(연차 하루)."""
    _day[0] += 1
    d = now().date() + timedelta(days=40 + _day[0])
    while d.weekday() >= 5:
        d += timedelta(days=1)
        _day[0] += 1
    return d.isoformat()


_slot = [0]


def future_slot(hours: float = 1) -> tuple[str, str]:
    """시험마다 겹치지 않는 미래 회의실 시간대."""
    _slot[0] += 1
    day = now().date() + timedelta(days=60 + _slot[0] // 4)
    start = datetime(day.year, day.month, day.day, 9 + (_slot[0] % 4) * 2, 0, tzinfo=KST)
    return start.isoformat(), (start + timedelta(hours=hours)).isoformat()


@pytest.fixture(scope="session")
def api(base_client) -> Api:
    return Api(base_client)
