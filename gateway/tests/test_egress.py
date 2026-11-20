import dataclasses
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
    assert locs == {"local": "local", "local-embed": "local", "external": "external"}


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


# ---------- 평가 경로(#63) ----------
EXT_SCHEMA = json.loads((ROOT / "contracts/events/external-request.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def ext_log(app, tmp_path):
    from gateway.audit import JsonlWriter

    app.state.egress.external_log = JsonlWriter(tmp_path / "external.jsonl")
    return app.state.egress.external_log


def test_external_request_log_has_redacted_body(client, app, token_for, litellm, ext_log):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": PII_MSG})
    assert r.status_code == 200
    (rec,) = ext_log.read_all()
    Draft202012Validator(EXT_SCHEMA).validate(rec)
    assert rec["conversationId"] == "conv-9" and rec["agentId"] == external_ok and rec["model"] == "external"
    assert rec["body"] == litellm.last_body()          # 실제 보낸 본문(가림 뒤) 그대로
    assert "010-1234-5678" not in json.dumps(rec, ensure_ascii=False)


def test_external_log_skips_local_denied_and_unsent(client, app, token_for, litellm, ext_log):
    local_only, external_ok = _agent_ids(app)
    client.post("/v1/chat/completions", json={"model": "local", "messages": MSG})
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                json={"model": "external", "messages": MSG})
    litellm.mode = "down"
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "external", "messages": MSG})
    assert ext_log.read_all() == []


def test_external_log_off_by_default(client, app, token_for, settings):
    assert app.state.egress.external_log is None


def test_embeddings_local_only(client, app, litellm):
    r = client.post("/v1/embeddings", json={"model": "local-embed", "input": ["규정 본문"]})
    assert r.status_code == 200 and r.json()["data"][0]["embedding"] == [0.1, 0.2]
    assert litellm.requests[-1].url.path == "/v1/embeddings"
    assert _audit(app)[-1]["model"]["name"] == "local-embed"
    n = len(litellm.requests)
    r = client.post("/v1/embeddings", json={"model": "external", "input": "x"})
    assert r.status_code == 403 and len(litellm.requests) == n
    assert client.post("/v1/embeddings", json={"model": "local-embed"}).status_code == 422
    assert client.post("/v1/embeddings", json={"model": "local-embed", "input": "x", "fallbacks": []}
                       ).status_code == 422


def test_reasoning_effort_is_forwarded(client, litellm):
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": MSG, "reasoning_effort": "low"})
    assert r.status_code == 200 and litellm.last_body()["reasoning_effort"] == "low"


def test_think_is_dropped_for_external_only(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "external", "messages": MSG, "think": False})
    assert "think" not in litellm.last_body()
    client.post("/v1/chat/completions", json={"model": "local", "messages": MSG, "think": False})
    assert litellm.last_body()["think"] is False


# ---------- 거절 감사와 response_format(#95) ----------
def _llm_events(app):
    return [e for e in _audit(app) if e["kind"] == "llm.request"]


def test_unknown_alias_rejection_is_audited_with_context(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "qwen3.5:9b", "messages": MSG})
    assert r.status_code == 422
    (ev,) = _llm_events(app)
    assert ev["result"] == "denied" and ev["problemType"] == "urn:problem:validation"
    assert ev["conversationId"] == "conv-9" and ev["actor"]["agentId"] == external_ok
    assert ev["model"] == {"name": "qwen3.5:9b"} and "qwen3.5:9b" in ev["detail"] and "422" in ev["detail"]
    assert "규정 알려 줘" not in json.dumps(ev, ensure_ascii=False)   # 본문은 넣지 않음


@pytest.mark.parametrize("kwargs,status,code", [
    ({"json": {"model": "local", "messages": MSG, "fallbacks": ["external"]}}, 422, "validation"),
    ({"content": b"{", "headers": {"content-type": "application/json"}}, 422, "validation"),
    ({"json": {"model": "local", "messages": MSG}, "headers": {"X-Delegation-Token": "bad"}}, 401, "unauthorized"),
])
def test_every_rejection_is_audited(client, app, kwargs, status, code):
    r = client.post("/v1/chat/completions", **kwargs)
    assert r.status_code == status
    (ev,) = _llm_events(app)
    assert ev["result"] == "denied" and ev["problemType"] == f"urn:problem:{code}"


def test_unregistered_agent_rejection_is_audited(client, app, issuer, staff_no):
    from gateway.registry import Requester

    agent = dataclasses.replace(app.state.registry.get("assistant"), id="router")
    token = issuer.issue(Requester(staff_no, "u", "staff", ("employee",), ()), agent, "conv-r").token
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token},
                    json={"model": "local", "messages": MSG})
    assert r.status_code == 403
    (ev,) = _llm_events(app)
    assert ev["problemType"] == "urn:problem:forbidden" and "router" in ev["detail"]


def test_policy_denial_is_audited_once(client, app, token_for):
    local_only, _ = _agent_ids(app)
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                json={"model": "external", "messages": MSG})
    assert len(_llm_events(app)) == 1


def test_response_format_on_local_is_400_before_sending(client, app, litellm, alerts):
    r = client.post("/v1/chat/completions", json={"model": "local", "messages": MSG,
                                                   "response_format": {"type": "json_object"}})
    assert r.status_code == 400 and r.json()["type"] == "urn:problem:unsupported-parameter"
    assert litellm.requests == [] and alerts == []
    assert _llm_events(app)[-1]["problemType"] == "urn:problem:unsupported-parameter"


def test_response_format_on_external_passes(client, app, token_for, litellm):
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG, "response_format": {"type": "json_object"}})
    assert r.status_code == 200 and litellm.last_body()["response_format"] == {"type": "json_object"}


def test_upstream_501_is_400_without_alert(client, app, token_for, litellm, alerts):
    _, external_ok = _agent_ids(app)
    litellm.mode = "501"
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG})
    assert r.status_code == 400 and "structured output is unavailable" in r.json()["detail"]
    assert alerts == []
    assert len(_llm_events(app)) == 1


def test_embedding_rejection_is_audited(client, app):
    assert client.post("/v1/embeddings", json={"model": "nope", "input": "x"}).status_code == 422
    assert _llm_events(app)[-1]["model"] == {"name": "nope"}


# ---------- 차례별 사용 모델(#121) ----------
def test_usage_records_models_sent_for_begun_conversation(client, app, token_for, litellm):
    local_only, external_ok = _agent_ids(app)
    usage = app.state.egress.usage
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "local", "messages": MSG})
    assert usage.take("conv-9") is None                        # begin 전에는 모으지 않음
    usage.begin("conv-9")
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "external", "messages": MSG})
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                json={"model": "local", "messages": MSG})
    assert usage.take("conv-9") == {"name": "external", "location": "external"}   # 한 번이라도 외부면 외부
    usage.begin("conv-9")
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                json={"model": "external", "messages": MSG})          # 정책 거절: 보내지 않음
    litellm.mode = "down"
    client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                json={"model": "local", "messages": MSG})             # 연결 실패: 보내지 않음
    assert usage.take("conv-9") is None


# ---------- 평가 조건별 출구 장치(#134) ----------
def _cond(app, condition):
    app.state.egress.condition_of = lambda cid: condition if cid == "conv-9" else None


def _send(client, token, model, content):
    return client.post("/v1/chat/completions", headers={"X-Delegation-Token": token},
                       json={"model": model, "messages": [{"role": "user", "content": content}]})


PII_TEXT = "연락처 010-1234-5678, 메일 hong@example.com"


def test_no_guard_turns_off_all_gateway_guards(client, app, token_for, litellm, glossary):
    local_only, _ = _agent_ids(app)
    _cond(app, "no_guard")
    t = token_for(local_only)
    assert _send(client, t, "external", PII_TEXT).status_code == 200            # 로컬 강제 끔
    assert litellm.last_body()["messages"][0]["content"] == PII_TEXT            # 가림 끔
    assert _send(client, t, "external", "원가표 요약").status_code == 200        # 기밀 판정 끔
    assert litellm.last_body()["model"] == "external"


def test_baseline_tools_uses_stock_recognizers_only(client, app, token_for, litellm, glossary):
    from gateway.pii import BaselineRedactor

    app.state.egress.baseline_redactor = BaselineRedactor()
    local_only, _ = _agent_ids(app)
    _cond(app, "baseline_tools")
    t = token_for(local_only)
    assert _send(client, t, "external", PII_TEXT).status_code == 200
    sent = litellm.last_body()["messages"][0]["content"]
    assert "<EMAIL_ADDRESS>" in sent and "[전화번호]" not in sent              # 기성 기본값, 한국 인식기 없음
    assert _send(client, t, "external", "원가표 요약").status_code == 200        # 기밀 판정 끔


@pytest.mark.parametrize("condition", ["write_blocked", "approve_all", "full"])
def test_guarded_conditions_keep_all_guards(client, app, token_for, litellm, glossary, condition):
    local_only, external_ok = _agent_ids(app)
    _cond(app, condition)
    assert _send(client, token_for(local_only), "external", "x").status_code == 403
    assert _send(client, token_for(external_ok), "external", PII_TEXT).status_code == 200
    assert "[전화번호]" in litellm.last_body()["messages"][0]["content"]
    assert _send(client, token_for(external_ok), "external", "원가표 요약").status_code == 403


def test_external_log_usage_and_cost(client, app, token_for, litellm, ext_log):
    _, external_ok = _agent_ids(app)
    litellm.usage = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    litellm.cost = "0.00042"
    _send(client, token_for(external_ok), "external", "안녕")
    (rec,) = ext_log.read_all()
    Draft202012Validator(EXT_SCHEMA).validate(rec)
    assert rec["usage"] == {"prompt_tokens": 12, "completion_tokens": 3} and rec["costUsd"] == 0.00042


def test_external_log_usage_from_stream(client, app, token_for, litellm, ext_log):
    from gateway.egress import response_usage

    sse = ('data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
           'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\ndata: [DONE]\n\n')
    assert response_usage(sse) == {"prompt_tokens": 5, "completion_tokens": 1}
    assert response_usage("not json") is None
    _, external_ok = _agent_ids(app)
    _send(client, token_for(external_ok), "external", "안녕")
    (rec,) = ext_log.read_all()
    assert rec["costUsd"] is None and "usage" not in rec              # 모르면 null·생략


# ---------- 외부 모델 Haiku 5.5(#139) ----------
def test_external_alias_is_haiku_5_5_and_drops_sampling():
    import yaml

    from gateway.egress import load_model_info
    doc = yaml.safe_load((ROOT / "gateway/litellm/config.yaml").read_text(encoding="utf-8"))
    ext = next(m for m in doc["model_list"] if m["model_name"] == "external")
    assert ext["litellm_params"]["model"] == "anthropic/claude-haiku-5-5"
    assert set(load_model_info(ROOT / "gateway/litellm/config.yaml")["external"]["drop_params"]) >= {"temperature", "top_p"}


def test_sampling_params_dropped_for_external_only(client, app, token_for, litellm):
    app.state.egress.drop_params = {"external": frozenset({"temperature", "top_p"})}
    _, external_ok = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(external_ok)},
                    json={"model": "external", "messages": MSG, "temperature": 0, "top_p": 0.9,
                          "reasoning_effort": "low"})
    assert r.status_code == 200
    body = litellm.last_body()
    assert "temperature" not in body and "top_p" not in body and body["reasoning_effort"] == "low"
    rec = app.state.audit.egress.read_all()[-1]
    assert rec["requestBeforeRedaction"]["temperature"] == 0 and "temperature" not in rec["requestSent"]
    client.post("/v1/chat/completions", json={"model": "local", "messages": MSG, "temperature": 0})
    assert litellm.last_body()["temperature"] == 0
