"""가짜 erp의 업무 규칙. 실제 erp(Spring Boot)와 같은 계약(contracts/openapi/erp.yaml)을 지킵니다.

메모리에 상태를 두고, 쓰기 함수는 상태를 바꾼 뒤 (요약, 변경, 되돌리기 가능 여부, 리소스)를 돌려줍니다.
dryRun은 상태를 깊은 복사한 뒤 같은 함수를 돌려 미리보기를 만듭니다. 그래서 검사 규칙이 실행과 같습니다.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import yaml
from jsonschema import Draft202012Validator

from tools.common import load

KST = ZoneInfo("Asia/Seoul")


class ProblemError(Exception):
    def __init__(self, status: int, code: str, detail: str = "", errors: list[dict[str, str]] | None = None):
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail
        self.errors = errors


TITLES = {
    "unauthorized": "로그인하지 못했습니다",
    "forbidden": "권한이 없습니다",
    "scope-missing": "위임 토큰에 필요한 scope가 없습니다",
    "delegation-token-not-allowed": "사람 화면 전용 기능입니다",
    "service-login-not-allowed": "슬랙에서는 쓸 수 없는 기능입니다",
    "not-found": "찾을 수 없습니다",
    "validation": "입력이 올바르지 않습니다",
    "form-validation-failed": "양식 입력이 올바르지 않습니다",
    "idempotency-key-required": "Idempotency-Key가 필요합니다",
    "idempotency-key-reused": "같은 Idempotency-Key로 다른 요청을 보냈습니다",
    "version-conflict": "그사이 다른 사람이 먼저 바꿨습니다",
    "invalid-state": "지금 상태에서는 할 수 없습니다",
    "not-current-approver": "지금 결재 대기 중인 문서가 아닙니다",
    "self-approval-forbidden": "본인이 기안한 문서는 결재할 수 없습니다",
    "delegation-not-found": "이 문서를 대결할 수 있는 대결 지정이 없습니다",
    "delegation-out-of-period": "대결 기간이 아닙니다",
    "delegation-out-of-scope": "대결 범위 밖의 문서입니다",
    "delegation-revoked": "해제된 대결입니다",
    "redelegation-not-allowed": "대결자는 맡은 결재를 다른 사람에게 다시 맡길 수 없습니다",
    "delegation-self": "본인을 대결자로 지정할 수 없습니다",
    "delegation-period-too-long": "대결 기간이 너무 깁니다",
    "delegation-registrar-forbidden": "대결을 지정할 권한이 없습니다",
    "leave-balance-insufficient": "남은 연차가 부족합니다",
    "room-conflict": "이미 예약된 시간입니다",
    "not-undoable": "실행 취소할 수 없는 작업입니다",
    "already-undone": "이미 실행 취소한 작업입니다",
    "undo-conflict": "그사이 상태가 바뀌어 실행 취소할 수 없습니다",
    "internal": "서버에서 요청을 처리하지 못했습니다",
}


def now() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def parse_dt(value: Any, field_name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        raise ProblemError(422, "validation", f"{field_name}: 날짜·시각 형식이 아닙니다",
                           [{"field": field_name, "message": "RFC 3339"}])
    if dt.tzinfo is None:
        raise ProblemError(422, "validation", f"{field_name}: 시간대 오프셋이 필요합니다",
                           [{"field": field_name, "message": "offset required"}])
    return dt


def parse_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ProblemError(422, "form-validation-failed", f"{field_name}: 날짜 형식이 아닙니다",
                           [{"field": field_name, "message": "YYYY-MM-DD"}])


@dataclass
class Principal:
    employee_id: str
    via_delegation_token: bool = False
    agent_id: str | None = None
    conversation_id: str | None = None
    scopes: frozenset[str] = frozenset()
    via_service_login: bool = False

    @property
    def channel(self) -> str:
        """감사 이벤트 actor.channel: 위임 토큰이면 agent, 서비스 로그인(amr slack)이면 slack, 그 밖에는 web."""
        return "agent" if self.via_delegation_token else "slack" if self.via_service_login else "web"


@dataclass
class Action:
    id: str
    operation: str
    actor: Principal
    resource_type: str
    resource_id: str
    undoable: bool
    undo: Callable[["State"], tuple[str, list[dict], dict]] | None
    created_at: datetime
    status: str = "done"
    undo_action_id: str | None = None


# ---------- IT 티켓 ----------

TICKET_CATEGORIES = ("incident", "access_request", "other")
TICKET_PRIORITIES = ("low", "normal", "high")
TICKET_STATUSES = ("open", "in_progress", "resolved", "closed", "cancelled")
TICKET_TRANSITIONS = {"open": ("in_progress", "resolved"), "in_progress": ("open", "resolved"),
                      "resolved": ("in_progress", "closed")}


def ticket_from_fixture(t: dict[str, Any]) -> dict[str, Any]:
    tid = t["id"]
    comments = [{"id": f"tcm_{tid.removeprefix('tkt_')}_{i + 1}", "ticketId": tid, "authorId": c["author_id"],
                 "body": c["body"], "createdAt": c["created_at"]} for i, c in enumerate(t.get("comments", []))]
    updated = max([t["created_at"], *(c["createdAt"] for c in comments)])
    return {"id": tid, "requesterId": t["requester_id"], "category": t["category"], "priority": t["priority"],
            "title": t["title"], "description": t["description"], "status": t["status"], "version": 0,
            "createdAt": t["created_at"], "updatedAt": updated, "comments": comments, "_status_log": {}}


def _text(body: dict[str, Any], name: str, max_len: int) -> str:
    v = body.get(name)
    if not isinstance(v, str) or not v.strip() or len(v) > max_len:
        raise ProblemError(422, "validation", f"{name}: 1~{max_len}자", [{"field": name, "message": "invalid"}])
    return v


def _one_of(body: dict[str, Any], name: str, allowed: tuple[str, ...], default: str | None = None) -> str:
    v = body.get(name, default)
    if v not in allowed:
        raise ProblemError(422, "validation", f"{name}: {', '.join(allowed)} 중 하나",
                           [{"field": name, "message": "invalid"}])
    return v


def _only(body: dict[str, Any], allowed: set[str]) -> None:
    if not isinstance(body, dict):
        raise ProblemError(422, "validation", "JSON 객체가 아닙니다")
    extra = sorted(set(body) - allowed)
    if extra:
        raise ProblemError(422, "validation", f"모르는 필드: {extra[0]}", [{"field": extra[0], "message": "unknown"}])


def ticket_view(t: dict[str, Any], detail: bool = False) -> dict[str, Any]:
    out = {k: copy.deepcopy(v) for k, v in t.items() if not k.startswith("_") and k != "comments"}
    out["commentCount"] = len(t["comments"])
    if detail:
        out["comments"] = copy.deepcopy(t["comments"])
    return out


class TicketsMixin:
    """State에 붙는 IT 티켓 규칙(erp.yaml tickets)."""

    tickets: dict[str, dict[str, Any]]

    def is_ticket_handler(self, emp_id: str) -> bool:
        return self.has_role(emp_id, self.erp_role("ticket_handler"))  # type: ignore[attr-defined]

    def visible_ticket(self, emp_id: str, tid: str) -> dict[str, Any]:
        t = self.tickets.get(tid)
        if t is None or (t["requesterId"] != emp_id and not self.is_ticket_handler(emp_id)):
            raise ProblemError(404, "not-found", "티켓이 없습니다")
        return t

    def list_tickets(self, emp_id: str, box: str, status: str | None, limit: int) -> list[dict[str, Any]]:
        if box not in ("mine", "all"):
            raise ProblemError(422, "validation", "box: mine, all 중 하나", [{"field": "box", "message": "invalid"}])
        if status is not None and status not in TICKET_STATUSES:
            raise ProblemError(422, "validation", "status: 모르는 상태", [{"field": "status", "message": "invalid"}])
        if box == "all" and not self.is_ticket_handler(emp_id):
            raise ProblemError(403, "forbidden", "티켓 담당만 전체를 봅니다")
        rows = [t for t in self.tickets.values()
                if (box == "all" or t["requesterId"] == emp_id) and (status is None or t["status"] == status)]
        rows.sort(key=lambda t: t["updatedAt"], reverse=True)
        return [ticket_view(t) for t in rows[: max(1, min(limit, 100))]]

    def create_ticket(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        _only(body, {"category", "title", "description", "priority"})
        category = _one_of(body, "category", TICKET_CATEGORIES)
        priority = _one_of(body, "priority", TICKET_PRIORITIES, "normal")
        title, description = _text(body, "title", 100), _text(body, "description", 2000)
        at = iso(now())
        t = {"id": new_id("tkt"), "requesterId": p.employee_id, "category": category, "priority": priority,
             "title": title, "description": description, "status": "open", "version": 0, "createdAt": at,
             "updatedAt": at, "comments": [], "_status_log": {}}
        self.tickets[t["id"]] = t
        view = ticket_view(t)
        return (f"IT 티켓 '{title}'을 올립니다", [{"op": "create", "resource": "ticket", "resourceId": t["id"],
                                             "before": None, "after": view}], True, view)

    def undo_create_ticket(self, tid: str) -> tuple[str, list, dict]:
        t = self.tickets[tid]
        if t["status"] != "open" or t["comments"]:
            raise ProblemError(409, "undo-conflict", "그사이 댓글이 달렸거나 처리가 시작됐습니다")
        before = ticket_view(t)
        t["status"], t["version"], t["updatedAt"] = "cancelled", t["version"] + 1, iso(now())
        return "IT 티켓 작성을 되돌렸습니다(취소)", [{"op": "update", "resource": "ticket", "resourceId": tid,
                                               "before": before, "after": ticket_view(t)}], ticket_view(t)

    def comment_ticket(self, p: Principal, tid: str, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        t = self.visible_ticket(p.employee_id, tid)
        _only(body, {"body"})
        text = _text(body, "body", 2000)
        if t["status"] in ("closed", "cancelled"):
            raise ProblemError(409, "invalid-state", f"{t['status']} 티켓에는 댓글을 달 수 없습니다")
        at = iso(now())
        c = {"id": new_id("tcm"), "ticketId": tid, "authorId": p.employee_id, "body": text, "createdAt": at}
        t["comments"].append(c)
        t["updatedAt"] = at
        return (f"IT 티켓 '{t['title']}'에 댓글을 답니다", [{"op": "create", "resource": "ticket_comment",
                                                     "resourceId": c["id"], "before": None, "after": dict(c)}],
                True, dict(c))

    def undo_comment_ticket(self, cid: str) -> tuple[str, list, dict]:
        t = next(t for t in self.tickets.values() if any(c["id"] == cid for c in t["comments"]))
        if t["status"] in ("closed", "cancelled"):
            raise ProblemError(409, "undo-conflict", f"티켓이 {t['status']}입니다")
        c = next(c for c in t["comments"] if c["id"] == cid)
        t["comments"].remove(c)
        return "IT 티켓 댓글을 지웠습니다", [{"op": "delete", "resource": "ticket_comment", "resourceId": cid,
                                         "before": dict(c), "after": None}], dict(c)

    def change_ticket_status(self, p: Principal, tid: str, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        t = self.visible_ticket(p.employee_id, tid)
        if not self.is_ticket_handler(p.employee_id):
            raise ProblemError(403, "forbidden", "티켓 담당만 상태를 바꿉니다")
        _only(body, {"status", "version"})
        status = _one_of(body, "status", TICKET_STATUSES)
        version = body.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise ProblemError(422, "validation", "version: 0 이상의 정수", [{"field": "version", "message": "invalid"}])
        if version != t["version"]:
            raise ProblemError(409, "version-conflict", "그사이 티켓이 바뀌었습니다")
        if status not in TICKET_TRANSITIONS.get(t["status"], ()):
            raise ProblemError(409, "invalid-state", f"{t['status']}에서 {status}로 바꿀 수 없습니다")
        before = ticket_view(t)
        prev = t["status"]
        t["status"], t["version"], t["updatedAt"] = status, t["version"] + 1, iso(now())
        t["_status_log"][t["version"]] = prev
        return (f"IT 티켓 '{t['title']}'을 {status}로 바꿉니다",
                [{"op": "update", "resource": "ticket", "resourceId": tid, "before": before, "after": ticket_view(t)}],
                True, ticket_view(t))

    def undo_ticket_status(self, tid: str, version: int) -> tuple[str, list, dict]:
        t = self.tickets[tid]
        if t["version"] != version:
            raise ProblemError(409, "undo-conflict", "그사이 상태가 다시 바뀌었습니다")
        before = ticket_view(t)
        t["status"], t["version"], t["updatedAt"] = t["_status_log"][version], t["version"] + 1, iso(now())
        return "IT 티켓 상태 변경을 되돌렸습니다", [{"op": "update", "resource": "ticket", "resourceId": tid,
                                              "before": before, "after": ticket_view(t)}], ticket_view(t)


# ---------- 품질·영업 ----------

SEVERITIES = ("minor", "major", "critical")


def _int(body: dict[str, Any], name: str, lo: int, hi: int) -> int:
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ProblemError(422, "validation", f"{name}: {lo}~{hi} 정수", [{"field": name, "message": "invalid"}])
    return v


def _opt_text(body: dict[str, Any], name: str, max_len: int) -> str | None:
    if body.get(name) is None:
        return None
    v = body[name]
    if not isinstance(v, str) or len(v) > max_len:
        raise ProblemError(422, "validation", f"{name}: {max_len}자 이하", [{"field": name, "message": "invalid"}])
    return v


def defect_from_fixture(d: dict[str, Any], items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"id": d["id"], "createdBy": d["created_by"], "itemCode": d["item_code"],
            "itemName": items[d["item_code"]]["name"], "defectType": d["defect_type"], "severity": d["severity"],
            "quantity": d["quantity"], "location": d.get("location"), "lotNo": d.get("lot_no"),
            "description": d["description"], "status": d["status"], "version": 0,
            "confirmedBy": d.get("confirmed_by"), "createdAt": d["created_at"], "updatedAt": d["created_at"]}


class QualitySalesMixin:
    """State에 붙는 품질(불량 보고서)·영업(견적, 품목, 고객사) 규칙(erp.yaml quality·sales·catalog)."""

    features: set[str]
    items: dict[str, dict[str, Any]]
    customers: dict[str, dict[str, Any]]
    defect_reports: dict[str, dict[str, Any]]
    quotes: dict[str, dict[str, Any]]

    def need(self, feature: str) -> None:
        if feature not in self.features:
            raise ProblemError(404, "not-found", "없는 경로입니다")

    def _role(self, emp_id: str, key: str) -> bool:
        return self.has_role(emp_id, self.erp_role(key))  # type: ignore[attr-defined]

    # 품목·고객사
    def list_items(self, q: str | None, limit: int) -> list[dict[str, Any]]:
        rows = [i for i in self.items.values() if not q or q.lower() in i["code"].lower() or q in i["name"]]
        return [{"code": i["code"], "name": i["name"], "unit": i["unit"], "unitPrice": i["unit_price"],
                 "stock": i["stock"]} for i in rows[: max(1, min(limit, 100))]]

    def list_customers(self, emp_id: str, q: str | None, limit: int) -> list[dict[str, Any]]:
        self.need("sales")
        rep = self._role(emp_id, "sales_rep")
        rows = [c for c in self.customers.values() if not q or q in c["name"]]
        return [{"id": c["id"], "name": c["name"],
                 "contact": {"name": c["contact_name"], "email": c["contact_email"], "phone": c["contact_phone"]}
                 if rep else None} for c in rows[: max(1, min(limit, 100))]]

    # 불량 보고서
    def visible_defect(self, emp_id: str, rid: str) -> dict[str, Any]:
        self.need("quality")
        d = self.defect_reports.get(rid)
        if d is None or (d["createdBy"] != emp_id and not self._role(emp_id, "quality_reviewer")):
            raise ProblemError(404, "not-found", "불량 보고서가 없습니다")
        return d

    def list_defects(self, emp_id: str, box: str, status: str | None, limit: int) -> list[dict[str, Any]]:
        self.need("quality")
        if box not in ("mine", "all"):
            raise ProblemError(422, "validation", "box: mine, all 중 하나", [{"field": "box", "message": "invalid"}])
        if box == "all" and not self._role(emp_id, "quality_reviewer"):
            raise ProblemError(403, "forbidden", "품질 확인 역할만 전체를 봅니다")
        rows = [d for d in self.defect_reports.values()
                if (box == "all" or d["createdBy"] == emp_id) and (status is None or d["status"] == status)]
        rows.sort(key=lambda d: d["createdAt"], reverse=True)
        return [dict(d) for d in rows[: max(1, min(limit, 100))]]

    def create_defect(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        self.need("quality")
        _only(body, {"itemCode", "defectType", "severity", "quantity", "location", "lotNo", "description"})
        code = _text(body, "itemCode", 32)
        if code not in self.items:
            raise ProblemError(422, "validation", "없는 품목입니다", [{"field": "itemCode", "message": "unknown"}])
        at = iso(now())
        d = {"id": new_id("dfr"), "createdBy": p.employee_id, "itemCode": code, "itemName": self.items[code]["name"],
             "defectType": _text(body, "defectType", 50), "severity": _one_of(body, "severity", SEVERITIES),
             "quantity": _int(body, "quantity", 1, 1_000_000), "location": _opt_text(body, "location", 100),
             "lotNo": _opt_text(body, "lotNo", 50), "description": _text(body, "description", 1000),
             "status": "draft", "version": 0, "confirmedBy": None, "createdAt": at, "updatedAt": at}
        self.defect_reports[d["id"]] = d
        return (f"{d['itemName']} 불량 보고서 초안을 씁니다", [{"op": "create", "resource": "defect_report",
                "resourceId": d["id"], "before": None, "after": dict(d)}], True, dict(d))

    def undo_create_defect(self, rid: str) -> tuple[str, list, dict]:
        d = self.defect_reports[rid]
        if d["status"] != "draft":
            raise ProblemError(409, "undo-conflict", "그사이 확정되었습니다")
        before = dict(d)
        d["status"], d["version"], d["updatedAt"] = "cancelled", d["version"] + 1, iso(now())
        return "불량 보고서 초안을 되돌렸습니다(취소)", [{"op": "update", "resource": "defect_report", "resourceId": rid,
                                                 "before": before, "after": dict(d)}], dict(d)

    def confirm_defect(self, p: Principal, rid: str, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        d = self.visible_defect(p.employee_id, rid)
        if not self._role(p.employee_id, "quality_reviewer"):
            raise ProblemError(403, "forbidden", "품질 확인 역할만 확정합니다")
        _only(body, {"version"})
        version = _int(body, "version", 0, 1_000_000)
        if version != d["version"]:
            raise ProblemError(409, "version-conflict", "그사이 보고서가 바뀌었습니다")
        if d["status"] != "draft":
            raise ProblemError(409, "invalid-state", f"{d['status']} 보고서는 확정할 수 없습니다")
        before = dict(d)
        d["status"], d["version"], d["confirmedBy"], d["updatedAt"] = "confirmed", d["version"] + 1, p.employee_id, iso(now())
        return (f"{d['itemName']} 불량 보고서를 확정합니다", [{"op": "update", "resource": "defect_report", "resourceId": rid,
                "before": before, "after": dict(d)}], False, dict(d))

    # 견적
    def visible_quote(self, emp_id: str, qid: str) -> dict[str, Any]:
        self.need("sales")
        q = self.quotes.get(qid)
        if q is None or (q["createdBy"] != emp_id and not self._role(emp_id, "sales_rep")):
            raise ProblemError(404, "not-found", "견적이 없습니다")
        return q

    def list_quotes(self, emp_id: str, box: str, status: str | None, limit: int) -> list[dict[str, Any]]:
        self.need("sales")
        if box not in ("mine", "all"):
            raise ProblemError(422, "validation", "box: mine, all 중 하나", [{"field": "box", "message": "invalid"}])
        if box == "all" and not self._role(emp_id, "sales_rep"):
            raise ProblemError(403, "forbidden", "영업 역할만 전체를 봅니다")
        rows = [q for q in self.quotes.values()
                if (box == "all" or q["createdBy"] == emp_id) and (status is None or q["status"] == status)]
        rows.sort(key=lambda q: q["createdAt"], reverse=True)
        return [copy.deepcopy(q) for q in rows[: max(1, min(limit, 100))]]

    def create_quote(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        self.need("sales")
        if not self._role(p.employee_id, "sales_rep"):
            raise ProblemError(403, "forbidden", "영업 역할만 견적을 씁니다")
        _only(body, {"customerId", "lines", "validUntil", "note"})
        cid = _text(body, "customerId", 32)
        if cid not in self.customers:
            raise ProblemError(422, "validation", "없는 고객사입니다", [{"field": "customerId", "message": "unknown"}])
        raw = body.get("lines")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise ProblemError(422, "validation", "lines: 1~20줄", [{"field": "lines", "message": "invalid"}])
        lines = []
        for i, ln in enumerate(raw):
            if not isinstance(ln, dict) or set(ln) - {"itemCode", "quantity"}:
                raise ProblemError(422, "validation", f"lines[{i}]: itemCode, quantity만", [{"field": f"lines/{i}", "message": "invalid"}])
            code = _text(ln, "itemCode", 32)
            if code not in self.items:
                raise ProblemError(422, "validation", "없는 품목입니다", [{"field": f"lines/{i}/itemCode", "message": "unknown"}])
            qty = _int(ln, "quantity", 1, 1_000_000)
            price = self.items[code]["unit_price"]
            lines.append({"itemCode": code, "itemName": self.items[code]["name"], "quantity": qty, "unitPrice": price,
                          "amount": qty * price})
        valid = body.get("validUntil")
        if valid is None:
            valid = (now().date() + timedelta(days=30)).isoformat()
        else:
            try:
                if date.fromisoformat(str(valid)) < now().date():
                    raise ValueError
            except ValueError:
                raise ProblemError(422, "validation", "validUntil: 오늘이나 그 뒤 날짜", [{"field": "validUntil", "message": "invalid"}])
        at = iso(now())
        q = {"id": new_id("quo"), "createdBy": p.employee_id, "customerId": cid, "customerName": self.customers[cid]["name"],
             "lines": lines, "totalAmount": sum(ln["amount"] for ln in lines), "validUntil": valid,
             "note": _opt_text(body, "note", 500), "status": "draft", "version": 0, "issuedBy": None,
             "createdAt": at, "updatedAt": at}
        self.quotes[q["id"]] = q
        return (f"{q['customerName']} 견적 초안({q['totalAmount']:,}원)을 씁니다",
                [{"op": "create", "resource": "quote", "resourceId": q["id"], "before": None, "after": copy.deepcopy(q)}],
                True, copy.deepcopy(q))

    def undo_create_quote(self, qid: str) -> tuple[str, list, dict]:
        q = self.quotes[qid]
        if q["status"] != "draft":
            raise ProblemError(409, "undo-conflict", "그사이 발행되었습니다")
        before = copy.deepcopy(q)
        q["status"], q["version"], q["updatedAt"] = "cancelled", q["version"] + 1, iso(now())
        return "견적 초안을 되돌렸습니다(취소)", [{"op": "update", "resource": "quote", "resourceId": qid,
                                            "before": before, "after": copy.deepcopy(q)}], copy.deepcopy(q)

    def issue_quote(self, p: Principal, qid: str, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        q = self.visible_quote(p.employee_id, qid)
        if not self._role(p.employee_id, "sales_rep"):
            raise ProblemError(403, "forbidden", "영업 역할만 발행합니다")
        _only(body, {"version"})
        version = _int(body, "version", 0, 1_000_000)
        if version != q["version"]:
            raise ProblemError(409, "version-conflict", "그사이 견적이 바뀌었습니다")
        if q["status"] != "draft":
            raise ProblemError(409, "invalid-state", f"{q['status']} 견적은 발행할 수 없습니다")
        if date.fromisoformat(q["validUntil"]) < now().date():
            raise ProblemError(409, "invalid-state", "유효 기한이 지났습니다")
        before = copy.deepcopy(q)
        q["status"], q["version"], q["issuedBy"], q["updatedAt"] = "issued", q["version"] + 1, p.employee_id, iso(now())
        return (f"{q['customerName']} 견적을 발행합니다", [{"op": "update", "resource": "quote", "resourceId": qid,
                "before": before, "after": copy.deepcopy(q)}], False, copy.deepcopy(q))


@dataclass
class State(TicketsMixin, QualitySalesMixin):
    pack: dict[str, Any]
    employees: dict[str, dict[str, Any]]
    units: dict[str, dict[str, Any]]
    forms: dict[str, dict[str, Any]]
    rooms: dict[str, dict[str, Any]]
    balances: dict[str, dict[str, Any]]
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    delegations: dict[str, dict[str, Any]] = field(default_factory=dict)
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    features: set[str] = field(default_factory=set)
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    customers: dict[str, dict[str, Any]] = field(default_factory=dict)
    defect_reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)

    # ---------- 적재 ----------
    @classmethod
    def from_pack(cls, pack_dir: Path) -> "State":
        org = yaml.safe_load((pack_dir / "org.yaml").read_text(encoding="utf-8"))
        forms = yaml.safe_load((pack_dir / "forms.yaml").read_text(encoding="utf-8"))
        emps = load(pack_dir / "fixtures/employees.json")["employees"]
        rooms = load(pack_dir / "fixtures/rooms.json")["rooms"]
        bals = load(pack_dir / "fixtures/leave_balances.json")["balances"]
        tickets_file = pack_dir / "fixtures/tickets.json"
        tickets = load(tickets_file)["tickets"] if tickets_file.exists() else []

        def optional(name: str, key: str) -> list[dict[str, Any]]:
            f = pack_dir / f"fixtures/{name}.json"
            return load(f)[key] if f.exists() else []
        pack_yaml = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8"))
        units = {u["id"]: dict(u) for u in org["units"]}
        employees = {e["id"]: dict(e) for e in emps}
        for e in employees.values():
            if e["grade"] in ("team_leader", "division_head", "ceo"):
                units[e["unit_id"]]["head_id"] = e["id"]
        st = cls(
            pack={"org": org},
            employees=employees,
            units=units,
            forms={f["id"]: f for f in forms["forms"]},
            rooms={r["id"]: r for r in rooms},
            balances={b["employee_id"]: {**b, "annual_pending": 0.0} for b in bals},
        )
        for e in employees.values():
            e["roles"] = st._roles_of(e)
        for t in tickets:
            st.tickets[t["id"]] = ticket_from_fixture(t)
        st.features = set(pack_yaml.get("requires_erp_features", []))
        st.items = {i["code"]: i for i in optional("items", "items")}
        st.customers = {c["id"]: c for c in optional("customers", "customers")}
        for d in optional("defect_reports", "defect_reports"):
            st.defect_reports[d["id"]] = defect_from_fixture(d, st.items)
        return st

    # ---------- 조직 ----------
    def _grant_match(self, grant: Any, emp: dict[str, Any], roles: list[str] | None = None) -> bool:
        if grant == "all":
            return True
        if emp["unit_id"] in grant.get("units", []):
            return True
        if emp["grade"] in grant.get("grades", []):
            return True
        if roles is not None and set(roles) & set(grant.get("roles", [])):
            return True
        return False

    def _roles_of(self, emp: dict[str, Any]) -> list[str]:
        return [r["id"] for r in self.pack["org"]["roles"] if self._grant_match(r["grant"], emp)]

    def access_tags(self, emp_id: str) -> list[str]:
        emp = self.employee(emp_id)
        return [t["id"] for t in self.pack["org"]["access_tags"]
                if self._grant_match(t["grant"], emp, emp["roles"])]

    def has_role(self, emp_id: str, role: str) -> bool:
        return role in self.employee(emp_id)["roles"]

    def erp_role(self, key: str) -> str:
        """org.yaml erp_roles의 역할 ID(hr, auditor, ticket_handler). 없으면 hr_staff·auditor·it_admin입니다."""
        defaults = {"hr": "hr_staff", "auditor": "auditor", "ticket_handler": "it_admin",
                    "quality_reviewer": "quality_staff", "sales_rep": "sales_staff"}
        return self.pack["org"].get("erp_roles", {}).get(key, defaults[key])

    def can_register_for_others(self, emp_id: str) -> bool:
        """대결을 대신 등록·해지·전체 조회할 수 있는 역할(delegation_policy.registrable_by)."""
        return any(self.has_role(emp_id, r) for r in self.pack["org"]["delegation_policy"]["registrable_by"]
                   if r != "self")

    def employee(self, emp_id: str) -> dict[str, Any]:
        e = self.employees.get(emp_id)
        if e is None:
            raise ProblemError(404, "not-found", f"직원 {emp_id}가 없습니다")
        return e

    def employee_full(self, emp_id: str) -> dict[str, Any]:
        e = self.employee(emp_id)
        return {**self.employee_summary(emp_id), "employeeNo": e["employee_no"], "email": e["email"],
                "roles": e["roles"], "hiredOn": e["hired_on"]}

    def employee_summary(self, emp_id: str) -> dict[str, Any]:
        e = self.employee(emp_id)
        return {"id": e["id"], "name": e["name"], "unitId": e["unit_id"],
                "unitName": self.units[e["unit_id"]]["name"], "grade": e["grade"]}

    def unit_view(self, u: dict[str, Any]) -> dict[str, Any]:
        return {"id": u["id"], "name": u["name"], "kind": u["kind"], "parentId": u.get("parent"),
                "headId": u.get("head_id")}

    def _root_head(self) -> str:
        root = next(u for u in self.units.values() if "parent" not in u)
        return root["head_id"]

    def _resolve(self, step: str, requester: dict[str, Any]) -> str | None:
        unit = self.units[requester["unit_id"]]
        if step == "ceo":
            return self._root_head()
        if step == "team_leader":
            if unit["kind"] == "team" and unit.get("head_id") != requester["id"]:
                return unit["head_id"]
            step = "division_head"
        if step == "division_head":
            div = unit if unit["kind"] == "division" else self.units.get(unit.get("parent", ""), unit)
            head = div.get("head_id")
            if head is None or head == requester["id"]:
                ceo = self._root_head()
                return None if ceo == requester["id"] else ceo
            return head
        raise ValueError(step)

    def approval_line(self, form: dict[str, Any], requester: dict[str, Any], amount: int | None) -> list[str]:
        for rule in form["approval_line"]:
            w = rule["when"]
            if "amount_lte" in w and not (amount is not None and amount <= w["amount_lte"]):
                continue
            if "amount_gt" in w and not (amount is not None and amount > w["amount_gt"]):
                continue
            line: list[str] = []
            for s in rule["steps"]:
                a = self._resolve(s, requester)
                if a and a != requester["id"] and a not in line:
                    line.append(a)
            return line
        raise ProblemError(422, "form-validation-failed", "맞는 결재선 규칙이 없습니다")

    # ---------- 감사·알림 ----------
    def record_audit(self, p: Principal, kind: str, operation: str, result: str, *,
                     action_id: str | None = None, undo_of: str | None = None,
                     on_behalf_of: str | None = None, delegation_id: str | None = None,
                     problem: str | None = None, detail: str | None = None) -> None:
        self.audit.append({
            "eventId": new_id("evt"), "occurredAt": iso(now()), "source": "erp", "kind": kind,
            "actor": {"employeeId": p.employee_id, "viaDelegationToken": p.via_delegation_token,
                      "channel": p.channel, "agentId": p.agent_id},
            "onBehalfOf": on_behalf_of, "delegationId": delegation_id,
            "conversationId": p.conversation_id, "actionId": action_id, "undoOf": undo_of,
            "operation": operation, "result": result,
            "problemType": f"urn:problem:{problem}" if problem else None, "detail": detail,
        })

    def notify(self, to: str, kind: str, message: str, document_id: str | None = None,
               delegation_id: str | None = None) -> None:
        self.notifications.append({"id": new_id("ntf"), "to": to, "kind": kind, "message": message,
                                   "documentId": document_id, "delegationId": delegation_id,
                                   "createdAt": iso(now()), "read": False})

    # ---------- 연차 ----------
    def balance_view(self, emp_id: str) -> dict[str, Any]:
        b = self.balances.get(emp_id) or {"employee_id": emp_id, "year": now().year, "annual_total": 0.0,
                                          "annual_used": 0.0, "annual_pending": 0.0}
        return {"employeeId": emp_id, "year": b["year"], "annualTotal": b["annual_total"],
                "annualUsed": b["annual_used"], "annualPending": b["annual_pending"],
                "annualRemaining": b["annual_total"] - b["annual_used"] - b["annual_pending"]}

    @staticmethod
    def leave_days(fields: dict[str, Any]) -> float:
        start = parse_date(fields["start_date"], "start_date")
        end = parse_date(fields["end_date"], "end_date")
        if end < start:
            raise ProblemError(422, "form-validation-failed", "end_date가 start_date보다 앞입니다",
                               [{"field": "end_date", "message": "before start_date"}])
        if fields["leave_type"] in ("half_am", "half_pm"):
            if start != end:
                raise ProblemError(422, "form-validation-failed", "반차는 하루만 씁니다",
                                   [{"field": "end_date", "message": "must equal start_date"}])
            return 0.5
        if fields["leave_type"] != "annual":
            return 0.0
        days, d = 0, start
        while d <= end:
            if d.weekday() < 5:
                days += 1
            d += timedelta(days=1)
        return float(days)

    # ---------- 결재 문서 ----------
    def doc_view(self, d: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in d.items() if not k.startswith("_")}
        return copy.deepcopy(out)

    def visible_doc(self, emp_id: str, doc_id: str) -> dict[str, Any]:
        d = self.documents.get(doc_id)
        if d is None:
            raise ProblemError(404, "not-found", "결재 문서가 없습니다")
        approvers = {s["approverId"] for s in d["steps"]}
        if emp_id == d["requesterId"] or emp_id in approvers:
            return d
        if any(self._valid_delegation(dl, d, now()) for dl in self.delegations.values()
               if dl["delegateId"] == emp_id and dl["delegatorId"] in approvers):
            return d
        if any(s.get("actedBy") == emp_id for s in d["steps"]):
            return d
        raise ProblemError(404, "not-found", "결재 문서가 없습니다")

    def create_document(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        form = self.forms.get(body.get("formId", ""))
        if form is None:
            raise ProblemError(422, "validation", "없는 양식입니다", [{"field": "formId", "message": "unknown"}])
        fields = body.get("fields") or {}
        errs = [{"field": "/".join(map(str, e.absolute_path)) or e.validator, "message": e.message}
                for e in Draft202012Validator(form["fields"]).iter_errors(fields)]
        if errs:
            raise ProblemError(422, "form-validation-failed", "양식 입력이 올바르지 않습니다", errs)
        product_of = form.get("amount_product_of")
        if product_of:
            want = 1
            for name in product_of:
                want *= fields[name]
            if fields[form["amount_field"]] != want:
                raise ProblemError(422, "form-validation-failed", f"{form['amount_field']}가 {' × '.join(product_of)}"
                                   f"({want})와 다릅니다", [{"field": form["amount_field"], "message": "mismatch"}])
        requester = self.employee(p.employee_id)
        amount = fields.get(form["amount_field"]) if form.get("amount_field") else None
        days = 0.0
        if form.get("effects", {}).get("on_final_approval") == "deduct_leave_balance":
            days = self.leave_days(fields)
            if days > self.balance_view(requester["id"])["annualRemaining"]:
                raise ProblemError(422, "leave-balance-insufficient",
                                   f"필요 {days}일, 남은 {self.balance_view(requester['id'])['annualRemaining']}일")
        line = self.approval_line(form, requester, amount)
        t = now()
        doc_id = new_id("doc")
        steps = [{"order": i + 1, "approverId": a, "status": "pending" if i == 0 else "waiting",
                  "actedBy": None, "onBehalfOf": None, "delegationId": None, "actedAt": None, "comment": None}
                 for i, a in enumerate(line)]
        doc = {"id": doc_id, "formId": form["id"], "title": body.get("title") or f"{form['name']} - {requester['name']}",
               "requesterId": requester["id"], "status": "in_progress" if steps else "approved",
               "fields": copy.deepcopy(fields), "amount": amount, "steps": steps,
               "currentStep": 1 if steps else None, "version": 1, "createdAt": iso(t), "updatedAt": iso(t),
               "_leave_days": days}
        self.documents[doc_id] = doc
        if days and steps:
            self.balances[requester["id"]]["annual_pending"] += days
        elif days:
            self.balances[requester["id"]]["annual_used"] += days
        if steps:
            self.notify(steps[0]["approverId"], "approval_turn", f"결재 차례: {doc['title']}", doc_id)
        change = {"op": "create", "resource": "approval_document", "resourceId": doc_id, "before": None,
                  "after": self.doc_view(doc)}
        return f"{form['name']} 결재를 올립니다(결재선 {len(steps)}단계)", [change], True, self.doc_view(doc)

    def undo_create_document(self, doc_id: str) -> tuple[str, list, dict]:
        d = self.documents[doc_id]
        if d["status"] != "in_progress" or any(s["status"] != "pending" and s["status"] != "waiting"
                                               for s in d["steps"]):
            raise ProblemError(409, "undo-conflict", "이미 결재가 진행됐거나 끝난 문서입니다")
        before = self.doc_view(d)
        self._close_document(d, "withdrawn")
        return "결재 요청을 되돌렸습니다(회수)", [{"op": "update", "resource": "approval_document",
                                         "resourceId": doc_id, "before": before, "after": self.doc_view(d)}], self.doc_view(d)

    def _close_document(self, d: dict[str, Any], status: str) -> None:
        was = d["status"]
        d["status"] = status
        d["currentStep"] = None
        d["version"] += 1
        d["updatedAt"] = iso(now())
        days = d.get("_leave_days", 0.0)
        bal = self.balances.get(d["requesterId"])
        if days and bal:
            if was == "in_progress" and status in ("withdrawn", "rejected"):
                bal["annual_pending"] -= days
            elif was == "in_progress" and status == "approved":
                bal["annual_pending"] -= days
                bal["annual_used"] += days
            elif was == "approved" and status == "withdrawn":
                bal["annual_used"] -= days

    def _valid_delegation(self, dl: dict[str, Any], d: dict[str, Any], at: datetime) -> bool:
        return self._delegation_problem(dl, d, at) is None

    def _delegation_problem(self, dl: dict[str, Any], d: dict[str, Any], at: datetime) -> str | None:
        if dl["revokedAt"]:
            return "delegation-revoked"
        if not (datetime.fromisoformat(dl["startsAt"]) <= at <= datetime.fromisoformat(dl["endsAt"])):
            return "delegation-out-of-period"
        types = dl["scope"]["formTypes"]
        if "*" not in types and d["formId"] not in types:
            return "delegation-out-of-scope"
        limit = dl["scope"].get("maxAmount")
        if limit is not None and d.get("amount") is not None and d["amount"] > limit:
            return "delegation-out-of-scope"
        return None

    def decide(self, p: Principal, doc_id: str, body: dict[str, Any], approve: bool) -> tuple[str, list, bool, dict]:
        d = self.documents.get(doc_id)
        if d is None:
            raise ProblemError(404, "not-found", "결재 문서가 없습니다")
        if d["status"] != "in_progress":
            raise ProblemError(409, "invalid-state", f"문서 상태가 {d['status']}입니다")
        if p.employee_id == d["requesterId"]:
            raise ProblemError(403, "self-approval-forbidden")
        step = d["steps"][d["currentStep"] - 1]
        approver = step["approverId"]
        delegation_id = None
        if p.employee_id != approver:
            t = now()
            direct = [dl for dl in self.delegations.values()
                      if dl["delegatorId"] == approver and dl["delegateId"] == p.employee_id]
            if not direct:
                mids = {dl["delegateId"] for dl in self.delegations.values() if dl["delegatorId"] == approver}
                chained = any(dl["delegatorId"] in mids and dl["delegateId"] == p.employee_id
                              for dl in self.delegations.values())
                if chained:
                    raise ProblemError(403, "redelegation-not-allowed")
                if any(s["approverId"] == p.employee_id for s in d["steps"]):
                    raise ProblemError(403, "not-current-approver")
                raise ProblemError(404, "not-found", "결재 문서가 없습니다")
            problems = [self._delegation_problem(dl, d, t) for dl in direct]
            valid = [dl for dl, pr in zip(direct, problems) if pr is None]
            if not valid:
                for code in ("delegation-out-of-scope", "delegation-out-of-period", "delegation-revoked"):
                    if code in problems:
                        raise ProblemError(403, code)
                raise ProblemError(403, "delegation-not-found")
            delegation_id = valid[0]["id"]
        if body.get("version") != d["version"]:
            raise ProblemError(409, "version-conflict", f"현재 version은 {d['version']}입니다")
        before = self.doc_view(d)
        step.update({"status": "approved" if approve else "rejected", "actedBy": p.employee_id,
                     "onBehalfOf": approver if delegation_id else None, "delegationId": delegation_id,
                     "actedAt": iso(now()), "comment": body.get("comment")})
        if delegation_id:
            self.notify(approver, "delegated_decision",
                        f"대결 처리(후열): {self.employees[p.employee_id]['name']}님이 '{d['title']}'을 "
                        f"{'승인' if approve else '반려'}했습니다", doc_id, delegation_id)
        if not approve:
            self._close_document(d, "rejected")
            self.notify(d["requesterId"], "approval_result", f"반려: {d['title']}", doc_id)
        elif d["currentStep"] == len(d["steps"]):
            self._close_document(d, "approved")
            self.notify(d["requesterId"], "approval_result", f"승인 완료: {d['title']}", doc_id)
        else:
            d["currentStep"] += 1
            d["steps"][d["currentStep"] - 1]["status"] = "pending"
            d["version"] += 1
            d["updatedAt"] = iso(now())
            self.notify(d["steps"][d["currentStep"] - 1]["approverId"], "approval_turn",
                        f"결재 차례: {d['title']}", doc_id)
        d["_last_delegation"] = delegation_id
        d["_last_on_behalf"] = approver if delegation_id else None
        verb = "승인" if approve else "반려"
        who = f"(대결: {self.employees[approver]['name']} 대신)" if delegation_id else ""
        return (f"'{d['title']}'을 {verb}합니다{who}",
                [{"op": "update", "resource": "approval_document", "resourceId": doc_id, "before": before,
                  "after": self.doc_view(d)}], False, self.doc_view(d))

    def withdraw(self, p: Principal, doc_id: str) -> tuple[str, list, bool, dict]:
        d = self.visible_doc(p.employee_id, doc_id)
        if d["requesterId"] != p.employee_id:
            raise ProblemError(403, "forbidden", "요청자 본인만 회수합니다")
        before = self.doc_view(d)
        if d["status"] == "in_progress":
            self._close_document(d, "withdrawn")
        elif d["status"] == "approved" and d.get("_leave_days") and \
                parse_date(d["fields"]["start_date"], "start_date") > now().date():
            self._close_document(d, "withdrawn")
        else:
            raise ProblemError(409, "invalid-state", f"문서 상태가 {d['status']}라 회수할 수 없습니다")
        return (f"'{d['title']}'을 회수합니다", [{"op": "update", "resource": "approval_document",
                                              "resourceId": doc_id, "before": before, "after": self.doc_view(d)}],
                False, self.doc_view(d))

    def list_documents(self, emp_id: str, box: str, status: str | None) -> list[dict[str, Any]]:
        t = now()
        out = []
        for d in self.documents.values():
            cur = d["steps"][d["currentStep"] - 1] if d["currentStep"] else None
            if box == "outbox":
                ok = d["requesterId"] == emp_id
            elif box == "inbox":
                ok = cur is not None and cur["approverId"] == emp_id
            elif box == "delegated":
                ok = cur is not None and d["requesterId"] != emp_id and any(
                    dl["delegatorId"] == cur["approverId"] and dl["delegateId"] == emp_id
                    and self._valid_delegation(dl, d, t) for dl in self.delegations.values())
            else:
                ok = any(s["actedBy"] == emp_id for s in d["steps"])
            if ok and (status is None or d["status"] == status):
                out.append(self.doc_view(d))
        return sorted(out, key=lambda x: x["createdAt"], reverse=True)

    # ---------- 대결 ----------
    def delegation_view(self, dl: dict[str, Any]) -> dict[str, Any]:
        t = now()
        if dl["revokedAt"]:
            status = "revoked"
        elif t < datetime.fromisoformat(dl["startsAt"]):
            status = "scheduled"
        elif t > datetime.fromisoformat(dl["endsAt"]):
            status = "expired"
        else:
            status = "active"
        return {**{k: copy.deepcopy(v) for k, v in dl.items() if not k.startswith("_")}, "status": status}

    def create_delegation(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        policy = self.pack["org"]["delegation_policy"]
        delegator = body.get("delegatorId") or p.employee_id
        if delegator != p.employee_id and not self.can_register_for_others(p.employee_id):
            raise ProblemError(403, "delegation-registrar-forbidden")
        if delegator not in self.employees:
            raise ProblemError(422, "validation", "없는 위임자입니다", [{"field": "delegatorId", "message": "unknown"}])
        delegate = body.get("delegateId")
        if delegate not in self.employees:
            raise ProblemError(422, "validation", "없는 대리인입니다", [{"field": "delegateId", "message": "unknown"}])
        if delegate == delegator:
            raise ProblemError(422, "delegation-self")
        starts, ends = parse_dt(body.get("startsAt"), "startsAt"), parse_dt(body.get("endsAt"), "endsAt")
        if starts >= ends:
            raise ProblemError(422, "validation", "시작이 끝보다 앞이어야 합니다", [{"field": "endsAt", "message": "<= startsAt"}])
        if ends <= now():
            raise ProblemError(422, "validation", "끝이 이미 지났습니다", [{"field": "endsAt", "message": "past"}])
        if ends - starts > timedelta(days=policy["max_period_days"]):
            raise ProblemError(422, "delegation-period-too-long", f"최대 {policy['max_period_days']}일")
        scope = body.get("scope") or {}
        types = scope.get("formTypes") or []
        if not types or any(t != "*" and t not in self.forms for t in types):
            raise ProblemError(422, "validation", "formTypes가 올바르지 않습니다", [{"field": "scope.formTypes", "message": "unknown form"}])
        dl_id = new_id("dlg")
        dl = {"id": dl_id, "delegatorId": delegator, "delegateId": delegate, "startsAt": iso(starts),
              "endsAt": iso(ends), "scope": {"formTypes": list(types), "maxAmount": scope.get("maxAmount")},
              "reason": body.get("reason", ""), "registeredBy": p.employee_id, "revokedAt": None,
              "revokedBy": None, "createdAt": iso(now())}
        self.delegations[dl_id] = dl
        self.notify(delegate, "delegation_registered",
                    f"{self.employees[delegator]['name']}님의 결재 대결을 맡았습니다({dl['startsAt'][:10]}~{dl['endsAt'][:10]})",
                    delegation_id=dl_id)
        view = self.delegation_view(dl)
        return (f"{self.employees[delegator]['name']}님의 결재를 {self.employees[delegate]['name']}님이 대신합니다"
                f"({dl['startsAt'][:16]} ~ {dl['endsAt'][:16]}, 양식 {', '.join(types)})",
                [{"op": "create", "resource": "delegation", "resourceId": dl_id, "before": None, "after": view}],
                True, view)

    def delegation_used(self, dl_id: str) -> bool:
        return any(s.get("delegationId") == dl_id for d in self.documents.values() for s in d["steps"])

    def undo_create_delegation(self, dl_id: str, by: str) -> tuple[str, list, dict]:
        dl = self.delegations[dl_id]
        if self.delegation_used(dl_id):
            raise ProblemError(409, "undo-conflict", "이 위임으로 이미 결재한 문서가 있습니다")
        if dl["revokedAt"]:
            raise ProblemError(409, "undo-conflict", "이미 해지된 위임입니다")
        before = self.delegation_view(dl)
        dl["revokedAt"], dl["revokedBy"] = iso(now()), by
        return "대결 위임 등록을 되돌렸습니다", [{"op": "update", "resource": "delegation", "resourceId": dl_id,
                                          "before": before, "after": self.delegation_view(dl)}], self.delegation_view(dl)

    def can_see_delegation(self, emp_id: str, dl: dict[str, Any]) -> bool:
        return emp_id in (dl["delegatorId"], dl["delegateId"], dl["registeredBy"]) or self.can_register_for_others(emp_id)

    def revoke_delegation(self, p: Principal, dl_id: str) -> tuple[str, list, bool, dict]:
        dl = self.delegations.get(dl_id)
        if dl is None or not self.can_see_delegation(p.employee_id, dl):
            raise ProblemError(404, "not-found", "위임이 없습니다")
        if p.employee_id != dl["delegatorId"] and not self.can_register_for_others(p.employee_id):
            raise ProblemError(403, "forbidden", "위임자 본인이나 등록 권한이 있는 역할만 해지합니다")
        view = self.delegation_view(dl)
        if view["status"] in ("revoked", "expired"):
            raise ProblemError(409, "invalid-state", f"이미 {view['status']}입니다")
        dl["revokedAt"], dl["revokedBy"] = iso(now()), p.employee_id
        return "대결 위임을 해지합니다", [{"op": "update", "resource": "delegation", "resourceId": dl_id,
                                     "before": view, "after": self.delegation_view(dl)}], False, self.delegation_view(dl)

    # ---------- 회의실 ----------
    def _overlap(self, room_id: str, s: datetime, e: datetime, ignore: str | None = None) -> bool:
        for r in self.reservations.values():
            if r["roomId"] == room_id and r["status"] == "confirmed" and r["id"] != ignore:
                if datetime.fromisoformat(r["startsAt"]) < e and s < datetime.fromisoformat(r["endsAt"]):
                    return True
        return False

    def validate_slot(self, s: datetime, e: datetime) -> None:
        sk, ek = s.astimezone(KST), e.astimezone(KST)
        bad = None
        if s >= e:
            bad = "시작이 끝보다 앞이어야 합니다"
        elif sk.minute % 30 or ek.minute % 30 or sk.second or ek.second:
            bad = "30분 단위로 예약합니다"
        elif sk.date() != ek.date():
            bad = "같은 날 안에서 예약합니다"
        elif e - s > timedelta(hours=4):
            bad = "최대 4시간입니다"
        elif s <= now():
            bad = "지난 시각은 예약할 수 없습니다"
        if bad:
            raise ProblemError(422, "validation", bad, [{"field": "startsAt", "message": bad}])

    def reserve(self, p: Principal, body: dict[str, Any]) -> tuple[str, list, bool, dict]:
        room = self.rooms.get(body.get("roomId", ""))
        if room is None:
            raise ProblemError(422, "validation", "없는 회의실입니다", [{"field": "roomId", "message": "unknown"}])
        s, e = parse_dt(body.get("startsAt"), "startsAt"), parse_dt(body.get("endsAt"), "endsAt")
        self.validate_slot(s, e)
        if self._overlap(room["id"], s, e):
            raise ProblemError(409, "room-conflict", f"{room['name']}에 겹치는 예약이 있습니다")
        rid = new_id("rsv")
        r = {"id": rid, "roomId": room["id"], "reservedBy": p.employee_id, "startsAt": iso(s), "endsAt": iso(e),
             "title": body.get("title", ""), "attendees": body.get("attendees"), "status": "confirmed"}
        self.reservations[rid] = r
        return (f"{room['name']}을 {r['startsAt'][:16]}~{r['endsAt'][11:16]}에 예약합니다",
                [{"op": "create", "resource": "room_reservation", "resourceId": rid, "before": None, "after": dict(r)}],
                True, dict(r))

    def cancel_reservation(self, p: Principal, rid: str) -> tuple[str, list, bool, dict]:
        r = self.reservations.get(rid)
        if r is None:
            raise ProblemError(404, "not-found", "예약이 없습니다")
        if r["reservedBy"] != p.employee_id:
            raise ProblemError(403, "forbidden", "예약자 본인만 취소합니다")
        if r["status"] != "confirmed":
            raise ProblemError(409, "invalid-state", "이미 취소된 예약입니다")
        before = dict(r)
        r["status"] = "cancelled"
        return (f"{self.rooms[r['roomId']]['name']} 예약({r['startsAt'][:16]})을 취소합니다",
                [{"op": "update", "resource": "room_reservation", "resourceId": rid, "before": before, "after": dict(r)}],
                True, dict(r))

    def undo_reserve(self, rid: str) -> tuple[str, list, dict]:
        r = self.reservations[rid]
        if r["status"] != "confirmed":
            raise ProblemError(409, "undo-conflict", "이미 취소된 예약입니다")
        if datetime.fromisoformat(r["startsAt"]) <= now():
            raise ProblemError(409, "undo-conflict", "예약 시작 시각이 지났습니다")
        before = dict(r)
        r["status"] = "cancelled"
        return "회의실 예약을 되돌렸습니다(취소)", [{"op": "update", "resource": "room_reservation", "resourceId": rid,
                                             "before": before, "after": dict(r)}], dict(r)

    def undo_cancel(self, rid: str) -> tuple[str, list, dict]:
        r = self.reservations[rid]
        s, e = datetime.fromisoformat(r["startsAt"]), datetime.fromisoformat(r["endsAt"])
        if r["status"] != "cancelled":
            raise ProblemError(409, "undo-conflict", "예약이 취소 상태가 아닙니다")
        if s <= now():
            raise ProblemError(409, "undo-conflict", "예약 시작 시각이 지났습니다")
        if self._overlap(r["roomId"], s, e, ignore=rid):
            raise ProblemError(409, "undo-conflict", "그 시간에 다른 예약이 들어왔습니다")
        before = dict(r)
        r["status"] = "confirmed"
        return "예약 취소를 되돌렸습니다", [{"op": "update", "resource": "room_reservation", "resourceId": rid,
                                       "before": before, "after": dict(r)}], dict(r)
