from __future__ import annotations

import pytest

from agent_runtime.registry import Registry
from agent_runtime.run.policy import ToolMeta, WideScope, decide, visible_to_model
from agent_runtime.run.trust import output_trusted, trusted_docs
from tests.conftest import PACK_DIR

READ = ToolMeta("leave_get_balance", "read", "any")
LEAVE = ToolMeta("leave_request", "reversible_write", "user_direct")
WITHDRAW = ToolMeta("approval_withdraw", "irreversible", "user_direct")
DLG = ToolMeta("delegation_register", "reversible_write", "user_direct")
ROOM = ToolMeta("room_reserve", "reversible_write", "user_direct")
WIDE = WideScope.from_pack(PACK_DIR)


def narrow_dlg(**kw):
    args = {"startsAt": "2027-03-08T00:00:00+09:00", "endsAt": "2027-03-10T00:00:00+09:00",
            "formTypes": ["leave"], "maxAmount": 500000}
    return {**args, **kw}


@pytest.fixture(scope="module")
def hr(registry: Registry):
    return registry.get("hr")


@pytest.fixture(scope="module")
def assistant(registry: Registry):
    return registry.get("assistant")


def test_wide_scope_is_read_from_pack() -> None:
    assert WIDE == WideScope(7, 1000000, True)


@pytest.mark.parametrize(
    ("args", "wide"),
    [
        (narrow_dlg(), False),
        (narrow_dlg(endsAt="2027-03-16T00:00:00+09:00"), True),  # 8일
        (narrow_dlg(maxAmount=2000000), True),
        (narrow_dlg(maxAmount=None), True),  # 한도 없음
        (narrow_dlg(formTypes=["*"]), True),
        ({"formTypes": ["leave"]}, True),  # 판단할 수 없으면 넓게
    ],
)
def test_wide_scope(args, wide: bool) -> None:
    assert WIDE.is_wide(args) is wide


@pytest.mark.parametrize(
    ("tool", "args", "action"),
    [
        (READ, {}, "auto"),
        (LEAVE, {}, "auto_with_undo"),
        (WITHDRAW, {}, "confirm"),
        (DLG, narrow_dlg(), "auto_with_undo"),
        (DLG, narrow_dlg(maxAmount=None), "confirm"),
    ],
)
def test_full_condition_follows_agent_risk_policy(hr, tool, args, action) -> None:
    assert decide(hr, tool, args, "full", False, WIDE).action == action


def test_risk_outside_allowed_risk_is_denied(assistant) -> None:
    # assistant의 allowed_risk에는 irreversible이 없습니다. 등록부에 있는 도구라고 가정해도 막힙니다.
    tool = ToolMeta("room_reserve", "irreversible", "user_direct")
    assert decide(assistant, tool, {}, "full", False, WIDE).action == "deny"


def test_tool_outside_agent_is_blocked(assistant) -> None:
    assert decide(assistant, LEAVE, {}, "full", False, WIDE).action == "blocked"
    assert decide(assistant, LEAVE, {}, "no_guard", False, WIDE).action == "blocked"


def test_taint_blocks_user_direct_tools_only_in_full(hr) -> None:
    assert decide(hr, LEAVE, {}, "full", True, WIDE).action == "blocked"
    assert decide(hr, READ, {}, "full", True, WIDE).action == "auto"
    assert decide(hr, LEAVE, {}, "approve_all", True, WIDE).action == "confirm"
    assert decide(hr, LEAVE, {}, "no_guard", True, WIDE).action == "auto"


def test_conversation_taint_turns_user_direct_into_confirm(hr) -> None:
    """앞 턴에서 신뢰 불가 출력을 읽은 대화: user_direct 도구는 바로 실행하지 않고 승인을 받습니다."""
    assert decide(hr, DLG, narrow_dlg(), "full", False, WIDE, True).action == "confirm"
    assert decide(hr, LEAVE, {}, "full", False, WIDE, True).action == "confirm"
    assert decide(hr, WITHDRAW, {}, "full", False, WIDE, True).action == "confirm"
    assert decide(hr, READ, {}, "full", False, WIDE, True).action == "auto"
    # 넓은 범위 대결(override=confirm)은 그대로 확인입니다.
    wide = narrow_dlg(endsAt="2027-04-30T00:00:00+09:00")
    assert decide(hr, DLG, wide, "full", False, WIDE, True).action == "confirm"
    assert decide(hr, DLG, narrow_dlg(), "full", False, WIDE, True).undo_note is True
    # 같은 턴의 신뢰 불가 출력은 여전히 막습니다.
    assert decide(hr, DLG, narrow_dlg(), "full", True, WIDE, True).action == "blocked"
    # 신뢰 등급은 full에서만 씁니다.
    assert decide(hr, LEAVE, {}, "no_guard", False, WIDE, True).action == "auto"


def test_conversation_taint_keeps_deny(assistant) -> None:
    # 금지는 확인으로 풀리지 않습니다.
    tool = ToolMeta("room_reserve", "irreversible", "user_direct")
    assert decide(assistant, tool, {}, "full", False, WIDE, True).action == "deny"


@pytest.mark.parametrize(
    ("condition", "read", "write"),
    [
        ("no_guard", "auto", "auto"),
        ("write_blocked", "auto", "blocked"),
        ("approve_all", "auto", "confirm"),
        ("baseline_tools", "auto", "confirm"),
        ("full", "auto", "auto_with_undo"),
    ],
)
def test_conditions(hr, condition: str, read: str, write: str) -> None:
    assert decide(hr, READ, {}, condition, False, WIDE).action == read
    assert decide(hr, LEAVE, {}, condition, False, WIDE).action == write


def test_unknown_condition(hr) -> None:
    with pytest.raises(ValueError):
        decide(hr, READ, {}, "magic", False, WIDE)


def test_write_blocked_hides_writes() -> None:
    assert visible_to_model(READ, "write_blocked") and not visible_to_model(LEAVE, "write_blocked")
    assert visible_to_model(LEAVE, "full")


# ---- 출력 신뢰 등급 ----

DOCS = trusted_docs(PACK_DIR)


def test_trusted_docs_from_pack() -> None:
    assert DOCS and all(isinstance(x, str) for x in DOCS)


@pytest.mark.parametrize(
    ("data", "trusted"),
    [
        ({"found": True, "citations": []}, True),
        ({"citations": [{"docId": "law-travel-expense"}]}, True),
        ({"citations": [{"docId": "law-travel-expense"}, {"docId": "injected-1"}]}, False),
    ],
)
def test_rag_trust(data, trusted: bool) -> None:
    assert output_trusted("rag", data, "E1", DOCS) is trusted


@pytest.mark.parametrize(
    ("data", "trusted"),
    [
        ({"total": 15, "used": 3}, True),
        ({"items": [{"id": "D1", "requesterId": "E1", "title": "연차"}]}, True),
        ({"items": [{"id": "G1", "delegatorId": "E2", "delegateId": "E1", "reason": "지시문"}]}, False),
        ({"items": [{"id": "G1", "delegatorId": "E1", "registeredBy": "E9", "reason": "출장"}]}, False),
        ({"items": [{"id": "X", "comment": "누가 썼는지 모름"}]}, False),
        ({"items": [{"name": "김", "unitId": "hr"}]}, True),
        ({"doc": {"requesterId": "E1", "title": "내 글", "line": [{"approverId": "E2", "comment": "반려 사유"}]}}, False),
    ],
)
def test_erp_trust(data, trusted: bool) -> None:
    assert output_trusted("erp", data, "E1", DOCS) is trusted


@pytest.mark.parametrize(
    ("text", "asks"),
    [("며칠인가요?", True), ("날짜를 알려 주세요.", True), ("올릴까요", True), ("확인해 주시겠어요?", True),
     ("연차를 올렸습니다.", False), ("", False), ("12일 남았습니다!", False)],
)
def test_asks_user(text: str, asks: bool) -> None:
    from agent_runtime.run.graph import asks_user

    assert asks_user(text) is asks


def test_nested_object_inherits_author() -> None:
    doc = {"items": [{"id": "D1", "requesterId": "E1", "fields": {"reason": "개인 사정"}}]}
    assert output_trusted("erp", doc, "E1", DOCS) is True
    assert output_trusted("erp", doc, "E2", DOCS) is False


EXPENSE = ToolMeta("expense_request", "reversible_write", "user_direct")
PURCHASE = ToolMeta("purchase_request", "reversible_write", "user_direct")


@pytest.fixture(scope="module")
def reg2() -> Registry:
    return Registry.load(PACK_DIR, stage=2)


@pytest.mark.parametrize(
    ("agent", "tool", "args", "action"),
    [
        ("finance", EXPENSE, {"amount": 1000000}, "auto_with_undo"),  # 같음은 넘지 않음
        ("finance", EXPENSE, {"amount": 1000001}, "confirm"),
        ("finance", EXPENSE, {"amount": 42000}, "auto_with_undo"),
        ("finance", EXPENSE, {"amount": 1000000.5}, "confirm"),
        ("finance", EXPENSE, {}, "confirm"),  # 인자가 없으면 엄격하게
        ("finance", EXPENSE, {"amount": "1000"}, "confirm"),  # 숫자가 아니면 엄격하게
        ("finance", EXPENSE, {"amount": True}, "confirm"),
        ("finance", EXPENSE, {"amount": None}, "confirm"),
        ("procurement", PURCHASE, {"total_amount": 5000000}, "auto_with_undo"),
        ("procurement", PURCHASE, {"total_amount": 5000001}, "confirm"),
        ("procurement", PURCHASE, {"total_amount": 700000}, "auto_with_undo"),
    ],
)
def test_amount_override(reg2: Registry, agent, tool, args, action) -> None:
    assert decide(reg2.get(agent), tool, args, "full", False, WIDE).action == action


def test_amount_override_only_in_full(reg2: Registry) -> None:
    fin = reg2.get("finance")
    assert decide(fin, EXPENSE, {"amount": 5000000}, "no_guard", False, WIDE).action == "auto"
    assert decide(fin, EXPENSE, {"amount": 10}, "approve_all", False, WIDE).action == "confirm"
