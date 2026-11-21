"""상태 있는 가짜 erp(FastAPI). contracts/openapi/erp.yaml을 따릅니다.

실행(contracts/에서): uv run uvicorn fakes.erp.app:app --port 8041
환경 변수: PACK_DIR(기본 packs/manufacturing), ERP_JWT_SECRET, ERP_DEMO_PASSWORD,
DELEGATION_TOKEN_PUBLIC_KEY(위임 토큰 검증용 PEM 경로), ERP_SERVICE_LOGIN_SECRET(없으면 서비스 로그인 경로 꺼짐)
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fakes.erp.domain import (
    TITLES,
    Action,
    Principal,
    ProblemError,
    State,
    iso,
    new_id,
    now,
    ticket_view,
)
from tools.common import ROOT

DEFAULT_SECRET = "fake-erp-only-not-a-real-secret-0000000000"


def problem(status: int, code: str, detail: str = "", errors: list | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": f"urn:problem:{code}", "title": TITLES.get(code, code), "status": status}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def body_hash(op: str, path: str, body: Any) -> str:
    raw = json.dumps({"op": op, "path": path, "body": body}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


SERVICE_LOGIN_TTL = 900


def create_app(pack_dir: Path | None = None, *, jwt_secret: str | None = None,
               demo_password: str | None = None, delegation_public_key: str | None = None,
               service_login_secret: str | None = None) -> FastAPI:
    pack_dir = pack_dir or Path(os.environ.get("PACK_DIR", ROOT / "packs/manufacturing"))
    secret = jwt_secret or os.environ.get("ERP_JWT_SECRET") or DEFAULT_SECRET
    password = demo_password or os.environ.get("ERP_DEMO_PASSWORD") or "demo"
    # 비었거나 공백뿐인 값은 설정되지 않은 것으로 봅니다(compose가 빈 문자열을 넘김).
    service_secret = (service_login_secret or os.environ.get("ERP_SERVICE_LOGIN_SECRET") or "").strip() or None
    if delegation_public_key is None and os.environ.get("DELEGATION_TOKEN_PUBLIC_KEY"):
        p = Path(os.environ["DELEGATION_TOKEN_PUBLIC_KEY"])
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            delegation_public_key = p.read_text()

    app = FastAPI(title="fake erp", version="0.1.0")
    st = State.from_pack(pack_dir)
    lock = threading.RLock()
    idem: dict[tuple[str, str], dict[str, Any]] = {}
    app.state.erp = st

    @app.exception_handler(ProblemError)
    async def _problem(_: Request, e: ProblemError) -> JSONResponse:
        return problem(e.status, e.code, e.detail, e.errors)

    # ---------- 인증 ----------
    def principal(request: Request, scope: str | None, *, human_only: bool = False,
                  scope_alts: list[str] | None = None) -> Principal:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise ProblemError(401, "unauthorized")
        token = auth[7:].strip()
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError:
            raise ProblemError(401, "unauthorized", "토큰 형식이 틀렸습니다")
        if alg == "HS256":
            try:
                claims = jwt.decode(token, secret, algorithms=["HS256"], audience="erp")
            except jwt.PyJWTError as e:
                raise ProblemError(401, "unauthorized", str(e))
            if claims.get("sub") not in st.employees:
                raise ProblemError(401, "unauthorized")
            slack = "slack" in (claims.get("amr") or [])
            if human_only and slack:
                raise ProblemError(403, "service-login-not-allowed")
            return Principal(employee_id=claims["sub"], via_service_login=slack)
        if alg == "ES256" and delegation_public_key:
            try:
                claims = jwt.decode(token, delegation_public_key, algorithms=["ES256"], audience="erp",
                                    issuer="gateway")
            except jwt.PyJWTError as e:
                raise ProblemError(401, "unauthorized", str(e))
            if claims.get("sub") not in st.employees:
                raise ProblemError(401, "unauthorized")
            if human_only:
                raise ProblemError(403, "delegation-token-not-allowed")
            scopes = frozenset(claims.get("scopes", []))
            wanted = [scope] + (scope_alts or []) if scope else []
            if wanted and not any(w in scopes for w in wanted):
                raise ProblemError(403, "scope-missing", f"필요한 scope: {scope}")
            return Principal(employee_id=claims["sub"], via_delegation_token=True, agent_id=claims.get("agt"),
                             conversation_id=claims.get("cid"), scopes=scopes)
        raise ProblemError(401, "unauthorized", "지원하지 않는 토큰입니다")

    # ---------- 쓰기 공통 ----------
    def run_write(request: Request, p: Principal, operation: str, body: Any,
                  fn: Callable[[State], tuple[str, list, bool, dict]],
                  undo_factory: Callable[[dict], Callable[[State], tuple[str, list, dict]] | None] | None = None,
                  resource_type: str = "", audit_extra: Callable[[State, dict], dict] | None = None) -> JSONResponse:
        dry = request.query_params.get("dryRun", "false").lower() == "true"
        with lock:
            if dry:
                shadow = copy.deepcopy(st)
                summary, changes, undoable, _ = fn(shadow)
                for c in changes:
                    if c["op"] == "create":
                        c["resourceId"] = None
                return JSONResponse({"dryRun": True, "operation": operation, "summary": summary,
                                     "changes": changes, "undoable": undoable, "warnings": []})
            key = request.headers.get("idempotency-key")
            if not key or not (8 <= len(key) <= 128):
                raise ProblemError(400, "idempotency-key-required")
            h = body_hash(operation, request.url.path, body)
            prev = idem.get((p.employee_id, key))
            if prev and time.time() - prev["at"] < 24 * 3600:
                if prev["hash"] != h:
                    raise ProblemError(422, "idempotency-key-reused")
                return JSONResponse(prev["body"], status_code=prev["status"])
            try:
                summary, changes, undoable, resource = fn(st)
            except ProblemError as e:
                st.record_audit(p, "erp.denied", operation, "conflict" if e.status == 409 else "denied",
                                problem=e.code, detail=e.detail or None)
                raise
            action_id = new_id("act")
            st.actions[action_id] = Action(
                id=action_id, operation=operation, actor=p, resource_type=resource_type,
                resource_id=resource.get("id", ""), undoable=undoable,
                undo=undo_factory(resource) if (undoable and undo_factory) else None, created_at=now())
            extra = audit_extra(st, resource) if audit_extra else {}
            st.record_audit(p, "erp.write", operation, "ok", action_id=action_id, **extra)
            out = {"actionId": action_id, "operation": operation, "summary": summary, "changes": changes,
                   "undoable": undoable, "resource": resource, "undoOf": None}
            idem[(p.employee_id, key)] = {"hash": h, "status": 201, "body": out, "at": time.time()}
            return JSONResponse(out, status_code=201)

    async def json_body(request: Request) -> Any:
        raw = await request.body()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ProblemError(422, "validation", "JSON 본문이 아닙니다")

    # ---------- 경로 ----------
    if os.environ.get("ERP_EVAL_RESET") == "1":
        @app.post("/api/v1/_eval/reset", status_code=204)
        def eval_reset() -> None:
            with lock:
                vars(st).update(vars(State.from_pack(pack_dir)))
                idem.clear()

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    async def login(request: Request) -> dict:
        body = await json_body(request)
        emp = st.employees.get(body.get("employeeNo", ""))
        if emp is None or body.get("password") != password:
            raise ProblemError(401, "unauthorized", "사번이나 비밀번호가 틀렸습니다")
        t = int(time.time())
        token = jwt.encode({"sub": emp["id"], "aud": "erp", "iss": "erp", "iat": t, "exp": t + 3600},
                           secret, algorithm="HS256")
        with lock:
            st.record_audit(Principal(emp["id"]), "auth.login", "login", "ok")
        return {"accessToken": token, "tokenType": "Bearer", "expiresIn": 3600,
                "employee": st.employee_full(emp["id"])}

    @app.post("/api/v1/auth/service-login")
    async def service_login(request: Request) -> dict:
        if not service_secret:
            raise ProblemError(404, "not-found", "없는 경로입니다")
        given = request.headers.get("x-service-login-secret", "")
        if not hmac.compare_digest(given.encode(), service_secret.encode()):
            raise ProblemError(401, "unauthorized", "서비스 비밀값이 틀렸습니다")
        body = await json_body(request)
        if not isinstance(body, dict) or set(body) != {"employeeId"} or not isinstance(body["employeeId"], str):
            raise ProblemError(422, "validation", "employeeId만 받습니다", [{"field": "employeeId", "message": "required"}])
        emp_id = body["employeeId"]
        if emp_id not in st.employees:
            raise ProblemError(422, "validation", "없는 직원입니다", [{"field": "employeeId", "message": "unknown"}])
        t = int(time.time())
        token = jwt.encode({"sub": emp_id, "aud": "erp", "iss": "erp", "iat": t, "exp": t + SERVICE_LOGIN_TTL,
                            "amr": ["slack"]}, secret, algorithm="HS256")
        with lock:
            st.record_audit(Principal(emp_id, via_service_login=True), "auth.login", "serviceLogin", "ok")
        return {"accessToken": token, "tokenType": "Bearer", "expiresIn": SERVICE_LOGIN_TTL,
                "employee": st.employee_full(emp_id)}

    @app.get("/api/v1/me")
    def me(request: Request) -> dict:
        p = principal(request, "profile:read")
        return st.employee_full(p.employee_id)

    @app.get("/api/v1/me/access-tags")
    def my_tags(request: Request) -> dict:
        p = principal(request, "profile:read")
        return {"employeeId": p.employee_id, "tags": st.access_tags(p.employee_id)}

    @app.get("/api/v1/org/units")
    def units(request: Request) -> dict:
        principal(request, "org:read")
        return {"items": [st.unit_view(u) for u in st.units.values()]}

    @app.get("/api/v1/employees")
    def search_employees(request: Request, q: str | None = None, unitId: str | None = None, limit: int = 20) -> dict:
        principal(request, "org:read")
        items = [st.employee_summary(e["id"]) for e in st.employees.values()
                 if (not q or q in e["name"]) and (not unitId or e["unit_id"] == unitId)]
        return {"items": items[: max(1, min(limit, 100))]}

    @app.get("/api/v1/employees/{employee_id}")
    def get_employee(request: Request, employee_id: str) -> dict:
        p = principal(request, "org:read")
        st.employee(employee_id)
        if p.employee_id == employee_id or st.has_role(p.employee_id, st.erp_role("hr")):
            return st.employee_full(employee_id)
        return st.employee_summary(employee_id)

    @app.get("/api/v1/approval-forms")
    def forms(request: Request) -> dict:
        principal(request, "approval:read")
        return {"items": [{"id": f["id"], "name": f["name"], "fieldsSchema": f["fields"],
                           "amountField": f.get("amount_field")} for f in st.forms.values()]}

    @app.get("/api/v1/approval-documents")
    def list_docs(request: Request, box: str, status: str | None = None, limit: int = 20) -> dict:
        p = principal(request, "approval:read")
        if box not in ("outbox", "inbox", "delegated", "done"):
            raise ProblemError(422, "validation", "box가 올바르지 않습니다")
        with lock:
            return {"items": st.list_documents(p.employee_id, box, status)[: max(1, min(limit, 100))]}

    @app.post("/api/v1/approval-documents")
    async def create_doc(request: Request) -> JSONResponse:
        body = await json_body(request)
        form_id = body.get("formId", "") if isinstance(body, dict) else ""
        p = principal(request, "approval:request", scope_alts=[f"approval:request:{form_id}"])
        return run_write(request, p, "createApprovalDocument", body, lambda s: s.create_document(p, body),
                         lambda r: (lambda s: s.undo_create_document(r["id"])), "approval_document")

    @app.get("/api/v1/approval-documents/{doc_id}")
    def get_doc(request: Request, doc_id: str) -> dict:
        p = principal(request, "approval:read")
        with lock:
            return st.doc_view(st.visible_doc(p.employee_id, doc_id))

    def decision_audit(s: State, r: dict) -> dict:
        d = s.documents[r["id"]]
        return {"delegation_id": d.get("_last_delegation"), "on_behalf_of": d.get("_last_on_behalf")}

    @app.post("/api/v1/approval-documents/{doc_id}/approve")
    async def approve(request: Request, doc_id: str) -> JSONResponse:
        p = principal(request, "approval:decide", human_only=True)
        body = await json_body(request)
        return run_write(request, p, "approveApprovalDocument", body, lambda s: s.decide(p, doc_id, body, True),
                         None, "approval_document", decision_audit)

    @app.post("/api/v1/approval-documents/{doc_id}/reject")
    async def reject(request: Request, doc_id: str) -> JSONResponse:
        p = principal(request, "approval:decide", human_only=True)
        body = await json_body(request)
        return run_write(request, p, "rejectApprovalDocument", body, lambda s: s.decide(p, doc_id, body, False),
                         None, "approval_document", decision_audit)

    @app.post("/api/v1/approval-documents/{doc_id}/withdraw")
    async def withdraw(request: Request, doc_id: str) -> JSONResponse:
        p = principal(request, "approval:withdraw")
        body = await json_body(request)
        return run_write(request, p, "withdrawApprovalDocument", body, lambda s: s.withdraw(p, doc_id),
                         None, "approval_document")

    @app.get("/api/v1/delegations")
    def list_delegations(request: Request, role: str, activeAt: str | None = None) -> dict:
        p = principal(request, "delegation:read")
        if role == "all" and not st.can_register_for_others(p.employee_id):
            raise ProblemError(403, "forbidden", "인사 담당만 전체를 봅니다")
        with lock:
            items = [st.delegation_view(d) for d in st.delegations.values()
                     if role == "all" or (role == "delegator" and d["delegatorId"] == p.employee_id)
                     or (role == "delegate" and d["delegateId"] == p.employee_id)]
        if activeAt:
            from fakes.erp.domain import parse_dt
            t = parse_dt(activeAt, "activeAt")
            from datetime import datetime
            items = [d for d in items if d["status"] != "revoked"
                     and datetime.fromisoformat(d["startsAt"]) <= t <= datetime.fromisoformat(d["endsAt"])]
        return {"items": items}

    @app.post("/api/v1/delegations")
    async def create_delegation(request: Request) -> JSONResponse:
        p = principal(request, "delegation:write")
        body = await json_body(request)
        return run_write(request, p, "createDelegation", body, lambda s: s.create_delegation(p, body),
                         lambda r: (lambda s: s.undo_create_delegation(r["id"], p.employee_id)), "delegation",
                         lambda s, r: {"delegation_id": r["id"]})

    @app.get("/api/v1/delegations/{dl_id}")
    def get_delegation(request: Request, dl_id: str) -> dict:
        p = principal(request, "delegation:read")
        d = st.delegations.get(dl_id)
        if d is None or not st.can_see_delegation(p.employee_id, d):
            raise ProblemError(404, "not-found")
        return st.delegation_view(d)

    @app.post("/api/v1/delegations/{dl_id}/revoke")
    async def revoke_delegation(request: Request, dl_id: str) -> JSONResponse:
        p = principal(request, "delegation:write")
        body = await json_body(request)
        return run_write(request, p, "revokeDelegation", body, lambda s: s.revoke_delegation(p, dl_id),
                         None, "delegation", lambda s, r: {"delegation_id": r["id"]})

    @app.get("/api/v1/delegations/{dl_id}/acted-documents")
    def acted_docs(request: Request, dl_id: str) -> dict:
        p = principal(request, "delegation:read")
        d = st.delegations.get(dl_id)
        if d is None or not st.can_see_delegation(p.employee_id, d):
            raise ProblemError(404, "not-found")
        with lock:
            return {"items": [st.doc_view(doc) for doc in st.documents.values()
                              if any(s.get("delegationId") == dl_id for s in doc["steps"])]}

    @app.get("/api/v1/leave/balance")
    def leave_balance(request: Request, employeeId: str | None = None) -> dict:
        p = principal(request, "leave:read")
        target = employeeId or p.employee_id
        if target != p.employee_id and not st.has_role(p.employee_id, st.erp_role("hr")):
            raise ProblemError(403, "forbidden", "본인 잔여만 봅니다")
        st.employee(target)
        with lock:
            return st.balance_view(target)

    @app.get("/api/v1/rooms")
    def rooms(request: Request, minCapacity: int | None = None) -> dict:
        principal(request, "room:read")
        return {"items": [r for r in st.rooms.values() if not minCapacity or r["capacity"] >= minCapacity]}

    @app.get("/api/v1/rooms/availability")
    def availability(request: Request, startsAt: str, endsAt: str, minCapacity: int | None = None) -> dict:
        principal(request, "room:read")
        from fakes.erp.domain import parse_dt
        s, e = parse_dt(startsAt, "startsAt"), parse_dt(endsAt, "endsAt")
        if s >= e:
            raise ProblemError(422, "validation", "시작이 끝보다 앞이어야 합니다")
        with lock:
            return {"items": [r for r in st.rooms.values()
                              if (not minCapacity or r["capacity"] >= minCapacity) and not st._overlap(r["id"], s, e)]}

    @app.get("/api/v1/room-reservations")
    def list_reservations(request: Request, mine: bool = True, roomId: str | None = None,
                          date: str | None = None) -> dict:
        p = principal(request, "room:read")
        with lock:
            items = [dict(r) for r in st.reservations.values()
                     if (not mine or r["reservedBy"] == p.employee_id) and (not roomId or r["roomId"] == roomId)
                     and (not date or r["startsAt"][:10] == date)]
        if not mine:
            for r in items:
                if r["reservedBy"] != p.employee_id:
                    r["title"] = "예약됨"
        return {"items": sorted(items, key=lambda r: r["startsAt"])}

    @app.post("/api/v1/room-reservations")
    async def reserve(request: Request) -> JSONResponse:
        p = principal(request, "room:write")
        body = await json_body(request)
        return run_write(request, p, "createRoomReservation", body, lambda s: s.reserve(p, body),
                         lambda r: (lambda s: s.undo_reserve(r["id"])), "room_reservation")

    @app.post("/api/v1/room-reservations/{rid}/cancel")
    async def cancel(request: Request, rid: str) -> JSONResponse:
        p = principal(request, "room:write")
        body = await json_body(request)
        return run_write(request, p, "cancelRoomReservation", body, lambda s: s.cancel_reservation(p, rid),
                         lambda r: (lambda s: s.undo_cancel(r["id"])), "room_reservation")

    # ---------- IT 티켓 ----------
    @app.get("/api/v1/tickets")
    def list_tickets(request: Request, box: str = "mine", status: str | None = None, limit: int = 20) -> dict:
        p = principal(request, "ticket:read")
        with lock:
            return {"items": st.list_tickets(p.employee_id, box, status, limit)}

    @app.get("/api/v1/tickets/{tid}")
    def get_ticket(request: Request, tid: str) -> dict:
        p = principal(request, "ticket:read")
        with lock:
            return ticket_view(st.visible_ticket(p.employee_id, tid), detail=True)

    @app.post("/api/v1/tickets")
    async def create_ticket(request: Request) -> JSONResponse:
        p = principal(request, "ticket:write")
        body = await json_body(request)
        return run_write(request, p, "createTicket", body, lambda s: s.create_ticket(p, body),
                         lambda r: (lambda s: s.undo_create_ticket(r["id"])), "ticket")

    @app.post("/api/v1/tickets/{tid}/comments")
    async def comment_ticket(request: Request, tid: str) -> JSONResponse:
        p = principal(request, "ticket:write")
        body = await json_body(request)
        return run_write(request, p, "addTicketComment", body, lambda s: s.comment_ticket(p, tid, body),
                         lambda r: (lambda s: s.undo_comment_ticket(r["id"])), "ticket_comment")

    @app.post("/api/v1/tickets/{tid}/status")
    async def ticket_status(request: Request, tid: str) -> JSONResponse:
        p = principal(request, "ticket:manage")
        body = await json_body(request)
        return run_write(request, p, "changeTicketStatus", body, lambda s: s.change_ticket_status(p, tid, body),
                         lambda r: (lambda s: s.undo_ticket_status(r["id"], r["version"])), "ticket")

    def action_view(a: Action) -> dict:
        return {"id": a.id, "operation": a.operation, "actorId": a.actor.employee_id,
                "viaDelegationToken": a.actor.via_delegation_token, "agentId": a.actor.agent_id,
                "conversationId": a.actor.conversation_id, "resourceType": a.resource_type,
                "resourceId": a.resource_id, "status": a.status, "undoable": a.undoable,
                "undoActionId": a.undo_action_id, "createdAt": iso(a.created_at)}

    def own_action(p: Principal, action_id: str) -> Action:
        a = st.actions.get(action_id)
        if a is None or a.actor.employee_id != p.employee_id:
            raise ProblemError(404, "not-found", "행동이 없습니다")
        return a

    @app.get("/api/v1/actions/{action_id}")
    def get_action(request: Request, action_id: str) -> dict:
        p = principal(request, "action:read")
        return action_view(own_action(p, action_id))

    @app.post("/api/v1/actions/{action_id}/undo")
    async def undo(request: Request, action_id: str) -> JSONResponse:
        p = principal(request, "action:undo")
        body = await json_body(request)
        a = own_action(p, action_id)

        def do_undo(s: State) -> tuple[str, list, bool, dict]:
            act = s.actions[action_id]
            if act.status == "undone":
                raise ProblemError(409, "already-undone")
            if not act.undoable or act.undo is None:
                raise ProblemError(409, "not-undoable")
            summary, changes, resource = act.undo(s)
            act.status = "undone"
            return summary, changes, False, resource

        dry = request.query_params.get("dryRun", "false").lower() == "true"
        resp = run_write(request, p, "undoAction", body, do_undo, None, a.resource_type)
        if not dry and resp.status_code == 201:
            out = json.loads(resp.body)
            if out.get("undoOf") is None:
                with lock:
                    out["undoOf"] = action_id
                    st.actions[action_id].undo_action_id = out["actionId"]
                    for ev in reversed(st.audit):
                        if ev.get("actionId") == out["actionId"]:
                            ev["kind"], ev["undoOf"] = "erp.undo", action_id
                            break
                    for v in idem.values():
                        if v["body"].get("actionId") == out["actionId"]:
                            v["body"] = out
                return JSONResponse(out, status_code=201)
        return resp

    @app.get("/api/v1/notifications")
    def notifications(request: Request, unreadOnly: bool = False) -> dict:
        p = principal(request, "notification:read")
        with lock:
            items = [{k: v for k, v in n.items() if k != "to"} for n in st.notifications
                     if n["to"] == p.employee_id and (not unreadOnly or not n["read"])]
        return {"items": list(reversed(items))}

    @app.get("/api/v1/audit-events")
    def audit_events(request: Request, actorId: str | None = None, actionId: str | None = None,
                     since: str | None = None, limit: int = 100) -> dict:
        p = principal(request, "audit:read", human_only=True)
        if not st.has_role(p.employee_id, st.erp_role("auditor")):
            raise ProblemError(403, "forbidden", "감사 조회 역할만 봅니다")
        with lock:
            items = [e for e in st.audit if (not actorId or e["actor"]["employeeId"] == actorId)
                     and (not actionId or e["actionId"] == actionId) and (not since or e["occurredAt"] >= since)]
        return {"items": items[-max(1, min(limit, 500)):]}

    return app


app = create_app()
