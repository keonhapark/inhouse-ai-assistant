"""장애마다 직원이 올렸을 법한 티켓 문장(지어낸 것). 직원은 증상만 알고 원인은 모릅니다."""

from __future__ import annotations

import random
import uuid
from typing import Any

import httpx

TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "db_down": [
        ("결재함이 열리지 않습니다", "결재함을 누르면 한참 돌다가 오류 화면이 나옵니다. 휴가 신청도 저장이 안 됩니다."),
        ("ERP 화면 전체가 오류입니다", "로그인은 되는데 연차 조회, 회의실 조회가 모두 실패합니다. 동료들도 같다고 합니다."),
        ("회의실 예약이 안 됩니다", "회의실을 고르고 예약 버튼을 누르면 서버 오류라고 나옵니다."),
    ],
    "db_lock": [
        ("회의실 예약 화면이 멈춥니다", "예약 버튼을 누르면 1분 가까이 기다리다 실패합니다. 조회는 가끔 됩니다."),
        ("결재 상신이 너무 느립니다", "휴가 신청을 올리는데 저장이 끝나지 않습니다. 새로고침하면 안 올라가 있습니다."),
        ("연차 조회가 오래 걸립니다", "연차 잔여를 보려고 하면 화면이 멈춘 것처럼 오래 걸립니다."),
    ],
    "erp_memory": [
        ("ERP가 갑자기 끊깁니다", "쓰던 중에 연결이 끊겼다가 잠시 뒤 다시 로그인하라고 나옵니다."),
        ("결재 화면이 하얗게 나옵니다", "결재함을 열면 아무것도 안 나오고 연결 오류가 납니다. 조금 전까지는 됐습니다."),
        ("휴가 신청 중 오류", "휴가 신청 버튼을 누르자 서버에 연결할 수 없다고 나왔습니다."),
    ],
    "llm_timeout": [
        ("AI 비서가 답을 안 합니다", "질문을 보내면 답이 오지 않고 계속 기다리기만 합니다. ERP 화면은 정상입니다."),
        ("사내 비서 응답 없음", "회의실 물어봤는데 1분 넘게 아무 답이 없다가 오류가 났습니다."),
        ("챗봇이 멈췄어요", "규정 질문을 했는데 답이 안 옵니다. 어제는 잘 됐습니다."),
    ],
    "rag_corrupt": [
        ("규정 검색이 안 됩니다", "AI 비서에게 출장비 규정을 물으면 문서를 찾을 수 없다는 오류가 납니다."),
        ("사내 규정 답변 오류", "다른 질문은 되는데 규정을 물으면 실패합니다."),
        ("규정 질문에 답이 없습니다", "취업규칙을 물어봤는데 처리 중 오류가 발생했다고만 나옵니다."),
    ],
    "gateway_bad_config": [
        ("AI 비서가 바로 오류를 냅니다", "질문을 보내자마자 오류가 납니다. 오늘 아침 업데이트 이후부터입니다."),
        ("챗봇 접속 오류", "사내 비서에 질문하면 즉시 실패합니다. 동료도 같은 증상입니다."),
        ("AI 비서 답변 실패", "어떤 질문을 해도 답변 생성에 실패했다고 나옵니다."),
    ],
}


def pick(fault_id: str, rng: random.Random) -> tuple[str, str]:
    return rng.choice(TEMPLATES[fault_id])


def file_ticket(erp_url: str, employee_no: str, password: str, title: str, description: str) -> dict[str, Any]:
    """직원으로 로그인해 erp에 티켓을 올리고 만든 티켓을 돌려줍니다."""
    with httpx.Client(base_url=erp_url, timeout=15) as c:
        r = c.post("/auth/login", json={"employeeNo": employee_no, "password": password})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['accessToken']}", "Idempotency-Key": uuid.uuid4().hex}
        r = c.post("/tickets", headers=h, json={"category": "incident", "priority": "high", "title": title,
                                                 "description": description})
        r.raise_for_status()
        return r.json()["resource"]
