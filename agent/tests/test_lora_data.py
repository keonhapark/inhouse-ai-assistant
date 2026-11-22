"""도구 호출 LoRA 학습 데이터 생성기(#469)."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from agent_runtime.registry import Registry
from agent_runtime.run.graph import system_prompt
from tests.conftest import CONTRACTS, PACK_DIR

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lora"))
import make_toolcall_data as gen  # noqa: E402

TOOLS = {t["name"]: t for t in json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))["tools"]}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return gen.generate(PACK_DIR, per_tool=12, seed=3)


def test_every_tool_maker_produces_examples_of_each_kind(rows: list[dict]) -> None:
    assert {r["tool"] for r in rows} == set(gen.MAKERS)
    assert {r["kind"] for r in rows} == {"direct", "resolve", "clarify"}
    assert len({r["id"] for r in rows}) == len(rows)


def test_calls_follow_tool_contract_and_agent(rows: list[dict]) -> None:
    reg = Registry.load(PACK_DIR, stage=2)
    checker = jsonschema.Draft202012Validator
    for r in rows:
        agent = reg.get(r["agent"])
        offered = [t["function"]["name"] for t in r["tools"]]
        assert offered == [n for n in TOOLS if n in agent.tools and TOOLS[n]["stage"] <= 2]
        reply = r["messages"][-1]
        if r["kind"] == "clarify":
            assert "tool_calls" not in reply and reply["content"].endswith("알려 주세요.")
            continue
        [tc] = reply["tool_calls"]
        name, args = tc["function"]["name"], tc["function"]["arguments"]
        assert name in offered, r["id"]
        checker(TOOLS[name]["inputSchema"], format_checker=checker.FORMAT_CHECKER).validate(args)


def test_system_prompt_is_the_business_prompt(rows: list[dict]) -> None:
    reg = Registry.load(PACK_DIR, stage=2)
    tools = {n: t for n, t in TOOLS.items() if t["stage"] <= 2}
    r = rows[0]
    agent = reg.get(r["agent"])
    today = datetime.fromisoformat(r["today"]).replace(hour=9)
    assert r["messages"][0]["content"] == system_prompt(agent, "full", today, True, list(agent.tools),
                                                        gen.write_optional(agent, tools))


def test_no_dev_set_utterance_and_deterministic(rows: list[dict]) -> None:
    dev = {gen._norm(json.loads(x)["utterance"]) for x in gen.DEV_SET.read_text("utf-8").splitlines() if x.strip()}
    assert not {gen._norm(r["messages"][1]["content"]) for r in rows} & dev
    assert gen.generate(PACK_DIR, per_tool=12, seed=3) == rows
    assert gen.generate(PACK_DIR, per_tool=12, seed=4) != rows


def test_purchase_total_and_dates(rows: list[dict]) -> None:
    for r in rows:
        reply = r["messages"][-1]
        for tc in reply.get("tool_calls", []):
            a = tc["function"]["arguments"]
            if tc["function"]["name"] == "purchase_request":
                assert a["total_amount"] == a["quantity"] * a["unit_price"]
            if tc["function"]["name"] == "leave_request":
                assert a["start_date"] <= a["end_date"]
            if tc["function"]["name"] == "expense_request":
                assert a["spent_on"] < r["today"]  # 지난 지출만


def test_split_is_disjoint_and_cli_writes_files(tmp_path: Path, rows: list[dict]) -> None:
    train, valid = gen.split(rows, 0.2, 3)
    assert len(train) + len(valid) == len(rows) and valid
    assert not {r["id"] for r in train} & {r["id"] for r in valid}
    assert gen.main(["--out", str(tmp_path), "--per-tool", "3", "--seed", "1"]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    lines = (tmp_path / "train.jsonl").read_text("utf-8").splitlines() + \
        (tmp_path / "valid.jsonl").read_text("utf-8").splitlines()
    assert manifest["train"] + manifest["valid"] == len(lines) == 3 * len(gen.MAKERS)


def test_clarify_text_particle() -> None:
    assert gen.clarify_text(["사유"]) == "사유를 알려 주세요."
    assert gen.clarify_text(["날짜", "시간"]) == "날짜, 시간을 알려 주세요."
