from __future__ import annotations

import pytest

from agent_runtime.llm import LLMSettings


def test_default_backend_is_gateway() -> None:
    s = LLMSettings.from_env({"PORT_GATEWAY": "8310"})
    assert s.base_url == "http://localhost:8310/v1"
    assert s.model == "qwen3.5:9b"
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
