"""erp 행동 계약 시험. 가짜와 실제 erp 양쪽에서 통과해야 합니다(기획서 5-3).

미리보기 → 실행 → 되돌리기, 멱등, 409, 결재 대결 규칙(기간 밖, 범위 밖, 해지 뒤, 자기 결재, 재위임, 동시 결재),
동시 예약, 위임 토큰 scope, IT 티켓(보는 사람, 댓글, 상태 변경, 되돌리기).
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import jwt
import pytest

from tests.conftest import SERVICE_LOGIN_SECRET, Api, Org, future_slot, future_weekday, now
from tests.schema_check import validate, validate_file

ERP = "openapi/erp.yaml"


def problem_code(r) -> str:
    assert r.headers["content-type"].startswith("application/problem+json"), r.text
    validate(ERP, "Problem", r.json())
    return r.json()["type"].removeprefix("urn:problem:")


# ---------- 인증·조회 ----------

def test_health_and_login(api: Api, org: Org) -> None:
    assert api.c.get("/health").json() == {"status": "ok"}
    r = api.c.post("/auth/login", json={"employeeNo": org.members("sales")[0], "password": "wrong-password"})
    assert r.status_code == 401
    assert problem_code(r) == "unauthorized"
    me = api.get("/me", org.members("sales")[0]).json()
    validate(ERP, "Employee", me)
    assert "employee" in me["roles"]


def test_unauthenticated_is_401(api: Api) -> None:
    r = api.c.get("/me")
    assert r.status_code == 401
    assert problem_code(r) == "unauthorized"


def test_access_tags_follow_pack_roles(api: Api, org: Org) -> None:
    hr_member = org.members("hr")[0]
    sales_member = org.members("sales")[0]
    hr_tags = api.get("/me/access-tags", hr_member).json()["tags"]
    sales_tags = api.get("/me/access-tags", sales_member).json()["tags"]
    assert "hr-restricted" in hr_tags
    assert "hr-restricted" not in sales_tags
    assert "public" in sales_tags


def test_other_employee_is_summary_unless_hr(api: Api, org: Org) -> None:
    target = org.members("sales")[1]
    r = api.get(f"/employees/{target}", org.members("quality")[0])
    assert r.status_code == 200
    assert "email" not in r.json()
    r = api.get(f"/employees/{target}", org.members("hr")[0])
    assert "email" in r.json()


# ---------- 미리보기·멱등 ----------

def test_dry_run_does_not_change_state(api: Api, org: Org) -> None:
    emp = org.members("sales")[0]
    before = api.get("/approval-documents", emp, params={"box": "outbox"}).json()["items"]
    bal_before = api.get("/leave/balance", emp).json()
    r = api.post("/approval-documents", emp, params={"dryRun": "true"}, json={"formId": "leave", "fields": {
        "leave_type": "annual", "start_date": future_weekday(), "end_date": future_weekday(),
        "reason": "미리보기"}})
    assert r.status_code == 200, r.text
    validate(ERP, "WritePreview", r.json())
    assert r.json()["dryRun"] is True
    assert r.json()["changes"][0]["resourceId"] is None
    after = api.get("/approval-documents", emp, params={"box": "outbox"}).json()["items"]
    assert len(after) == len(before)
    assert api.get("/leave/balance", emp).json() == bal_before


def test_dry_run_reports_same_validation_errors(api: Api, org: Org) -> None:
    emp = org.members("sales")[0]
    r = api.post("/approval-documents", emp, params={"dryRun": "true"},
                 json={"formId": "leave", "fields": {"leave_type": "annual"}})
    assert r.status_code == 422
    assert problem_code(r) == "form-validation-failed"


def test_execution_requires_idempotency_key(api: Api, org: Org) -> None:
    day = future_weekday()
    r = api.post("/approval-documents", org.members("sales")[0], key=None, json={"formId": "leave", "fields": {
        "leave_type": "half_am", "start_date": day, "end_date": day, "reason": "x"}})
    assert r.status_code == 400
    assert problem_code(r) == "idempotency-key-required"


def test_same_key_same_body_replays(api: Api, org: Org) -> None:
    emp = org.members("sales")[1]
    day = future_weekday()
    body = {"formId": "leave", "fields": {"leave_type": "half_pm", "start_date": day, "end_date": day,
                                          "reason": "병원"}}
    key = uuid.uuid4().hex
    r1 = api.post("/approval-documents", emp, json=body, key=key)
    r2 = api.post("/approval-documents", emp, json=body, key=key)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["actionId"] == r2.json()["actionId"]
    outbox = api.get("/approval-documents", emp, params={"box": "outbox"}).json()["items"]
    assert sum(1 for d in outbox if d["fields"].get("start_date") == day) == 1


def test_same_key_different_body_is_422(api: Api, org: Org) -> None:
    emp = org.members("sales")[1]
    day = future_weekday()
    key = uuid.uuid4().hex
    base = {"formId": "leave", "fields": {"leave_type": "half_am", "start_date": day, "end_date": day,
                                          "reason": "a"}}
    assert api.post("/approval-documents", emp, json=base, key=key).status_code == 201
    other = {**base, "fields": {**base["fields"], "reason": "b"}}
    r = api.post("/approval-documents", emp, json=other, key=key)
    assert r.status_code == 422
    assert problem_code(r) == "idempotency-key-reused"


# ---------- 결재 ----------

def test_leave_approval_flow_updates_balance(api: Api, org: Org) -> None:
    emp, leader = org.members("sales")[2], org.leader("sales")
    bal0 = api.get("/leave/balance", emp).json()
    res = api.request_leave(emp, future_weekday())
    doc = res["resource"]
    assert doc["status"] == "in_progress"
    assert [s["approverId"] for s in doc["steps"]] == [leader]
    assert api.get("/leave/balance", emp).json()["annualPending"] == bal0["annualPending"] + 1
    inbox = api.get("/approval-documents", leader, params={"box": "inbox"}).json()["items"]
    assert doc["id"] in [d["id"] for d in inbox]
    r = api.approve(leader, doc["id"])
    assert r.status_code == 201, r.text
    assert r.json()["undoable"] is False
    final = api.doc(emp, doc["id"])
    assert final["status"] == "approved"
    assert final["steps"][0]["actedBy"] == leader
    assert final["steps"][0]["onBehalfOf"] is None
    bal = api.get("/leave/balance", emp).json()
    assert bal["annualUsed"] == bal0["annualUsed"] + 1
    assert bal["annualPending"] == bal0["annualPending"]


def test_team_leader_leave_goes_to_division_head(api: Api, org: Org) -> None:
    leader = org.leader("production-control")
    doc = api.request_leave(leader, future_weekday())["resource"]
    assert [s["approverId"] for s in doc["steps"]] == [org.head("production-div")]


def test_expense_over_limit_has_two_steps_and_order(api: Api, org: Org) -> None:
    emp, leader, head = org.members("sales")[3], org.leader("sales"), org.head("sales-div")
    doc = api.request_expense(emp, 1_500_000)["resource"]
    assert [s["approverId"] for s in doc["steps"]] == [leader, head]
    r = api.approve(head, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "not-current-approver"
    assert api.approve(leader, doc["id"]).status_code == 201
    assert api.approve(head, doc["id"]).status_code == 201
    assert api.doc(emp, doc["id"])["status"] == "approved"


def test_stale_version_is_409(api: Api, org: Org) -> None:
    emp, leader = org.members("sales")[3], org.leader("sales")
    doc = api.request_leave(emp, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(leader, doc["id"], version=doc["version"] + 5)
    assert r.status_code == 409
    assert problem_code(r) == "version-conflict"


def test_unrelated_employee_cannot_see_or_approve(api: Api, org: Org) -> None:
    emp = org.members("sales")[4]
    doc = api.request_leave(emp, future_weekday(), leave_type="half_pm")["resource"]
    stranger = org.members("quality")[0]
    assert api.get(f"/approval-documents/{doc['id']}", stranger).status_code == 404
    r = api.approve(stranger, doc["id"], version=doc["version"])
    assert r.status_code == 404


def test_requester_cannot_approve_own(api: Api, org: Org) -> None:
    emp = org.members("sales")[4]
    doc = api.request_leave(emp, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(emp, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "self-approval-forbidden"


def test_reject_closes_and_restores_pending(api: Api, org: Org) -> None:
    emp, leader = org.members("sales")[5], org.leader("sales")
    bal0 = api.get("/leave/balance", emp).json()
    doc = api.request_leave(emp, future_weekday())["resource"]
    r = api.post(f"/approval-documents/{doc['id']}/reject", leader, json={"version": doc["version"],
                                                                          "comment": "일정 겹침"})
    assert r.status_code == 201
    assert api.doc(emp, doc["id"])["status"] == "rejected"
    assert api.get("/leave/balance", emp).json() == bal0


def test_leave_balance_insufficient(api: Api, org: Org) -> None:
    emp = org.members("sales")[6]
    start = now().date() + timedelta(days=200)
    end = start + timedelta(days=60)
    r = api.post("/approval-documents", emp, json={"formId": "leave", "fields": {
        "leave_type": "annual", "start_date": start.isoformat(), "end_date": end.isoformat(), "reason": "긴 휴가"}})
    assert r.status_code == 422
    assert problem_code(r) == "leave-balance-insufficient"


# ---------- 회수 ----------

def test_withdraw_by_requester_only(api: Api, org: Org) -> None:
    emp, other = org.members("sales")[6], org.members("sales")[7]
    bal0 = api.get("/leave/balance", emp).json()
    doc = api.request_leave(emp, future_weekday())["resource"]
    r = api.post(f"/approval-documents/{doc['id']}/withdraw", other)
    assert r.status_code in (403, 404)
    r = api.post(f"/approval-documents/{doc['id']}/withdraw", emp, json={"reason": "일정 변경"})
    assert r.status_code == 201
    assert r.json()["undoable"] is False
    assert api.doc(emp, doc["id"])["status"] == "withdrawn"
    assert api.get("/leave/balance", emp).json() == bal0
    r = api.post(f"/approval-documents/{doc['id']}/withdraw", emp)
    assert r.status_code == 409
    assert problem_code(r) == "invalid-state"


def test_withdraw_approved_future_leave_restores_used(api: Api, org: Org) -> None:
    emp, leader = org.members("sales")[7], org.leader("sales")
    bal0 = api.get("/leave/balance", emp).json()
    doc = api.request_leave(emp, future_weekday())["resource"]
    assert api.approve(leader, doc["id"]).status_code == 201
    assert api.post(f"/approval-documents/{doc['id']}/withdraw", emp).status_code == 201
    assert api.get("/leave/balance", emp).json() == bal0


# ---------- 되돌리기 ----------

def test_undo_request_then_already_undone(api: Api, org: Org) -> None:
    emp = org.members("production-control")[0]
    res = api.request_leave(emp, future_weekday(), leave_type="half_am")
    assert res["undoable"] is True
    r = api.post(f"/actions/{res['actionId']}/undo", emp, params={"dryRun": "true"})
    assert r.status_code == 200
    validate(ERP, "WritePreview", r.json())
    assert api.doc(emp, res["resource"]["id"])["status"] == "in_progress"
    r = api.post(f"/actions/{res['actionId']}/undo", emp)
    assert r.status_code == 201, r.text
    validate(ERP, "ActionResult", r.json())
    assert r.json()["undoOf"] == res["actionId"]
    assert api.doc(emp, res["resource"]["id"])["status"] == "withdrawn"
    action = api.get(f"/actions/{res['actionId']}", emp).json()
    validate(ERP, "Action", action)
    assert action["status"] == "undone"
    r = api.post(f"/actions/{res['actionId']}/undo", emp)
    assert r.status_code == 409
    assert problem_code(r) == "already-undone"


def test_undo_after_approval_is_conflict(api: Api, org: Org) -> None:
    emp, leader = org.members("production-control")[1], org.leader("production-control")
    res = api.request_leave(emp, future_weekday(), leave_type="half_pm")
    assert api.approve(leader, res["resource"]["id"]).status_code == 201
    r = api.post(f"/actions/{res['actionId']}/undo", emp)
    assert r.status_code == 409
    assert problem_code(r) == "undo-conflict"
    assert api.doc(emp, res["resource"]["id"])["status"] == "approved"


def test_irreversible_action_is_not_undoable(api: Api, org: Org) -> None:
    emp, leader = org.members("production-control")[2], org.leader("production-control")
    doc = api.request_leave(emp, future_weekday(), leave_type="half_am")["resource"]
    approval = api.approve(leader, doc["id"]).json()
    r = api.post(f"/actions/{approval['actionId']}/undo", leader)
    assert r.status_code == 409
    assert problem_code(r) == "not-undoable"


def test_cannot_undo_someone_elses_action(api: Api, org: Org) -> None:
    emp = org.members("production-control")[3]
    res = api.request_leave(emp, future_weekday(), leave_type="half_am")
    r = api.post(f"/actions/{res['actionId']}/undo", org.leader("production-control"))
    assert r.status_code == 404
    assert api.get(f"/actions/{res['actionId']}", org.members("quality")[1]).status_code == 404


# ---------- 결재 대결 ----------

_created_actions: dict[str, str] = {}


def _delegate(api: Api, *args, **kw) -> dict:
    r = api.delegate(*args, **kw)
    assert r.status_code == 201, r.text
    _created_actions[r.json()["resource"]["id"]] = r.json()["actionId"]
    return r.json()["resource"]


def test_delegate_can_approve_within_period_and_scope(api: Api, org: Org) -> None:
    leader = org.leader("quality")
    delegate, requester = org.members("quality")[0], org.members("quality")[1]
    dl = _delegate(api, leader, delegate)
    validate(ERP, "Delegation", dl)
    assert dl["status"] == "active"
    doc = api.request_leave(requester, future_weekday())["resource"]
    delegated = api.get("/approval-documents", delegate, params={"box": "delegated"}).json()["items"]
    assert doc["id"] in [d["id"] for d in delegated]
    r = api.approve(delegate, doc["id"])
    assert r.status_code == 201, r.text
    step = api.doc(requester, doc["id"])["steps"][0]
    assert step["approverId"] == leader
    assert step["actedBy"] == delegate
    assert step["onBehalfOf"] == leader
    assert step["delegationId"] == dl["id"]
    notes = api.get("/notifications", leader).json()["items"]
    assert any(n["kind"] == "delegated_decision" and n["documentId"] == doc["id"] for n in notes)
    for n in notes:
        validate(ERP, "Notification", n)
    acted = api.get(f"/delegations/{dl['id']}/acted-documents", leader).json()["items"]
    assert doc["id"] in [d["id"] for d in acted]
    # 쓴 위임은 등록 되돌리기가 막힙니다
    r = api.post(f"/actions/{_created_actions[dl['id']]}/undo", leader)
    assert r.status_code == 409
    assert problem_code(r) == "undo-conflict"
    assert api.post(f"/delegations/{dl['id']}/revoke", leader).status_code == 201


def test_delegation_out_of_period(api: Api, org: Org) -> None:
    leader = org.leader("procurement")
    delegate, requester = org.members("procurement")[0], org.members("procurement")[1]
    dl = _delegate(api, leader, delegate, start=now() + timedelta(days=2), days=2)
    assert dl["status"] == "scheduled"
    doc = api.request_leave(requester, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(delegate, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "delegation-out-of-period"
    assert api.doc(requester, doc["id"])["status"] == "in_progress"


def test_delegation_out_of_form_scope(api: Api, org: Org) -> None:
    leader = org.leader("rnd")
    delegate, requester = org.members("rnd")[0], org.members("rnd")[1]
    _delegate(api, leader, delegate, form_types=["expense"])
    doc = api.request_leave(requester, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(delegate, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "delegation-out-of-scope"


def test_delegation_over_amount_limit(api: Api, org: Org) -> None:
    leader = org.leader("finance")
    delegate, requester = org.members("finance")[0], org.members("finance")[1]
    _delegate(api, leader, delegate, form_types=["expense"], max_amount=100_000)
    doc = api.request_expense(requester, 500_000)["resource"]
    r = api.approve(delegate, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "delegation-out-of-scope"
    small = api.request_expense(requester, 50_000)["resource"]
    assert api.approve(delegate, small["id"]).status_code == 201


def test_delegation_after_revoke(api: Api, org: Org) -> None:
    leader = org.leader("general-affairs")
    delegate, requester = org.members("general-affairs")[0], org.members("general-affairs")[1]
    dl = _delegate(api, leader, delegate)
    r = api.post(f"/delegations/{dl['id']}/revoke", leader)
    assert r.status_code == 201
    assert r.json()["resource"]["status"] == "revoked"
    doc = api.request_leave(requester, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(delegate, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "delegation-revoked"
    r = api.post(f"/delegations/{dl['id']}/revoke", leader)
    assert r.status_code == 409
    assert problem_code(r) == "invalid-state"


def test_delegate_cannot_approve_own_document(api: Api, org: Org) -> None:
    leader = org.leader("it-ops")
    delegate = org.members("it-ops")[0]
    _delegate(api, leader, delegate)
    doc = api.request_leave(delegate, future_weekday(), leave_type="half_am")["resource"]
    assert doc["steps"][0]["approverId"] == leader
    r = api.approve(delegate, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "self-approval-forbidden"


def test_redelegation_is_not_followed(api: Api, org: Org) -> None:
    leader = org.leader("production-control")
    first, second = org.members("production-control")[4], org.members("production-control")[5]
    requester = org.members("production-control")[6]
    _delegate(api, leader, first)
    _delegate(api, first, second)
    doc = api.request_leave(requester, future_weekday(), leave_type="half_am")["resource"]
    r = api.approve(second, doc["id"], version=doc["version"])
    assert r.status_code == 403
    assert problem_code(r) == "redelegation-not-allowed"


def test_concurrent_decision_only_one_wins(api: Api, org: Org) -> None:
    leader = org.leader("hr")
    delegate, requester = org.members("hr")[0], org.members("hr")[1]
    _delegate(api, leader, delegate)
    doc = api.request_leave(requester, future_weekday(), leave_type="half_am")["resource"]
    api.token(leader), api.token(delegate)
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go(emp: str) -> None:
        barrier.wait()
        results.append(api.approve(emp, doc["id"], version=doc["version"]).status_code)

    ts = [threading.Thread(target=go, args=(e,)) for e in (leader, delegate)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(results) == [201, 409]
    steps = api.doc(requester, doc["id"])["steps"]
    assert steps[0]["status"] == "approved"


def test_delegation_registration_rules(api: Api, org: Org) -> None:
    leader = org.leader("sales")
    member, other = org.members("sales")[0], org.members("sales")[1]
    hr_staff = org.members("hr")[2]
    r = api.delegate(leader, member, as_emp=other)
    assert r.status_code == 403
    assert problem_code(r) == "delegation-registrar-forbidden"
    r = api.delegate(leader, leader)
    assert r.status_code == 422
    assert problem_code(r) == "delegation-self"
    r = api.delegate(leader, member, days=45)
    assert r.status_code == 422
    assert problem_code(r) == "delegation-period-too-long"
    r = api.delegate(leader, member, form_types=["no-such-form"])
    assert r.status_code == 422
    assert problem_code(r) == "validation"
    r = api.delegate(leader, member, as_emp=hr_staff)
    assert r.status_code == 201, r.text
    dl = r.json()["resource"]
    assert dl["delegatorId"] == leader and dl["registeredBy"] == hr_staff
    mine = api.get("/delegations", leader, params={"role": "delegator"}).json()["items"]
    assert dl["id"] in [d["id"] for d in mine]
    assert api.get("/delegations", member, params={"role": "all"}).status_code == 403
    undo = api.post(f"/actions/{r.json()['actionId']}/undo", hr_staff)
    assert undo.status_code == 201
    assert api.get(f"/delegations/{dl['id']}", leader).json()["status"] == "revoked"


# ---------- 회의실 ----------

def test_room_reserve_conflict_and_undo(api: Api, org: Org) -> None:
    a, b = org.members("rnd")[2], org.members("rnd")[3]
    s, e = future_slot()
    res = api.post("/room-reservations", a, json={"roomId": "room-a", "startsAt": s, "endsAt": e, "title": "주간 회의"})
    assert res.status_code == 201, res.text
    validate(ERP, "RoomReservation", res.json()["resource"])
    r = api.post("/room-reservations", b, json={"roomId": "room-a", "startsAt": s, "endsAt": e, "title": "겹침"})
    assert r.status_code == 409
    assert problem_code(r) == "room-conflict"
    avail = api.get("/rooms/availability", b, params={"startsAt": s, "endsAt": e}).json()["items"]
    assert "room-a" not in [x["id"] for x in avail]
    assert api.post(f"/actions/{res.json()['actionId']}/undo", a).status_code == 201
    r = api.post("/room-reservations", b, json={"roomId": "room-a", "startsAt": s, "endsAt": e, "title": "이제 됨"})
    assert r.status_code == 201


def test_room_slot_validation(api: Api, org: Org) -> None:
    a = org.members("rnd")[2]
    s, _ = future_slot()
    from datetime import datetime
    start = datetime.fromisoformat(s)
    bad = [
        (start + timedelta(minutes=10), start + timedelta(hours=1)),
        (start, start + timedelta(hours=5)),
        (start, start - timedelta(hours=1)),
        (now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2),
         now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)),
    ]
    for bs, be in bad:
        r = api.post("/room-reservations", a, json={"roomId": "room-b", "startsAt": bs.isoformat(),
                                                    "endsAt": be.isoformat(), "title": "x"})
        assert r.status_code == 422, (bs, be, r.text)
        assert problem_code(r) == "validation"


def test_concurrent_room_reservation_one_wins(api: Api, org: Org) -> None:
    a, b = org.members("quality")[2], org.members("quality")[3]
    api.token(a), api.token(b)
    s, e = future_slot()
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go(emp: str) -> None:
        barrier.wait()
        r = api.post("/room-reservations", emp, json={"roomId": "room-c", "startsAt": s, "endsAt": e, "title": "경쟁"})
        results.append(r.status_code)

    ts = [threading.Thread(target=go, args=(x,)) for x in (a, b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(results) == [201, 409]


def test_cancel_undo_conflicts_when_slot_taken(api: Api, org: Org) -> None:
    a, b = org.members("quality")[2], org.members("quality")[3]
    s, e = future_slot()
    res = api.post("/room-reservations", a, json={"roomId": "room-d", "startsAt": s, "endsAt": e, "title": "원래"})
    rid = res.json()["resource"]["id"]
    assert api.post(f"/room-reservations/{rid}/cancel", b).status_code == 403
    cancel = api.post(f"/room-reservations/{rid}/cancel", a)
    assert cancel.status_code == 201
    assert api.post("/room-reservations", b, json={"roomId": "room-d", "startsAt": s, "endsAt": e,
                                                   "title": "새 예약"}).status_code == 201
    r = api.post(f"/actions/{cancel.json()['actionId']}/undo", a)
    assert r.status_code == 409
    assert problem_code(r) == "undo-conflict"


# ---------- 위임 토큰 ----------

def test_delegation_token_cannot_use_human_only(api: Api, org: Org) -> None:
    emp, leader = org.members("finance")[2], org.leader("finance")
    doc = api.request_leave(emp, future_weekday(), leave_type="half_am")["resource"]
    tok = api.delegation_token(leader, ["approval:decide", "approval:read"])
    r = api.req("POST", f"/approval-documents/{doc['id']}/approve", token=tok, json={"version": doc["version"]})
    assert r.status_code == 403
    assert problem_code(r) == "delegation-token-not-allowed"


def test_delegation_token_scope_is_enforced(api: Api, org: Org) -> None:
    emp = org.members("finance")[3]
    tok = api.delegation_token(emp, ["profile:read", "approval:request:leave", "action:undo"])
    assert api.req("GET", "/me", token=tok).status_code == 200
    r = api.req("GET", "/leave/balance", token=tok)
    assert r.status_code == 403
    assert problem_code(r) == "scope-missing"
    day = future_weekday()
    r = api.req("POST", "/approval-documents", token=tok, json={"formId": "leave", "fields": {
        "leave_type": "half_am", "start_date": day, "end_date": day, "reason": "에이전트 경유"}})
    assert r.status_code == 201, r.text
    r2 = api.req("POST", "/approval-documents", token=tok, json={"formId": "expense", "fields": {
        "amount": 1000, "spent_on": "2026-11-02", "merchant": "가상상회", "purpose": "x"}})
    assert r2.status_code == 403
    assert problem_code(r2) == "scope-missing"
    # 토큰으로 한 행동은 토큰 주인이 되돌립니다
    assert api.req("POST", f"/actions/{r.json()['actionId']}/undo", token=tok).status_code == 201


def test_expired_or_forged_delegation_token_is_401(api: Api, org: Org) -> None:
    emp = org.members("finance")[3]
    expired = api.delegation_token(emp, ["profile:read"], ttl=-10)
    assert api.req("GET", "/me", token=expired).status_code == 401
    forged = expired[:-4] + ("AAAA" if not expired.endswith("AAAA") else "BBBB")
    assert api.req("GET", "/me", token=forged).status_code == 401


# ---------- 감사 ----------

def test_audit_records_delegated_decision(api: Api, org: Org) -> None:
    auditor = org.leader("it-ops")
    r = api.get("/audit-events", org.members("sales")[0])
    assert r.status_code == 403
    events = api.get("/audit-events", auditor, params={"limit": 500}).json()["items"]
    assert events
    for ev in events[-50:]:
        validate_file("events/audit.schema.json", ev)
    assert any(ev["operation"] == "approveApprovalDocument" and ev["onBehalfOf"] for ev in events)
    assert any(ev["kind"] == "erp.undo" and ev["undoOf"] for ev in events)
    assert any(ev["kind"] == "erp.denied" for ev in events)
    tok = api.delegation_token(auditor, ["audit:read"])
    assert api.req("GET", "/audit-events", token=tok).status_code == 403


# ---------- IT 티켓 ----------

def _ticket(api: Api, emp: str, title: str = "프린터가 인쇄하지 않습니다") -> dict:
    r = api.post("/tickets", emp, json={"category": "incident", "title": title, "description": "3층 복합기 오류"})
    assert r.status_code == 201, r.text
    validate(ERP, "Ticket", r.json()["resource"])
    return r.json()


def test_ticket_create_dry_run_and_undo(api: Api, org: Org) -> None:
    emp = org.members("sales")[5]
    before = api.get("/tickets", emp).json()["items"]
    r = api.post("/tickets", emp, params={"dryRun": "true"}, key=None,
                 json={"category": "access_request", "title": "권한 요청", "description": "공유 폴더 열람"})
    assert r.status_code == 200, r.text
    validate(ERP, "WritePreview", r.json())
    assert api.get("/tickets", emp).json()["items"] == before
    r = api.post("/tickets", emp, json={"category": "nope", "title": "x", "description": "y"})
    assert r.status_code == 422
    assert problem_code(r) == "validation"

    out = _ticket(api, emp)
    t = api.get(f"/tickets/{out['resource']['id']}", emp).json()
    validate(ERP, "TicketDetail", t)
    assert (t["status"], t["priority"], t["requesterId"], t["comments"]) == ("open", "normal", emp, [])
    assert api.post(f"/actions/{out['actionId']}/undo", emp).status_code == 201
    assert api.get(f"/tickets/{t['id']}", emp).json()["status"] == "cancelled"


def test_ticket_visibility_follows_requester_and_handler(api: Api, org: Org) -> None:
    emp, other = org.members("sales")[6], org.members("quality")[2]
    handler = org.members("it-ops")[0]
    tid = _ticket(api, emp)["resource"]["id"]
    r = api.get(f"/tickets/{tid}", other)
    assert r.status_code == 404
    assert problem_code(r) == "not-found"
    r = api.get("/tickets", other, params={"box": "all"})
    assert r.status_code == 403
    assert problem_code(r) == "forbidden"
    assert tid in [t["id"] for t in api.get("/tickets", emp).json()["items"]]
    assert tid not in [t["id"] for t in api.get("/tickets", other).json()["items"]]
    every = api.get("/tickets", handler, params={"box": "all", "limit": 100}).json()["items"]
    assert tid in [t["id"] for t in every]
    assert api.get(f"/tickets/{tid}", handler).status_code == 200
    # 팩 고정 데이터의 티켓(댓글 포함)
    fixed = api.get("/tickets/tkt_0001", handler).json()
    validate(ERP, "TicketDetail", fixed)
    assert len(fixed["comments"]) >= 2 and fixed["commentCount"] == len(fixed["comments"])


def test_ticket_comment_and_undo(api: Api, org: Org) -> None:
    emp, handler = org.members("sales")[7], org.members("it-ops")[1]
    created = _ticket(api, emp)
    tid = created["resource"]["id"]
    r = api.post(f"/tickets/{tid}/comments", handler, json={"body": "확인하겠습니다"})
    assert r.status_code == 201, r.text
    validate(ERP, "TicketComment", r.json()["resource"])
    t = api.get(f"/tickets/{tid}", emp).json()
    assert [(c["authorId"], c["body"]) for c in t["comments"]] == [(handler, "확인하겠습니다")]
    # 댓글이 달린 뒤에는 작성을 되돌리지 못합니다
    u = api.post(f"/actions/{created['actionId']}/undo", emp)
    assert u.status_code == 409
    assert problem_code(u) == "undo-conflict"
    assert api.post(f"/actions/{r.json()['actionId']}/undo", handler).status_code == 201
    assert api.get(f"/tickets/{tid}", emp).json()["comments"] == []
    r = api.post(f"/tickets/{tid}/comments", org.members("quality")[3], json={"body": "남의 티켓"})
    assert r.status_code == 404


def test_ticket_status_rules(api: Api, org: Org) -> None:
    emp, handler = org.members("production-control")[4], org.members("it-ops")[2]
    tid = _ticket(api, emp)["resource"]["id"]
    path = f"/tickets/{tid}/status"
    r = api.post(path, emp, json={"status": "resolved", "version": 0})
    assert r.status_code == 403
    assert problem_code(r) == "forbidden"
    assert api.post(path, org.members("quality")[4], json={"status": "resolved", "version": 0}).status_code == 404
    r = api.post(path, handler, json={"status": "in_progress", "version": 1})
    assert r.status_code == 409
    assert problem_code(r) == "version-conflict"
    r = api.post(path, handler, json={"status": "closed", "version": 0})
    assert r.status_code == 409
    assert problem_code(r) == "invalid-state"

    r = api.post(path, handler, json={"status": "in_progress", "version": 0})
    assert r.status_code == 201, r.text
    assert (r.json()["resource"]["status"], r.json()["resource"]["version"]) == ("in_progress", 1)
    assert api.post(f"/actions/{r.json()['actionId']}/undo", handler).status_code == 201
    t = api.get(f"/tickets/{tid}", emp).json()
    assert t["status"] == "open"
    r = api.post(path, handler, json={"status": "resolved", "version": t["version"]})
    assert r.status_code == 201, r.text
    stale = r.json()["actionId"]
    r = api.post(path, handler, json={"status": "closed", "version": r.json()["resource"]["version"]})
    assert r.status_code == 201, r.text
    # 그사이 상태가 다시 바뀌었으면 앞 변경은 되돌리지 못합니다
    u = api.post(f"/actions/{stale}/undo", handler)
    assert u.status_code == 409
    assert problem_code(u) == "undo-conflict"
    r = api.post(f"/tickets/{tid}/comments", emp, json={"body": "닫힌 뒤 댓글"})
    assert r.status_code == 409
    assert problem_code(r) == "invalid-state"


def test_ticket_delegation_token_scope(api: Api, org: Org) -> None:
    emp, handler = org.members("sales")[2], org.members("it-ops")[0]
    body = {"category": "other", "title": "에이전트 경유", "description": "노트북 배터리 교체"}
    r = api.req("POST", "/tickets", token=api.delegation_token(emp, ["ticket:read"]), json=body)
    assert r.status_code == 403
    assert problem_code(r) == "scope-missing"
    r = api.req("POST", "/tickets", token=api.delegation_token(emp, ["ticket:read", "ticket:write"]), json=body)
    assert r.status_code == 201, r.text
    tid = r.json()["resource"]["id"]
    r = api.req("POST", f"/tickets/{tid}/status", token=api.delegation_token(handler, ["ticket:read", "ticket:write"]),
                json={"status": "in_progress", "version": 0})
    assert r.status_code == 403
    assert problem_code(r) == "scope-missing"


# ---------- 금액 대조 ----------

def test_purchase_total_must_equal_quantity_times_price(api: Api, org: Org) -> None:
    emp = org.members("procurement")[2]
    fields = {"item_code": "BRG-6204", "quantity": 1000, "unit_price": 100000, "total_amount": 1, "reason": "증산"}
    for params in ({"dryRun": "true"}, {}):
        r = api.post("/approval-documents", emp, params=params, json={"formId": "purchase", "fields": fields})
        assert r.status_code == 422, r.text
        assert problem_code(r) == "form-validation-failed"
        assert any(e["field"] == "total_amount" for e in r.json().get("errors", []))
    ok = {**fields, "total_amount": 100_000_000}
    r = api.post("/approval-documents", emp, json={"formId": "purchase", "fields": ok})
    assert r.status_code == 201, r.text
    # 500만 원을 넘으므로 팀장 + 본부장 두 단계입니다
    assert len(r.json()["resource"]["steps"]) == 2


# ---------- 서비스 로그인(슬랙 입구) ----------

def _service_login(api: Api, emp: str | None, secret: str | None = SERVICE_LOGIN_SECRET):
    headers = {} if secret is None else {"X-Service-Login-Secret": secret}
    r = api.c.post("/auth/service-login", headers=headers, json={"employeeId": emp})
    if r.status_code == 404:
        pytest.skip("erp에 ERP_SERVICE_LOGIN_SECRET이 설정되지 않아 서비스 로그인 경로가 꺼져 있습니다")
    return r


def test_service_login_issues_short_slack_token(api: Api, org: Org) -> None:
    emp = org.members("sales")[3]
    r = _service_login(api, emp)
    assert r.status_code == 200, r.text
    validate(ERP, "LoginResponse", r.json())
    assert r.json()["expiresIn"] == 900
    token = r.json()["accessToken"]
    assert jwt.decode(token, options={"verify_signature": False})["amr"] == ["slack"]
    me = api.req("GET", "/me", token=token)
    assert me.status_code == 200 and me.json()["id"] == emp
    for secret in (None, "wrong-secret"):
        bad = _service_login(api, emp, secret)
        assert bad.status_code == 401
        assert problem_code(bad) == "unauthorized"
    unknown = _service_login(api, "E9999")
    assert unknown.status_code == 422
    assert problem_code(unknown) == "validation"


def test_service_login_token_cannot_use_human_only(api: Api, org: Org) -> None:
    member, leader = org.members("quality")[1], org.leader("quality")
    doc = api.request_leave(member, future_weekday())["resource"]
    token = _service_login(api, leader).json()["accessToken"]
    r = api.req("POST", f"/approval-documents/{doc['id']}/approve", token=token, json={"version": doc["version"]})
    assert r.status_code == 403
    assert problem_code(r) == "service-login-not-allowed"
    auditor = next(e["id"] for e in org.all if e["grade"] == "ceo")
    r = api.req("GET", "/audit-events", token=_service_login(api, auditor).json()["accessToken"])
    assert r.status_code == 403
    assert problem_code(r) == "service-login-not-allowed"
    # 사람 전용이 아닌 일은 직원 JWT와 같이 됩니다(본인 결재함 조회)
    assert api.req("GET", "/approval-documents", token=token, params={"box": "inbox"}).status_code == 200
