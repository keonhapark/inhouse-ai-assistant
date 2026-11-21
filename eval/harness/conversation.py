"""시나리오 한 회차의 대화를 끝까지 진행합니다: 사용자 발화, 실행 승인, 되묻기 응답."""

from __future__ import annotations

import time
from typing import Any

import httpx

from harness.approver import decide, resolve_approver
from harness.attachments import turn_attachments
from harness.clarify import answer_for, looks_like_question
from harness.record import ApprovalDecision, Clarification, RunRecord
from harness.sut import ChatSystem

MAX_CLARIFICATIONS = 3
MAX_APPROVALS = 5
# 하네스가 대상 시스템에 닿지도 못한 경우만 실행 환경 문제로 봅니다. 응답 시간 초과·HTTP 오류는 "실패로 끝남"입니다
CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


def _pending_approval(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """아직 결정하지 않은 마지막 승인 카드(gateway ChatEvent approval)."""
    decided = {e.get("decision", {}).get("approvalId") for e in events if e.get("type") == "approval_decided"}
    for e in reversed(events):
        if e.get("type") == "approval_required":
            return None if e["approval"]["approvalId"] in decided else e["approval"]
    return None


def _last_message(events: list[dict[str, Any]]) -> str | None:
    for e in reversed(events):
        if e.get("type") == "message":
            return e.get("text", "")
    return None


def run_conversation(scenario: dict[str, Any], system: ChatSystem, *, time_limit_s: float = 300,
                     condition: str | None = None) -> RunRecord:
    record = RunRecord(scenario_id=scenario["id"])
    approver = resolve_approver(scenario, condition)
    record.approver = approver
    clarifications = scenario.get("clarifications", [])
    deadline = time.monotonic() + time_limit_s
    try:
        cid = system.start(scenario["requester"])
        record.conversation_id = cid
        for turn in scenario["turns"]:
            attachments = turn_attachments(turn)
            if attachments:
                record.events.extend(system.send(cid, turn["content"], attachments=attachments))
            else:
                record.events.extend(system.send(cid, turn["content"]))
            asked = approvals = 0
            while True:
                if time.monotonic() > deadline:
                    record.timed_out = True
                    return record
                approval = _pending_approval(record.events)
                if approval and approvals < MAX_APPROVALS:
                    approvals += 1
                    decision, why = decide(approver, approval, scenario["expect"])
                    record.approval_decisions.append(ApprovalDecision(approval.get("tool", ""), decision, why))
                    record.events.extend(system.decide(cid, approval["approvalId"], decision))
                    continue
                msg = _last_message(record.events)
                if msg and looks_like_question(msg) and asked < MAX_CLARIFICATIONS and not approval:
                    asked += 1
                    answer, matched = answer_for(msg, clarifications)
                    record.clarifications.append(Clarification(msg, answer, matched))
                    record.events.extend(system.send(cid, answer))
                    continue
                break
    except Exception as e:  # noqa: BLE001 - 대상 시스템의 어떤 오류든 "실패로 끝남"으로 기록합니다
        record.error = f"{type(e).__name__}: {e}"
        if isinstance(e, CONNECTION_ERRORS):
            record.env_failure = "gateway 연결 실패"
    retryable = [e for e in record.events if e.get("type") == "error" and e.get("error", {}).get("retryable")]
    if retryable:
        # gateway는 agent 오류·시간 초과에도 재시도 가능으로 표시하므로 이것만으로는 실행 환경 문제로 보지 않습니다.
        # "실패로 끝남"으로 남기고, 모델 서버가 죽었는지는 실행기가 확인합니다(eval/protocol.md 2절)
        record.retryable_event = True
        if not record.error:
            record.error = "재시도 가능한 오류: " + str(retryable[-1]["error"].get("message", ""))[:200]
    return record
