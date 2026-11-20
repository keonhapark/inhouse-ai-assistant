import pytest
import json

import httpx

from harness.sut import GatewayChat, parse_sse


def test_parse_sse():
    text = ('event: delta\ndata: {"type":"delta","text":"가"}\n\n'
            ': keepalive\n\n'
            'event: message\ndata: {"type":"message",\ndata: "text":"나"}\n\n'
            'event: done\ndata: {"type":"done"}')
    assert [e["type"] for e in parse_sse(text.split("\n"))] == ["delta", "message", "done"]


def _sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)


def test_gateway_chat_flow():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        p = req.url.path
        if p == "/api/auth/login":
            who = json.loads(req.content)["employeeNo"]
            return httpx.Response(200, json={"accessToken": f"tok-{who}"})
        if p == "/api/conversations":
            return httpx.Response(201, json={"conversationId": "c1", "createdAt": "x", "status": "active"})
        if p == "/api/conversations/c1/messages":
            return httpx.Response(200, text=_sse({"type": "message", "conversationId": "c1", "seq": 1, "text": "hi"},
                                                 {"type": "done", "conversationId": "c1", "seq": 2}),
                                  headers={"content-type": "text/event-stream"})
        if p == "/api/execution-approvals/p1":
            assert json.loads(req.content) == {"decision": "approve"}
            return httpx.Response(200, text=_sse({"type": "done", "conversationId": "c1", "seq": 3}))
        if p == "/api/audit-events":
            if req.url.params.get("cursor") is None:
                return httpx.Response(200, json={"items": [{"kind": "tool.called"}], "nextCursor": "n"})
            return httpx.Response(200, json={"items": [{"kind": "erp.write"}], "nextCursor": None})
        return httpx.Response(404)

    c = httpx.Client(base_url="http://gw/api", transport=httpx.MockTransport(handler))
    g = GatewayChat(c, auditor="E0050", password="pw",
                    external_log=lambda cid: [{"conversationId": cid, "model": "external", "body": f"body-{cid}",
                                                "costUsd": 0.002}])
    cid = g.start("E0016")
    assert [e["type"] for e in g.send(cid, "안녕")] == ["message", "done"]
    assert [e["type"] for e in g.decide(cid, "p1", "approve")] == ["done"]
    got = g.collect(cid)
    assert [a["kind"] for a in got.audit_events] == ["tool.called", "erp.write"]
    assert got.external_requests == ["body-c1"]
    assert got.cost_usd == 0.002
    assert got.external_models == ["external"]
    chat_auth = {a for m, p, a in seen if p.startswith("/api/conversations")}
    assert chat_auth == {"Bearer tok-E0016"}
    assert {a for m, p, a in seen if p == "/api/audit-events"} == {"Bearer tok-E0050"}


def test_condition_header_and_external_log(tmp_path):
    seen = {}

    def handler(req):
        if req.url.path == "/api/auth/login":
            return httpx.Response(200, json={"accessToken": "t"})
        seen["cond"] = req.headers.get("x-eval-condition")
        return httpx.Response(201, json={"conversationId": "c9", "createdAt": "x", "status": "active"})

    from harness.sut import jsonl_external_log
    c = httpx.Client(base_url="http://gw/api", transport=httpx.MockTransport(handler))
    assert GatewayChat(c, auditor=None, condition="write_blocked").start("E0016") == "c9"
    assert seen["cond"] == "write_blocked"

    log = tmp_path / "ext.jsonl"
    read = jsonl_external_log(log)
    assert read("c9") == []  # 파일 없음 = 외부 요청 없음
    log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"conversationId": "c9", "at": "t", "model": "m", "body": {"messages": [{"content": "가"}]}},
        {"conversationId": "other", "at": "t", "model": "m", "body": {"messages": []}},
    ]) + "\n", encoding="utf-8")
    assert [r["body"] for r in read("c9")] == [{"messages": [{"content": "가"}]}]


def test_docker_external_log(monkeypatch):
    import subprocess

    from harness.sut import docker_external_log

    lines = "\n".join(json.dumps(r) for r in [{"conversationId": "c1", "at": "t", "model": "m", "body": {"a": 1}},
                                              {"conversationId": "c2", "at": "t", "model": "m", "body": {"a": 2}}])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=lines + "\n"))
    assert [r["body"] for r in docker_external_log("gw", "/audit/x.jsonl")("c1")] == [{"a": 1}]

    def boom(*a, **k):
        raise OSError("no docker")
    monkeypatch.setattr(subprocess, "run", boom)
    assert docker_external_log("gw", "/audit/x.jsonl")("c1") is None


def test_external_cost():
    from harness.sut import external_cost
    assert external_cost([]) == 0.0
    assert external_cost([{"costUsd": 0.001}, {"costUsd": 0.002}]) == pytest.approx(0.003)
    assert external_cost([{"costUsd": 0.001}, {"costUsd": None}]) is None
