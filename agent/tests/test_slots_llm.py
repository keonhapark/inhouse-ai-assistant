"""LLM 슬롯 채우기는 각본 LLM으로 형식만 시험합니다(모델 품질은 평가가 봅니다)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from agent_runtime.baseline.__main__ import main
from agent_runtime.baseline.llm_filler import SLOT_TOOLS, LlmSlotFiller, load_slot_tools
from agent_runtime.llm import LLMError
from tests.conftest import CONTRACTS
from tests.run_support import ScriptedLLM, call, say

TOOLS = load_slot_tools(CONTRACTS / "mcp" / "tools.json")
TODAY = date(2027, 3, 2)


def test_slot_tools_come_from_contract() -> None:
    assert sorted(t["name"] for t in TOOLS) == sorted(SLOT_TOOLS)


def test_llm_fill_returns_same_shape_as_rule() -> None:
    llm = ScriptedLLM([call("leave_request", {"leave_type": "annual", "start_date": "2027-03-05",
                                              "end_date": "2027-03-05"})])
    r = LlmSlotFiller(llm, TOOLS).fill("금요일 연차", TODAY, [{"id": "room-a", "name": "회의실 A"}])
    assert (r.intent, r.tool, r.missing) == ("leave", "leave_request", ("reason",))
    req = llm.requests[0]
    assert "2027-03-02(화)" in req["messages"][0]["content"] and "회의실 A(id room-a)" in req["messages"][0]["content"]
    assert sorted(t["function"]["name"] for t in req["tools"]) == sorted(SLOT_TOOLS)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (say("무엇을 도와드릴까요?"), (None, None, ())),
        (call("delegation_register", {}), (None, None, ())),
        (LLMError("x"), (None, None, ("llm_error",))),
    ],
)
def test_llm_fill_edge_cases(reply, expected) -> None:
    r = LlmSlotFiller(ScriptedLLM([reply]), TOOLS).fill("x", TODAY)
    assert (r.intent, r.tool, r.missing) == expected


def test_llm_fill_bad_arguments() -> None:
    bad = call("room_reserve", {})
    bad["tool_calls"][0]["function"]["arguments"] = "{oops"
    r = LlmSlotFiller(ScriptedLLM([bad]), TOOLS).fill("x", TODAY)
    assert (r.tool, r.missing) == ("room_reserve", ("arguments",))


def test_cli_rule(capsys, tmp_path) -> None:
    rooms = tmp_path / "rooms.json"
    rooms.write_text(json.dumps({"rooms": [{"id": "room-b", "name": "회의실 B"}]}), "utf-8")
    assert main(["--today", "2027-03-02", "--rooms", str(rooms), "금요일 연차", "내일 3시 회의실 B 예약"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [(x["method"], x["tool"]) for x in lines] == [("rule", "leave_request"), ("rule", "room_reserve")]
    assert lines[1]["arguments"]["roomId"] == "room-b"


# ---- POST /baseline/slots(contracts/openapi/agent.yaml) ----


def _client(tmp_path, llm=None):
    from fastapi.testclient import TestClient

    from agent_runtime.app import Services, create_app, load_rooms
    from agent_runtime.audit import AuditLog
    from agent_runtime.baseline.slots import RuleSlotFiller
    from agent_runtime.registry import Registry
    from agent_runtime.router import Router
    from tests.conftest import PACK_DIR

    reg = Registry.load(PACK_DIR)
    fillers = {"rule": RuleSlotFiller()}
    if llm is not None:
        fillers["llm"] = LlmSlotFiller(llm, TOOLS)
    svc = Services(reg, Router(reg, None), AuditLog(tmp_path / "a.jsonl"), None, fillers, load_rooms(PACK_DIR))
    return TestClient(create_app(svc))


def _response_schema() -> dict:
    import yaml

    spec = yaml.safe_load((CONTRACTS / "openapi" / "agent.yaml").read_text("utf-8"))
    return spec["paths"]["/baseline/slots"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]


def test_endpoint_rule_uses_pack_rooms(tmp_path) -> None:
    import jsonschema

    from agent_runtime.app import load_rooms
    from tests.conftest import PACK_DIR

    room = load_rooms(PACK_DIR)[0]
    c = _client(tmp_path)
    r = c.post("/baseline/slots", json={"message": f"내일 오후 3시 {room['name']} 예약해 줘", "today": "2027-03-02",
                                        "method": "rule"})
    assert r.status_code == 200
    body = r.json()
    jsonschema.validate(body, _response_schema())
    assert body["tool"] == "room_reserve" and body["arguments"]["roomId"] == room["id"]
    assert body["arguments"]["startsAt"] == "2027-03-03T15:00:00+09:00"


def test_endpoint_llm(tmp_path) -> None:
    import jsonschema

    llm = ScriptedLLM([call("room_list_availability", {"startsAt": "2027-03-03T15:00:00+09:00",
                                                       "endsAt": "2027-03-03T16:00:00+09:00"})])
    body = _client(tmp_path, llm).post("/baseline/slots", json={"message": "내일 3시 빈 회의실", "method": "llm",
                                                                "today": "2027-03-02"}).json()
    jsonschema.validate(body, _response_schema())
    assert body["intent"] == "room" and body["missing"] == []


def test_endpoint_validation_and_unconfigured(tmp_path) -> None:
    c = _client(tmp_path)
    assert c.post("/baseline/slots", json={"message": "x"}).status_code == 422
    assert c.post("/baseline/slots", json={"message": "x", "method": "regex"}).status_code == 422
    assert c.post("/baseline/slots", json={"message": "x", "method": "rule", "today": "내일"}).status_code == 422
    assert c.post("/baseline/slots", json={"message": "x", "method": "llm"}).status_code == 503
    assert c.post("/baseline/slots", json={"message": "점심 뭐 먹지", "method": "rule"}).json() == \
        {"intent": None, "tool": None, "arguments": {}, "missing": []}


@pytest.mark.parametrize("raw", ["null", "[1]", '"x"'])
def test_llm_non_object_arguments(raw: str) -> None:
    bad = call("leave_request", {})
    bad["tool_calls"][0]["function"]["arguments"] = raw
    r = LlmSlotFiller(ScriptedLLM([bad]), TOOLS).fill("x", TODAY)
    assert (r.arguments, r.missing) == ({}, ("arguments",))
