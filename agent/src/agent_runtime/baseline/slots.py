"""LLM 없는 슬롯 파서 기준선. 휴가·회의실 요청 문장을 규칙으로 도구 인자에 채웁니다.

기능 품질 비교(같은 입력을 LLM 경로와 규칙 경로로 채워 실행 후 DB 상태를 비교)에 씁니다.
채운 인자는 contracts/mcp/tools.json의 입력 스키마(leave_request, room_list_availability, room_reserve)를 따릅니다.
실행은 하지 않습니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = "월화수목금토일"
NATIVE_NUMBERS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
                  "열한": 11, "열두": 12}
ORDINALS = {"첫": 1, "첫째": 1, "첫 번째": 1, "첫번째": 1, "둘째": 2, "두 번째": 2, "두번째": 2, "셋째": 3,
            "세 번째": 3, "세번째": 3, "넷째": 4, "네 번째": 4, "네번째": 4, "마지막": -1}
DEFAULT_REASON = "개인 사정"
DEFAULT_TITLE = "회의"


@dataclass(frozen=True)
class SlotResult:
    intent: str | None  # leave, room, None
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "tool": self.tool, "arguments": self.arguments, "missing": list(self.missing)}


class SlotFiller(Protocol):
    """같은 입력을 규칙(RuleSlotFiller)과 LLM(llm_filler.LlmSlotFiller)으로 채워 비교하는 공통 인터페이스."""

    def fill(self, message: str, today: date, rooms: list[dict[str, Any]] | None = None) -> SlotResult: ...


# ---------- 정규화 ----------

_NATIVE = "|".join(sorted(NATIVE_NUMBERS, key=len, reverse=True))


def normalize(text: str) -> str:
    t = text.replace("～", "~").replace("〜", "~").replace("：", ":")
    # "두 시", "네 명", "한 시간" 같은 고유어 수를 숫자로 바꿉니다.
    t = re.sub(rf"(?<![가-힣])({_NATIVE})\s*(시간|시|명|분)", lambda m: f"{NATIVE_NUMBERS[m.group(1)]}{m.group(2)}", t)
    return t


# ---------- 날짜 ----------


@dataclass(frozen=True)
class Found:
    start: int
    value: date


def _next_weekday(today: date, wd: int, strictly_after: bool = True) -> date:
    delta = (wd - today.weekday()) % 7
    if delta == 0 and strictly_after:
        delta = 7
    return today + timedelta(days=delta)


def _week_of(today: date, offset_weeks: int, wd: int) -> date:
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)
    return monday + timedelta(days=wd)


def _month_add(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def _nth_weekday(first_of_month: date, n: int, wd: int) -> date:
    if n == -1:
        nxt = _month_add(first_of_month, 1)
        d = nxt - timedelta(days=1)
        while d.weekday() != wd:
            d -= timedelta(days=1)
        return d
    d = first_of_month + timedelta(days=(wd - first_of_month.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, today: date) -> list[Found]:
    """문장 안의 날짜를 나온 순서대로 찾습니다. 겹치는 표현은 먼저 맞은(더 구체적인) 규칙을 씁니다."""
    found: list[tuple[int, int, date]] = []

    def add(m: re.Match[str], d: date | None) -> None:
        if d is None:
            return
        if any(s <= m.start() < e or m.start() <= s < m.end() for s, e, _ in found):
            return
        found.append((m.start(), m.end(), d))

    ord_pat = "|".join(sorted(map(re.escape, ORDINALS), key=len, reverse=True))
    rules: list[tuple[str, Any]] = [
        (r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?",
         lambda m: _safe_date(int(m[1]), int(m[2]), int(m[3]))),
        (rf"(다음|이번)\s*달\s*({ord_pat})\s*(?:주\s*)?([{WEEKDAYS}])요일",
         lambda m: _nth_weekday(_month_add(today, 1 if m[1] == "다음" else 0), ORDINALS[m[2]], WEEKDAYS.index(m[3]))),
        (r"(다음|이번)\s*달\s*(\d{1,2})\s*일",
         lambda m: (lambda f: _safe_date(f.year, f.month, int(m[2])))(_month_add(today, 1 if m[1] == "다음" else 0))),
        (r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", lambda m: _this_or_next_year(today, int(m[1]), int(m[2]))),
        (r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])", lambda m: _this_or_next_year(today, int(m[1]), int(m[2]))),
        (rf"(다다음\s*주|다음\s*주|담주|이번\s*주|금주)\s*([{WEEKDAYS}])요일?",
         lambda m: _week_of(today, _week_offset(m[1]), WEEKDAYS.index(m[2]))),
        (rf"([{WEEKDAYS}])요일", lambda m: _next_weekday(today, WEEKDAYS.index(m[1]))),
        (r"오늘", lambda m: today),
        (r"내일", lambda m: today + timedelta(days=1)),
        (r"모레", lambda m: today + timedelta(days=2)),
        (r"글피", lambda m: today + timedelta(days=3)),
        (r"(?<![\d월])(\d{1,2})\s*일(?!\s*(?:간|동안|치))", lambda m: _this_or_next_month(today, int(m[1]))),
    ]
    for pattern, make in rules:
        for m in re.finditer(pattern, text):
            add(m, make(m))
    found.sort()
    return [Found(s, d) for s, _, d in found]


def _week_offset(word: str) -> int:
    w = word.replace(" ", "")
    return {"다다음주": 2, "다음주": 1, "담주": 1}.get(w, 0)


def _this_or_next_year(today: date, m: int, d: int) -> date | None:
    x = _safe_date(today.year, m, d)
    if x is not None and x < today:
        x = _safe_date(today.year + 1, m, d)
    return x


def _this_or_next_month(today: date, d: int) -> date | None:
    x = _safe_date(today.year, today.month, d)
    if x is None or x < today:
        nxt = _month_add(today, 1)
        x = _safe_date(nxt.year, nxt.month, d)
    return x


def _duration_days(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*일\s*(?:간|동안)", text)
    return int(m[1]) if m else None


def _add_business_days(start: date, days: int) -> date:
    d, left = start, days - 1
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


# ---------- 시각 ----------


@dataclass(frozen=True)
class FoundTime:
    start: int
    end_pos: int
    value: time


def find_times(text: str) -> list[FoundTime]:
    out: list[FoundTime] = []
    pattern = r"(오전|오후|아침|저녁|낮|밤)?\s*(\d{1,2})\s*(?:시\s*(반|(\d{1,2})\s*분)?|:(\d{2}))"
    last_period: str | None = None
    for m in re.finditer(pattern, text):
        if re.match(r"\s*간", text[m.end():]) and m[5] is None:
            continue  # "2시간"은 시각이 아님
        period = m[1] or last_period
        if m[1]:
            last_period = m[1]
        h = int(m[2])
        minute = 30 if m[3] == "반" else int(m[4] or m[5] or 0)
        if period in ("오후", "저녁", "밤") and h < 12:
            h += 12
        elif period is None and 1 <= h <= 7:
            h += 12  # 업무 시간 기준: "3시"는 15시
        if 0 <= h <= 23 and 0 <= minute <= 59:
            out.append(FoundTime(m.start(), m.end(), time(h, minute)))
    return out


def _duration_minutes(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*시간\s*(반)?", text)
    if m:
        return int(m[1]) * 60 + (30 if m[2] else 0)
    m = re.search(r"(\d{1,3})\s*분\s*(?:간|동안)", text)
    if m:
        return int(m[1])
    if re.search(r"반\s*시간", text):
        return 30
    return None


# ---------- 휴가 ----------

LEAVE_WORDS = ("연차", "휴가", "반차", "병가", "월차", "쉬", "경조", "공가", "출근 안", "출근 못")
ROOM_WORDS = ("회의실", "미팅룸", "회의 장소", "방 ", "방을", "방 하나", "룸")


def _leave_type(text: str) -> str | None:
    if "반차" in text or "반가" in text:
        if "오전" in text:
            return "half_am"
        if "오후" in text:
            return "half_pm"
        return None
    if "병가" in text:
        return "sick"
    if any(w in text for w in ("경조", "공가", "특별휴가", "특별 휴가")):
        return "special"
    return "annual"


def _reason(text: str) -> str | None:
    m = re.search(r"사유\s*(?:는|은|:)?\s*(.+?)(?:[.。]|$)", text)
    if m and m[1].strip():
        return m[1].strip()[:200]
    m = re.search(r"([^,.。]*?(?:해서|라서|때문에|가야\s*해서|있어서))", text)
    if m and m[1].strip():
        return m[1].strip()[:200]
    return None


def parse_leave(text: str, today: date) -> SlotResult:
    t = normalize(text)
    missing: list[str] = []
    leave_type = _leave_type(t)
    if leave_type is None:
        missing.append("leave_type")
    dates = find_dates(t, today)
    args: dict[str, Any] = {}
    if leave_type:
        args["leave_type"] = leave_type
    if not dates:
        missing += ["start_date", "end_date"]
    else:
        start = dates[0].value
        if len(dates) >= 2 and re.search(r"부터|~|-|에서", t[dates[0].start:dates[1].start + 1]):
            end = dates[1].value
        elif (n := _duration_days(t)) and leave_type in (None, "annual", "sick", "special"):
            end = _add_business_days(start, n)
        else:
            end = start
        if end < start:
            missing.append("end_date")
        else:
            args["start_date"], args["end_date"] = start.isoformat(), end.isoformat()
    args["reason"] = _reason(t) or DEFAULT_REASON
    return SlotResult("leave", "leave_request", args, tuple(missing))


# ---------- 회의실 ----------


def _attendees(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:명|인)", text)
    return int(m[1]) if m and int(m[1]) >= 1 else None


def _title(text: str) -> str:
    m = re.search(r"(?:제목은|제목:)\s*(.+?)(?:[.。,]|$)", text)
    if m:
        return m[1].strip()[:100]
    m = re.search(r"([가-힣A-Za-z0-9]+(?:\s[가-힣A-Za-z0-9]+)?)\s*(회의|미팅|면접|교육|발표)(?:용|하려고|할|로|$)", text)
    if m and m[1] not in ("회의실", "방"):
        return f"{m[1]} {m[2]}".strip()[:100]
    return DEFAULT_TITLE


def _room_id(text: str, rooms: list[dict[str, Any]] | None) -> str | None:
    if not rooms:
        return None
    for r in sorted(rooms, key=lambda r: len(str(r.get("name", ""))), reverse=True):
        name = str(r.get("name", ""))
        if name and name in text:
            return r["id"]
        if r.get("id") and str(r["id"]) in text:
            return r["id"]
    return None


def parse_room(text: str, today: date, rooms: list[dict[str, Any]] | None = None) -> SlotResult:
    t = normalize(text)
    missing: list[str] = []
    dates = find_dates(t, today)
    times = find_times(t)
    args: dict[str, Any] = {}
    asks_free = bool(re.search(r"비어|빈\s|빈 |가능한|남는|있어\?|있나|있을까|있는지", t))
    wants_reserve = bool(re.search(r"잡아|예약|빌려|잡고|잡을|잡자", t))
    tool = "room_reserve" if wants_reserve else "room_list_availability" if asks_free else "room_reserve"
    if not dates:
        missing.append("date")
    if not times:
        missing.append("startsAt")
    if dates and times:
        day = dates[0].value
        start = datetime.combine(day, times[0].value, KST)
        if len(times) >= 2 and re.search(r"부터|~|-|에서", t[times[0].start:times[1].start + 1]):
            end = datetime.combine(day, times[1].value, KST)
        else:
            end = start + timedelta(minutes=_duration_minutes(t) or 60)
        if end <= start:
            missing.append("endsAt")
        else:
            args["startsAt"], args["endsAt"] = start.isoformat(), end.isoformat()
    n = _attendees(t)
    if tool == "room_list_availability":
        if n:
            args["minCapacity"] = n
    else:
        room = _room_id(t, rooms)
        if room:
            args["roomId"] = room
        else:
            missing.append("roomId")
        args["title"] = _title(t)
        if n:
            args["attendees"] = n
    return SlotResult("room", tool, args, tuple(missing))


# ---------- 입구 ----------


def detect_intent(text: str) -> str | None:
    t = normalize(text)
    room = sum(1 for w in ROOM_WORDS if w in t + " ")
    leave = sum(1 for w in LEAVE_WORDS if w in t)
    if room == leave == 0:
        return None
    return "room" if room > leave else "leave" if leave > room else None


class RuleSlotFiller:
    def fill(self, message: str, today: date, rooms: list[dict[str, Any]] | None = None) -> SlotResult:
        intent = detect_intent(message)
        if intent == "leave":
            return parse_leave(message, today)
        if intent == "room":
            return parse_room(message, today, rooms)
        return SlotResult(None, None, {}, ())
