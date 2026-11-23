"""감사 조회 `GET /api/audit-events`(auditor 역할만). 여러 서비스의 감사 이벤트를 시각 순으로 합칩니다.

출처
- gateway: 자기 audit.jsonl
- erp: `GET /audit-events`(직원 JWT, 사람 화면 전용)
- agent·MCP·rag: 각 서비스가 쓰는 JSON Lines 파일. `AUDIT_EVENT_FILES`(쉼표로 구분한 경로나 glob)로 받습니다.
  compose에서는 공유 볼륨으로 붙입니다. 읽지 못한 줄은 건너뛰고 경고 로그에 개수만 남깁니다.

커서는 마지막으로 돌려준 이벤트의 (occurredAt, eventId)입니다. 다음 쪽은 그보다 뒤의 이벤트입니다.
erp는 한 번에 최근 500건까지만 주므로, 그보다 오래된 erp 이벤트는 since로 좁혀서 봅니다.
"""

from __future__ import annotations

import base64
import glob
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from gateway.audit import AuditLog
from gateway.erp_client import ErpClient
from gateway.problems import ProblemError
from gateway.relay import bearer

log = logging.getLogger(__name__)

AUDITOR_ROLE = "auditor"  # contracts/openapi/gateway.yaml listAuditEvents: "auditor 역할만"


def _ts(e: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(e["occurredAt"].replace("Z", "+00:00"))


def _key(e: dict[str, Any]) -> tuple[datetime, str]:
    return _ts(e), e.get("eventId", "")


def encode_cursor(e: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps([e["occurredAt"], e["eventId"]]).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        at, eid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(at.replace("Z", "+00:00")), eid
    except (ValueError, TypeError):
        raise ProblemError(422, "validation", "cursor가 올바르지 않습니다")


def read_files(patterns: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bad = 0
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                    _key(e)
                    out.append(e)
                except (ValueError, KeyError, TypeError, AttributeError):
                    bad += 1
    if bad:
        log.warning("감사 이벤트 파일에서 읽지 못한 줄 %d개를 건너뜀", bad)
    return out


def matches(e: dict[str, Any], *, conversation_id: str | None, actor_id: str | None, agent_id: str | None,
            kind: str | None, since: datetime | None, until: datetime | None) -> bool:
    actor = e.get("actor") or {}
    if conversation_id and e.get("conversationId") != conversation_id:
        return False
    if actor_id and actor.get("employeeId") != actor_id:
        return False
    if agent_id and actor.get("agentId") != agent_id and (e.get("routing") or {}).get("agentId") != agent_id:
        return False
    if kind and e.get("kind") != kind:
        return False
    t = _ts(e)
    return not ((since and t < since) or (until and t > until))


def build_router(erp: ErpClient, audit: AuditLog, files: tuple[str, ...]) -> APIRouter:
    api = APIRouter()

    @api.get("/audit-events")
    async def list_audit_events(
        request: Request,
        conversationId: str | None = None, actorId: str | None = None, agentId: str | None = None,
        kind: str | None = None, since: datetime | None = None, until: datetime | None = None,
        cursor: str | None = None, limit: int = Query(100, ge=1, le=500),
        order: Literal["asc", "desc"] = "asc",
    ) -> JSONResponse:
        token = bearer(request)
        if any(t is not None and t.tzinfo is None for t in (since, until)):
            raise ProblemError(422, "validation", "since·until에는 시간대 오프셋이 필요합니다")
        me = await erp.get_json("/me", token)
        if AUDITOR_ROLE not in me.get("roles", []):
            raise ProblemError(403, "forbidden", "감사 기록은 감사 조회 역할이 있어야 볼 수 있습니다.")

        params: dict[str, Any] = {"limit": 500}
        if actorId:
            params["actorId"] = actorId
        if since:
            params["since"] = since.isoformat()
        erp_events = (await erp.get_json("/audit-events", token, params=params)).get("items", [])

        events = erp_events + audit.events.read_all() + read_files(files)
        seen: set[str] = set()
        merged = []
        for e in sorted(events, key=_key):
            if e.get("eventId") in seen:
                continue
            seen.add(e.get("eventId"))
            if matches(e, conversation_id=conversationId, actor_id=actorId, agent_id=agentId, kind=kind,
                       since=since, until=until):
                merged.append(e)
        if order == "desc":
            merged.reverse()
        if cursor:
            # cursor는 앞 페이지 마지막 이벤트입니다. desc면 그보다 오래된 쪽, asc면 그보다 새 쪽을 이어 봅니다.
            mark = decode_cursor(cursor)
            merged = [e for e in merged if (_key(e) < mark if order == "desc" else _key(e) > mark)]
        page = merged[:limit]
        next_cursor = encode_cursor(page[-1]) if len(merged) > limit else None
        return JSONResponse({"items": page, "nextCursor": next_cursor})

    return api
