"""모델 교체 회귀용 별칭과 평가 대화의 별칭 바꿔 끼우기(#346, 계약 #348)."""

import json

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from gateway.egress import load_model_info, load_provider_models
from gateway.main import create_app

from .conftest import ROOT
from .test_chat import FakeAgent, _login
from .test_egress import _agent_ids, _audit

MSG = [{"role": "user", "content": "규정 알려 줘"}]
BOTH = "local=local-exaone,external=external-sonnet"


def test_config_has_eval_aliases_and_keeps_defaults():
    cfg = ROOT / "gateway/litellm/config.yaml"
    info = load_model_info(cfg)
    models = load_provider_models(cfg)
    assert info["external-sonnet"]["location"] == "external" and models["external-sonnet"] == "anthropic/claude-sonnet-5-5"
    assert float(info["external-sonnet"]["input_cost_per_token"]) == 0.000002
    assert float(info["external-sonnet"]["output_cost_per_token"]) == 0.00001
    assert set(info["external-sonnet"]["drop_params"]) >= {"temperature", "top_p"}
    assert info["local-exaone"]["location"] == "local"
    assert models["local-exaone"].endswith("EXAONE-4.0-1.2B-GGUF:Q4_K_M")
    assert models["local"] == "ollama_chat/qwen3.5:9b" and models["external"] == "anthropic/claude-haiku-5-5"


def test_config_has_k_exaone_alias():
    """K-EXAONE 2.5 API(#436). OpenAI 호환 엔드포인트로 보내고 키는 환경 변수에서만 읽습니다."""
    import yaml

    cfg = ROOT / "gateway/litellm/config.yaml"
    entry = next(m for m in yaml.safe_load(cfg.read_text(encoding="utf-8"))["model_list"]
                 if m["model_name"] == "external-exaone")
    assert entry["model_info"]["location"] == "external"
    assert entry["litellm_params"] == {"model": "openai/k-exaone_v2.5", "api_base": "https://api.exaone.ai/v1",
                                       "api_key": "os.environ/K_EXAONE_API_KEY"}


@pytest.fixture
def ec(settings, fake_erp, issuer):
    """채팅으로 대화를 만들고, 그 대화의 위임 토큰으로 출구를 부릅니다."""
    from .conftest import FakeLiteLLM

    llm, agent = FakeLiteLLM(), FakeAgent()
    app = create_app(settings, erp_transport=httpx.ASGITransport(app=fake_erp), issuer=issuer,
                     llm_transport=httpx.MockTransport(llm), agent_transport=httpx.MockTransport(agent))
    with TestClient(app) as c:
        c.app_ref, c.llm, c.agent = app, llm, agent
        app.state.chat.eval_mode = True
        yield c


def _conv(c, staff_no, override=None, agent_id=None):
    h = _login(c, staff_no)
    headers = {**h, **({"X-Eval-Model-Override": override} if override else {})}
    r = c.post("/api/conversations", headers=headers, json={"agentId": agent_id} if agent_id else {})
    return r, h


def _token(c, staff_no, cid, agent_id):
    app = c.app_ref
    who = app.state.chat.conversations[cid]
    from gateway.registry import Requester
    req = Requester(staff_no, who.unit_id or "u", "staff", ("employee",), ())
    return app.state.issuer.issue(req, app.state.registry.get(agent_id), cid).token


@pytest.mark.parametrize("override,requested,sent", [
    (BOTH, "local", "local-exaone"),
    (BOTH, "local-gguf", "local-exaone"),
    (BOTH, "external", "external-sonnet"),
    ("local=local-exaone", "external", "external"),
    ("external=external-sonnet", "local", "local"),
    ("external=external-exaone", "external", "external-exaone"),
    ("external=external-exaone", "local", "local"),
    (None, "external", "external"),
])
def test_override_swaps_aliases_for_that_conversation(ec, staff_no, override, requested, sent):
    _, ext = _agent_ids(ec.app_ref)
    r, _ = _conv(ec, staff_no, override)
    assert r.status_code == 201, r.text
    cid = r.json()["conversationId"]
    tok = _token(ec, staff_no, cid, ext)
    r = ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": requested, "messages": MSG})
    assert r.status_code == 200, r.text
    assert ec.llm.last_body()["model"] == sent and r.headers["x-egress-model"] == sent
    ev = _audit(ec.app_ref)[-1]
    assert ev["model"]["name"] == sent
    if sent != requested:
        assert f"{requested} 대신 {sent}" in ev["detail"]


def test_override_does_not_loosen_policy(ec, staff_no):
    """external을 external-sonnet으로 바꿔도 위치가 같아 local_only 에이전트는 여전히 403입니다."""
    local_only, _ = _agent_ids(ec.app_ref)
    r, _ = _conv(ec, staff_no, BOTH)
    tok = _token(ec, staff_no, r.json()["conversationId"], local_only)
    r = ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 403 and ec.llm.requests == []


def test_override_applies_to_confidential_reroute_and_fallback(ec, staff_no):
    from gateway.confidential import Glossary

    _, ext = _agent_ids(ec.app_ref)
    r, _ = _conv(ec, staff_no, BOTH)
    tok = _token(ec, staff_no, r.json()["conversationId"], ext)
    ec.app_ref.state.egress.glossary = Glossary.from_doc({"terms": [{"term": "오리온", "level": "confidential",
                                                                      "action": "local_only"}]})
    r = ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok},
                json={"model": "external", "messages": [{"role": "user", "content": "오리온 일정"}]})
    assert r.status_code == 200 and ec.llm.last_body()["model"] == "local-exaone"
    ec.llm.external_mode = "down"   # external-sonnet 장애 → 로컬 폴백도 바꿔 끼운 별칭
    r = ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": MSG})
    assert r.status_code == 200
    assert [json.loads(q.content)["model"] for q in ec.llm.requests[-2:]] == ["external-sonnet", "local-exaone"]


def test_images_and_tokenless_calls_are_not_swapped(ec, staff_no):
    from .test_vision import _msg, _png, _url

    _, ext = _agent_ids(ec.app_ref)
    r, _ = _conv(ec, staff_no, BOTH)
    tok = _token(ec, staff_no, r.json()["conversationId"], ext)
    ec.post("/v1/chat/completions", headers={"X-Delegation-Token": tok},
            json={"model": "local", "messages": _msg(_url(_png()))})
    assert ec.llm.last_body()["model"] == "local-vision"
    ec.post("/v1/chat/completions", json={"model": "local", "messages": MSG})
    assert ec.llm.last_body()["model"] == "local"


def test_header_needs_eval_mode_and_valid_value(ec, staff_no):
    ec.app_ref.state.chat.eval_mode = False
    assert _conv(ec, staff_no, BOTH)[0].status_code == 400
    ec.app_ref.state.chat.eval_mode = True
    for bad in ("local=external", "external=external-sonnet,local=local-exaone", "local=qwen"):
        r, _ = _conv(ec, staff_no, bad)
        assert r.status_code == 422, bad


def test_run_receives_no_override_field(ec, staff_no):
    """별칭 바꿔 끼우기는 gateway 출구에서만 합니다. agent /run 계약에는 넣지 않습니다."""
    r, h = _conv(ec, staff_no, BOTH)
    cid = r.json()["conversationId"]
    ec.post(f"/api/conversations/{cid}/messages", headers=h, json={"content": "출장비 규정 알려 줘"})
    body = [b for p, b, _ in ec.agent.calls if p == "/run"][-1]
    assert "modelOverride" not in json.dumps(body)
    assert jwt.decode([t for p, _, t in ec.agent.calls if p == "/run"][-1], options={"verify_signature": False})["cid"] == cid
