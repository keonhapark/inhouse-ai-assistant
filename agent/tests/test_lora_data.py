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
    # 저장소 밖 평가 묶음 경로는 남기지 않고 이름·해시·문장 수만
    assert [e["name"] for e in manifest["excluded"]] == ["tool_calls.jsonl"]
    assert str(tmp_path) not in json.dumps(manifest)


def test_exclude_drops_exact_and_near_duplicates(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.jsonl"
    bundle.write_text(json.dumps({"utterance": "연차 며칠 남았어?"}, ensure_ascii=False) + "\n" +
                      json.dumps({"utterance": "남은 휴가 일수 알려 줘"}, ensure_ascii=False) + "\n", "utf-8")
    ex = gen.Excluded([bundle])
    assert ex.hit("연차 며칠 남았어 ?")                 # 띄어쓰기·문장부호만 다름 → 정확 일치
    assert ex.hit("남은 휴가 일수 알려 주세요")          # 말끝만 다름 → 근접 중복
    assert not ex.hit("결재 doc-1234 회수해 줘")
    assert ex.dropped == {"exact": 1, "near": 1, "skeleton": 0}
    rows = gen.generate(PACK_DIR, per_tool=12, seed=3, excluded=gen.Excluded([gen.DEV_SET, bundle]))
    texts = [r["messages"][1]["content"] for r in rows]
    assert not [t for t in texts if gen._norm(t) in {gen._norm("연차 며칠 남았어?"), gen._norm("남은 휴가 일수 알려 줘")}]


def test_exclude_drops_value_only_variants(tmp_path: Path) -> None:
    # #653 검수에서 남던 문장: 개발 묶음 문장을 ID·말끝만 바꾼 것. 문장 틀 기준으로 거릅니다
    bundle = tmp_path / "bundle.jsonl"
    bundle.write_text("".join(json.dumps({"id": f"t{i}", "utterance": u}, ensure_ascii=False) + "\n" for i, u in enumerate(
        ["결재 doc-1077 회수해 줘", "rsv-0042 취소해 줘", "내가 다른 사람한테 맡긴 대결 목록 보여 줘"])), "utf-8")
    ex = gen.Excluded([bundle])
    assert ex.hit("결재 doc-6617 회수해 줘")
    assert ex.hit("rsv-7131 취소해 주세요")
    assert ex.hit("내가 다른 사람한테 넘긴 대결 목록 보여 주세요")
    assert not ex.hit("내일 오후 3시부터 한 시간 회의실 잡아 줘")
    assert ex.dropped["skeleton"] == 3


def test_exclude_reads_scenario_yaml(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text(
        "scenarios:\n- id: N-1\n  turns:\n  - {role: user, content: 결재 doc-1077 회수해 줘}\n"
        "  expect: {requiredTools: [approval_withdraw]}\n", "utf-8")
    ex = gen.Excluded([tmp_path])  # 폴더째
    assert ex.hit("결재 doc-2222 회수 부탁해요")


def test_no_near_duplicate_of_dev_set(rows: list[dict]) -> None:
    dev = gen.Excluded([gen.DEV_SET])
    assert not [r["messages"][1]["content"] for r in rows if dev.hit(r["messages"][1]["content"])]


def test_clarify_text_particle() -> None:
    assert gen.clarify_text(["사유"]) == "사유를 알려 주세요."
    assert gen.clarify_text(["날짜", "시간"]) == "날짜, 시간을 알려 주세요."


def test_particles_follow_final_sound() -> None:
    assert gen.ira("출장") == "출장이라" and gen.ira("휴가") == "휴가라"
    assert gen.euro("결혼") == "결혼으로" and gen.euro("이사") == "이사로" and gen.euro("야근 식대") == "야근 식대로"
    assert gen.euro("택배 발송") == "택배 발송으로" and gen.euro("회의실 A") == "회의실 A로"
    assert gen.ieyo("감기 몸살") == "감기 몸살이에요" and gen.ieyo("두통") == "두통이에요"


def test_utterances_are_varied(rows: list[dict]) -> None:
    texts = [r["messages"][1]["content"] for r in rows]
    assert len(set(texts)) >= 0.95 * len(texts)
    assert not [t for t in texts if "부탁부탁" in t or "?." in t or "  " in t]
