"""사람 화면 경로: 결재함·대결·되돌리기·알림을 직원 JWT로 erp에 그대로 넘깁니다(contracts/openapi/gateway.yaml).

- 쓰기는 `Idempotency-Key`와 `?dryRun`을 그대로 넘기고, erp 응답(오류 포함)의 상태 코드와 본문을 그대로 돌려줍니다.
- 읽기는 erp 응답에 화면이 쓸 이름(요청자, 원 결재자, 양식, 위임자·대리인)을 붙입니다. 이름 조회는 요청 하나 안에서만
  기억합니다(직원 정보가 바뀌어도 다음 요청에는 새로 읽음).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from gateway.erp_client import ErpClient, as_problem
from gateway.problems import ProblemError

FORWARD_HEADERS = ("idempotency-key",)


def bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        raise ProblemError(401, "unauthorized", "로그인이 필요합니다")
    return auth[7:].strip()


def relay_response(r: httpx.Response) -> Response:
    return Response(r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


class Names:
    """한 요청 안에서 직원 이름과 양식 이름을 한 번씩만 읽습니다."""

    def __init__(self, erp: ErpClient, token: str):
        self.erp, self.token = erp, token
        self._emps: dict[str, dict[str, Any] | None] = {}
        self._forms: dict[str, str] | None = None

    async def employee(self, emp_id: str | None) -> dict[str, Any] | None:
        if not emp_id:
            return None
        if emp_id not in self._emps:
            r = await self.erp.request("GET", f"/employees/{emp_id}", bearer=self.token)
            self._emps[emp_id] = r.json() if r.status_code == 200 else None
        return self._emps[emp_id]

    async def name(self, emp_id: str | None) -> str:
        e = await self.employee(emp_id)
        return e["name"] if e else (emp_id or "")

    async def form_name(self, form_id: str) -> str:
        if self._forms is None:
            data = await self.erp.get_json("/approval-forms", self.token)
            self._forms = {f["id"]: f["name"] for f in data.get("items", [])}
        return self._forms.get(form_id, form_id)


async def _active_delegations_to_me(erp: ErpClient, token: str) -> list[dict[str, Any]]:
    data = await erp.get_json("/delegations", token, params={"role": "delegate"})
    return [d for d in data.get("items", []) if d.get("status") == "active"]


async def inbox_item(doc: dict[str, Any], me: str, names: Names,
                     delegations: list[dict[str, Any]] | None) -> dict[str, Any]:
    requester = await names.employee(doc["requesterId"])
    steps = [{**st, "approverName": await names.name(st["approverId"]),
              "actedByName": await names.name(st["actedBy"]) if st.get("actedBy") else None}
             for st in doc.get("steps", [])]
    item = {**doc, "steps": steps, "formName": await names.form_name(doc["formId"]),
            "requesterName": requester["name"] if requester else doc["requesterId"],
            "viaDelegation": None}
    if requester and requester.get("unitName"):
        item["requesterUnitName"] = requester["unitName"]

    # 대결로 내 함에 들어온 것: 지금 단계의 원 결재자가 내가 아니고, 그 사람이 나에게 준 유효한 위임이 있음
    current = next((s for s in doc.get("steps", []) if s["order"] == doc.get("currentStep")), None)
    if current and current["approverId"] != me and delegations:
        d = next((d for d in delegations if d["delegatorId"] == current["approverId"]), None)
        if d:
            item["viaDelegation"] = {"delegationId": d["id"], "originalApproverId": d["delegatorId"],
                                     "originalApproverName": await names.name(d["delegatorId"]),
                                     "endsAt": d["endsAt"]}
            return item
    # 이미 대결로 처리한 것
    acted = next((s for s in doc.get("steps", []) if s.get("actedBy") == me and s.get("delegationId")), None)
    if acted:
        item["viaDelegation"] = {"delegationId": acted["delegationId"], "originalApproverId": acted["approverId"],
                                 "originalApproverName": await names.name(acted["approverId"])}
    return item


def build_router(erp: ErpClient) -> APIRouter:
    api = APIRouter()

    async def forward(request: Request, method: str, path: str, *, with_body: bool = True) -> Response:
        token = bearer(request)
        headers = {h: request.headers[h] for h in FORWARD_HEADERS if h in request.headers}
        body = None
        if with_body:
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw)
                except ValueError:
                    raise ProblemError(422, "validation", "JSON 본문이 아닙니다")
        params = dict(request.query_params)
        return relay_response(await erp.request(method, path, bearer=token, json=body, params=params or None,
                                                headers=headers))

    async def me_id(token: str) -> str:
        return (await erp.get_json("/me", token))["id"]

    # ---------- 조회(대결 설정 화면) ----------
    @api.get("/employees")
    async def search_employees(request: Request) -> Response:
        return await forward(request, "GET", "/employees", with_body=False)

    @api.get("/approval-forms")
    async def approval_forms(request: Request) -> Response:
        return await forward(request, "GET", "/approval-forms", with_body=False)

    # ---------- 되돌리기 ----------
    @api.post("/actions/{action_id}/undo")
    async def undo(request: Request, action_id: str) -> Response:
        return await forward(request, "POST", f"/actions/{action_id}/undo")

    # ---------- 결재함 ----------
    @api.get("/inbox")
    async def list_inbox(request: Request, box: str) -> JSONResponse:
        token = bearer(request)
        r = await erp.request("GET", "/approval-documents", bearer=token, params=dict(request.query_params))
        if r.status_code != 200:
            raise as_problem(r)
        me = await me_id(token)
        names = Names(erp, token)
        delegations = await _active_delegations_to_me(erp, token) if box == "delegated" else None
        items = [await inbox_item(d, me, names, delegations) for d in r.json().get("items", [])]
        return JSONResponse({"items": items})

    @api.get("/inbox/{document_id}")
    async def get_inbox_item(request: Request, document_id: str) -> JSONResponse:
        token = bearer(request)
        doc = await erp.get_json(f"/approval-documents/{document_id}", token)
        me = await me_id(token)
        current = next((s for s in doc.get("steps", []) if s["order"] == doc.get("currentStep")), None)
        delegations = (await _active_delegations_to_me(erp, token)
                       if current and current["approverId"] != me else None)
        return JSONResponse(await inbox_item(doc, me, Names(erp, token), delegations))

    @api.post("/inbox/{document_id}/approve")
    async def approve(request: Request, document_id: str) -> Response:
        return await forward(request, "POST", f"/approval-documents/{document_id}/approve")

    @api.post("/inbox/{document_id}/reject")
    async def reject(request: Request, document_id: str) -> Response:
        return await forward(request, "POST", f"/approval-documents/{document_id}/reject")

    # ---------- 대결 ----------
    @api.get("/delegations")
    async def list_delegations(request: Request, role: str) -> JSONResponse:
        token = bearer(request)
        data = await erp.get_json("/delegations", token, params={"role": role})
        names = Names(erp, token)
        items = [{**d, "delegatorName": await names.name(d["delegatorId"]),
                  "delegateName": await names.name(d["delegateId"])} for d in data.get("items", [])]
        items.sort(key=lambda d: datetime.fromisoformat(d["startsAt"]), reverse=True)
        return JSONResponse({"items": items})

    @api.post("/delegations")
    async def create_delegation(request: Request) -> Response:
        return await forward(request, "POST", "/delegations")

    @api.post("/delegations/{delegation_id}/revoke")
    async def revoke_delegation(request: Request, delegation_id: str) -> Response:
        return await forward(request, "POST", f"/delegations/{delegation_id}/revoke")

    # ---------- 알림 ----------
    @api.get("/notifications")
    async def notifications(request: Request) -> Response:
        return await forward(request, "GET", "/notifications", with_body=False)

    return api
