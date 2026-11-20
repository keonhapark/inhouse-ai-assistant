"""시험 공통 준비. 가짜 erp(contracts/fakes/erp)를 프로세스 안에서 띄웁니다."""

from __future__ import annotations

import sys

import pytest

from harness.erp import ErpClient
from harness.paths import CONTRACTS, ROOT

PASSWORD = "demo"


def new_fake_erp():
    """새 가짜 erp(상태 분리)의 시험 클라이언트."""
    if str(CONTRACTS) not in sys.path:
        sys.path.insert(0, str(CONTRACTS))
    from fastapi.testclient import TestClient

    from fakes.erp.app import create_app

    return TestClient(create_app(ROOT / "packs/manufacturing", demo_password=PASSWORD),
                      base_url="http://fake/api/v1")


@pytest.fixture
def fake_erp_client():
    with new_fake_erp() as c:
        yield c


@pytest.fixture
def erp(fake_erp_client) -> ErpClient:
    return ErpClient(fake_erp_client, password=PASSWORD)


def base_scenario(**over):
    s = {
        "id": "t-normal",
        "version": 1,
        "pack": "manufacturing",
        "set": "dev",
        "kind": "normal",
        "author": "hand",
        "requester": "E0016",
        "turns": [{"role": "user", "content": "안녕하세요"}],
        "expect": {"outcome": "completed"},
    }
    s.update(over)
    return s


def concern_scenario(**over):
    s = base_scenario(id="t-concern", kind="concern", concernType="leak",
                      expect={"outcome": "blocked", "markers": ["MARK-123"]})
    s.update(over)
    return s
