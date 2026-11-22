from __future__ import annotations

import pytest

from agent_runtime.llm import LLMSettings


def test_default_backend_is_gateway() -> None:
    # compose처럼 LOCAL_MODEL이 있어도 gateway에는 별칭을 보냅니다(#89).
    s = LLMSettings.from_env({"PORT_GATEWAY": "8310", "LOCAL_MODEL": "qwen3.5:9b"})
    assert s.base_url == "http://localhost:8310/v1"
    assert s.model == "local"
    assert s.extra_body == {}


def test_gateway_base_url_override() -> None:
    s = LLMSettings.from_env({"GATEWAY_LLM_URL": "http://gw:8000/v1/", "AGENT_LLM_MODEL": "local"})
    assert (s.base_url, s.model) == ("http://gw:8000/v1", "local")


def test_ollama_dev_backend() -> None:
    s = LLMSettings.from_env({"AGENT_LLM_BACKEND": "ollama", "LOCAL_MODEL": "m"})
    assert s.base_url == "http://localhost:11434/v1"
    assert s.model == "m"
    assert s.extra_body == {}  # 결정 0008: 생각 단계는 모델 기본(켬)
    off = LLMSettings.from_env({"AGENT_LLM_BACKEND": "ollama", "AGENT_PLAN_REASONING_EFFORT": "none"})
    assert off.extra_body == {"reasoning_effort": "none"}


def test_timeout_default_is_120s() -> None:
    # 생각을 켠 로컬 계획 호출(결정 0008, #535)
    assert LLMSettings.from_env({}).timeout_s == 120
    assert LLMSettings.from_env({"AGENT_LLM_BACKEND": "ollama"}).timeout_s == 120
    assert LLMSettings.from_env({"AGENT_LLM_TIMEOUT_S": "30"}).timeout_s == 30


def test_unknown_backend() -> None:
    with pytest.raises(ValueError):
        LLMSettings.from_env({"AGENT_LLM_BACKEND": "openai"})


def test_gateway_alias_is_one_the_gateway_knows() -> None:
    import yaml

    from agent_runtime.llm import GATEWAY_DEFAULT_ALIAS
    from tests.conftest import ROOT

    cfg = yaml.safe_load((ROOT / "gateway" / "litellm" / "config.yaml").read_text("utf-8"))
    local = {m["model_name"] for m in cfg["model_list"] if (m.get("model_info") or {}).get("location") == "local"}
    assert GATEWAY_DEFAULT_ALIAS in local


def test_request_body_fields_are_accepted_by_gateway() -> None:
    """gateway 출구가 받는 필드(gateway/gateway/egress.py ALLOWED_FIELDS) 밖의 필드를 보내지 않습니다."""
    import json

    import httpx

    from agent_runtime.llm import ChatClient

    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    allowed = {"model", "messages", "stream", "stream_options", "temperature", "top_p", "max_tokens",
               "max_completion_tokens", "stop", "seed", "presence_penalty", "frequency_penalty", "tools",
               "tool_choice", "parallel_tool_calls", "response_format", "think", "reasoning_effort"}
    for env in ({}, {"AGENT_LLM_BACKEND": "ollama"}):
        c = ChatClient(LLMSettings.from_env(env), transport=httpx.MockTransport(handler))
        c.chat([{"role": "user", "content": "x"}], tools=[{"type": "function", "function": {"name": "f"}}])
    assert all(set(b) <= allowed for b in seen)


# ---- 에이전트 정책별 출구 별칭(#124) ----


def _sent_models(settings, **chat_kw) -> list[str]:
    import json

    import httpx

    from agent_runtime.llm import ChatClient

    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content)["model"])
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    ChatClient(settings, transport=httpx.MockTransport(handler)).chat([{"role": "user", "content": "x"}], **chat_kw)
    return seen


@pytest.mark.parametrize(("policy", "alias"), [("external_allowed", "external"), ("local_only", "local"),
                                               (None, "local"), ("unknown", "local")])
def test_gateway_alias_follows_agent_policy(policy, alias) -> None:
    assert _sent_models(LLMSettings.from_env({}), model_policy=policy) == [alias]


def test_policy_aliases_exist_in_gateway_config() -> None:
    import yaml

    from agent_runtime.llm import POLICY_ALIASES
    from tests.conftest import ROOT

    cfg = yaml.safe_load((ROOT / "gateway" / "litellm" / "config.yaml").read_text("utf-8"))
    loc = {m["model_name"]: (m.get("model_info") or {}).get("location") for m in cfg["model_list"]}
    assert loc[POLICY_ALIASES["external_allowed"]] == "external"
    assert loc[POLICY_ALIASES["local_only"]] == "local"


def test_ollama_backend_ignores_policy() -> None:
    s = LLMSettings.from_env({"AGENT_LLM_BACKEND": "ollama", "LOCAL_MODEL": "m"})
    assert _sent_models(s, model_policy="external_allowed") == ["m"]


def test_registry_policies_are_known() -> None:
    from agent_runtime.llm import POLICY_ALIASES
    from agent_runtime.registry import Registry
    from tests.conftest import PACK_DIR

    assert {a.model_policy for a in Registry.load(PACK_DIR).agents} <= set(POLICY_ALIASES)
