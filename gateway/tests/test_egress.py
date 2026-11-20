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
