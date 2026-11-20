import json

import pytest
from jsonschema import Draft202012Validator

from gateway.egress import load_model_locations

from .conftest import ROOT

AUDIT_SCHEMA = json.loads((ROOT / "contracts/events/audit.schema.json").read_text(encoding="utf-8"))
MSG = [{"role": "user", "content": "규정 알려 줘"}]


@pytest.fixture
def token_for(login, issue, staff_no):
    def _t(agent_id: str) -> str:
        return issue(login(staff_no), agent_id, "conv-9").token
    return _t


def _agent_ids(app):
    by_mode = {}
    for a in app.state.registry.all():
        by_mode.setdefault(a.model_policy["mode"], a.id)
    return by_mode["local_only"], by_mode["external_allowed"]


def _audit(app) -> list[dict]:
    events = app.state.audit.events.read_all()
    for e in events:
        Draft202012Validator(AUDIT_SCHEMA).validate(e)
    return events


def test_litellm_config_aliases_have_location():
    locs = load_model_locations(ROOT / "gateway/litellm/config.yaml")
    assert locs == {"local": "local", "external": "external"}


def test_local_only_agent_cannot_use_external(client, app, token_for, litellm):
    local_only, _ = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                    json={"model": "external", "messages": MSG})
    assert r.status_code == 403
    assert r.json()["type"] == "urn:problem:model-policy"
    assert litellm.requests == []  # 밖으로 아무것도 나가지 않음
    ev = _audit(app)[-1]
    assert ev["kind"] == "llm.request" and ev["result"] == "denied"
    assert ev["actor"]["agentId"] == local_only and ev["model"]["externalSent"] is False
    assert app.state.audit.egress.read_all() == []


def test_local_only_agent_uses_local(client, app, token_for, litellm):
    local_only, _ = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                    json={"model": "local", "messages": MSG})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "답입니다"
    ev = _audit(app)[-1]
    assert ev["result"] == "ok" and ev["model"] == {"name": "local", "location": "local", "externalSent": False,
                                                     "redactions": 0}
    assert ev["conversationId"] == "conv-9"
    assert app.state.audit.egress.read_all() == []  # 로컬은 외부 전송 기록에 남지 않음


def test_external_allowed_agent_sends_and_records_body(client, app, token_for, litellm, staff_no):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG})
    assert r.status_code == 200
    rec = app.state.audit.egress.read_all()[-1]
    assert rec["agentId"] == external_ok and rec["model"] == "external"
    assert rec["requestBeforeRedaction"]["messages"] == MSG and rec["requestSent"]["messages"] == MSG
    assert "답입니다" in rec["response"]
    assert _audit(app)[-1]["model"]["externalSent"] is True


def test_no_token_means_local_only(client, app, litellm):
    assert client.post("/v1/chat/completions", json={"model": "external", "messages": MSG}).status_code == 403
    assert client.post("/v1/chat/completions", json={"model": "local", "messages": MSG}).status_code == 200
    assert _audit(app)[-1]["actor"] == {"employeeId": None, "viaDelegationToken": False, "agentId": None}


def test_token_is_not_forwarded_and_scrubbed_from_body(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    token = token_for(external_ok)
    leak = [{"role": "user", "content": f"헤더 값은 {token} 입니다"}]
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token},
                    json={"model": "external", "messages": leak})
    assert r.status_code == 200
    sent = litellm.requests[-1]
    assert "x-delegation-token" not in {k.lower() for k in sent.headers}
    assert token not in sent.content.decode()
    var = (app.state.settings.audit_dir)
    for f in var.iterdir():
        assert token not in f.read_text(encoding="utf-8")


def test_invalid_token_is_401(client, litellm):
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": "not-a-token"},
                    json={"model": "local", "messages": MSG})
    assert r.status_code == 401 and litellm.requests == []


def test_unknown_alias_and_bad_body_are_422(client):
    assert client.post("/v1/chat/completions", json={"model": "gpt-x", "messages": MSG}).status_code == 422
    assert client.post("/v1/chat/completions", json={"messages": MSG}).status_code == 422
    assert client.post("/v1/chat/completions", content=b"{", headers={"content-type": "application/json"}
                       ).status_code == 422


@pytest.mark.parametrize("mode,status,code", [
    ("timeout", 504, "llm-timeout"),
    ("down", 502, "llm-unavailable"),
    ("500", 502, "llm-upstream-error"),
])
def test_failures_alert_and_audit(client, app, litellm, alerts, mode, status, code):
    litellm.mode = mode
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": MSG})
    assert r.status_code == status and r.json()["type"] == f"urn:problem:{code}"
    assert len(alerts) == 1 and "[gateway]" in alerts[0]["text"]
    assert app.state.alerter.sent
    ev = _audit(app)[-1]
    assert ev["result"] == "error" and ev["problemType"] == f"urn:problem:{code}"


def test_stream_is_relayed_and_recorded(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG, "stream": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert "하세요" in r.text and r.text.rstrip().endswith("data: [DONE]")
    assert litellm.last_body()["stream"] is True
    assert "하세요" in app.state.audit.egress.read_all()[-1]["response"]
    assert _audit(app)[-1]["result"] == "ok"


def test_stream_upstream_error(client, app, litellm, alerts):
    litellm.mode = "500"
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": MSG, "stream": True})
    assert r.status_code == 502 and len(alerts) == 1


# ---------- 가림과 기밀 판정(#10) ----------
PII_MSG = [{"role": "user", "content": "제 연락처는 010-1234-5678, 주민번호 900101-1234568입니다"}]


def test_external_request_is_redacted_and_recorded(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": PII_MSG})
    assert r.status_code == 200
    sent = litellm.last_body()["messages"][0]["content"]
    assert "010-1234-5678" not in sent and "900101-1234568" not in sent
    assert "[전화번호]" in sent and "[주민등록번호]" in sent
    rec = app.state.audit.egress.read_all()[-1]
    assert rec["requestBeforeRedaction"]["messages"] == PII_MSG       # 가림 전 원문은 외부 전송 기록에만
    assert rec["requestSent"]["messages"][0]["content"] == sent and rec["redactions"] == 2
    events = _audit(app)
    red = [e for e in events if e["kind"] == "llm.redacted"][-1]
    assert red["detail"] == "KR_PHONE=1, KR_RRN=1" and red["model"]["redactions"] == 2
    assert events[-1]["kind"] == "llm.request" and events[-1]["model"]["redactions"] == 2
    audit_text = app.state.audit.events.path.read_text(encoding="utf-8")
    assert "010-1234-5678" not in audit_text and "900101" not in audit_text  # 감사 이벤트에 원문 없음


def test_local_request_is_not_redacted(client, app, litellm):
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": PII_MSG})
    assert r.status_code == 200
    assert litellm.last_body()["messages"] == PII_MSG
    assert not [e for e in _audit(app) if e["kind"] == "llm.redacted"]


@pytest.fixture
def glossary(app):
    from gateway.confidential import Glossary

    app.state.egress.glossary = Glossary.from_doc({"terms": [
        {"term": "프로젝트 해오름", "action": "local_only"},
        {"term": "원가표", "action": "block", "reason": "원가 정보는 외부로 보내지 않습니다"},
    ]})


def test_confidential_term_reroutes_to_local(client, app, token_for, litellm, glossary):
    _, external_ok = _agent_ids(app)
    msg = [{"role": "user", "content": "프로젝트 해오름 담당자 010-1234-5678 일정"}]
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": msg})
    assert r.status_code == 200
    assert litellm.last_body()["model"] == "local"
    assert litellm.last_body()["messages"] == msg          # 로컬로 가면 가리지 않음
    assert app.state.audit.egress.read_all() == []          # 밖으로 나가지 않음
    events = _audit(app)
    assert events[-2]["kind"] == "llm.redacted" and "로컬" in events[-2]["detail"]
    assert "해오름" not in events[-2]["detail"]              # 용어 자체는 남기지 않음
    assert events[-1]["model"]["location"] == "local" and events[-1]["model"]["externalSent"] is False


def test_confidential_block_term_denies(client, app, token_for, litellm, glossary):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": [{"role": "user", "content": "원가표 요약해 줘"}]})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:confidential"
    assert litellm.requests == []
    assert _audit(app)[-1]["result"] == "denied"


def test_confidential_term_to_local_model_passes(client, litellm, glossary):
    r = client.post("/v1/chat/completions", json={"model": "local",
                                                   "messages": [{"role": "user", "content": "원가표 요약"}]})
    assert r.status_code == 200


# ---------- 리뷰에서 고친 것 ----------
def test_tool_call_arguments_are_redacted(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    msgs = [{"role": "user", "content": "등록해 줘"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "register", "arguments": "{\"phone\": \"010-1234-5678\"}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "계좌 110-123-456789 확인"}]
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": msgs})
    assert r.status_code == 200
    sent = litellm.last_body()["messages"]
    assert sent[1]["tool_calls"][0]["function"]["arguments"] == "{\"phone\": \"[전화번호]\"}"
    assert sent[1]["tool_calls"][0]["id"] == "call_1" and sent[2]["tool_call_id"] == "call_1"
    assert sent[2]["content"] == "계좌 [계좌번호] 확인"


def test_glossary_looks_into_tool_definitions(client, app, token_for, litellm, glossary):
    _, external_ok = _agent_ids(app)
    tools = [{"type": "function", "function": {"name": "f", "description": "원가표 조회", "parameters": {}}}]
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG, "tools": tools})
    assert r.status_code == 403 and litellm.requests == []


@pytest.mark.parametrize("field,value", [
    ("fallbacks", ["external"]), ("api_base", "http://elsewhere"), ("mock_response", "x"), ("metadata", {}),
])
def test_unlisted_fields_are_rejected(client, app, token_for, litellm, field, value):
    local_only, _ = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                    json={"model": "local", "messages": MSG, field: value})
    assert r.status_code == 422 and field in r.json()["detail"]
    assert litellm.requests == []


def test_stream_closed_by_caller_is_still_recorded(app, token_for):
    import asyncio
    import json as _json

    from starlette.requests import Request

    _, external_ok = _agent_ids(app)
    raw = _json.dumps({"model": "external", "messages": MSG, "stream": True}).encode()
    token = token_for(external_ok)

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def go():
        scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions", "query_string": b"",
                 "headers": [(b"x-delegation-token", token.encode()), (b"content-type", b"application/json")]}
        resp = await app.state.egress.handle(Request(scope, receive))
        it = resp.body_iterator
        await it.__anext__()          # 조각 하나만 받고
        await it.aclose()             # 호출한 쪽이 끊음

    asyncio.run(go())
    ev = _audit(app)[-1]
    assert ev["kind"] == "llm.request" and ev["result"] == "error"
    assert ev["problemType"] == "urn:problem:llm-stream-aborted" and ev["model"]["externalSent"] is True
    assert "안녕" in app.state.audit.egress.read_all()[-1]["response"]
