"""GATEWAY_EVAL_TOOLCALL=1일 때만 토큰 없는 외부 호출을 받습니다(#268·#294, 도구 호출 측정 #103의 외부 기준)."""

import json

import pytest
from jsonschema import Draft202012Validator

from .test_egress import EXT_SCHEMA, MSG, PII_MSG, _audit, ext_log, glossary, token_for  # noqa: F401  (픽스처)


@pytest.fixture
def eval_mode(app):
    app.state.egress.eval_toolcall = True


def test_outside_eval_mode_tokenless_external_is_still_403(client, app, litellm):
    r = client.post("/v1/chat/completions", json={"model": "external", "messages": MSG})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:model-policy"
    assert litellm.requests == []


def test_eval_mode_allows_tokenless_external_with_redaction_and_records(client, app, litellm, eval_mode, ext_log):
    r = client.post("/v1/chat/completions", json={"model": "external", "messages": PII_MSG})
    assert r.status_code == 200, r.text
    assert r.headers["x-egress-location"] == "external"
    assert "010-1234-5678" not in json.dumps(litellm.last_body(), ensure_ascii=False)  # 가림은 그대로
    (rec,) = ext_log.read_all()
    Draft202012Validator(EXT_SCHEMA).validate(rec)
    assert rec["agentId"] is None and rec["conversationId"] is None and rec["body"] == litellm.last_body()
    (ops,) = app.state.audit.egress.read_all()
    assert ops["agentId"] is None and ops["employeeId"] is None
    ev = _audit(app)[-1]
    assert ev["result"] == "ok" and ev["model"]["externalSent"] is True
    assert "purpose=eval-toolcall" in ev["detail"]


def test_eval_mode_still_applies_confidential_block(client, app, litellm, eval_mode, glossary):
    r = client.post("/v1/chat/completions",
                    json={"model": "external", "messages": [{"role": "user", "content": "원가표 요약해 줘"}]})
    assert r.status_code == 403 and r.json()["type"] == "urn:problem:confidential"
    assert litellm.requests == []


def test_eval_mode_tokenless_local_is_unchanged(client, app, litellm, eval_mode):
    assert client.post("/v1/chat/completions", json={"model": "local", "messages": MSG}).status_code == 200
    assert "purpose" not in (_audit(app)[-1].get("detail") or "")


def test_eval_mode_does_not_loosen_local_only_agents(client, app, litellm, eval_mode, token_for):
    from .test_egress import _agent_ids

    local_only, _ = _agent_ids(app)
    r = client.post("/v1/chat/completions", headers={"X-Delegation-Token": token_for(local_only)},
                    json={"model": "external", "messages": MSG})
    assert r.status_code == 403


def test_app_reads_eval_toolcall_flag_separately_from_eval_mode(settings, fake_erp, issuer, litellm):
    """GATEWAY_EVAL_MODE만 켠 스택(정상·확인 셋)은 토큰 없는 외부 호출을 지금처럼 403으로 막습니다(#294)."""
    import dataclasses

    import httpx
    from fastapi.testclient import TestClient

    from gateway.main import create_app

    def build(**kw):
        return create_app(dataclasses.replace(settings, **kw), erp_transport=httpx.ASGITransport(app=fake_erp),
                          issuer=issuer, llm_transport=httpx.MockTransport(litellm))

    for kw, status in (({"eval_mode": True}, 403), ({"eval_toolcall": True}, 200),
                       ({"eval_mode": True, "eval_toolcall": True}, 200)):
        with TestClient(build(**kw)) as c:
            r = c.post("/v1/chat/completions", json={"model": "external", "messages": MSG})
            assert r.status_code == status, (kw, r.text)


def test_settings_read_flag_from_env(monkeypatch):
    from gateway.config import Settings

    monkeypatch.setenv("GATEWAY_EVAL_MODE", "1")
    monkeypatch.delenv("GATEWAY_EVAL_TOOLCALL", raising=False)
    assert Settings.from_env().eval_toolcall is False
    monkeypatch.setenv("GATEWAY_EVAL_TOOLCALL", "1")
    assert Settings.from_env().eval_toolcall is True
