"""별칭별 모델 프로필(#595, 결정 0009, 계약 #600)."""

import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.profiles import effort_for, load_model_profiles

from .conftest import ROOT, FakeLiteLLM
from .test_egress import _agent_ids, token_for  # noqa: F401  (픽스처)
from .test_ops import auditor, schema_check  # noqa: F401  (픽스처)

CFG = ROOT / "gateway/litellm/config.yaml"
HR = [{"role": "user", "content": "2027년 3월 11일 병가 하루 신청해 줘."}]   # 업무 주제 → 로컬로 돌림


def _by_alias():
    return {p["alias"]: p for p in load_model_profiles(CFG)}


def test_qwen_profile_keeps_decision_0008():
    """Qwen3.5-9B 별칭은 0008 그대로: 계획·로컬 돌림은 모델 기본(생각 켬), 이미지 읽기·rag 답·장애 분석은 끔, 120초."""
    for alias in ("local", "local-gguf", "local-vision"):
        p = _by_alias()[alias]
        assert p["profile"]["thinking"] == {"plan": "default", "reroute": "default", "imageRead": "off",
                                            "ragAnswer": "off", "incident": "off"}
        assert p["profile"]["timeoutSeconds"] == 120 and p["evalOnly"] is False
        assert effort_for(p, "plan") is None and effort_for(p, "imageRead") == "none"
    assert _by_alias()["local"]["profile"]["structuredOutput"] is False


def test_eval_only_aliases_and_gemma():
    by = _by_alias()
    assert {a for a, p in by.items() if p["evalOnly"]} == {"local-exaone", "local-gemma4", "external-sonnet",
                                                             "external-exaone"}
    g = by["local-gemma4"]
    assert g["model"] == "ollama_chat/gemma4:12b" and g["location"] == "local"
    assert set(g["profile"]["thinking"].values()) == {"off"}
    assert by["local-embed"]["mode"] == "embedding"


def test_profiles_match_contract():
    schema_check.validate("openapi/gateway.yaml", "ModelProfiles", {"aliases": load_model_profiles(CFG)})


@pytest.mark.parametrize("profile,error", [
    ({"thinking": {"plan": "maybe"}}, "on·off·default"),
    ({"thinking": {"chat": "off"}}, "profile.thinking에는"),
    ({"timeoutSeconds": 0}, "1 이상의 정수"),
    ({"speed": 1}, "모르는 키"),
])
def test_bad_profile_stops_startup(tmp_path, profile, error):
    import yaml

    cfg = tmp_path / "c.yaml"
    cfg.write_text(yaml.safe_dump({"model_list": [{"model_name": "x", "litellm_params": {"model": "m"},
                                                   "model_info": {"location": "local", "profile": profile}}]}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        load_model_profiles(cfg)


def test_unquoted_on_off_and_external_vision(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("model_list:\n  - model_name: x\n    litellm_params: {model: m}\n"
                   "    model_info: {location: local, profile: {thinking: {plan: off, reroute: on}}}\n", encoding="utf-8")
    (p,) = load_model_profiles(cfg)
    assert p["profile"]["thinking"]["plan"] == "off" and p["profile"]["thinking"]["reroute"] == "on"
    cfg.write_text("model_list:\n  - model_name: x\n    litellm_params: {model: m}\n"
                   "    model_info: {location: external, profile: {vision: true}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="로컬 별칭만"):
        load_model_profiles(cfg)


def test_v1_model_profiles_for_modules(client):
    r = client.get("/v1/model-profiles")
    assert r.status_code == 200
    schema_check.validate("openapi/gateway.yaml", "ModelProfiles", r.json())
    assert [p["alias"] for p in r.json()["aliases"]] == [p["alias"] for p in load_model_profiles(CFG)]


def test_ops_models_is_auditor_only(client, auditor, login, staff_no):
    assert client.get("/api/ops/models", headers={"Authorization": f"Bearer {login(staff_no)}"}).status_code == 403
    r = client.get("/api/ops/models", headers=auditor)
    assert r.status_code == 200 and r.json() == client.get("/v1/model-profiles").json()


@pytest.fixture
def profile_app(settings, fake_erp, issuer):
    """LLM_TIMEOUT_SECONDS 없이(프로필을 따르게) 띄웁니다. 받은 요청의 시간 제한을 모읍니다."""
    llm, seen = FakeLiteLLM(), []

    def handler(request):
        seen.append(request.extensions["timeout"]["read"])
        return llm(request)

    app = create_app(dataclasses.replace(settings, llm_timeout_seconds=None), erp_transport=httpx.ASGITransport(app=fake_erp),
                     issuer=issuer, llm_transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        c.app_ref, c.llm, c.timeouts = app, llm, seen
        yield c


def test_timeout_comes_from_alias_profile(profile_app):
    eg = profile_app.app_ref.state.egress
    eg.profiles["local-gguf"]["profile"]["timeoutSeconds"] = 45
    profile_app.post("/v1/chat/completions", json={"model": "local", "messages": HR})
    profile_app.post("/v1/chat/completions", json={"model": "local-gguf", "messages": HR})
    assert profile_app.timeouts == [120.0, 45.0]
    eg._timeout = 7.0                                    # LLM_TIMEOUT_SECONDS가 있으면 모든 별칭을 덮어씀
    assert eg.timeout_for("local-gguf") == 7.0


@pytest.mark.parametrize("reroute,sent,note", [("default", None, None), ("off", "none", "생각 단계 끔(reasoning_effort=none)"),
                                               ("on", "low", "생각 단계 켬(reasoning_effort=low)")])
def test_reroute_thinking_comes_from_profile(profile_app, reroute, sent, note):
    from gateway.registry import Requester

    app = profile_app.app_ref
    app.state.egress.profiles["local"]["profile"]["thinking"]["reroute"] = reroute
    ext = next(a for a in app.state.registry.all() if a.model_policy.get("mode") == "external_allowed")
    tok = app.state.issuer.issue(Requester("E0001", "u", "staff", ("employee",), ()), ext, "conv-p").token
    r = profile_app.post("/v1/chat/completions", headers={"X-Delegation-Token": tok}, json={"model": "external", "messages": HR})
    assert r.status_code == 200
    body = json.loads(profile_app.llm.requests[-1].content)
    assert body["model"] == "local" and body.get("reasoning_effort") == sent
    detail = [e for e in app.state.audit.events.read_all() if e["kind"] == "llm.request"][-1].get("detail") or ""
    assert (note in detail) if note else ("생각 단계" not in detail)
