"""1단계 정상 흐름: 채팅 반차 신청(미리보기 → 실행 승인 → 실행 → 되돌리기), 규정 질의(인용),
팀장 승인함 승인, 대결 등록 뒤 대리 결재. 모델(로컬)을 실제로 부릅니다."""

from __future__ import annotations

from typing import Any

from harness.clarify import looks_like_question
from harness.erp import ErpClient
from harness.sut import GatewayChat

STAFF, LEADER, DELEGATE = "E0016", "E0011", "E0012"  # 재무팀 팀원, 팀장, 팀원


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def run_turn(chat: GatewayChat, cid: str, text: str, max_approvals: int = 3, followup: str | None = None,
             max_followups: int = 2) -> list[dict[str, Any]]:
    """발화 하나를 보내고, 되묻기면 followup으로 답하고, 실행 승인이 나오면 승인합니다. 받은 이벤트를 모두 돌려줍니다."""
    events = chat.send(cid, text)
    for _ in range(max_followups):
        msgs = [e["text"] for e in events if e["type"] == "message"]
        if not followup or not msgs or not looks_like_question(msgs[-1]) or any(
                e["type"] in ("approval_required", "action") for e in events):
            break
        events += chat.send(cid, followup)
    for _ in range(max_approvals):
        pending = [e for e in events if e["type"] == "approval_required"]
        decided = {e.get("decision", {}).get("approvalId") for e in events if e["type"] == "approval_decided"}
        todo = [e for e in pending if e["approval"]["approvalId"] not in decided]
        if not todo:
            break
        assert todo[-1]["approval"]["preview"], "미리보기가 비어 있음"
        events += chat.decide(cid, todo[-1]["approval"]["approvalId"], "approve")
    assert events and events[-1]["type"] == "done", types(events)
    return events


def leave_docs(erp: ErpClient, emp: str, date: str) -> list[dict]:
    items = erp.call_ok(emp, "listApprovalDocuments", {"box": "outbox"})["items"]
    return [d for d in items if d["formId"] == "leave" and d["fields"].get("start_date") == date]


def test_chat_leave_preview_approve_execute_undo(chat, human, erp):
    cid = chat.start(STAFF)
    events = run_turn(chat, cid, "2027년 3월 9일 화요일 오후 반차 신청해 줘. 사유는 병원 진료야.",
                      followup="네, 2027년 3월 9일 하루 오후 반차(half_pm)예요. 사유는 병원 진료이고 바로 신청해 주세요.")
    route = [e for e in events if e["type"] == "route"]
    assert route and route[0]["route"]["agentId"] == "hr", types(events)
    actions = [e["action"] for e in events if e["type"] == "action" and e["action"]["tool"] == "leave_request"]
    assert actions, f"휴가 신청이 실행되지 않음: {types(events)}"
    docs = leave_docs(erp, STAFF, "2027-03-09")
    assert len(docs) == 1 and docs[0]["fields"]["leave_type"] == "half_pm" and docs[0]["status"] == "in_progress"
    assert actions[-1]["undoable"]
    r = human.post(STAFF, f"/actions/{actions[-1]['actionId']}/undo")
    assert r.status_code == 201, r.text
    assert erp.call_ok(STAFF, "getApprovalDocument", {"documentId": docs[0]["id"]})["status"] == "withdrawn"


def test_policy_question_has_citations(chat):
    cid = chat.start(STAFF)
    events = run_turn(chat, cid, "결재 대결은 최대 며칠까지 맡길 수 있어?")
    cites = [c for e in events if e["type"] == "citations" for c in e["citations"]]
    msgs = [e["text"] for e in events if e["type"] == "message"]
    assert msgs, types(events)
    assert cites, f"근거 없음: {msgs[-1][:200]}"


def test_leader_approves_from_inbox(human, erp):
    doc = erp.call_ok(STAFF, "createApprovalDocument", body={"formId": "leave", "fields": {
        "leave_type": "annual", "start_date": "2027-03-10", "end_date": "2027-03-10", "reason": "개인 사정"}})["resource"]
    inbox = human.get(LEADER, "/inbox", params={"box": "inbox"})
    assert inbox.status_code == 200, inbox.text
    item = next(i for i in inbox.json()["items"] if i["id"] == doc["id"])
    assert item["requesterName"] and item["formName"]
    r = human.post(LEADER, f"/inbox/{doc['id']}/approve", json={"version": item["version"]})
    assert r.status_code == 201, r.text
    assert erp.call_ok(STAFF, "getApprovalDocument", {"documentId": doc["id"]})["status"] == "approved"


def test_delegation_then_proxy_approval(human, erp):
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    r = human.post(LEADER, "/delegations", json={
        "delegateId": DELEGATE, "startsAt": start.isoformat(), "endsAt": (start + timedelta(days=3)).isoformat(),
        "scope": {"formTypes": ["leave"]}, "reason": "출장"})
    assert r.status_code == 201, r.text
    delegation_id = r.json()["resource"]["id"]
    doc = erp.call_ok(STAFF, "createApprovalDocument", body={"formId": "leave", "fields": {
        "leave_type": "annual", "start_date": "2027-03-11", "end_date": "2027-03-11", "reason": "가족 행사"}})["resource"]
    box = human.get(DELEGATE, "/inbox", params={"box": "delegated"})
    assert box.status_code == 200, box.text
    item = next(i for i in box.json()["items"] if i["id"] == doc["id"])
    assert item["viaDelegation"]["originalApproverId"] == LEADER
    r = human.post(DELEGATE, f"/inbox/{doc['id']}/approve", json={"version": item["version"]})
    assert r.status_code == 201, r.text
    got = erp.call_ok(STAFF, "getApprovalDocument", {"documentId": doc["id"]})
    assert got["status"] == "approved"
    step = got["steps"][0]
    assert step["actedBy"] == DELEGATE and step["onBehalfOf"] == LEADER and step["delegationId"] == delegation_id
