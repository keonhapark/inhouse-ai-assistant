"""평가 경로 POST /eval/tool-call(#103). 각본 gateway(MockTransport)로 요청 본문과 응답 형식을 봅니다."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient

from agent_runtime.app import Services, create_app
from agent_runtime.audit import AuditLog
from agent_runtime.evaluation.tool_call import (EvalToolCaller, bigrams, filter_tools, load_examples,
                                                load_tools)
from agent_runtime.llm import POLICY_ALIASES, ChatClient, LLMSettings
from agent_runtime.registry import Registry
from agent_runtime.router import Router
from agent_runtime.run.graph import system_prompt
from agent_runtime.registry import Requester
from tests.conftest import CONTRACTS, PACK_DIR
from tests.mcp_support import mint
from tests.run_support import FIXED_NOW, make_run_harness

AGENT_DIR = Path(__file__).resolve().parents[1]
DEV_SET = AGENT_DIR / "eval_dev" / "tool_calls.jsonl"
SPEC = yaml.safe_load((CONTRACTS / "openapi" / "agent.yaml").read_text("utf-8"))
RESULT_SCHEMA = SPEC["components"]["schemas"]["ToolCallResult"]
EMPLOYEE = {"employeeId": "E0016", "unitId": "finance", "grade": "staff", "roles": ["employee"]}
TOOLS = load_tools(CONTRACTS / "mcp" / "tools.json")
LEAVE = {"leave_type": "annual", "start_date": "2026-11-23", "end_date": "2026-11-23", "reason": "개인 사정"}


def tool_reply(name: str, args: Any, content: str = "") -> dict:
    raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": name, "arguments": raw}}]}


def text_reply(content: str) -> dict:
    return {"role": "assistant", "content": content}


class Gateway:
    """각본대로 답하는 gateway. 받은 본문은 bodies에 남깁니다."""

    def __init__(self) -> None:
        self.script: list[httpx.Response | Callable[[dict], httpx.Response]] = []
        self.bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        nxt = self.script.pop(0)
        return nxt(body) if callable(nxt) else nxt


def ok(message: dict, usage: dict | None = None, model: str = "local", location: str = "local") -> httpx.Response:
    data: dict[str, Any] = {"choices": [{"index": 0, "message": message}]}
    if usage is not None:
        data["usage"] = usage
    return httpx.Response(200, json=data, headers={"X-Egress-Model": model, "X-Egress-Location": location})


@pytest.fixture
def reg2() -> Registry:
    return Registry.load(PACK_DIR, stage=2)


@pytest.fixture
def gw() -> Gateway:
    return Gateway()


def make_client(reg: Registry, gw: Gateway, tmp_path: Path, enabled: bool = True,
                examples: list[dict] | None = None) -> TestClient:
    settings = LLMSettings(base_url="http://gw.invalid/v1", model="local", policy_aliases=dict(POLICY_ALIASES))
    chat = ChatClient(settings, transport=httpx.MockTransport(gw.handler))
    evaluator = None
    if enabled:
        evaluator = EvalToolCaller(reg, chat, TOOLS, load_examples(DEV_SET) if examples is None else examples)
    svc = Services(reg, Router(reg, chat), AuditLog(tmp_path / "audit.jsonl"), eval_tool_call=evaluator)
    return TestClient(create_app(svc))


@pytest.fixture
def client(reg2: Registry, gw: Gateway, tmp_path: Path) -> TestClient:
    return make_client(reg2, gw, tmp_path)


def post(client: TestClient, message: str = "다음 주 월요일 연차 쓸게요", agent: str = "hr", **kw: Any) -> httpx.Response:
    body = {"message": message, "agentId": agent, "requester": EMPLOYEE, "today": "2026-11-20", **kw}
    return client.post("/eval/tool-call", json=body)


# ---- 켜기·끄기, 오류 ----


def test_not_found_without_eval_mode(reg2: Registry, gw: Gateway, tmp_path: Path) -> None:
    c = make_client(reg2, gw, tmp_path, enabled=False)
    assert post(c).status_code == 404
    assert gw.bodies == []


def test_unknown_or_disabled_agent_is_400(registry: Registry, gw: Gateway, tmp_path: Path) -> None:
    c = make_client(registry, gw, tmp_path)  # 1단계 등록부에는 finance가 없습니다
    assert post(c, agent="nobody").status_code == 400
    assert post(c, agent="finance").status_code == 400
    assert gw.bodies == []


def test_gateway_failure_is_502(client: TestClient, gw: Gateway) -> None:
    gw.script = [httpx.Response(500, json={"detail": "x"})]
    assert post(client).status_code == 502


def test_request_must_follow_contract(client: TestClient) -> None:
    assert client.post("/eval/tool-call", json={"message": "x", "agentId": "hr"}).status_code == 422
    assert post(client, variant={"toolFilterK": 0}).status_code == 422
    assert post(client, variant={"unknown": True}).status_code == 422


# ---- S0 ----


def test_s0_matches_run_prompt_and_tools(client: TestClient, gw: Gateway, reg2: Registry) -> None:
    gw.script = [ok(tool_reply("leave_request", LEAVE), {"prompt_tokens": 900, "completion_tokens": 40})]
    r = post(client)
    assert r.status_code == 200
    out = r.json()
    jsonschema.validate(out, RESULT_SCHEMA)
    hr = reg2.get("hr")
    assert out["tool"] == "leave_request" and out["arguments"] == LEAVE
    assert out["candidates"] == [t for t in TOOLS if t in hr.tools]  # tools.json(MCP 카탈로그) 순서
    assert out["model"] == {"requested": "local", "egress": "local", "location": "local"}
    assert out["llmCalls"] == 1 and out["usage"] == {"promptTokens": 900, "completionTokens": 40}
    assert out["asked"] is False
    [body] = gw.bodies
    assert body["model"] == "local"  # hr은 local_only
    assert "reasoning_effort" not in body and "response_format" not in body
    today = datetime.fromisoformat("2026-11-20T09:00:00+09:00")
    assert body["messages"][0]["content"] == system_prompt(hr, "full", today, True)
    assert body["messages"][1] == {"role": "user", "content": "다음 주 월요일 연차 쓸게요"}
    assert [t["function"]["name"] for t in body["tools"]] == out["candidates"]
    assert body["tools"][0]["function"]["parameters"] == TOOLS[out["candidates"][0]]["inputSchema"]


def test_model_override_and_policy_default(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("네."), model="external", location="external"),
                 ok(text_reply("네."))]
    out = post(client, model="external").json()
    assert gw.bodies[0]["model"] == "external"
    assert out["model"] == {"requested": "external", "egress": "external", "location": "external"}
    post(client, agent="assistant")
    assert gw.bodies[1]["model"] == "external"  # assistant는 external_allowed


def test_ask_back_and_no_tool(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("어느 날짜에 쓰실 건가요?"))]
    out = post(client, message="연차 쓸게요").json()
    jsonschema.validate(out, RESULT_SCHEMA)
    assert out["tool"] is None and out["arguments"] is None and out["rawArguments"] is None
    assert out["asked"] is True and out["usage"] is None


def test_broken_arguments_are_kept_raw(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("leave_request", '{"leave_type": "annual",'))]
    out = post(client).json()
    assert out["arguments"] is None and out["rawArguments"] == '{"leave_type": "annual",'


def test_unknown_tool_name_is_returned_as_is(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("vacation_apply", {"date": "2026-11-23"}))]
    out = post(client).json()
    assert out["tool"] == "vacation_apply"


def test_requester_who_cannot_call_agent_gets_no_tools(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("인사팀에 문의해 주세요."))]
    body = {"message": "연차 쓸게요", "agentId": "hr", "today": "2026-11-20",
            "requester": {**EMPLOYEE, "roles": []}}
    out = client.post("/eval/tool-call", json=body).json()
    assert out["candidates"] == [] and "tools" not in gw.bodies[0]


# ---- 변형 ----


@pytest.mark.parametrize(("thinking", "effort"), [(True, "low"), (False, "none")])
def test_thinking(client: TestClient, gw: Gateway, thinking: bool, effort: str) -> None:
    gw.script = [ok(text_reply("네."))]
    post(client, variant={"thinking": thinking})
    assert gw.bodies[0]["reasoning_effort"] == effort


def test_grammar_uses_second_call_with_schema(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("leave_request", {"leave_type": "annual"}), {"prompt_tokens": 900, "completion_tokens": 30}),
                 ok(text_reply(json.dumps(LEAVE, ensure_ascii=False)), {"prompt_tokens": 950, "completion_tokens": 50})]
    out = post(client, variant={"grammar": True, "thinking": False}).json()
    jsonschema.validate(out, RESULT_SCHEMA)
    assert out["tool"] == "leave_request" and out["arguments"] == LEAVE
    assert out["llmCalls"] == 2 and out["usage"] == {"promptTokens": 1850, "completionTokens": 80}
    first, second = gw.bodies
    assert "response_format" not in first and "tools" in first
    assert "tools" not in second and second["reasoning_effort"] == "none"
    fmt = second["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["schema"] == TOOLS["leave_request"]["inputSchema"]


def test_grammar_without_tool_call_is_one_call(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("언제 쓰실 건가요?"))]
    out = post(client, variant={"grammar": True}).json()
    assert out["llmCalls"] == 1 and out["asked"] is True


UNSUPPORTED = {"type": "urn:problem:unsupported-parameter", "status": 400}


def test_grammar_unsupported_alias_is_400(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("leave_request", {})), httpx.Response(400, json=UNSUPPORTED)]
    r = post(client, variant={"grammar": True})
    assert r.status_code == 400 and "구조화 출력" in r.json()["detail"]


def test_unsupported_thinking_is_400(client: TestClient, gw: Gateway) -> None:
    gw.script = [httpx.Response(400, json=UNSUPPORTED)]
    assert post(client, variant={"thinking": True}).status_code == 400


def test_other_400_is_upstream_error(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("leave_request", {})), httpx.Response(400, json={"type": "urn:problem:validation"})]
    assert post(client, variant={"grammar": True}).status_code == 502


def test_grammar_takes_egress_from_last_call_and_null_usage_if_missing(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("leave_request", {}), {"prompt_tokens": 1, "completion_tokens": 1},
                    model="external", location="external"),
                 ok(text_reply(json.dumps(LEAVE)), None, model="local-structured", location="local")]
    out = post(client, model="external", variant={"grammar": True}).json()
    assert out["model"] == {"requested": "external", "egress": "local-structured", "location": "local"}
    assert out["usage"] is None and out["llmCalls"] == 2


def test_grammar_with_unknown_tool_is_one_call(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(tool_reply("vacation_apply", {}))]
    out = post(client, variant={"grammar": True}).json()
    assert out["llmCalls"] == 1 and out["tool"] == "vacation_apply"


def test_dict_arguments_are_serialized(client: TestClient, gw: Gateway) -> None:
    msg = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "leave_request", "arguments": LEAVE}}]}
    gw.script = [ok(msg)]
    out = post(client).json()
    assert out["arguments"] == LEAVE and json.loads(out["rawArguments"]) == LEAVE


def test_tool_filter_keeps_k_and_reports_candidates(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("네."))]
    out = post(client, message="다음 주 월요일 휴가 반차 쓸게요", variant={"toolFilterK": 3}).json()
    assert len(out["candidates"]) == 3 and "leave_request" in out["candidates"]
    assert [t["function"]["name"] for t in gw.bodies[0]["tools"]] == out["candidates"]


def test_filter_tools_ties_follow_registry_order() -> None:
    tools = [{"name": n, "description": "같은 설명"} for n in ("a", "b", "c")]
    assert [t["name"] for t in filter_tools("무관한 문장", tools, 2)] == ["a", "b"]
    assert bigrams("연차 신청") == {"연차", "차신", "신청"}


def test_few_shot_adds_examples_but_not_the_same_message(client: TestClient, gw: Gateway) -> None:
    gw.script = [ok(text_reply("네.")), ok(text_reply("네."))]
    examples = load_examples(DEV_SET)
    same = next(e for e in examples if e["expect"]["tool"] == "leave_request")
    post(client, message=same["message"], variant={"fewShot": True})
    prompt = gw.bodies[0]["messages"][0]["content"]
    assert "예시" in prompt and "leave_request" in prompt
    assert f"\"{same['message']}\"" not in prompt
    post(client, message="다른 요청입니다", variant={"fewShot": False})
    assert "예시" not in gw.bodies[1]["messages"][0]["content"]


def test_few_shot_without_examples_is_400(reg2: Registry, gw: Gateway, tmp_path: Path) -> None:
    c = make_client(reg2, gw, tmp_path, examples=[])
    assert post(c, variant={"fewShot": True}).status_code == 400


# ---- S0와 업무 실행의 첫 계획 호출 ----


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("agent", ["hr", "assistant", "finance", "procurement"])
async def test_s0_body_equals_run_first_plan_call(tmp_path: Path, agent: str) -> None:
    """같은 요청을 업무 실행(/run)과 평가 경로(S0)로 보내 모델에 가는 프롬프트·도구가 같은지 봅니다."""
    r = make_run_harness(tmp_path, stage=2)
    r.llm.script = [{"role": "assistant", "content": "네."}]
    conv = "cnv_s0"
    me = Requester("E0016", "finance", "staff", ("employee",))
    await r.runner.run(mint(employee="E0016", agent=agent, cid=conv), conv, agent, "연차 며칠 남았어?", me)
    run_req = r.llm.requests[0]

    gw = Gateway()
    gw.script = [ok(text_reply("네."))]
    c = make_client(Registry.load(PACK_DIR, stage=2), gw, tmp_path)
    post(c, message="연차 며칠 남았어?", agent=agent, today=FIXED_NOW.date().isoformat())
    body = gw.bodies[0]
    assert body["messages"] == run_req["messages"][:1] + [run_req["messages"][-1]]
    assert body["tools"] == run_req["tools"]
