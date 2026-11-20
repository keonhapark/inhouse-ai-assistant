from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from tests.llm_cassette import Cassette

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "packs" / "manufacturing"
CONTRACTS = ROOT / "contracts"
RECORDINGS = Path(__file__).parent / "recordings"

RECORDED_MODEL = "qwen3.5:9b"


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load(PACK_DIR)


@pytest.fixture
def employee() -> Requester:
    return Requester("E0016", "finance", "staff", ("employee",))


@pytest.fixture(scope="session")
def router_cassette() -> Iterator[Cassette]:
    cassette = Cassette.from_env(RECORDINGS / "router_llm.json")
    yield cassette
    cassette.save()


@pytest.fixture(scope="session")
def recorded_chat(router_cassette: Cassette) -> ChatClient:
    if router_cassette.record:
        settings = LLMSettings.from_env()
    else:
        settings = LLMSettings(base_url="http://recorded.invalid/v1", model=os.environ.get("AGENT_LLM_MODEL", RECORDED_MODEL))
    return ChatClient(settings, transport=router_cassette)


@pytest.fixture
def stub_chat() -> Callable[[Callable[[httpx.Request], httpx.Response]], ChatClient]:
    def make(handler: Callable[[httpx.Request], httpx.Response]) -> ChatClient:
        settings = LLMSettings(base_url="http://stub.invalid/v1", model="stub")
        return ChatClient(settings, transport=httpx.MockTransport(handler))

    return make


def content_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]})
