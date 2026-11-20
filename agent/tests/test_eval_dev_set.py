"""개발 묶음(eval_dev/tool_calls.jsonl)이 확인 묶음과 같은 형식(#103 리드 코멘트)이고 팩·도구 계약과 맞는지 봅니다."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import jsonschema

from agent_runtime.registry import Registry
from tests.conftest import CONTRACTS, PACK_DIR

DEV_SET = Path(__file__).resolve().parents[1] / "eval_dev" / "tool_calls.jsonl"
FREE_TEXT = {"reason", "title", "purpose", "question", "q"}
WHY = {"ambiguous_date", "same_name", "missing_field"}


def items() -> list[dict]:
    return [json.loads(line) for line in DEV_SET.read_text("utf-8").splitlines() if line.strip()]


def test_dev_set_follows_format_and_contracts() -> None:
    reg = Registry.load(PACK_DIR, stage=2)
    tools = {t["name"]: t for t in json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))["tools"]}
    raw = json.loads((PACK_DIR / "fixtures" / "employees.json").read_text("utf-8"))
    employees = {e["id"] for e in (raw.get("employees", raw) if isinstance(raw, dict) else raw)}
    data = items()
    assert len(data) == 60
    assert len({i["id"] for i in data}) == 60 and len({(i["agentId"], i["message"]) for i in data}) == 60
    for it in data:
        assert set(it) == {"id", "agentId", "requester", "today", "message", "expect", "tags"}, it["id"]
        assert reg.has(it["agentId"]) and it["requester"] in employees, it["id"]
        date.fromisoformat(it["today"])
        exp = it["expect"]
        if "tool" in exp:
            assert set(exp) == {"tool", "arguments"}
            name = exp["tool"]
            assert name in reg.get(it["agentId"]).tools, it["id"]
            args = exp["arguments"]
            assert not FREE_TEXT & set(args), it["id"]
            schema = tools[name]["inputSchema"]
            # 자유 문장 필수 인자는 적지 않으므로 채워서 스키마를 봅니다.
            filled = {**{k: "x" for k in schema.get("required", []) if k in FREE_TEXT}, **args}
            jsonschema.validate(filled, schema, format_checker=jsonschema.FormatChecker())
            assert set(schema.get("required", [])) - FREE_TEXT <= set(args), it["id"]
        elif "ask" in exp:
            assert exp == {"ask": True, "why": exp["why"]} and exp["why"] in WHY, it["id"]
        else:
            assert exp == {"refuse": True}, it["id"]


def test_purchase_total_is_quantity_times_price() -> None:
    for it in items():
        if it["expect"].get("tool") == "purchase_request":
            a = it["expect"]["arguments"]
            assert a["total_amount"] == a["quantity"] * a["unit_price"], it["id"]


def test_dev_set_covers_every_agent_and_kind() -> None:
    data = items()
    kinds = Counter("tool" if "tool" in i["expect"] else next(iter(i["expect"])) for i in data)
    assert kinds["ask"] >= 8 and kinds["refuse"] >= 6
    assert {i["agentId"] for i in data} == {"assistant", "hr", "finance", "procurement"}
