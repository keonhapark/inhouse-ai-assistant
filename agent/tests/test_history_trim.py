"""#423: 여러 턴 대화의 입력 줄이기. 최근 사용자 턴만 남기고 이전 턴의 긴 도구 출력은 줄입니다."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from agent_runtime.registry import Requester
from agent_runtime.run.graph import PRIOR_TOOL_MAX_CHARS, PRIOR_TURNS_KEEP, UNTRUSTED_NOTE, prepare_history
from tests.mcp_support import mint
from tests.run_support import RunHarness, call, make_run_harness, say

ME = Requester("E0016", "finance", "staff", ("employee",))


def turn(i: int, tool_len: int = 100) -> list[dict]:
    cid = f"c{i}"
    return [{"role": "user", "content": f"요청 {i}"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function",
                                                                "function": {"name": "approval_list_mine",
                                                                             "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": cid, "content": "x" * tool_len},
            {"role": "assistant", "content": f"답 {i}"}]


def test_keeps_recent_turns_from_a_user_message() -> None:
    history = [m for i in range(10) for m in turn(i)]
    out = prepare_history(history)
    users = [m["content"] for m in out if m["role"] == "user"]
    assert users == [f"요청 {i}" for i in range(10 - PRIOR_TURNS_KEEP, 10)]
    assert out[0]["role"] == "user"
    calls = {c["id"] for m in out if m["role"] == "assistant" for c in m.get("tool_calls") or []}
    answers = {m["tool_call_id"] for m in out if m["role"] == "tool"}
    assert calls == answers  # 짝이 깨지지 않음


def test_short_history_is_untouched() -> None:
    history = [m for i in range(3) for m in turn(i)]
    assert prepare_history(history) == history


def test_long_prior_tool_output_is_cut() -> None:
    out = prepare_history(turn(0, tool_len=10_000))
    tool = next(m for m in out if m["role"] == "tool")
    assert len(tool["content"]) < PRIOR_TOOL_MAX_CHARS + 60 and "전체 10000자" in tool["content"]


def test_attachment_note_does_not_count_as_a_turn() -> None:
    history = []
    for i in range(PRIOR_TURNS_KEEP + 1):
        history += [{"role": "user", "content": f"요청 {i}"}, {"role": "user", "content": f"{UNTRUSTED_NOTE}\n[첨부 영수증 1장]"},
                    {"role": "assistant", "content": f"답 {i}"}]
    out = prepare_history(history)
    assert out[0] == {"role": "user", "content": "요청 1"}  # 안내 메시지에서 끊기지 않음


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_long_conversation_input_stays_bounded(tmp_path: Path) -> None:
    r: RunHarness = make_run_harness(tmp_path)
    conv = f"cnv_{uuid.uuid4().hex[:8]}"
    token = mint(agent="hr", cid=conv)
    sizes = []
    for i in range(12):
        r.llm.script = [call("approval_list_mine", {}, f"c{i}"), say(f"답 {i}")]
        await r.runner.run(token, conv, "hr", f"내 결재 목록 보여 줘 {i}", ME)
        sizes.append(len(json.dumps(r.llm.requests[-2]["messages"], ensure_ascii=False)))
    users = [m for m in r.llm.requests[-2]["messages"] if m["role"] == "user"]
    assert len(users) == PRIOR_TURNS_KEEP + 1  # 이전 6턴 + 이번 턴
    assert sizes[-1] <= sizes[PRIOR_TURNS_KEEP + 1] * 1.1  # 턴이 늘어도 입력 크기가 더 늘지 않음
