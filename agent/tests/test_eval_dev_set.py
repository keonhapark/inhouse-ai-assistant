"""개발 묶음(eval_dev/tool_calls.jsonl)이 toolcall-v1 형식(contracts/eval/toolcall)이고 팩·도구 계약과 맞는지 봅니다."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import jsonschema

from agent_runtime.registry import Registry
from tests.conftest import CONTRACTS, PACK_DIR

DEV_SET = Path(__file__).resolve().parents[1] / "eval_dev" / "tool_calls.jsonl"
ITEM_SCHEMA = json.loads((CONTRACTS / "eval" / "toolcall" / "item.schema.json").read_text("utf-8"))
TOOLS = {t["name"]: t for t in json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))["tools"]}
WEEKDAYS = "월화수목금토일"


def items() -> list[dict]:
    return [json.loads(line) for line in DEV_SET.read_text("utf-8").splitlines() if line.strip()]


def actions(it: dict) -> list[dict]:
    return [it["expected"], *it.get("alsoAcceptable", [])]


def test_dev_set_follows_item_schema_and_contracts() -> None:
    reg = Registry.load(PACK_DIR, stage=2)
    raw = json.loads((PACK_DIR / "fixtures" / "employees.json").read_text("utf-8"))
    employees = {e["id"] for e in (raw.get("employees", raw) if isinstance(raw, dict) else raw)}
    stage_tools = {t for a in reg.agents for t in a.tools}
    data = items()
    assert len(data) == 60
    assert len({i["id"] for i in data}) == 60 and len({i["utterance"] for i in data}) == 60
    for it in data:
        jsonschema.validate(it, ITEM_SCHEMA)
        # 확인 묶음(tc-001~tc-120)과 번호가 겹치지 않게 9xx를 씁니다.
        assert it["id"] >= "tc-900", it["id"]
        assert it["requester"] in employees and it["targetTool"] in stage_tools, it["id"]
        assert WEEKDAYS[date.fromisoformat(it["referenceDate"]).weekday()] == it["referenceWeekday"], it["id"]
        for act in actions(it):
            if act["type"] == "call":
                schema = TOOLS[act["tool"]]["inputSchema"]
                jsonschema.validate(act["args"], schema, format_checker=jsonschema.FormatChecker())
                assert set(schema.get("required", [])) <= set(act["args"]), it["id"]
            else:
                props = TOOLS[it["targetTool"]]["inputSchema"].get("properties", {})
                assert set(act["missing"]) <= set(props), it["id"]
        assert set(it.get("argMatch", {})) <= set(it["expected"].get("args", {})), it["id"]


def test_purchase_total_is_quantity_times_price() -> None:
    for it in items():
        if it["expected"].get("tool") == "purchase_request":
            a = it["expected"]["args"]
            assert a["total_amount"] == a["quantity"] * a["unit_price"], it["id"]


def test_dev_set_covers_categories_and_agents() -> None:
    data = items()
    cats = Counter(i["category"] for i in data)
    assert set(cats) == {"direct", "clarify", "confusable", "resolve"} and cats["clarify"] >= 8
    reg = Registry.load(PACK_DIR, stage=2)
    owners = {a.id for a in reg.agents for i in data if i["targetTool"] in a.tools}
    # it_ops는 policy_search로만 걸립니다(티켓 도구 항목은 아직 없음).
    assert owners == {"assistant", "hr", "finance", "procurement", "it_ops"}
