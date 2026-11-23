"""모델 프로필(#601, 결정 0009): gateway /v1/model-profiles에서 계획·이미지 읽기 생각 단계와 시간 제한을 읽습니다."""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import httpx
import jsonschema
import pytest
import yaml

from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.profiles import FALLBACK, ProfileCache, RunProfile, StaticProfile, read_profile, with_env
from agent_runtime.registry import Requester
from agent_runtime.run.graph import build_graph
from agent_runtime.run.image_reading import ImageReader, ImageSpec, FieldSpec
from tests.conftest import CONTRACTS
from tests.mcp_support import mint
from tests.run_support import RunHarness, make_run_harness, say
from tests.test_plan_reasoning import _deps

ROOT = CONTRACTS.parent
ME = Requester("E0016", "finance", "staff", ("employee",))


PURPOSES = ("plan", "reroute", "imageRead", "ragAnswer", "incident")


def gateway_body() -> dict:
    """gateway/litellm/config.yaml의 model_info.profile로 만든 응답. 빠진 값은 gateway(#595 profiles.py)와 같은 기본값
    (thinking default, timeoutSeconds 120, structuredOutput true, vision false)으로 채웁니다."""
    cfg = yaml.safe_load((ROOT / "gateway" / "litellm" / "config.yaml").read_text("utf-8"))
    out = []
    for m in cfg["model_list"]:
        info = m.get("model_info") or {}
        p = info.get("profile") or {}
        thinking = {k: p.get("thinking", {}).get(k, "default") for k in PURPOSES}
        out.append({"alias": m["model_name"], "location": info["location"], "model": m["litellm_params"]["model"],
                    "evalOnly": bool(info.get("evalOnly", False)),
                    "profile": {"thinking": thinking, "timeoutSeconds": p.get("timeoutSeconds", 120),
                                "structuredOutput": bool(p.get("structuredOutput", True)),
                                "vision": bool(p.get("vision", False))}})
    return {"aliases": out}


def transport(body: dict | None = None, status: int = 200, calls: list | None = None) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req.url.path)
        return httpx.Response(status, json=body or {})
    return httpx.MockTransport(handler)


def test_qwen_profile_keeps_current_behavior() -> None:
    body = gateway_body()
    spec = yaml.safe_load((CONTRACTS / "openapi" / "gateway.yaml").read_text("utf-8"))
    jsonschema.validate(body, {**spec["components"]["schemas"]["ModelProfiles"], "components": spec["components"]})
    p = read_profile("http://gw/v1", transport(body))
    # 결정 0008(계획 생각 켬=모델 기본), 이미지 읽기 생각 끔, 120초: 프로필 전과 같음
    assert (p.plan_effort, p.image_effort, p.timeout_s, p.source) == (None, "none", 120.0, "profile")
    assert (FALLBACK.plan_effort, FALLBACK.image_effort, FALLBACK.timeout_s) == (None, "none", 120.0)


def test_env_overrides_only_when_set() -> None:
    p = RunProfile(None, "none", 120.0, "profile")
    assert with_env(p, {}) == p
    q = with_env(p, {"AGENT_PLAN_REASONING_EFFORT": "none", "AGENT_LLM_TIMEOUT_S": "60"})
    assert (q.plan_effort, q.timeout_s, q.source) == ("none", 60.0, "profile+env")


def test_profile_on_off_maps_to_effort() -> None:
    body = gateway_body()
    local = next(a for a in body["aliases"] if a["alias"] == "local")
    local["profile"]["thinking"]["plan"] = "on"
    local["profile"]["timeoutSeconds"] = 90
    p = read_profile("http://gw/v1", transport(body))
    assert (p.plan_effort, p.timeout_s) == ("low", 90.0)


def test_cache_falls_back_then_retries_until_read() -> None:
    calls: list[str] = []
    bad = ProfileCache("http://gw/v1", env={}, transport=transport(status=404, calls=calls))
    assert bad.get() == FALLBACK and bad.get() == FALLBACK
    assert calls == ["/v1/model-profiles", "/v1/model-profiles"]  # 못 읽으면 다음에 다시 읽음
    calls.clear()
    good = ProfileCache("http://gw/v1", env={}, transport=transport(gateway_body(), calls=calls))
    good.get()
    good.get()
    assert calls == ["/v1/model-profiles"]  # 읽은 뒤에는 다시 부르지 않음


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(("agent", "extra"), [("hr", {"reasoning_effort": "low"}), ("assistant", None)])
async def test_plan_call_uses_profile_for_local(tmp_path: Path, agent: str, extra) -> None:
    r: RunHarness = make_run_harness(tmp_path)
    prof = StaticProfile(RunProfile("low", "none", 120.0, "profile"), env={})
    r.runner.graph = build_graph(dataclasses.replace(_deps(r), profile=prof))
    r.llm.script = [say("네.")]
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    await r.runner.run(mint(agent=agent, cid=conv), conv, agent, "연차 며칠 남았어?", ME, "full", None)
    assert r.llm.requests[0]["extra"] == extra  # external_allowed(assistant)에는 보내지 않음


@pytest.mark.anyio
@pytest.mark.parametrize(("image_effort", "sent"), [("none", "none"), (None, None)])
async def test_image_read_uses_profile(image_effort, sent) -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": '{"x": "1"}'}}]})

    chat = ChatClient(LLMSettings(base_url="http://gw/v1", model="local"), transport=httpx.MockTransport(handler))
    reader = ImageReader(chat, profile=StaticProfile(RunProfile(None, image_effort, 120.0, "profile"), env={}))
    await reader.read("data:image/png;base64,AA==", "t", ImageSpec("사진", (FieldSpec("x", "string", "값"),)))
    assert seen[0].get("reasoning_effort") == sent


def test_chat_timeout_from_profile() -> None:
    seen: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.extensions["timeout"]["read"])
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "네"}}]})

    chat = ChatClient(LLMSettings(base_url="http://gw/v1", model="local", timeout_s=120),
                      transport=httpx.MockTransport(handler), timeout_source=lambda: 45.0)
    chat.complete([{"role": "user", "content": "x"}])
    assert seen == [45.0]
