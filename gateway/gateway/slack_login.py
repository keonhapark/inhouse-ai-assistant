"""슬랙 브리지 로그인 `POST /api/auth/slack`(#273, contracts/openapi/gateway.yaml).

슬랙 브리지만 부릅니다. 브리지 비밀값(`SLACK_BRIDGE_SECRET`)이 맞고 슬랙 사용자 ID가 매핑 파일(`SLACK_USERS_FILE`,
워크스페이스마다 달라 팩이 아니라 로컬 설정, 커밋하지 않음)에 있으면, erp `POST /auth/service-login`으로 그 직원의
짧은 직원 JWT(`amr: [slack]`)를 받아 돌려줍니다. 직원 JWT의 발급 주체는 erp입니다(리드 결정 A안).

이 토큰은 허용 목록(`SLACK_ALLOWED`)의 경로만 부를 수 있습니다(리드 결정): 내 정보, 알림, 대화 만들기·조회·메시지,
실행 승인, 되돌리기. 나머지(대결, 결재함, 감사, 운영 등)는 `relay.bearer`가 403 `service-login-not-allowed`로 막습니다.
막을 경로를 나열하지 않고 허용할 경로를 나열해, 새 사람 화면 경로가 생겨도 슬랙 토큰에는 닫혀 있게 합니다.
erp도 자기 사람 전용 경로(`x-human-only`)를 따로 막습니다.
비밀값·토큰·매핑 파일 내용은 로그와 감사에 남기지 않습니다.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.audit import AuditLog
from gateway.erp_client import ErpClient
from gateway.problems import ProblemError

log = logging.getLogger(__name__)

SOURCE = "slack"

# 슬랙 토큰으로 부를 수 있는 사람 화면 경로(메서드, /api 뒤 경로). contracts/openapi/gateway.yaml /auth/slack
SLACK_ALLOWED = (
    ("GET", re.compile(r"/api/me")),
    ("GET", re.compile(r"/api/notifications")),
    ("GET", re.compile(r"/api/conversations")),
    ("POST", re.compile(r"/api/conversations")),
    ("GET", re.compile(r"/api/conversations/[^/]+")),
    ("POST", re.compile(r"/api/conversations/[^/]+/messages")),
    ("POST", re.compile(r"/api/execution-approvals/[^/]+")),
    ("POST", re.compile(r"/api/actions/[^/]+/undo")),
)


def is_service_login_token(token: str) -> bool:
    """erp 서비스 로그인 토큰(`amr`에 slack)인지. 서명은 보지 않습니다(진위는 erp가 확인)."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    amr = claims.get("amr") if isinstance(claims, dict) else None
    # 배열이 계약이지만, 문자열로 발급돼도 막습니다(발급 쪽 모양이 바뀌어도 열리지 않게)
    return amr == SOURCE or (isinstance(amr, list) and SOURCE in amr)


def check_service_login(token: str, method: str, path: str) -> None:
    """슬랙 토큰이 허용 목록 밖 경로를 부르면 403입니다."""
    if not is_service_login_token(token):
        return
    if any(method == m and p.fullmatch(path.rstrip("/") or "/") for m, p in SLACK_ALLOWED):
        return
    raise ProblemError(403, "service-login-not-allowed", "슬랙 로그인 토큰으로는 부를 수 없는 기능입니다")


def load_users(path: Path) -> dict[str, str]:
    """매핑 파일 `{"users": {슬랙 사용자 ID: 직원 ID}}`. 파일이 없으면 아무도 매핑되지 않은 것으로 봅니다."""
    if not path.exists():
        return {}
    try:
        users = json.loads(path.read_text(encoding="utf-8")).get("users", {})
    except (ValueError, AttributeError):
        log.error("슬랙 사용자 매핑 파일을 읽지 못했습니다: %s", path)
        raise ProblemError(500, "internal", "슬랙 사용자 매핑을 읽지 못했습니다")
    return {k: v for k, v in users.items() if isinstance(k, str) and isinstance(v, str)}


def build_router(erp: ErpClient, audit: AuditLog, *, bridge_secret: str | None, users_file: Path,
                 service_secret: str | None) -> APIRouter:
    api = APIRouter()

    def record(result: str, employee_id: str | None = None, problem: str | None = None, why: str = "") -> None:
        audit.event("auth.login", employee_id=employee_id, agent_id=None, via_token=False, result=result,
                    problem_type=f"urn:problem:{problem}" if problem else None,
                    detail=f"출처 {SOURCE}" + (f": {why}" if why else ""))

    @api.post("/auth/slack")
    async def slack_login(request: Request) -> JSONResponse:
        if not bridge_secret:
            raise ProblemError(404, "not-found", "없는 경로입니다")
        given = request.headers.get("x-slack-bridge-secret", "")
        if not hmac.compare_digest(given.encode(), bridge_secret.encode()):
            record("denied", problem="unauthorized", why="브리지 비밀값이 틀림")
            raise ProblemError(401, "unauthorized", "브리지 비밀값이 틀렸습니다")
        try:
            body: Any = json.loads(await request.body())
        except ValueError:
            body = None
        if not isinstance(body, dict) or set(body) != {"slackUserId"} or not isinstance(body["slackUserId"], str):
            raise ProblemError(422, "validation", "slackUserId만 받습니다")
        employee_id = load_users(users_file).get(body["slackUserId"])
        if employee_id is None:
            record("denied", problem="forbidden", why="매핑에 없는 슬랙 사용자")
            raise ProblemError(403, "forbidden", "이 슬랙 사용자와 연결된 직원이 없습니다")

        if not service_secret:
            # 빈 비밀값으로 erp를 부르지 않습니다(erp가 빈 값을 "설정됨"으로 볼 위험). gateway 설정 문제입니다.
            record("error", employee_id, "upstream-error", "ERP_SERVICE_LOGIN_SECRET 없음")
            log.error("ERP_SERVICE_LOGIN_SECRET이 없어 슬랙 로그인을 할 수 없습니다")
            raise ProblemError(502, "upstream-error", "erp 서비스 로그인에 실패했습니다", "서비스 비밀값이 설정되지 않음")
        r = await erp.request("POST", "/auth/service-login", json={"employeeId": employee_id},
                              headers={"X-Service-Login-Secret": service_secret})
        if r.status_code == 422:  # 매핑된 직원이 erp에 없음
            record("denied", problem="forbidden", why="매핑된 직원이 erp에 없음")
            raise ProblemError(403, "forbidden", "이 슬랙 사용자와 연결된 직원이 없습니다")
        if r.status_code != 200:
            # 서비스 비밀값 불일치(401)·erp 서비스 로그인 꺼짐(404) 등은 gateway 설정 문제입니다. 브리지 인증 실패와 가립니다.
            record("error", employee_id, "upstream-error", f"erp 서비스 로그인 {r.status_code}")
            log.error("erp 서비스 로그인이 %d로 실패했습니다(ERP_SERVICE_LOGIN_SECRET 확인)", r.status_code)
            raise ProblemError(502, "upstream-error", "erp 서비스 로그인에 실패했습니다", f"erp {r.status_code}")
        record("ok", employee_id)
        return JSONResponse(r.json())

    return api
