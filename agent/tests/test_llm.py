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
    assert s.extra_body == {"reasoning_effort": "none"}


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
