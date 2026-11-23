"""답 생성이 gateway 모델 프로필에서 생각 단계·시간 제한을 읽는지(#602, 결정 0009)."""

import json

import httpx
import pytest

from rag.answer import GatewayChat
from rag.profile import FALLBACK, ProfileCache, profile_url, resolve, with_env

URL = "http://gw:8000/v1"


def profiles(thinking="off", seconds=120, alias="local"):
    return {"aliases": [
        {"alias": "other", "location": "local", "model": "x", "evalOnly": False,
         "profile": {"thinking": {"ragAnswer": "on"}, "timeoutSeconds": 5, "structuredOutput": True, "vision": False}},
        {"alias": alias, "location": "local", "model": "ollama_chat/qwen3.5:9b", "evalOnly": False,
         "profile": {"thinking": {"plan": "default", "reroute": "default", "imageRead": "off", "ragAnswer": thinking,
                                  "incident": "off"},
                     "timeoutSeconds": seconds, "structuredOutput": True, "vision": False}},
    ]}


def gateway(profile_body=None, status=200, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        if request.url.path == "/v1/model-profiles":
            if profile_body is None:
                return httpx.Response(status)
            return httpx.Response(status, json=profile_body)
        body = json.loads(request.content)
        handler.sent.append((body, request.extensions.get("timeout")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    handler.sent = []
    return handler


def test_프로필_주소는_gateway_v1_주소에서_만든다():
    assert profile_url("http://gw:8000/v1") == "http://gw:8000/v1/model-profiles"
    assert profile_url("http://gw:8000/v1/") == "http://gw:8000/v1/model-profiles"
    assert profile_url("http://gw:8000") == "http://gw:8000/v1/model-profiles"


@pytest.mark.parametrize("thinking,effort", [("off", "none"), ("on", "low"), ("default", None)])
def test_프로필의_ragAnswer가_reasoning_effort가_된다(thinking, effort):
    s = resolve(URL, "local", {}, httpx.MockTransport(gateway(profiles(thinking, 45))))
    assert s.reasoning_effort == effort and s.timeout_s == 45.0 and s.source == "profile"
    assert s.model == "ollama_chat/qwen3.5:9b"


def test_Qwen_프로필은_지금_동작과_같다():
    """결정 0008: ragAnswer off, 120초. 프로필 전 동작은 reasoning_effort none, 120초였습니다."""
    handler = gateway(profiles("off", 120))
    chat = GatewayChat(URL, "local", settings=ProfileCache(URL, "local", {}, httpx.MockTransport(handler)).get,
                       transport=httpx.MockTransport(handler))
    chat.complete([{"role": "user", "content": "q"}], "tok")
    body, timeout = handler.sent[0]
    assert body["reasoning_effort"] == "none" and body["temperature"] == 0 and body["model"] == "local"
    assert timeout["read"] == 120.0


def test_default면_reasoning_effort를_보내지_않는다():
    handler = gateway(profiles("default", 60))
    chat = GatewayChat(URL, "local", settings=ProfileCache(URL, "local", {}, httpx.MockTransport(handler)).get,
                       transport=httpx.MockTransport(handler))
    chat.complete([], "tok")
    body, timeout = handler.sent[0]
    assert "reasoning_effort" not in body and timeout["read"] == 60.0


def test_부르는_별칭의_프로필을_읽는다():
    s = resolve(URL, "other", {}, httpx.MockTransport(gateway(profiles())))
    assert s.reasoning_effort == "low" and s.timeout_s == 5.0


@pytest.mark.parametrize("env,effort", [({"RAG_LLM_REASONING": "on"}, "low"), ({"RAG_LLM_REASONING": "off"}, "none"),
                                        ({"RAG_LLM_REASONING": "default"}, None), ({"RAG_LLM_REASONING": "high"}, "high"),
                                        ({"RAG_LLM_REASONING": "none"}, "none")])
def test_RAG_LLM_REASONING은_프로필을_덮어쓴다(env, effort):
    s = resolve(URL, "local", env, httpx.MockTransport(gateway(profiles("on", 120))))
    assert s.reasoning_effort == effort and s.source == ("profile+env" if effort != "low" else "profile")


def test_환경_변수가_비어_있으면_덮지_않는다():
    s = resolve(URL, "local", {"RAG_LLM_REASONING": " ", "RAG_LLM_TIMEOUT_SECONDS": ""},
                httpx.MockTransport(gateway(profiles("on", 90))))
    assert s.reasoning_effort == "low" and s.timeout_s == 90.0 and s.source == "profile"


def test_시간_제한_덮어쓰기():
    s = resolve(URL, "local", {"RAG_LLM_TIMEOUT_SECONDS": "30"}, httpx.MockTransport(gateway(profiles())))
    assert s.timeout_s == 30.0 and s.source == "profile+env"


@pytest.mark.parametrize("env", [{"RAG_LLM_REASONING": "maybe"}, {"RAG_LLM_TIMEOUT_SECONDS": "0"},
                                 {"RAG_LLM_TIMEOUT_SECONDS": "abc"}])
def test_틀린_덮어쓰기_값은_알린다(env):
    with pytest.raises(ValueError):
        with_env(FALLBACK, env)


@pytest.mark.parametrize("make", [
    lambda: gateway(None, 404),
    lambda: gateway({"aliases": []}),
    lambda: gateway({"aliases": [{"alias": "local", "profile": {"thinking": {"ragAnswer": "maybe"},
                                                                  "timeoutSeconds": 10}}]}),
    lambda: gateway({"nope": 1}),
])
def test_프로필을_못_읽으면_프로필_전_동작으로_부른다(make):
    s = resolve(URL, "local", {}, httpx.MockTransport(make()))
    assert s == FALLBACK and (s.reasoning_effort, s.timeout_s) == ("none", 120.0)


def test_연결이_안_되어도_프로필_전_동작이다():
    def boom(request):
        raise httpx.ConnectError("x")

    assert resolve(URL, "local", {}, httpx.MockTransport(boom)) == FALLBACK


def test_못_읽으면_다음_호출에서_다시_읽고_읽은_뒤에는_다시_읽지_않는다():
    calls: list[str] = []
    state = {"up": False}

    def handler(request):
        calls.append(request.url.path)
        if not state["up"]:
            return httpx.Response(503)
        return httpx.Response(200, json=profiles("on", 77))

    cache = ProfileCache(URL, "local", {}, httpx.MockTransport(handler))
    assert cache.get().source == "fallback"
    state["up"] = True
    assert cache.get().timeout_s == 77.0
    assert cache.get().reasoning_effort == "low"
    assert calls == ["/v1/model-profiles"] * 2  # 실패 1회 + 성공 1회, 이후는 읽어 둔 값
