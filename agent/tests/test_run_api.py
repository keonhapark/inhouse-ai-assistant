"""/run·/resume HTTP 계약(contracts/openapi/agent.yaml)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_runtime.app import Services, create_app
from agent_runtime.audit import AuditLog
from agent_runtime.mcp_server.service import CallMeta
from agent_runtime.router import Router
from tests.mcp_support import future_weekday, mint
from tests.run_support import RunHarness, call, make_run_harness, say

EMPLOYEE = {"employeeId": "E0016", "unitId": "finance", "grade": "staff", "roles": ["employee"]}


@pytest.fixture
def r(tmp_path: Path) -> RunHarness:
    return make_run_harness(tmp_path)


@pytest.fixture
def client(r: RunHarness, registry, tmp_path: Path) -> TestClient:
    svc = Services(registry, Router(registry, None), AuditLog(tmp_path / "a.jsonl"), r.runner)
    return TestClient(create_app(svc))


def test_run_requires_token_header(client: TestClient) -> None:
    body = {"conversationId": "c", "agentId": "hr", "message": "x", "requester": EMPLOYEE}
    assert client.post("/run", json=body).status_code == 422


def test_run_rejects_unknown_condition(client: TestClient) -> None:
    body = {"conversationId": "c", "agentId": "hr", "message": "x", "requester": EMPLOYEE, "condition": "magic"}
    assert client.post("/run", json=body, headers={"X-Delegation-Token": "t"}).status_code == 422


def test_run_and_resume_over_http(client: TestClient, r: RunHarness) -> None:
    import anyio

    day = future_weekday()
    created = anyio.run(lambda: r.h.service.call(
        "leave_request", {"leave_type": "annual", "start_date": day, "end_date": day, "reason": "x"}, mint(),
        CallMeta(trust_level="user_direct", idempotency_key=uuid.uuid4().hex)))
    doc = created.data["resource"]["id"]
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    headers = {"X-Delegation-Token": mint(cid=conv)}
    r.llm.script = [call("approval_withdraw", {"documentId": doc}), say("회수했습니다.")]
    body = {"conversationId": conv, "agentId": "hr", "message": "회수해 줘", "requester": EMPLOYEE}
    s = client.post("/run", json=body, headers=headers).json()
    assert s["status"] == "awaiting_approval"
    assert set(s) >= {"conversationId", "agentId", "status", "messages"}
    approval = s["pendingApproval"]["approvalId"]

    wrong = client.post("/resume", json={"conversationId": conv, "approvalId": "nope", "decision": "approve"},
                        headers=headers)
    assert wrong.status_code == 409
    ok = client.post("/resume", json={"conversationId": conv, "approvalId": approval, "decision": "approve"},
                     headers=headers)
    assert ok.status_code == 200 and ok.json()["status"] == "completed"
    again = client.post("/resume", json={"conversationId": conv, "approvalId": approval, "decision": "approve"},
                        headers=headers)
    assert again.status_code == 409


def test_runner_not_configured(registry, tmp_path: Path) -> None:
    c = TestClient(create_app(Services(registry, Router(registry, None), AuditLog(tmp_path / "a.jsonl"))))
    body = {"conversationId": "c", "agentId": "hr", "message": "x", "requester": EMPLOYEE}
    assert c.post("/run", json=body, headers={"X-Delegation-Token": "t"}).status_code == 503
