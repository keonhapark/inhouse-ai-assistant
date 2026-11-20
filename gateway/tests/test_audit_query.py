import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app

from .conftest import _employees


@pytest.fixture(scope="module")
def auditor_no():
    # 팩 org.yaml에서 auditor 역할은 IT 운영 부서나 대표에게 주어집니다.
    return next(e["employee_no"] for e in _employees() if e["unit_id"] == "it-ops")


def _ev(eid, at, kind="tool.called", source="agent", conv="c-1", actor="E0099", agent="assistant"):
    return {"eventId": eid, "occurredAt": at, "source": source, "kind": kind,
            "actor": {"employeeId": actor, "viaDelegationToken": True, "agentId": agent},
            "conversationId": conv, "result": "ok"}


@pytest.fixture
def agent_file(tmp_path):
    p = tmp_path / "agent-audit.jsonl"
    lines = [json.dumps(_ev("a1", "2026-11-20T10:00:00+09:00")),
             "{깨진 줄",
             json.dumps(_ev("a2", "2026-11-20T10:00:02+09:00", kind="route.decided", conv="c-2")),
             json.dumps(_ev("a3", "2026-11-20T01:00:01Z", source="mcp"))]   # = 10:00:01+09:00
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def aclient(settings, fake_erp, issuer, agent_file):
    s = dataclasses.replace(settings, audit_event_files=(str(agent_file.parent / "*.jsonl"),))
    app = create_app(s, erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer,
                     llm_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})))
    with TestClient(app) as c:
        yield c


def _login(c, no):
    r = c.post("/api/auth/login", json={"employeeNo": no, "password": "demo-pass"})
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def test_merges_sources_in_time_order(aclient, auditor_no, caplog):
    h = _login(aclient, auditor_no)                       # erp가 auth.login을 남깁니다
    aclient.post("/v1/chat/completions", json={"model": "local", "messages": [{"role": "user", "content": "x"}]})
    r = aclient.get("/api/audit-events", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    sources = {e["source"] for e in items}
    assert {"erp", "gateway", "agent", "mcp"} <= sources
    ids = [e["eventId"] for e in items]
    assert ids.index("a1") < ids.index("a3") < ids.index("a2")   # 시간대가 달라도 시각 순
    assert "읽지 못한 줄 1개" in caplog.text


def test_filters(aclient, auditor_no):
    h = _login(aclient, auditor_no)
    got = aclient.get("/api/audit-events?conversationId=c-2", headers=h).json()["items"]
    assert [e["eventId"] for e in got] == ["a2"]
    got = aclient.get("/api/audit-events?kind=tool.called&agentId=assistant", headers=h).json()["items"]
    assert {e["eventId"] for e in got} == {"a1", "a3"}
    got = aclient.get("/api/audit-events", headers=h,
                      params={"since": "2026-11-20T10:00:01+09:00", "until": "2026-11-20T10:00:01+09:00"}).json()
    assert [e["eventId"] for e in got["items"]] == ["a3"]


def test_cursor_pages_without_overlap(aclient, auditor_no):
    h = _login(aclient, auditor_no)
    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = aclient.get("/api/audit-events", headers=h, params=params).json()
        seen += [e["eventId"] for e in body["items"]]
        cursor = body["nextCursor"]
        if not cursor:
            break
    everything = [e["eventId"] for e in aclient.get("/api/audit-events?limit=500", headers=h).json()["items"]]
    assert seen == everything and len(seen) == len(set(seen))


def test_non_auditor_is_403(aclient, staff_no):
    r = aclient.get("/api/audit-events", headers=_login(aclient, staff_no))
    assert r.status_code == 403


def test_bad_inputs_are_422(aclient, auditor_no):
    h = _login(aclient, auditor_no)
    assert aclient.get("/api/audit-events?cursor=@@", headers=h).status_code == 422
    assert aclient.get("/api/audit-events?since=2026-11-20T10:00:00", headers=h).status_code == 422
    assert aclient.get("/api/audit-events?limit=0", headers=h).status_code == 422
