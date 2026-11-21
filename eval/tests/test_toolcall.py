"""도구 호출 채점기(#237): contracts/eval/toolcall/README.md 채점 규칙."""

import json

import pytest

from harness.paths import ROOT
from harness.toolcall import ToolcallError, load_items, match_arg, rescore, run_items, score
from harness.toolcall_report import render, summarize

DEV = ROOT / "agent/eval_dev/tool_calls.jsonl"


def item(**kw):
    base = {"id": "tc-001", "targetTool": "leave_request", "category": "direct", "requester": "E0016",
            "referenceDate": "2027-03-10", "referenceWeekday": "수", "utterance": "3월 15일 연차 쓸게요. 개인 사정",
            "expected": {"type": "call", "tool": "leave_request",
                         "args": {"leave_type": "annual", "start_date": "2027-03-15", "reason": "개인 사정"}},
            "argMatch": {"reason": "nonempty"}}
    return {**base, **kw}


def result(tool=None, arguments=None, asked=False, **kw):
    return {"tool": tool, "arguments": arguments, "rawArguments": json.dumps(arguments) if arguments else None,
            "content": "", "asked": asked, "candidates": [], "model": {"requested": "local", "egress": "x",
                                                                       "location": "local"},
            "latencyMs": 1200, "llmCalls": 1, "usage": None, **kw}


def write_items(tmp_path, rows):
    p = tmp_path / "items.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


def test_dev_bundle_is_valid():
    items = load_items(DEV)
    assert len(items) == 60 and len({i["id"] for i in items}) == 60


def test_load_items_rejects_bad(tmp_path):
    bad = [item(id="tc-1"), item(id="tc-002", expected={"type": "call", "tool": "nope", "args": {}}),
           item(id="tc-003"), item(id="tc-003")]
    with pytest.raises(ToolcallError) as e:
        load_items(write_items(tmp_path, bad))
    text = str(e.value)
    assert "tc-1" in text and "계약에 없는 도구 nope" in text and "겹칩니다" in text


@pytest.mark.parametrize("how, name, want, got, ok", [
    ("exact", "startsAt", "2027-03-15T14:00:00+09:00", "2027-03-15T05:00:00Z", True),
    ("exact", "startsAt", "2027-03-15T14:00:00+09:00", "2027-03-15T15:00:00+09:00", False),
    ("exact", "start_date", "2027-03-15", "2027-03-15", True),
    ("exact", "leave_type", "annual", "half_am", False),
    ("date", "startsAt", "2027-03-15", "2027-03-14T15:00:00Z", True),  # KST로는 3월 15일 0시
    ("date", "endsAt", "2027-03-19", "2027-03-19T23:59:59+09:00", True),
    ("date", "endsAt", "2027-03-19", "2027-03-20T00:00:00+09:00", True),  # 다음 날 0시도 맞음
    ("date", "startsAt", "2027-03-19", "2027-03-20T00:00:00+09:00", False),
    ("date", "endsAt", "2027-03-19", "2027-03-20T09:00:00+09:00", False),
    ("set", "formTypes", ["leave", "expense"], ["expense", "leave"], True),
    ("set", "formTypes", ["leave"], ["leave", "expense"], False),
    ("normalized", "merchant", "Star Bucks", "starbucks", True),
    ("nonempty", "reason", "개인 사정", "가족 일", True),
    ("nonempty", "reason", "개인 사정", " ", False),
    ("nonempty", "reason", "개인 사정", None, False),
    ("ignore", "title", "x", None, True),
])
def test_match_arg(how, name, want, got, ok):
    assert match_arg(how, name, want, got) is ok


def test_score_call_outcomes():
    it = item()
    good = {"leave_type": "annual", "start_date": "2027-03-15", "end_date": "2027-03-15", "reason": "사정"}
    s = score(it, 200, result("leave_request", good))
    assert s.outcome == "correct" and s.passed and s.schema_valid is True
    s = score(it, 200, result("leave_request", {**good, "start_date": "2027-03-16"}))
    assert s.outcome == "wrong_args" and s.mismatched == ["start_date"] and not s.passed
    s = score(it, 200, result("leave_request", None))
    assert s.outcome == "unparsed_args"
    s = score(it, 200, result("room_reserve", {"roomId": "room-a"}))
    assert s.outcome == "wrong_tool" and s.schema_valid is False
    assert score(it, 200, result(None, asked=True)).outcome == "no_call_asked"
    assert score(it, 200, result(None)).outcome == "no_call_answered"
    s = score(it, 502, "gateway 오류")
    assert s.outcome == "error" and s.error == "HTTP 502"


def test_score_alternative_and_confirm_then_proceed():
    it = item(expected={"type": "call", "tool": "approval_withdraw", "args": {"documentId": "D-1"}},
              alsoAcceptable=[{"type": "call", "tool": "approval_list_mine", "args": {}}], targetTool="approval_withdraw")
    assert score(it, 200, result("approval_list_mine", {})).outcome == "alternative"
    # 되돌릴 수 없는 도구는 부르기 전 확인 질문도 맞음(따로 셈)
    s = score(it, 200, result(None, asked=True))
    assert s.outcome == "confirm_then_proceed" and s.passed


def test_score_clarify():
    it = item(expected={"type": "clarify", "missing": ["start_date"]}, category="clarify")
    assert score(it, 200, result(None, asked=True)).outcome == "correct"
    assert score(it, 200, result(None)).outcome == "no_call_answered"
    assert score(it, 200, result("leave_request", {"leave_type": "annual"})).outcome == "called_instead_of_clarify"


def test_fabricated_required_value_counted():
    it = item(expected={"type": "call", "tool": "leave_request", "args": {"leave_type": "annual"}})
    s = score(it, 200, result("leave_request", {"leave_type": "annual", "start_date": "2027-03-15",
                                                "end_date": "2027-03-15", "reason": "건강검진"}))
    # start_date·end_date·reason은 정답에 없고 발화(utterance)에도 그대로 없는 값
    assert s.fabricated == 3


def test_run_items_perfect_agent_and_report():
    items = load_items(DEV)[:6]

    def post(body):
        it = next(i for i in items if i["utterance"] == body["message"])
        e = it["expected"]
        if e["type"] == "clarify":
            return 200, result(None, asked=True)
        return 200, result(e["tool"], dict(e["args"]))

    rows = run_items(items, post, variant={"thinking": False}, model="local", repeats=2)
    assert len(rows) == 12 and all(r["passed"] for r in rows), [(r["id"], r["outcome"], r["mismatched"]) for r in rows]
    assert rows[0]["agentId"] in ("hr", "assistant", "finance", "procurement")
    s = summarize(rows, 2)
    assert s["accuracy"]["n"] == 12 and s["passK"]["n"] == 6 and s["errors"] == 0
    assert [(x["key"], x["rate"]["N"]) for x in s["byLocation"]] == [("local", 12)]
    text = render(rows, {"model": "local", "repeats": 2})
    assert "| 전체(회차 단위) | 12/12" in text and "| pass^2(항목 단위) | 6/6" in text


def test_setup_items_need_erp_and_get_substituted():
    it = item(id="tc-005", setup=[{"as": "E0016", "operation": "createApprovalDocument", "body": {}, "saveAs": "doc"}],
              utterance="${doc} 회수해 줘", targetTool="approval_withdraw",
              expected={"type": "call", "tool": "approval_withdraw", "args": {"documentId": "${doc}"}})
    with pytest.raises(ToolcallError, match="erp가 필요"):
        run_items([it], lambda body: (200, result()))
    seen = []

    def post(body):
        seen.append(body["message"])
        return 200, result("approval_withdraw", {"documentId": "D-77"})

    rows = run_items([it], post, setup=lambda i: {"doc": "D-77"})
    assert seen == ["D-77 회수해 줘"] and rows[0]["outcome"] == "correct"


def test_rescore_uses_current_rules(tmp_path):
    items = [item()]
    rows = [{"id": "tc-001", "repeat": 1, "status": 200,
             "result": result("leave_request", {"leave_type": "annual", "start_date": "2027-03-15", "reason": "x"}),
             "outcome": "wrong_args", "passed": False}]
    out = rescore(items, rows)
    assert out[0]["outcome"] == "correct" and out[0]["passed"]
