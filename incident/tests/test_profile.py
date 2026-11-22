"""장애 분석 호출의 생각 단계·시간 제한을 gateway 모델 프로필에서 읽습니다(결정 0009, #603)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from incident.llm import FALLBACK, CallSettings, ProfileCache, analyze, resolve, with_env

# 계약 ModelProfile 모양. Qwen3.5-9B 값은 결정 0008 그대로: plan·reroute default, imageRead·ragAnswer·incident off, 120초
QWEN = {"alias": "local", "location": "local", "model": "ollama_chat/qwen3.5:9b", "evalOnly": False,
        "profile": {"thinking": {"plan": "default", "reroute": "default", "imageRead": "off", "ragAnswer": "off",
                                 "incident": "off"},
                    "timeoutSeconds": 120, "structuredOutput": True, "vision": False}}
ANSWER = '{"candidates": [{"service": "rag", "kind": "data_corruption", "reason": "r", "evidence": []}]}'


def gateway(profiles: dict[str, Any] | None, seen: list[dict[str, Any]] | None = None,
            calls: list[str] | None = None) -> httpx.MockTransport:
    """profiles가 None이면 프로필 경로가 없는 gateway(404)입니다. 채팅 요청의 본문과 시간 제한을 seen에 남깁니다."""
    def h(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v1/model-profiles":
            return httpx.Response(404) if profiles is None else httpx.Response(200, json=profiles)
        if seen is not None:
            seen.append({"body": json.loads(request.content), "timeout": request.extensions["timeout"]["read"]})
        return httpx.Response(200, json={"choices": [{"message": {"content": ANSWER}}]})
    return httpx.MockTransport(h)


def with_thinking(value: str, alias: str = "local") -> dict[str, Any]:
    entry = json.loads(json.dumps(QWEN))
    entry["alias"] = alias
    entry["profile"]["thinking"]["incident"] = value
    return {"aliases": [entry]}


def test_qwen_profile_keeps_thinking_off_and_uses_profile_timeout() -> None:
    seen: list[dict[str, Any]] = []
    t = gateway({"aliases": [QWEN]}, seen)
    s = resolve("http://gw", env={}, transport=t)
    assert s == CallSettings("off", 120.0, "profile", "ollama_chat/qwen3.5:9b")
    analyze("http://gw", "진단", settings=s, transport=t)
    assert seen[0]["body"]["reasoning_effort"] == "none"  # 프로필 전과 같음
    assert seen[0]["timeout"] == 120.0


@pytest.mark.parametrize(("value", "effort"), [("on", "low"), ("off", "none"), ("default", None)])
def test_thinking_maps_to_reasoning_effort(value: str, effort: str | None) -> None:
    seen: list[dict[str, Any]] = []
    t = gateway(with_thinking(value), seen)
    analyze("http://gw", "진단", settings=resolve("http://gw", env={}, transport=t), transport=t)
    assert seen[0]["body"].get("reasoning_effort") == effort
    assert ("reasoning_effort" in seen[0]["body"]) is (effort is not None)  # default면 보내지 않음


@pytest.mark.parametrize("profiles", [
    None,  # 프로필 경로가 없는 gateway
    {"aliases": []},  # local 별칭 없음
    with_thinking("maybe"),  # 계약 밖 값
    {"unexpected": True},
])
def test_without_profile_behaves_as_before(profiles: dict[str, Any] | None) -> None:
    seen: list[dict[str, Any]] = []
    t = gateway(profiles, seen)
    s = resolve("http://gw", env={}, transport=t)
    assert s == FALLBACK
    analyze("http://gw", "진단", settings=s, transport=t)
    assert seen[0]["body"]["reasoning_effort"] == "none" and seen[0]["timeout"] == 90.0


def test_env_overrides_only_when_set() -> None:
    base = CallSettings("off", 120.0, "profile", "m")
    assert with_env(base, {}) == base
    assert with_env(base, {"INCIDENT_LLM_THINKING": "", "INCIDENT_LLM_TIMEOUT_SECONDS": " "}) == base
    assert with_env(base, {"INCIDENT_LLM_THINKING": "On", "INCIDENT_LLM_TIMEOUT_SECONDS": "30"}) == \
        CallSettings("on", 30.0, "profile+env", "m")
    assert with_env(FALLBACK, {"INCIDENT_LLM_TIMEOUT_SECONDS": "60"}).source == "fallback+env"
    with pytest.raises(ValueError):
        with_env(base, {"INCIDENT_LLM_THINKING": "high"})
    with pytest.raises(ValueError):
        with_env(base, {"INCIDENT_LLM_TIMEOUT_SECONDS": "0"})


def test_cache_retries_until_profile_is_read_then_keeps_it() -> None:
    state: dict[str, Any] = {"profiles": None}
    calls: list[str] = []

    def h(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        p = state["profiles"]
        return httpx.Response(404) if p is None else httpx.Response(200, json=p)

    cache = ProfileCache("http://gw", env={}, transport=httpx.MockTransport(h))
    assert cache.get() == FALLBACK  # gateway에 아직 프로필 경로 없음
    state["profiles"] = {"aliases": [QWEN]}
    assert cache.get().source == "profile"  # 다시 읽음
    assert cache.get().timeout_s == 120.0
    assert calls == ["/v1/model-profiles", "/v1/model-profiles"]  # 읽은 뒤에는 다시 부르지 않음


def test_app_uses_profile_for_llm_call() -> None:
    from tests.test_app import KEY, Logs, erp, token

    from incident.app import TokenVerifier, create_app

    seen: list[dict[str, Any]] = []
    t = gateway(with_thinking("on"), seen)
    app = create_app(Logs(), TokenVerifier(key=KEY.public_key()), "http://erp/api/v1", "http://gw",
                     erp_transport=erp(True), llm_transport=t, profiles=ProfileCache("http://gw", env={}, transport=t))
    r = TestClient(app).post("/analyze", json={"ticketId": "tkt_1", "windowSeconds": 120},
                             headers={"X-Delegation-Token": token()})
    assert r.status_code == 200 and r.json()["method"] == "llm", r.text
    assert seen[0]["body"]["reasoning_effort"] == "low" and seen[0]["timeout"] == 120.0
