"""compose 전체(--profile full)에 붙는 끝까지 시험. E2E_GATEWAY_URL이 없으면 모두 건너뜁니다.

    E2E_GATEWAY_URL=http://localhost:8510/api E2E_ERP_URL=http://localhost:8540/api/v1 \
    ERP_DEMO_PASSWORD=... uv run pytest e2e -v
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from harness.erp import ErpClient
from harness.sut import GatewayChat

GATEWAY = os.environ.get("E2E_GATEWAY_URL")
ERP = os.environ.get("E2E_ERP_URL")
TIMEOUT = float(os.environ.get("E2E_TIMEOUT_S", "300"))



def pytest_collection_modifyitems(items):
    if GATEWAY and ERP:
        return
    skip = pytest.mark.skip(reason="E2E_GATEWAY_URL·E2E_ERP_URL이 없음")
    for item in items:
        item.add_marker(skip)


class Human:
    """사람 화면 경로(gateway, 직원 JWT)."""

    def __init__(self, client: httpx.Client, password: str) -> None:
        self.c = client
        self.password = password
        self.tokens: dict[str, str] = {}

    def h(self, emp: str, write: bool = False) -> dict[str, str]:
        if emp not in self.tokens:
            r = self.c.post("/auth/login", json={"employeeNo": emp, "password": self.password})
            assert r.status_code == 200, r.text
            self.tokens[emp] = r.json()["accessToken"]
        h = {"Authorization": f"Bearer {self.tokens[emp]}"}
        if write:
            h["Idempotency-Key"] = uuid.uuid4().hex
        return h

    def get(self, emp: str, path: str, **kw) -> httpx.Response:
        return self.c.get(path, headers=self.h(emp), **kw)

    def post(self, emp: str, path: str, json=None, **kw) -> httpx.Response:
        return self.c.post(path, headers=self.h(emp, write=True), json=json, **kw)


@pytest.fixture(scope="session")
def password() -> str:
    return os.environ.get("ERP_DEMO_PASSWORD", "demo")


@pytest.fixture(scope="session")
def gw_client():
    with httpx.Client(base_url=GATEWAY, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def erp(password):
    with httpx.Client(base_url=ERP, timeout=60) as c:
        e = ErpClient(c, password=password)
        e.reset()  # 팩 고정 데이터 상태에서 시작(ERP_EVAL_RESET=1)
        yield e


@pytest.fixture
def human(gw_client, password) -> Human:
    return Human(gw_client, password)


@pytest.fixture
def chat(gw_client, password) -> GatewayChat:
    return GatewayChat(gw_client, auditor=None, password=password)
