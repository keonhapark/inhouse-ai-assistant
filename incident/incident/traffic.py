"""장애 전후로 평소 같은 요청을 흘려 로그가 생기게 합니다. 응답(상태·지연)은 사용자가 겪은 증상 기록으로 남깁니다."""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

KST = timezone(timedelta(hours=9))
CHAT_QUESTIONS = ("내일 오후 2시에 4명 들어갈 회의실 있어?", "내 연차 며칠 남았어?", "출장비 정산 규정 알려줘")


def now() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")


class Traffic:
    """erp 직접 요청(0.5초마다)과 gateway 대화(chat_every초마다)를 따로 돌립니다."""

    def __init__(self, erp_url: str, gateway_url: str, employee_no: str, password: str, chat_every: float = 20.0):
        self.erp_url, self.gateway_url = erp_url, gateway_url
        self.employee_no, self.password = employee_no, password
        self.chat_every = chat_every
        self.records: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def _note(self, target: str, op: str, started: float, status: int | None, error: str | None) -> None:
        with self._lock:
            self.records.append({"at": now(), "target": target, "op": op, "status": status,
                                 "ms": round((time.monotonic() - started) * 1000), "error": error})

    def _call(self, client: httpx.Client, target: str, op: str, method: str, url: str, **kw: Any) -> httpx.Response | None:
        started = time.monotonic()
        try:
            r = client.request(method, url, **kw)
            self._note(target, op, started, r.status_code, None)
            return r
        except httpx.HTTPError as e:
            self._note(target, op, started, None, type(e).__name__)
            return None

    def _token(self, client: httpx.Client, base: str, target: str) -> str | None:
        r = self._call(client, target, "login", "POST", f"{base}/auth/login",
                       json={"employeeNo": self.employee_no, "password": self.password})
        return r.json().get("accessToken") if r is not None and r.status_code == 200 else None

    def _erp_loop(self) -> None:
        token = None
        with httpx.Client(timeout=10) as c:
            while not self._stop.is_set():
                if token is None:
                    token = self._token(c, self.erp_url, "erp")
                    if token is None:
                        self._stop.wait(1)
                        continue
                h = {"Authorization": f"Bearer {token}"}
                start = (datetime.now(KST) + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
                for op, method, path, kw in (
                    ("listOutbox", "GET", "/approval-documents", {"params": {"box": "outbox"}}),
                    ("leaveBalance", "GET", "/leave/balance", {}),
                    ("listTickets", "GET", "/tickets", {}),
                    ("reservePreview", "POST", "/room-reservations", {"params": {"dryRun": "true"}, "json": {
                        "roomId": "room-a", "startsAt": start.isoformat(),
                        "endsAt": (start + timedelta(minutes=30)).isoformat(), "title": "주간 회의"}}),
                ):
                    r = self._call(c, "erp", op, method, f"{self.erp_url}{path}", headers=h, **kw)
                    if r is not None and r.status_code == 401:
                        token = None
                self._stop.wait(0.5)

    def _chat_loop(self) -> None:
        token = None
        i = 0
        with httpx.Client(timeout=60) as c:
            while not self._stop.is_set():
                if token is None:
                    token = self._token(c, f"{self.gateway_url}/api", "gateway")
                if token is not None:
                    h = {"Authorization": f"Bearer {token}"}
                    r = self._call(c, "gateway", "createConversation", "POST", f"{self.gateway_url}/api/conversations",
                                   headers=h, json={})
                    if r is not None and r.status_code == 201:
                        cid = r.json()["conversationId"]
                        q = CHAT_QUESTIONS[i % len(CHAT_QUESTIONS)]
                        i += 1
                        started = time.monotonic()
                        try:
                            with c.stream("POST", f"{self.gateway_url}/api/conversations/{cid}/messages", headers=h,
                                          json={"content": q}) as s:
                                body = "".join(s.iter_text())
                            err = "error_event" if '"type": "error"' in body or '"type":"error"' in body else None
                            self._note("gateway", "postMessage", started, s.status_code, err)
                        except httpx.HTTPError as e:
                            self._note("gateway", "postMessage", started, None, type(e).__name__)
                self._stop.wait(self.chat_every)

    def start(self) -> None:
        for fn in (self._erp_loop, self._chat_loop):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=90)
        return list(self.records)


def idem() -> str:
    return uuid.uuid4().hex


def dumps(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
