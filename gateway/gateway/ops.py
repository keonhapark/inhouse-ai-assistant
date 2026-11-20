"""관리자 콘솔 조회(auditor 역할만, contracts/openapi/gateway.yaml `ops` 태그).

`GET /api/ops/egress`: 외부 모델로 실제 보낸 요청을 최근 것부터 돌려줍니다. 가림 뒤 본문과 가린 자리(종류·위치)만
돌려주고, 가림 전 원문은 저장하지도 돌려주지도 않습니다. 위치는 화면(JavaScript)과 맞도록 UTF-16 단위입니다.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gateway.audit import AuditLog
from gateway.audit_query import AUDITOR_ROLE
from gateway.egress import response_usage
from gateway.erp_client import ErpClient
from gateway.problems import ProblemError
from gateway.registry import Registry
from gateway.relay import bearer

PART_SEP = "\n"  # content가 부분 배열이면 텍스트 부분을 이 문자로 이어 붙입니다


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _ts(at: str) -> datetime:
    return datetime.fromisoformat(at.replace("Z", "+00:00"))


def to_egress_record(rec: dict[str, Any], registry: Registry) -> dict[str, Any]:
    """운영 기록 한 줄을 계약의 EgressRecord로 바꿉니다."""
    sent = rec.get("requestSent") or {}
    messages: list[dict[str, str]] = []
    # (메시지, 부분) → 이어 붙인 content 안에서 그 부분이 시작하는 파이썬 문자 위치
    part_start: dict[tuple[int, int | None], int] = {}
    for mi, m in enumerate(sent.get("messages") or []):
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            text = content
            part_start[(mi, None)] = 0
        elif isinstance(content, list):
            pieces, pos = [], 0
            for pi, p in enumerate(content):
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                    if pieces:
                        pos += len(PART_SEP)
                    part_start[(mi, pi)] = pos
                    pieces.append(p["text"])
                    pos += len(p["text"])
            text = PART_SEP.join(pieces)
        else:
            text = ""
        messages.append({"role": str(m.get("role", "")) if isinstance(m, dict) else "", "content": text})

    redactions = []
    for sp in rec.get("redactionSpans") or []:
        if sp.get("field") != "content":
            continue  # 도구 호출 인자처럼 content 밖에서 가린 것은 위치를 표시할 수 없습니다
        mi, pi = sp["messageIndex"], sp.get("partIndex")
        base = part_start.get((mi, pi))
        if base is None or mi >= len(messages):
            continue
        content = messages[mi]["content"]
        a, b = base + sp["start"], base + sp["end"]
        redactions.append({"entity": sp["entity"], "placeholder": sp["placeholder"], "messageIndex": mi,
                           "start": utf16_len(content[:a]), "end": utf16_len(content[:b])})

    usage = rec.get("usage")
    if usage is None and rec.get("response"):
        usage = response_usage(rec["response"])
    agent = registry.get(rec["agentId"]) if rec.get("agentId") else None
    return {
        "recordId": rec.get("recordId") or "",
        "at": rec["occurredAt"],
        "agentId": rec.get("agentId"),
        "agentName": agent.name if agent else None,
        "conversationId": rec.get("conversationId"),
        "actorId": rec.get("employeeId"),
        "model": rec.get("providerModel") or rec.get("model") or "",
        "usage": None if usage is None else {"promptTokens": usage.get("prompt_tokens", 0),
                                             "completionTokens": usage.get("completion_tokens", 0)},
        "costUsd": rec.get("costUsd"),
        "messages": messages,
        "redactions": redactions,
    }


def _cursor(rec: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps([rec["occurredAt"], rec.get("recordId", "")]).encode()).decode()


def _uncursor(cursor: str) -> tuple[datetime, str]:
    try:
        at, rid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return _ts(at), rid
    except (ValueError, TypeError):
        raise ProblemError(400, "validation", "cursor가 올바르지 않습니다")


async def require_auditor(erp: ErpClient, request: Request) -> None:
    me = await erp.get_json("/me", bearer(request))
    if AUDITOR_ROLE not in me.get("roles", []):
        raise ProblemError(403, "forbidden", "감사 조회 역할만 봅니다")


def build_router(erp: ErpClient, audit: AuditLog, registry: Registry) -> APIRouter:
    api = APIRouter()

    @api.get("/ops/egress")
    async def list_egress(request: Request, since: datetime | None = None, until: datetime | None = None,
                          agentId: str | None = None, cursor: str | None = None,
                          limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
        if any(t is not None and t.tzinfo is None for t in (since, until)):
            raise ProblemError(400, "validation", "since·until에는 시간대 오프셋이 필요합니다")
        await require_auditor(erp, request)
        rows = [r for r in audit.egress.read_all() if r.get("occurredAt") and r.get("status") is not None]
        rows = [r for r in rows
                if (agentId is None or r.get("agentId") == agentId)
                and (since is None or _ts(r["occurredAt"]) >= since)
                and (until is None or _ts(r["occurredAt"]) <= until)]
        rows.sort(key=lambda r: (_ts(r["occurredAt"]), r.get("recordId", "")), reverse=True)
        if cursor:
            after = _uncursor(cursor)
            rows = [r for r in rows if (_ts(r["occurredAt"]), r.get("recordId", "")) < after]
        page = rows[:limit]
        return JSONResponse({"items": [to_egress_record(r, registry) for r in page],
                             "nextCursor": _cursor(page[-1]) if len(rows) > limit else None})

    return api
