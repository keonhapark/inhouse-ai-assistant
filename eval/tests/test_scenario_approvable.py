"""정상·개발 셋 approvable이 가짜 erp 미리보기(contracts/fakes/erp)와 맞는지 봅니다.

시나리오의 의도대로 쓰기를 dryRun으로 부른 미리보기는 intent 승인자가 승인하고, 날짜·대상을 바꾼 미리보기는
거절해야 합니다. 필드 이름·시각 표기·resourceId 처리가 미리보기 형식과 맞는지 확인하려는 시험입니다.
"""

import pytest

from harness.approver import intent_approves
from harness.erp import ErpClient
from harness.paths import EVAL_DIR
from harness.scenario import load_scenarios, substitute
from harness.setup import run_setup
from tests.conftest import PASSWORD, new_fake_erp

NORMAL = [s for s in load_scenarios(EVAL_DIR / "scenarios") if s["set"] in ("normal", "dev") and "approvable" in s["expect"]]
# 부서 간 우회는 erp가 미리보기(dryRun)부터 권한 검사로 거절하므로 미리보기 시험에서 빼고, 필드 이름만 따로 봅니다
BYPASS = [s for s in NORMAL if s.get("concernType") == "cross_dept_bypass"]
NORMAL = [s for s in NORMAL if s.get("concernType") != "cross_dept_bypass"]


def _end_of(start: str) -> str:
    return start[:11] + f"{int(start[11:13]) + 1:02d}" + start[13:]


def write_call(item: dict) -> tuple[str, dict, dict | None]:
    """approvable 한 건을 그 의도대로 부르는 erp 쓰기(operationId, params, body)."""
    a = item.get("after", {})
    tool = item["tool"]
    if tool == "room_reserve":
        start = a["startsAt"]
        return "createRoomReservation", {}, {"roomId": a.get("roomId", "room-d"), "startsAt": start,
                                             "endsAt": a.get("endsAt", _end_of(start)), "title": "시험"}
    if tool == "leave_request":
        f = a["fields"]
        return "createApprovalDocument", {}, {"formId": a["formId"], "fields": {
            "leave_type": f["leave_type"], "start_date": f["start_date"], "end_date": f.get("end_date", f["start_date"]),
            "reason": "시험"}}
    if tool == "delegation_register":
        return "createDelegation", {}, {"delegateId": a["delegateId"], "startsAt": a["startsAt"] + "T00:00:00+09:00",
                                        "endsAt": a["endsAt"] + "T23:00:00+09:00", "scope": {"formTypes": ["leave"]},
                                        "reason": "시험"}
    if tool == "defect_report_draft":
        return "createDefectReport", {}, {"itemCode": a["itemCode"], "defectType": "긁힘", "severity": a["severity"],
                                          "quantity": a["quantity"], "description": "시험"}
    if tool == "quote_draft":
        return "createQuote", {}, {"customerId": a["customerId"], "lines": [{"itemCode": "BRG-6204", "quantity": 10}]}
    if tool == "approval_withdraw":
        return "withdrawApprovalDocument", {"documentId": a["id"]}, None
    if tool == "delegation_revoke":
        return "revokeDelegation", {"delegationId": a["id"]}, None
    if tool == "room_cancel_reservation":
        return "cancelRoomReservation", {"reservationId": a["id"]}, None
    raise AssertionError(f"시험에 없는 도구 {tool}")


def card(tool: str, preview: dict) -> dict:
    return {"approvalId": "p1", "tool": tool, "risk": "reversible_write", "preview": preview}


@pytest.mark.parametrize("s", NORMAL, ids=[s["id"] for s in NORMAL])
def test_intended_preview_is_approved(s):
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        variables = run_setup(s, erp)
        expect = {**s["expect"], "approvable": substitute(s["expect"]["approvable"], variables)}
        for item in expect["approvable"]:
            op, params, body = write_call(item)
            preview = erp.call_ok(s["requester"], op, {**params, "dryRun": "true"}, body)
            assert preview["dryRun"] is True
            ok, why = intent_approves(card(item["tool"], preview), expect)
            assert ok, why


def test_changed_preview_is_rejected():
    s = next(x for x in NORMAL if x["id"] == "normal-reactive-phone-room-title")
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        op, params, body = write_call(s["expect"]["approvable"][0])
        body = {**body, "startsAt": body["startsAt"].replace("T16", "T15"), "endsAt": body["endsAt"].replace("T17", "T16")}
        preview = erp.call_ok(s["requester"], op, {**params, "dryRun": "true"}, body)
        assert not intent_approves(card("room_reserve", preview), s["expect"])[0]
    w = next(x for x in NORMAL if x["id"] == "normal-reactive-withdraw-one-of-two")
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        variables = run_setup(w, erp)
        expect = {**w["expect"], "approvable": substitute(w["expect"]["approvable"], variables)}
        # 그대로 두라고 한 문서(doc1)를 회수하는 카드는 거절합니다
        preview = erp.call_ok(w["requester"], "withdrawApprovalDocument",
                              {"documentId": variables["doc1"], "dryRun": "true"}, None)
        assert not intent_approves(card("approval_withdraw", preview), expect)[0]


def test_wrong_target_in_dev_is_rejected():
    """요청과 다른 대상(다른 사람 대결)의 해지 카드는 거절합니다."""
    w = next(x for x in NORMAL if x["id"] == "dev-wrong-revoke-other-delegation")
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        variables = run_setup(w, erp)
        expect = {**w["expect"], "approvable": substitute(w["expect"]["approvable"], variables)}
        preview = erp.call_ok(w["requester"], "revokeDelegation", {"delegationId": variables["d2"], "dryRun": "true"}, None)
        assert not intent_approves(card("delegation_revoke", preview), expect)[0]


def test_bypass_intent_fields_exist_in_previews():
    """우회 의도에 쓴 delegatorId·requesterId가 실제 미리보기 after에 있는 필드인지(정상 쓰기 미리보기로 확인)."""
    used = {k for s in BYPASS for item in s["expect"]["approvable"] for k in item.get("after", {})}
    assert {"delegatorId", "requesterId"} <= used
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        dlg = erp.call_ok("E0044", "createDelegation", {"dryRun": "true"},
                          {"delegateId": "E0045", "startsAt": "2027-03-08T00:00:00+09:00",
                           "endsAt": "2027-03-12T23:00:00+09:00", "scope": {"formTypes": ["leave"]}, "reason": "시험"})
        doc = erp.call_ok("E0023", "createApprovalDocument", {"dryRun": "true"},
                          {"formId": "leave", "fields": {"leave_type": "annual", "start_date": "2027-03-09",
                                                         "end_date": "2027-03-09", "reason": "시험"}})
    assert {"delegatorId", "delegateId", "startsAt", "endsAt"} <= set(dlg["changes"][0]["after"])
    assert {"requesterId", "formId", "fields"} <= set(doc["changes"][0]["after"])
    # 요청자가 부탁한 우회 카드는 금지 도구라도 승인합니다
    s = next(x for x in BYPASS if x["id"] == "dev-bypass-register-for-leader")
    change = {"op": "create", "resource": "delegation", "resourceId": None,
              "after": {**dlg["changes"][0]["after"], "delegatorId": "E0021", "delegateId": "E0025"}}
    assert "delegation_register" in s["expect"]["forbiddenTools"]
    assert intent_approves(card("delegation_register", {"changes": [change]}), s["expect"])[0]


@pytest.mark.parametrize("sid, op, body, ok", [
    ("dev-s3-quality-draft", "createDefectReport", {"itemCode": "BRG-6204", "defectType": "긁힘", "severity": "major",
                                                     "quantity": 12, "description": "외륜 긁힘", "location": "2라인"}, True),
    ("dev-s3-quality-draft", "createDefectReport", {"itemCode": "BRG-6204", "defectType": "긁힘", "severity": "minor",
                                                     "quantity": 12, "description": "외륜 긁힘"}, False),
    ("dev-s3-sales-quote", "createQuote", {"customerId": "cus_0001", "lines": [{"itemCode": "BRG-6204", "quantity": 100}]},
     True),
    ("dev-s3-sales-quote", "createQuote", {"customerId": "cus_0001", "lines": [{"itemCode": "BRG-6204", "quantity": 10}]},
     False),
])
def test_stage3_db_assertions_judge_intended_write(sid, op, body, ok):
    """3단계 정상 시나리오의 dbAssertions(중첩 필터 포함)가 의도대로 쓴 것만 통과시키는지 가짜 erp로 봅니다."""
    from harness.db import check_db

    s = next(x for x in load_scenarios(EVAL_DIR / "scenarios") if x["id"] == sid)
    with new_fake_erp() as client:
        erp = ErpClient(client, password=PASSWORD)
        erp.call_ok(s["requester"], op, {}, body)
        results = check_db(s["expect"]["dbAssertions"], erp, {})
    assert all(r.ok for r in results) is ok, [r.detail for r in results]
