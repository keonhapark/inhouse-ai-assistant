"""gateway 시험 공통 준비. contracts/의 가짜 erp를 프로세스 안에서 띄워 erp 자리에 둡니다."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contracts"))

from fakes.erp.app import create_app as create_fake_erp  # noqa: E402

from gateway.config import Settings  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.tokens import DelegationTokenIssuer  # noqa: E402

PACK = ROOT / "packs/manufacturing"
PASSWORD = "demo-pass"


def _employees() -> list[dict]:
    return json.loads((PACK / "fixtures/employees.json").read_text(encoding="utf-8"))["employees"]


@pytest.fixture(scope="session")
def hr_staff_no() -> str:
    return next(e["employee_no"] for e in _employees() if e["unit_id"] == "hr" and e["grade"] == "staff")


@pytest.fixture(scope="session")
def staff_no() -> str:
    return next(e["employee_no"] for e in _employees()
                if e["grade"] == "staff" and e["unit_id"] not in ("hr", "rnd", "rnd-center"))


@pytest.fixture
def issuer() -> DelegationTokenIssuer:
    return DelegationTokenIssuer.ephemeral()


@pytest.fixture
def fake_erp(issuer):
    return create_fake_erp(PACK, demo_password=PASSWORD, delegation_public_key=issuer.public_pem())


@pytest.fixture
def erp_http(fake_erp):
    """가짜 erp를 직접 부르는 클라이언트(위임 토큰을 erp가 받아들이는지 볼 때)."""
    return TestClient(fake_erp, base_url="http://erp/api/v1")


@pytest.fixture
def settings() -> Settings:
    return Settings(erp_base_url="http://erp/api/v1", pack_dir=PACK, contracts_dir=ROOT / "contracts",
                    delegation_private_key=None)


@pytest.fixture
def app(settings, fake_erp, issuer):
    return create_app(settings, erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    def _login(employee_no: str) -> str:
        r = client.post("/api/auth/login", json={"employeeNo": employee_no, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["accessToken"]
    return _login


@pytest.fixture
def issue(app):
    def _issue(employee_jwt: str, agent_id: str, conversation_id: str = "conv-1"):
        return asyncio.run(app.state.delegation.issue(employee_jwt, agent_id, conversation_id))
    return _issue
