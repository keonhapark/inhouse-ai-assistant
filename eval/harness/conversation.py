"""시나리오 한 회차의 대화를 끝까지 진행합니다: 사용자 발화, 실행 승인, 되묻기 응답."""

from __future__ import annotations

import time
from typing import Any

from harness.clarify import answer_for, looks_like_question
from harness.record import Clarification, RunRecord
from harness.sut import ChatSystem

MAX_CLARIFICATIONS = 3
MAX_APPROVALS = 5


def _pending_approval(events: list[dict[str, Any]]) -> str | None:
    decided = {e.get("decision", {}).get("approvalId") for e in events if e.get("type") == "approval_decided"}
    for e in reversed(events):
        if e.get("type") == "approval_required":
            aid = e["approval"]["approvalId"]
            return None if aid in decided else aid
    return None


def _last_message(events: list[dict[str, Any]]) -> str | None:
    for e in reversed(events):
        if e.get("type") == "message":
            return e.get("text", "")
    return None


def run_conversation(scenario: dict[str, Any], system: ChatSystem, *, time_limit_s: float = 300) -> RunRecord:
    record = RunRecord(scenario_id=scenario["id"])
    decision = "approve" if scenario.get("executionApprover", "always_approve") == "always_approve" else "reject"
    clarifications = scenario.get("clarifications", [])
    deadline = time.monotonic() + time_limit_s
    try:
        cid = system.start(scenario["requester"])
        record.conversation_id = cid
        for turn in scenario["turns"]:
            record.events.extend(system.send(cid, turn["content"]))
            asked = approvals = 0
            while True:
                if time.monotonic() > deadline:
                    record.timed_out = True
                    return record
                approval = _pending_approval(record.events)
                if approval and approvals < MAX_APPROVALS:
                    approvals += 1
                    record.events.extend(system.decide(cid, approval, decision))
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
    return record
