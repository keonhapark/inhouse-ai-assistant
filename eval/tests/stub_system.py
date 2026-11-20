"""계약 스텁: gateway·agent 대신 ChatEvent를 내고, 실행은 가짜 erp에 요청자 권한으로 합니다.

장치 구현을 흉내 내지 않습니다. 판정기가 기록만으로 결과를 가리는지 보려는 대본입니다.
"""

from __future__ import annotations

from typing import Any, Callable

from harness.erp import ErpClient
from harness.sut import Collected

# 도구 → (erp operationId, 인자로 params·body를 만드는 함수)
Action = tuple[str, str, Callable[[], tuple[dict[str, Any], Any]]]


class ScriptedChat:
    """send마다 replies에서 하나씩 꺼내 답합니다. 답은 'ask:<질문>', 'say:<글>', 'do:<도구>' 중 하나입니다."""

    def __init__(self, erp: ErpClient, replies: list[str], actions: dict[str, Action] | None = None,
                 external: list[Any] | None = None) -> None:
        self.erp = erp
        self.replies = list(replies)
        self.actions = actions or {}
        self.external = external
        self.requester = ""
        self.seq = 0
        self.received: list[str] = []
        self.pending: dict[str, str] = {}
        self.audit: list[dict[str, Any]] = []

    def _ev(self, type_: str, **kw: Any) -> dict[str, Any]:
        self.seq += 1
        return {"type": type_, "conversationId": "c1", "seq": self.seq, **kw}

    def _done(self) -> dict[str, Any]:
        return self._ev("done", model={"name": "stub", "location": "local"})

    def start(self, requester: str) -> str:
        self.requester = requester
        return "c1"

    def send(self, conversation_id: str, text: str) -> list[dict[str, Any]]:
        self.received.append(text)
        kind, _, arg = self.replies.pop(0).partition(":")
        if kind in ("ask", "say"):
            return [self._ev("message", text=arg, model={"name": "stub", "location": "local"}), self._done()]
        approval_id = f"p{self.seq}"
        self.pending[approval_id] = arg
        return [self._ev("approval_required", approval={"approvalId": approval_id, "tool": arg,
                                                        "risk": "reversible_write", "preview": {}}), self._done()]

    def decide(self, conversation_id: str, approval_id: str, decision: str) -> list[dict[str, Any]]:
        tool = self.pending.pop(approval_id)
        out = [self._ev("approval_decided", decision={"approvalId": approval_id, "decision": decision})]
        if decision == "approve":
            label, op, make = self.actions[tool]
            params, body = make()
            res = self.erp.call_ok(self.requester, op, params, body)
            self.audit.append({"kind": "tool.called", "result": "ok", "operation": tool})
            out.append(self._ev("action", action={"actionId": res["actionId"], "tool": tool, "summary": label,
                                                  "undoable": res["undoable"]}))
            out.append(self._ev("message", text=f"{label} 했습니다.", model={"name": "stub", "location": "local"}))
        out.append(self._done())
        return out

    def collect(self, conversation_id: str) -> Collected:
        return Collected(audit_events=self.audit, external_requests=self.external)
