"""묶음 로그를 줄 단위 사건(시각, 서비스, 수준, 본문)으로 읽습니다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 헬스 검사 줄은 평소에도 일정하게 찍혀 신호가 없고, LLM에 줄 진단 텍스트만 길게 만듭니다.
NOISE = re.compile(r'"GET /health(/liveliness)? HTTP|application_name=pg_isready|GET /api/v1/health ')
# 오류·경고: 단어 중간(ValueError, SQLException)도 잡고, HTTP 상태는 접근 로그 모양(uvicorn '" 503', erp '503 12ms')일 때만 봅니다.
ERROR = re.compile(r"ERROR|FATAL|PANIC|CRITICAL|Traceback|Exception\b|Error\b|refused|timed out|[Tt]imeout|unhealthy|"
                   r"\b(oom|die)\b|\" 5\d\d\b|\s5\d\d \d+ms\b")
WARN = re.compile(r"\b(WARN|WARNING|still waiting|duration:)\b|\" 4\d\d\b|\s4\d\d \d+ms\b")
# 앱이 줄 앞에 다시 찍는 시각·프로세스 번호 등(템플릿을 흐리게 함)
APP_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T][\d:.,]+Z?( UTC)?\s+|\d{2}:\d{2}:\d{2}\s+-\s+)")
# 컨테이너 이벤트 중 사람이 한 조작(주입·복구 명령)은 장애의 증상이 아니라 빼고 읽습니다.
OPERATOR_ACTIONS = ("pause", "unpause", "kill", "stop", "update", "extract-to-dir", "archive-path", "copy",
                    "create", "destroy", "rename", "attach", "resize", "commit", "export", "top", "restart")


@dataclass(frozen=True)
class Line:
    at: datetime
    service: str
    level: str
    """error, warn, info, heartbeat(헬스 검사 줄: 템플릿 변화에는 안 쓰고, 로그가 끊겼는지 볼 때만 씀)"""
    text: str


def parse_ts(s: str) -> datetime | None:
    # docker: 2026-11-20T15:58:09.397774845Z (나노초) → 마이크로초로 자릅니다.
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z", s)
    if not m:
        return None
    frac = (m.group(2) or ".0")[:7]
    return datetime.fromisoformat(f"{m.group(1)}{frac}+00:00")


def level_of(text: str) -> str:
    if ERROR.search(text):
        return "error"
    if WARN.search(text):
        return "warn"
    return "info"


def read_service(path: Path, service: str) -> list[Line]:
    out: list[Line] = []
    last: datetime | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        head, _, rest = raw.partition(" ")
        at = parse_ts(head)
        if at is None:
            at, rest = last, raw
        if at is None:
            continue
        last = at
        if NOISE.search(rest):
            out.append(Line(at, service, "heartbeat", rest.strip()[:200]))
            continue
        # 들여쓴 줄(자바 "\tat ...", 파이썬 "  File ...")은 앞 줄의 스택 추적이라 앞 줄에 붙입니다.
        if out and rest[:1] in (" ", "\t") and out[-1].service == service and out[-1].level != "heartbeat":
            prev = out[-1]
            if len(prev.text) < 2000:
                out[-1] = Line(prev.at, service, prev.level, f"{prev.text} | {rest.strip()}")
            continue
        text = APP_PREFIX.sub("", rest.strip())
        if text:
            out.append(Line(at, service, level_of(text), text))
    return out


def read_events(path: Path) -> list[Line]:
    """logs/docker-events.log: '<시각> <동작> <서비스> [exitCode=n]'. 조작 이벤트는 뺍니다."""
    out: list[Line] = []
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split(" ")
        if len(parts) < 3:
            continue
        at = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
        action, service = parts[1].rstrip(":"), parts[-1] if not parts[-1].startswith("exitCode") else parts[-2]
        if action in OPERATOR_ACTIONS or (action == "health_status" and "healthy" in raw and "unhealthy" not in raw):
            continue
        text = " ".join(parts[1:])
        out.append(Line(at, service, level_of(text) if action != "start" else "warn", f"[container] {text}"))
    return out


def read_bundle(bundle: Path) -> list[Line]:
    lines: list[Line] = []
    for path in sorted((bundle / "logs").glob("*.log")):
        if path.name == "docker-events.log":
            lines += read_events(path)
        else:
            lines += read_service(path, path.stem)
    return sorted(lines, key=lambda x: x.at)
