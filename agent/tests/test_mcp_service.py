"""MCP 도구 호출을 가짜 erp로 시험합니다(도구별, 막는 규칙, 감사 기록)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from agent_runtime.mcp_server.service import CallMeta
from tests.conftest import CONTRACTS
from tests.mcp_support import OTHER_PRIVATE_KEY, Harness, future_slot, future_weekday, make_harness, mint

AUDIT_SCHEMA = json.loads((CONTRACTS / "events" / "audit.schema.json").read_text("utf-8"))
USER = CallMeta(trust_level="user_direct")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return make_harness(tmp_path)


def _key() -> str:
    import uuid
    return f"idem-{uuid.uuid4().hex}"


def execute(**kw) -> CallMeta:
    return CallMeta(trust_level="user_direct", idempotency_key=_key(), **kw)


# ---- 읽기 도구 ----

READS = [
    ("hr_get_my_profile", "hr", {}, "id"),
    ("org_search_employees", "hr", {"q": "김"}, "items"),
    ("leave_get_balance", "hr", {}, None),
    ("approval_list_mine", "hr", {}, "items"),
    ("approval_list_mine", "hr", {"status": "in_progress"}, "items"),
    ("delegation_list", "hr", {"role": "delegator"}, "items"),
    ("room_list_my_reservations", "assistant", {}, "items"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "agent", "args", "key"), READS)
async def test_read_tools(h: Harness, tool: str, agent: str, args: dict, key: str | None) -> None:
    r = await h.service.call(tool, args, mint(agent=agent), CallMeta())
    assert r.ok, r.problem
    if key:
        assert key in r.data


@pytest.mark.anyio
async def test_room_availability(h: Harness) -> None:
    s, e = future_slot()
    r = await h.service.call("room_list_availability", {"startsAt": s, "endsAt": e, "minCapacity": 4},
                             mint(agent="assistant"), CallMeta())
    assert r.ok, r.problem
    assert all(room["capacity"] >= 4 for room in r.data["items"])


@pytest.mark.anyio
async def test_policy_search_passes_token_only_as_rag_header(h: Harness) -> None:
    token = mint(agent="assistant")
    r = await h.service.call("policy_search", {"question": "출장비 규정"}, token, CallMeta())
    assert r.ok
    [req] = h.rag.calls
    assert req.url.path == "/answer"
    assert req.headers["x-delegation-token"] == token
    assert "authorization" not in req.headers
    assert json.loads(req.content) == {"question": "출장비 규정"}


# ---- 쓰기 도구: 미리보기와 실행 ----


@pytest.mark.anyio
async def test_leave_request_preview_then_execute_then_withdraw(h: Harness) -> None:
    token = mint()
    day = future_weekday()
    args = {"leave_type": "annual", "start_date": day, "end_date": day, "reason": "개인 사정"}

    preview = await h.service.call("leave_request", args, token, CallMeta(trust_level="user_direct", dry_run=True))
    assert preview.ok, preview.problem
    assert preview.data["dryRun"] is True
    assert preview.data["operation"] == "createApprovalDocument"

    done = await h.service.call("leave_request", args, token, execute())
    assert done.ok, done.problem
    doc_id = done.data["resource"]["id"]
    assert done.data["resource"]["formId"] == "leave"
    assert done.data["undoable"] is True

    got = await h.service.call("approval_get", {"documentId": doc_id}, token, CallMeta())
    assert got.ok and got.data["fields"]["leave_type"] == "annual"

    withdrawn = await h.service.call("approval_withdraw", {"documentId": doc_id, "reason": "일정 변경"}, token, execute())
    assert withdrawn.ok, withdrawn.problem
    assert withdrawn.data["undoable"] is False

    called = [e for e in h.events() if e["kind"] == "tool.called"]
    assert called[1]["actionId"] == done.data["actionId"]
    assert called[0]["detail"] == "dryRun" and called[0]["actionId"] is None


@pytest.mark.anyio
async def test_write_without_idempotency_key_is_refused_by_erp(h: Harness) -> None:
    day = future_weekday()
    args = {"leave_type": "annual", "start_date": day, "end_date": day, "reason": "x"}
    r = await h.service.call("leave_request", args, mint(), USER)
    assert not r.ok
    assert r.problem["type"] == "urn:problem:idempotency-key-required"


@pytest.mark.anyio
async def test_room_reserve_and_cancel(h: Harness) -> None:
    token = mint(agent="assistant")
    s, e = future_slot()
    r = await h.service.call("room_reserve", {"roomId": "room-b", "startsAt": s, "endsAt": e, "title": "주간 회의",
                                              "attendees": 4}, token, execute())
    assert r.ok, r.problem
    res_id = r.data["resource"]["id"]
    mine = await h.service.call("room_list_my_reservations", {}, token, CallMeta())
    assert res_id in [x["id"] for x in mine.data["items"]]
    c = await h.service.call("room_cancel_reservation", {"reservationId": res_id}, token, execute())
    assert c.ok, c.problem


@pytest.mark.anyio
async def test_room_conflict_is_reported_as_conflict(h: Harness) -> None:
    token = mint(agent="assistant")
    s, e = future_slot()
    args = {"roomId": "room-a", "startsAt": s, "endsAt": e, "title": "회의"}
    assert (await h.service.call("room_reserve", args, token, execute())).ok
    again = await h.service.call("room_reserve", args, token, execute())
    assert not again.ok and again.problem["type"] == "urn:problem:room-conflict"
    assert h.events()[-1]["result"] == "conflict"


@pytest.mark.anyio
async def test_delegation_register_nests_scope_and_revoke(h: Harness) -> None:
    from datetime import datetime, timedelta

    from tests.mcp_support import KST

    token = mint(employee="E0016")
    start = datetime.now(KST) + timedelta(days=1)
    args = {"delegateId": "E0017", "startsAt": start.isoformat(), "endsAt": (start + timedelta(days=2)).isoformat(),
            "formTypes": ["leave"], "maxAmount": None, "reason": "출장"}
    r = await h.service.call("delegation_register", args, token, execute())
    assert r.ok, r.problem
    assert r.data["resource"]["scope"]["formTypes"] == ["leave"]
    rv = await h.service.call("delegation_revoke", {"delegationId": r.data["resource"]["id"]}, token, execute())
    assert rv.ok, rv.problem


# ---- 막는 규칙 ----


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("token", "code"),
    [
        (None, "unauthorized"),
        (mint(ttl=-60), "unauthorized"),
        (mint(aud=["erp"]), "unauthorized"),
        (mint(key=OTHER_PRIVATE_KEY), "unauthorized"),
        ("not-a-jwt", "unauthorized"),
        (mint(tools=["hr_get_my_profile"]), "tool-not-allowed"),
        # 토큰 tools에 있어도 토큰 에이전트의 등록부에 없으면 거절
        (mint(agent="assistant", tools=["leave_get_balance"]), "tool-not-allowed"),
        (mint(agent="nobody", tools=["leave_get_balance"]), "tool-not-allowed"),
    ],
    ids=["none", "expired", "no-mcp-aud", "wrong-key", "garbage", "not-in-token", "not-in-agent", "unknown-agent"],
)
async def test_blocked_token_cases(h: Harness, token: str | None, code: str) -> None:
    r = await h.service.call("leave_get_balance", {}, token, CallMeta())
    assert not r.ok
    assert r.problem["type"] == f"urn:problem:{code}"
    [event] = h.events()
    assert event["kind"] == "tool.blocked" and event["result"] == "denied"


@pytest.mark.anyio
async def test_unknown_or_unexposed_tool(h: Harness) -> None:
    for name in ["approval_approve", "drop_tables"]:
        r = await h.service.call(name, {}, mint(), CallMeta())
        assert r.problem["type"] == "urn:problem:unknown-tool"


@pytest.mark.anyio
@pytest.mark.parametrize("trust", [None, "trusted", "untrusted"])
async def test_user_direct_tool_needs_user_direct_trust(h: Harness, trust: str | None) -> None:
    day = future_weekday()
    args = {"leave_type": "annual", "start_date": day, "end_date": day, "reason": "x"}
    r = await h.service.call("leave_request", args, mint(), CallMeta(trust_level=trust, dry_run=True))
    assert r.problem["type"] == "urn:problem:trust-required"


@pytest.mark.anyio
async def test_any_trust_tool_runs_with_untrusted_input(h: Harness) -> None:
    r = await h.service.call("leave_get_balance", {}, mint(), CallMeta(trust_level="untrusted"))
    assert r.ok


@pytest.mark.anyio
@pytest.mark.parametrize(
    "args",
    [
        {"leave_type": "vacation", "start_date": "2027-01-04", "end_date": "2027-01-04", "reason": "x"},
        {"leave_type": "annual", "start_date": "내일", "end_date": "2027-01-04", "reason": "x"},
        {"leave_type": "annual", "start_date": "2027-01-04", "end_date": "2027-01-04"},
        {"leave_type": "annual", "start_date": "2027-01-04", "end_date": "2027-01-04", "reason": "x", "formId": "expense"},
    ],
    ids=["enum", "format", "required", "extra"],
)
async def test_input_schema_is_enforced(h: Harness, args: dict) -> None:
    r = await h.service.call("leave_request", args, mint(), CallMeta(trust_level="user_direct", dry_run=True))
    assert r.problem["type"] == "urn:problem:validation"
    assert h.events()[-1]["result"] == "error"


@pytest.mark.anyio
async def test_path_argument_cannot_escape(h: Harness) -> None:
    r = await h.service.call("approval_get", {"documentId": "../../audit-events"}, mint(), CallMeta())
    assert r.problem["type"] == "urn:problem:validation"


@pytest.mark.anyio
async def test_erp_scope_check_is_passed_through(h: Harness) -> None:
    r = await h.service.call("leave_get_balance", {}, mint(scopes=["profile:read"]), CallMeta())
    assert r.problem["type"] == "urn:problem:scope-missing"
    assert h.events()[-1]["result"] == "denied"


# ---- 감사 기록 ----


@pytest.mark.anyio
async def test_audit_events_match_schema_and_hold_no_token_or_args(h: Harness) -> None:
    token = mint(cid="cnv_audit")
    await h.service.call("org_search_employees", {"q": "비밀검색어"}, token, CallMeta(trust_level="trusted"))
    await h.service.call("leave_request", {}, token, CallMeta())
    raw = h.audit_path.read_text("utf-8")
    assert token not in raw and "비밀검색어" not in raw
    events = h.events()
    for e in events:
        jsonschema.validate(e, AUDIT_SCHEMA, format_checker=jsonschema.FormatChecker())
    ok, blocked = events
    assert ok["kind"] == "tool.called" and ok["result"] == "ok"
    assert ok["source"] == "mcp" and ok["conversationId"] == "cnv_audit"
    assert ok["actor"] == {"employeeId": "E0016", "viaDelegationToken": True, "agentId": "hr"}
    assert ok["riskLevel"] == "read" and ok["trustLevel"] == "trusted"
    assert ok["argsHash"].startswith("sha256:")
    assert blocked["kind"] == "tool.blocked" and blocked["problemType"] == "urn:problem:trust-required"


def test_visible_tools_follow_token(h: Harness) -> None:
    all_names = {t.name for t in h.service.visible_tools(None)}
    assert {t.name for t in h.service.visible_tools(mint(agent="assistant"))} < all_names
    assert [t.name for t in h.service.visible_tools(mint(tools=["leave_get_balance"]))] == ["leave_get_balance"]
