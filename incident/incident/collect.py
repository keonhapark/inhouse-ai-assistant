"""장애 구간의 서비스 로그·감사 이벤트를 묶음으로 저장합니다."""

from __future__ import annotations

import json
import re
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


# 묶음은 커밋하므로 비밀값처럼 보이는 값을 가립니다.
# - 위임 토큰 ID(jti): 비밀은 아니지만 비밀값 검사가 키로 봅니다(해시로 바꿔도 잡힘). 분석에 쓰지 않아 지웁니다.
# - Spring 기본 사용자 비밀번호("Using generated security password: ..."): 실제 비밀번호라 지웁니다.
TOKEN_ID = re.compile(r'("delegationTokenId"\s*:\s*)"([^"]+)"')
GENERATED_PASSWORD = re.compile(r"(generated security password: )\S+")


def sanitize(text: str) -> str:
    text = TOKEN_ID.sub(r'\1"<가림>"', text)
    return GENERATED_PASSWORD.sub(r"\1<가림>", text)


def sanitize_bundle(bundle: Path) -> int:
    """이미 모은 묶음의 logs·audit 파일을 가립니다. 바꾼 파일 수를 돌려줍니다."""
    changed = 0
    for path in [*bundle.glob("logs/*.log"), *bundle.glob("audit/*.jsonl")]:
        text = path.read_text(encoding="utf-8")
        clean = sanitize(text)
        if clean != text:
            path.write_text(clean, encoding="utf-8")
            changed += 1
    return changed


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
        if not line.strip():
            continue
        head = line.split(" ", 1)[0]
        if len(head) >= 20 and head[4] == "-" and "T" in head:
            last = head
        entries.append((last, i, line))
    entries.sort(key=lambda e: (e[0], e[1]))
    return "".join(e[2] + "\n" for e in entries)


def erp_audit(erp_url: str, auditor_no: str, password: str, start: datetime, end: datetime) -> str:
    """erp 감사 이벤트(감사 조회 역할로 로그인). erp에 닿지 못하면 빈 묶음으로 둡니다."""
    try:
        return _erp_audit(erp_url, auditor_no, password, start, end)
    except httpx.HTTPError:
        return ""


def _erp_audit(erp_url: str, auditor_no: str, password: str, start: datetime, end: datetime) -> str:
    with httpx.Client(base_url=erp_url, timeout=15) as c:
        r = c.post("/auth/login", json={"employeeNo": auditor_no, "password": password})
        if r.status_code != 200:
            return ""
        h = {"Authorization": f"Bearer {r.json()['accessToken']}"}
        r = c.get("/audit-events", headers=h, params={"since": start.isoformat(), "limit": 500})
        if r.status_code != 200:
            return ""
        return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in r.json()["items"] if in_window(e, start, end))


def service_logs(stack: Stack, start: datetime, end: datetime) -> dict[str, str]:
    """서비스별 컨테이너 로그. 복구가 컨테이너를 새로 만들면 옛 로그가 사라지므로 복구 직전에 한 번 더 부릅니다."""
    return {svc: stack.logs(svc, start.isoformat(), end.isoformat()) for svc in SERVICES}


def collect(stack: Stack, out: Path, start: datetime, end: datetime, auditor_no: str, password: str,
            earlier: dict[str, str] | None = None, earlier_end: datetime | None = None) -> dict[str, int]:
    """logs/<서비스>.log, audit/<파일>.jsonl을 쓰고 파일별 줄 수를 돌려줍니다. earlier는 start~earlier_end에 미리
    받아 둔 로그이고, 그 뒤(earlier_end~end)만 새로 받아 잇습니다."""
    counts: dict[str, int] = {}
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "audit").mkdir(parents=True, exist_ok=True)
    later = service_logs(stack, earlier_end or start, end)
    for svc in SERVICES:
        text = sanitize(sort_log((earlier or {}).get(svc, "") + "\n" + later[svc]))
        (out / "logs" / f"{svc}.log").write_text(text, encoding="utf-8")
        counts[f"logs/{svc}.log"] = text.count("\n")
    for name, text in stack.audit_lines().items():
        kept = sanitize(filter_jsonl(text, start, end))
        path = out / "audit" / name.replace("/", "_")
        path.write_text(kept, encoding="utf-8")
        counts[f"audit/{path.name}"] = kept.count("\n")
    erp = sanitize(erp_audit(stack.erp_url, auditor_no, password, start, end))
    (out / "audit" / "erp.jsonl").write_text(erp, encoding="utf-8")
    counts["audit/erp.jsonl"] = erp.count("\n")
    return counts
