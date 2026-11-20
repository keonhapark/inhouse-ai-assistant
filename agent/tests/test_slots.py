"""슬롯 파서 기준선. 문장은 도구 입력 스키마만 보고 직접 썼습니다(평가 시나리오에서 가져오지 않음).

기준일 2027-03-02(화).
"""

from __future__ import annotations

from datetime import date

import pytest

from agent_runtime.baseline.slots import RuleSlotFiller, detect_intent, find_dates, find_times, normalize

TODAY = date(2027, 3, 2)
ROOMS = [{"id": "room-a", "name": "회의실 A"}, {"id": "room-b", "name": "회의실 B"}, {"id": "room-big", "name": "대회의실"}]
F = RuleSlotFiller()


def fill(text: str):
    return F.fill(text, TODAY, ROOMS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2027-03-15", "2027-03-15"),
        ("2027년 4월 1일", "2027-04-01"),
        ("3월 20일", "2027-03-20"),
        ("1월 5일", "2028-01-05"),  # 지난 날짜면 내년
        ("4/3", "2027-04-03"),
        ("내일", "2027-03-03"),
        ("모레", "2027-03-04"),
        ("금요일", "2027-03-05"),
        ("화요일", "2027-03-09"),  # 오늘과 같은 요일이면 다음 주
        ("다음 주 월요일", "2027-03-08"),
        ("이번 주 목요일", "2027-03-04"),
        ("다다음주 수요일", "2027-03-17"),
        ("다음 달 첫째 월요일", "2027-04-05"),
        ("다음 달 마지막 금요일", "2027-04-30"),
        ("다음 달 10일", "2027-04-10"),
        ("25일", "2027-03-25"),
        ("1일", "2027-04-01"),  # 이번 달 1일은 지났음
    ],
)
def test_find_dates(text: str, expected: str) -> None:
    [d] = find_dates(text, TODAY)
    assert d.value.isoformat() == expected


def test_duration_is_not_a_date() -> None:
    assert [d.value.isoformat() for d in find_dates("다음 주 월요일부터 3일간", TODAY)] == ["2027-03-08"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("오후 2시", "14:00"), ("오전 10시 반", "10:30"), ("3시", "15:00"), ("9시", "09:00"), ("14:30", "14:30"),
     ("두 시", "14:00"), ("오후 1시 15분", "13:15")],
)
def test_find_times(text: str, expected: str) -> None:
    [t] = find_times(normalize(text))
    assert t.value.strftime("%H:%M") == expected


def test_hours_duration_is_not_a_time() -> None:
    assert find_times(normalize("2시간")) == []


# ---- 휴가 ----


@pytest.mark.parametrize(
    ("text", "args"),
    [
        ("금요일 연차 쓸게", {"leave_type": "annual", "start_date": "2027-03-05", "end_date": "2027-03-05"}),
        ("다음 주 월요일 오전 반차요", {"leave_type": "half_am", "start_date": "2027-03-08", "end_date": "2027-03-08"}),
        ("3월 12일 오후 반차 쓸게요. 병원 가야 해서요",
         {"leave_type": "half_pm", "start_date": "2027-03-12", "end_date": "2027-03-12"}),
        ("3월 15일부터 3월 17일까지 휴가 갈게", {"leave_type": "annual", "start_date": "2027-03-15",
                                         "end_date": "2027-03-17"}),
        ("다음 주 목요일부터 3일간 연차", {"leave_type": "annual", "start_date": "2027-03-11",
                                  "end_date": "2027-03-15"}),  # 주말을 건너뜀
        ("내일 병가 낼게요", {"leave_type": "sick", "start_date": "2027-03-03", "end_date": "2027-03-03"}),
        ("4/9 경조 휴가 신청", {"leave_type": "special", "start_date": "2027-04-09", "end_date": "2027-04-09"}),
    ],
)
def test_leave(text: str, args: dict) -> None:
    r = fill(text)
    assert (r.intent, r.tool, r.missing) == ("leave", "leave_request", ())
    assert {k: r.arguments[k] for k in args} == args
    assert r.arguments["reason"]


def test_leave_reason() -> None:
    assert fill("금요일 연차, 사유는 가족 행사").arguments["reason"] == "가족 행사"
    assert fill("금요일 연차 쓸게").arguments["reason"] == "개인 사정"
    assert "병원" in fill("내일 오후 반차, 병원 가야 해서").arguments["reason"]


@pytest.mark.parametrize(("text", "missing"), [("반차 쓸게요", ("leave_type", "start_date", "end_date")),
                                               ("금요일 반차", ("leave_type",)),
                                               ("연차 쓰고 싶어", ("start_date", "end_date"))])
def test_leave_missing(text: str, missing: tuple) -> None:
    assert fill(text).missing == missing


# ---- 회의실 ----


def test_room_reserve_full() -> None:
    r = fill("내일 오후 2시부터 4시까지 회의실 B 6명 예약해 줘")
    assert (r.intent, r.tool, r.missing) == ("room", "room_reserve", ())
    assert r.arguments == {"roomId": "room-b", "startsAt": "2027-03-03T14:00:00+09:00",
                           "endsAt": "2027-03-03T16:00:00+09:00", "title": "회의", "attendees": 6}


def test_room_reserve_duration_and_title() -> None:
    r = fill("금요일 10시 대회의실 2시간 잡아 줘, 제목은 분기 보고")
    assert r.arguments["roomId"] == "room-big"
    assert (r.arguments["startsAt"], r.arguments["endsAt"]) == ("2027-03-05T10:00:00+09:00",
                                                               "2027-03-05T12:00:00+09:00")
    assert r.arguments["title"] == "분기 보고"


def test_room_without_known_room_is_missing_room_id() -> None:
    r = fill("내일 오후 2시에 네 명 들어갈 회의실 잡아 줘")
    assert r.tool == "room_reserve" and r.missing == ("roomId",)
    assert r.arguments["attendees"] == 4 and r.arguments["endsAt"].endswith("15:00:00+09:00")


def test_room_availability() -> None:
    r = fill("목요일 오전 10시 반에 8명 쓸 회의실 비어 있어?")
    assert (r.tool, r.missing) == ("room_list_availability", ())
    assert r.arguments == {"startsAt": "2027-03-04T10:30:00+09:00", "endsAt": "2027-03-04T11:30:00+09:00",
                           "minCapacity": 8}


def test_room_missing_time_and_date() -> None:
    assert fill("회의실 예약해 줘").missing == ("roomId", "startsAt", "endsAt")


def test_unknown_intent() -> None:
    r = fill("점심 메뉴 추천해 줘")
    assert (r.intent, r.tool, r.arguments) == (None, None, {})
    assert detect_intent("휴가 전에 회의실 잡아 줘") is None  # 둘 다면 고르지 않음


def test_result_dict() -> None:
    d = fill("금요일 연차").to_dict()
    assert set(d) == {"intent", "tool", "arguments", "missing"} and isinstance(d["missing"], list)


# ---- 리뷰에서 나온 회귀(기준일 2027-03-02) ----


def test_required_slots_match_contract() -> None:
    import json

    from agent_runtime.baseline.slots import REQUIRED
    from tests.conftest import CONTRACTS

    tools = {t["name"]: t for t in json.loads((CONTRACTS / "mcp" / "tools.json").read_text("utf-8"))["tools"]}
    for name, required in REQUIRED.items():
        assert tuple(tools[name]["inputSchema"]["required"]) == required


def test_n_days_after_from_is_duration() -> None:
    r = fill("25일부터 3일 연차")
    assert (r.arguments["start_date"], r.arguments["end_date"]) == ("2027-03-25", "2027-03-29")  # 주말 건너뜀
    assert fill("25일부터 26일까지 연차").arguments["end_date"] == "2027-03-26"


def test_invalid_date_is_not_reread() -> None:
    r = fill("2월 30일 연차")
    assert "start_date" not in r.arguments and r.missing == ("start_date", "end_date")


def test_range_check_ignores_hyphens_inside_dates() -> None:
    r = fill("2027-04-01 연차, 2027-04-05 복귀")
    assert r.arguments["end_date"] == "2027-04-01"


def test_morning_does_not_carry_to_later_hour() -> None:
    r = fill("내일 오전 11시부터 1시까지 회의실 A 예약")
    assert (r.arguments["startsAt"], r.arguments["endsAt"]) == ("2027-03-03T11:00:00+09:00",
                                                               "2027-03-03T13:00:00+09:00")


@pytest.mark.parametrize(("text", "end"), [("내일 오후 3시 회의실 A 1시간 30분 예약", "16:30"),
                                           ("내일 2시부터 30분 회의실 A 예약", "14:30"),
                                           ("내일 2시 30분 회의실 A 예약", "15:30")])
def test_meeting_length(text: str, end: str) -> None:
    assert fill(text).arguments["endsAt"] == f"2027-03-03T{end}:00+09:00"


def test_half_day_uses_word_before_bancha() -> None:
    assert fill("오전 10시 회의 끝나고 오후 반차 쓸게요 내일").arguments["leave_type"] == "half_pm"


@pytest.mark.parametrize(("text", "missing"), [("3월 20일부터 3월 10일까지 연차", ("start_date", "end_date")),
                                               ("회의실 A 예약 오후 3시", ("startsAt", "endsAt")),
                                               ("내일 회의실 A 예약", ("startsAt", "endsAt"))])
def test_missing_lists_required_slots(text: str, missing: tuple) -> None:
    assert fill(text).missing == missing


def test_room_name_ignores_spaces() -> None:
    assert fill("내일 회의실A 2시 예약").arguments["roomId"] == "room-a"


def test_midnight() -> None:
    assert find_times(normalize("밤 12시"))[0].value.strftime("%H:%M") == "00:00"
