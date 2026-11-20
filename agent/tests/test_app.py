from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from agent_runtime import app as app_module
from agent_runtime.app import Services, create_app
from agent_runtime.audit import AuditLog
from agent_runtime.registry import Registry
from agent_runtime.router import Router
from tests.conftest import CONTRACTS, PACK_DIR, content_response

AUDIT_SCHEMA = json.loads((CONTRACTS / "events" / "audit.schema.json").read_text("utf-8"))
EMPLOYEE = {"employeeId": "E0016", "unitId": "finance", "grade": "staff", "roles": ["employee"]}


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def client(registry: Registry, stub_chat, audit_path: Path) -> TestClient:
    chat = stub_chat(lambda req: content_response('{"agentId": "hr", "confidence": 0.9, "reason": "연차 신청"}'))
    svc = Services(registry, Router(registry, chat), AuditLog(audit_path))
    return TestClient(create_app(svc))


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_list_agents(client: TestClient) -> None:
    items = client.get("/agents").json()["items"]
    assert [i["id"] for i in items] == ["assistant", "hr"]
    hr = items[1]
    assert set(hr) == {"id", "name", "description", "modelPolicy"}
    assert hr["modelPolicy"] == "local_only"


def test_route_llm_writes_valid_audit_event(client: TestClient, audit_path: Path) -> None:
    resp = client.post("/route", json={"message": "다음 주 금요일 연차 쓸게", "requester": EMPLOYEE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agentId"] == "hr"
    assert body["method"] == "llm"
    assert body["confidence"] == 0.9
    assert body["suggestedAgentId"] is None

    [event] = _events(audit_path)
    jsonschema.validate(event, AUDIT_SCHEMA, format_checker=jsonschema.FormatChecker())
    assert event["kind"] == "route.decided"
    assert event["source"] == "agent"
    assert event["actor"] == {"employeeId": "E0016", "viaDelegationToken": False, "agentId": "hr"}
    assert event["routing"] == {"agentId": "hr", "method": "llm", "reason": "llm:chosen", "confidence": 0.9}
    # 요청 원문과 모델이 쓴 문장은 감사 기록에 남지 않습니다.
    raw = audit_path.read_text("utf-8")
    assert "연차" not in raw


def test_route_keyword(client: TestClient, audit_path: Path) -> None:
    resp = client.post("/route", json={"message": "회의실 잡아 줘", "requester": EMPLOYEE, "method": "keyword"})
    assert resp.json()["agentId"] == "assistant"
    assert resp.json()["method"] == "keyword"
    [event] = _events(audit_path)
    jsonschema.validate(event, AUDIT_SCHEMA)
    assert event["routing"]["method"] == "keyword"


def test_route_fallback_is_audited(client: TestClient, audit_path: Path) -> None:
    resp = client.post("/route", json={"message": "점심 뭐 먹지", "requester": EMPLOYEE, "method": "keyword"})
    assert resp.json()["method"] == "fallback"
    [event] = _events(audit_path)
    jsonschema.validate(event, AUDIT_SCHEMA)
    assert event["routing"]["method"] == "fallback"


def test_route_not_callable_suggests(client: TestClient) -> None:
    requester = dict(EMPLOYEE, roles=[])
    body = client.post("/route", json={"message": "연차 쓸게", "requester": requester}).json()
    assert (body["agentId"], body["method"], body["suggestedAgentId"]) == ("assistant", "fallback", "hr")


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x"},
        {"message": "x", "requester": EMPLOYEE, "method": "explicit"},
        {"message": "x", "requester": EMPLOYEE, "extra": 1},
        {"message": "x", "requester": {"employeeId": "E1"}},
    ],
)
def test_route_rejects_invalid_body(client: TestClient, payload: dict) -> None:
    assert client.post("/route", json=payload).status_code == 422


def test_services_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PACK_DIR", str(PACK_DIR))
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    monkeypatch.setenv("AGENT_ROUTER_MIN_CONFIDENCE", "0.7")
    svc = app_module.services_from_env()
    assert svc.router.min_confidence == 0.7
    assert svc.registry.fallback_agent_id == "assistant"


def test_services_from_env_requires_pack_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PACK_DIR", raising=False)
    with pytest.raises(RuntimeError, match="PACK_DIR"):
        app_module.services_from_env()
