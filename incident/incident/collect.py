"""장애 구간의 서비스 로그·감사 이벤트를 묶음으로 저장합니다."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from incident.stack import SERVICES, Stack


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def in_window(event: dict[str, Any], start: datetime, end: datetime) -> bool:
    at = event.get("occurredAt")
    if not isinstance(at, str):
        return False
    try:
        t = parse_time(at)
    except ValueError:
        return False
    return start <= t <= end


def filter_jsonl(text: str, start: datetime, end: datetime) -> str:
    out = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and in_window(ev, start, end):
            out.append(line)
    return "".join(x + "\n" for x in out)


def sort_log(text: str) -> str:
    """docker logs --timestamps 줄(stdout·stderr를 따로 받음)을 시각 순으로 합칩니다. 시각 없는 줄은 앞 줄을 따릅니다."""
    entries: list[tuple[str, int, str]] = []
    last = ""
    for i, line in enumerate(text.splitlines()):
        head = line.split(" ", 1)[0]
        if len(head) >= 20 and head[4] == "-" and "T" in head:
            last = head
        entries.append((last, i, line))
    entries.sort(key=lambda e: (e[0], e[1]))
    return "".join(e[2] + "\n" for e in entries)


def erp_audit(erp_url: str, auditor_no: str, password: str, start: datetime, end: datetime) -> str:
    with httpx.Client(base_url=erp_url, timeout=15) as c:
        r = c.post("/auth/login", json={"employeeNo": auditor_no, "password": password})
        if r.status_code != 200:
            return ""
        h = {"Authorization": f"Bearer {r.json()['accessToken']}"}
        r = c.get("/audit-events", headers=h, params={"since": start.isoformat(), "limit": 500})
        if r.status_code != 200:
            return ""
        return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in r.json()["items"] if in_window(e, start, end))


def collect(stack: Stack, out: Path, start: datetime, end: datetime, auditor_no: str, password: str) -> dict[str, int]:
    """logs/<서비스>.log, audit/<파일>.jsonl을 쓰고 파일별 줄 수를 돌려줍니다."""
    counts: dict[str, int] = {}
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "audit").mkdir(parents=True, exist_ok=True)
    since, until = start.isoformat(), end.isoformat()
    for svc in SERVICES:
        text = sort_log(stack.logs(svc, since, until))
        (out / "logs" / f"{svc}.log").write_text(text, encoding="utf-8")
        counts[f"logs/{svc}.log"] = text.count("\n")
    for name, text in stack.audit_lines().items():
        kept = filter_jsonl(text, start, end)
        path = out / "audit" / name.replace("/", "_")
        path.write_text(kept, encoding="utf-8")
        counts[f"audit/{path.name}"] = kept.count("\n")
    erp = erp_audit(stack.erp_url, auditor_no, password, start, end)
    (out / "audit" / "erp.jsonl").write_text(erp, encoding="utf-8")
    counts["audit/erp.jsonl"] = erp.count("\n")
    return counts
