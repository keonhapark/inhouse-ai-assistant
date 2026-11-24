"""도구 호출 LoRA 학습 데이터 생성기(#469, #111). GPU 없이 돕니다. 학습은 GPU 사용권을 받아 따로 합니다(QLoRA).

학습 예시는 업무 실행의 첫 계획 호출과 같은 모양입니다: 에이전트 system 프롬프트(`run/graph.py` system_prompt), 그 에이전트가
보는 도구 정의(`contracts/mcp/tools.json`의 inputSchema, OpenAI 함수 형식), 사용자 발화 한 줄, 그리고 정답 행동 하나.

- direct: 필요한 값이 발화에 다 있어 그 도구를 바로 부름
- resolve: 값을 조회로 찾을 수 있어 조회 도구를 먼저 부름(직원 이름 → org_search_employees, 문서·예약·위임 ID 없음 → 목록)
- clarify: 필수 값이 빠져 도구 없이 빠진 값만 물음(선택 값은 묻지 않음)

값은 도구 계약과 팩 고정 데이터(직원·회의실·품목·양식)에서만 고르고, 문장 틀은 이 파일에 직접 썼습니다. 평가용 묶음과 섞이지
않게 확인 묶음은 읽지 않고, 개발 묶음(`eval_dev/tool_calls.jsonl`)과 같은 문장이 나오면 버립니다. 같은 시드면 같은 데이터입니다.

    uv run python lora/make_toolcall_data.py --out <저장소 밖 폴더> [--per-tool 150] [--seed 7] [--valid-ratio 0.1]

출력: `train.jsonl`, `valid.jsonl`(줄마다 {id, agent, kind, tool, today, tools, messages}), `manifest.json`(개수·시드·입력 해시).
assistant 도구 호출은 `{"role": "assistant", "content": "", "tool_calls": [{"type": "function", "function": {"name", "arguments"}}]}`이고
arguments는 객체입니다(Hugging Face chat template의 tools·tool_calls 형식).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.registry import Agent, Registry
from agent_runtime.run.args import optional_args
from agent_runtime.run.graph import system_prompt
from overlap import CONTAIN_NEAR, JACCARD_NEAR, is_overlap, pack_names, read_eval, scores, skeleton

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS_JSON = ROOT / "contracts" / "mcp" / "tools.json"
DEV_SET = HERE.parent / "eval_dev" / "tool_calls.jsonl"
DEFAULT_PACK = ROOT / "packs" / "manufacturing"
WEEKDAYS = "월화수목금토일"
GRADE_WORDS = {"team_leader": "팀장님", "division_head": "본부장님", "staff": "님", "ceo": "대표님"}

# 자유 문장 값(사유·목적·제목·질문). 업종과 관계없는 말만 씁니다.
LEAVE_REASONS = ["개인 사정", "가족 행사", "병원 진료", "이사", "자녀 학교 행사", "여행", "은행 업무", "건강 검진",
                 "부모님 병원 동행", "집안 일", "관공서 업무", "자격증 시험", "가족 여행", "휴식"]
SICK_REASONS = ["감기 몸살", "병원 진료", "치과 치료", "장염", "허리 통증", "독감", "두통"]
SPECIAL_REASONS = ["본인 결혼", "형제 결혼", "조부모 장례", "배우자 출산", "자녀 결혼"]
DELEGATION_REASONS = ["출장", "휴가", "교육 참석", "외근", "파견", "해외 출장", "장기 교육"]
MEETING_TITLES = ["주간 회의", "고객 미팅", "신입 면담", "분기 계획 회의", "프로젝트 점검", "업체 미팅", "교육 준비",
                  "면접", "월간 보고", "팀 회식 계획", "제안서 검토", "1:1 면담"]
MERCHANTS = ["가람식당", "온누리택시", "한빛문구", "새솔카페", "푸른주유소", "다온한식", "하늘빛편의점", "미소분식",
             "바른약국", "솔내음중식", "누리복사", "해든주차장"]
EXPENSE_PURPOSES = ["팀 회의 식사", "고객사 방문 교통비", "사무용품 구입", "외근 이동", "야근 식대", "거래처 접대",
                    "출장 숙박", "주차비", "회의 다과", "택배 발송"]
PURCHASE_REASONS = ["재고 보충", "설비 정비", "신규 작업 준비", "소모품 교체", "시험용", "예비품 확보", "고장 부품 교체"]
POLICY_QUESTIONS = [
    ("출장 일비는 하루 얼마야?", "출장 일비 기준"), ("경조사 휴가 며칠 쓸 수 있어?", "경조사 휴가 일수"),
    ("야근 식대 한도가 얼마야?", "야근 식대 한도"), ("재택근무 신청은 어떻게 해?", "재택근무 신청 절차"),
    ("법인카드 분실하면 어떻게 해야 돼?", "법인카드 분실 처리 절차"), ("교육비 지원 규정 알려 줘", "교육비 지원 규정"),
    ("회의실 예약은 며칠 전까지 해야 돼?", "회의실 예약 기한"), ("명절 선물 받으면 신고해야 해?", "선물 수수 신고 규정"),
    ("반차는 몇 시부터 몇 시까지야?", "반차 시간 기준"), ("연차는 몇 년 차에 며칠 생겨?", "연차 발생 기준"),
    ("병가 쓸 때 진단서가 필요해?", "병가 증빙 서류"), ("해외 출장 숙박비 한도 알려 주세요", "해외 출장 숙박비 한도"),
    ("택시비는 언제 경비로 인정돼?", "택시비 경비 인정 기준"), ("결재는 누가 대신 해 줄 수 있어?", "결재 대결 규정"),
    ("구매 요청은 얼마부터 본부장 결재야?", "구매 요청 결재선 금액 기준"), ("보안 교육은 일 년에 몇 번 들어야 해?", "보안 교육 이수 기준"),
]
TICKETS = [("incident", "노트북이 부팅되지 않아요", "아침부터 노트북 전원이 켜지지 않습니다"),
           ("incident", "사내 메일 접속 오류", "메일에 로그인하면 계속 오류가 납니다"),
           ("access_request", "공유 폴더 권한 요청", "팀 공유 폴더 읽기 권한이 필요합니다"),
           ("incident", "프린터 인쇄 안 됨", "3층 프린터로 인쇄가 되지 않습니다"),
           ("other", "모니터 추가 요청", "작업용 모니터 한 대가 더 필요합니다"),
           ("incident", "VPN 연결 끊김", "재택 중 VPN이 10분마다 끊깁니다"),
           ("access_request", "회계 시스템 조회 권한", "회계 시스템 조회 권한을 신청합니다"),
           ("incident", "화상 회의 소리 안 들림", "화상 회의에서 상대 목소리가 들리지 않습니다"),
           ("other", "키보드 교체 요청", "키보드 몇 개 키가 눌리지 않습니다")]
KOREAN_HOURS = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열",
                11: "열한", 12: "열두"}
DO = ["해 줘", "해 주세요", "해줘", "해 줄래?", "해 주실래요?", "해 주시겠어요?", " 부탁해요", " 부탁드립니다"]
SHOW = ["보여 줘", "보여 주세요", "알려 줘", "알려 주세요", "확인해 줘", "좀 봐 줘"]


def josa(word: str, pair: str = "을를") -> str:
    """받침이 있으면 앞 글자(을·이·은), 없으면 뒤 글자(를·가·는)."""
    ch = word[-1]
    if ch.isascii():
        # 영문·숫자로 끝나면 읽는 소리로 받침을 가립니다(0·1·3·6·7·8과 L·M·N·R은 받침)
        has = ch.upper() in "0136789LMNR"
    else:
        has = 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 != 0
    return word + (pair[0] if has else pair[1])


def _batchim(word: str) -> int:
    """끝 글자 받침 번호(0이면 없음, 8이면 ㄹ). 영문·숫자는 읽는 소리로 어림합니다."""
    ch = word[-1]
    if ch.isascii():
        return 8 if ch.upper() in "1782L" else (1 if ch.upper() in "036MNR" else 0)
    return (ord(ch) - 0xAC00) % 28 if 0xAC00 <= ord(ch) <= 0xD7A3 else 0


def euro(word: str) -> str:
    """으로/로(받침이 없거나 ㄹ이면 로)."""
    return word + ("로" if _batchim(word) in (0, 8) else "으로")


def ira(word: str) -> str:
    """이라/라."""
    return word + ("이라" if _batchim(word) else "라")


def ieyo(word: str) -> str:
    """이에요/예요."""
    return word + ("이에요" if _batchim(word) else "예요")


@dataclass
class Ctx:
    rng: random.Random
    today: date
    me: dict[str, Any]
    people: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    items: list[dict[str, Any]]
    forms: dict[str, str]  # 양식 id → 이름

    def pick(self, xs: list[Any]) -> Any:
        return self.rng.choice(xs)

    def do(self, verb: str, rest: str = "") -> str:
        """'신청' → '신청해 줘', '신청 부탁해요' …. rest가 있으면 문장을 끊고 잇습니다('신청해 주세요. 사유는 …')."""
        s = verb + self.pick(DO)
        if rest:
            s += ("" if s.endswith(("?", ".")) else ".") + " " + rest
        return s

    def show(self) -> str:
        return self.pick(SHOW)

    # ---- 날짜 표현(말, 값) ----
    def day(self, future: bool = True) -> tuple[str, date]:
        t, r = self.today, self.rng.random()
        if not future:
            if r < 0.25:
                return "어제", t - timedelta(days=1)
            if r < 0.35:
                return "그저께", t - timedelta(days=2)
            if r < 0.55:
                wd = self.rng.randint(0, 4)
                return f"지난주 {WEEKDAYS[wd]}요일", t - timedelta(days=t.weekday() + 7 - wd)
            d = t - timedelta(days=self.rng.randint(1, 20))
            return (f"{d.month}/{d.day}" if self.rng.random() < 0.3 else f"{d.month}월 {d.day}일"), d
        if r < 0.15:
            return "내일", t + timedelta(days=1)
        if r < 0.22:
            return "모레", t + timedelta(days=2)
        if r < 0.32 and t.weekday() < 3:
            wd = self.rng.randint(t.weekday() + 1, 4)
            return f"이번 주 {WEEKDAYS[wd]}요일", t + timedelta(days=wd - t.weekday())
        if r < 0.52:
            wd = self.rng.randint(0, 4)
            return f"다음 주 {WEEKDAYS[wd]}요일", t + timedelta(days=7 - t.weekday() + wd)
        if r < 0.6:
            first = (t.replace(day=1) + timedelta(days=32)).replace(day=1)
            d = first.replace(day=self.rng.randint(1, 25))
            return f"다음 달 {d.day}일", d
        d = t + timedelta(days=self.rng.randint(3, 45))
        if r < 0.7:
            return f"{d.month}/{d.day}", d
        if r < 0.78 and d.month == t.month:
            return f"{d.day}일", d
        return f"{d.month}월 {d.day}일", d

    def time(self) -> tuple[str, int, int]:
        """(말, 시, 분). 업무 시간 안에서만 고릅니다."""
        h = self.pick([9, 10, 11, 13, 14, 15, 16])
        m = 30 if self.rng.random() < 0.2 else 0
        r = self.rng.random()
        half = " 반" if m else ""
        if r < 0.45:
            text = f"오전 {h}시{half}" if h < 12 else f"오후 {h - 12}시{half}"
        elif r < 0.65:
            text = f"{h}시" + (" 30분" if m else "")
        elif r < 0.85:
            text = (f"오전 {KOREAN_HOURS[h]} 시" if h < 12 else f"오후 {KOREAN_HOURS[h - 12]} 시") + half
        else:
            text = f"{h}:{m:02d}"
        return text, h, m

    def duration(self) -> tuple[str, int]:
        return self.pick([("한 시간", 60), ("1시간", 60), ("30분", 30), ("1시간 반", 90), ("두 시간", 120), ("2시간", 120)])

    def other(self) -> dict[str, Any]:
        return self.pick([p for p in self.people if p["id"] != self.me["id"]])

    def rid(self, prefix: str) -> str:
        return f"{prefix}-{self.rng.randint(1000, 9999)}"

    def won(self, n: int) -> str:
        return self.pick([f"{n:,}원", f"{n}원", f"{n:,} 원"])


def iso(d: date, h: int = 0, m: int = 0) -> str:
    return datetime(d.year, d.month, d.day, h, m).isoformat() + "+09:00"


def slot(d: date, h: int, m: int, minutes: int) -> tuple[str, str]:
    start = datetime(d.year, d.month, d.day, h, m)
    end = start + timedelta(minutes=minutes)
    return start.isoformat() + "+09:00", end.isoformat() + "+09:00"


def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "call", "tool": tool, "args": args}


def ask(*labels: str) -> dict[str, Any]:
    return {"type": "clarify", "labels": list(labels)}


Example = tuple[str, str, dict[str, Any]]  # (kind, 발화, 정답)
Maker = Callable[[Ctx], Example]


# ---- 도구별 문장 틀 ----

def leave(c: Ctx) -> Example:
    k = c.rng.random()
    word, d = c.day()
    reason = c.pick(LEAVE_REASONS)
    one = {"start_date": d.isoformat(), "end_date": d.isoformat()}
    if k < 0.3:
        typ, kw = c.pick([("annual", "연차"), ("annual", "연차 하루"), ("half_am", "오전 반차"), ("half_pm", "오후 반차")])
        text = c.pick([f"{word} {kw} 쓸게요. {reason} 때문이에요", f"{word} {kw} {c.do('신청', f'사유는 {reason}')}",
                       f"{reason} 때문에 {word} {kw} 낼게요", f"{word}에 {kw} 좀 쓸게. {reason}"])
        return "direct", text, call("leave_request", {"leave_type": typ, **one, "reason": reason})
    if k < 0.48:
        n = c.rng.randint(2, 5)
        end = d + timedelta(days=n - 1)
        span = c.pick([f"{d.month}월 {d.day}일부터 {end.month}월 {end.day}일까지", f"{d.month}/{d.day}~{end.month}/{end.day}",
                       f"{word}부터 {n}일 동안"])
        text = c.pick([f"{span} 연차 {c.do('신청', f'사유는 {reason}')}", f"{ira(reason)} {span} 휴가 쓸게요",
                       f"{span} 연차 낼게요. {reason}"])
        return "direct", text, call("leave_request", {"leave_type": "annual", "start_date": d.isoformat(),
                                                      "end_date": end.isoformat(), "reason": reason})
    if k < 0.58:
        reason = c.pick(SICK_REASONS)
        text = c.pick([f"{word} 병가 하루 낼게요. {reason}", f"{reason} 때문에 {word} 병가 {c.do('신청')}",
                       f"{word} 아파서 병가 쓸게요. {ieyo(reason)}"])
        return "direct", text, call("leave_request", {"leave_type": "sick", **one, "reason": reason})
    if k < 0.65:
        reason = c.pick(SPECIAL_REASONS)
        return "direct", f"{euro(reason)} {word} 특별휴가 {c.do('신청')}", call(
            "leave_request", {"leave_type": "special", **one, "reason": reason})
    if k < 0.8:
        return "clarify", c.pick([f"{word} 연차 쓸게요", f"{word} 오후 반차 {c.do('신청')}", f"{word} 하루 쉴게요"]), ask("사유")
    if k < 0.9:
        return "clarify", c.pick([f"{reason} 때문에 연차 하루 쓸게요", f"연차 {c.do('신청', ieyo(reason))}"]), ask("날짜")
    return "clarify", c.pick(["휴가 좀 쓰려고요", "연차 신청하고 싶어", "휴가 신청서 올려 줘"]), ask("휴가 종류", "날짜", "사유")


def leave_balance(c: Ctx) -> Example:
    return "direct", c.pick([
        "연차 며칠 남았어?", "남은 휴가 일수 알려 줘", "올해 쓸 수 있는 연차가 몇 개야?", "내 휴가 잔여 확인해 줘",
        "연차 잔여 일수 좀 알려 주세요", "올해 연차 얼마나 썼고 얼마나 남았어?", "휴가 몇 개 남았나요?",
        "남은 연차 조회해 줘", "이번 해 남은 연차 있어?", "제 연차 잔여 확인 부탁드려요"]), call("leave_get_balance", {})


def profile(c: Ctx) -> Example:
    return "direct", c.pick([
        "내 직급이 뭐로 돼 있어?", "내 소속이랑 입사일 알려 줘", "내 인사 정보 보여 줘", "제 사번이 뭐였죠?",
        "내가 무슨 팀으로 등록돼 있어?", "제 입사일 확인해 주세요", "내 프로필 정보 알려 줘"]), call("hr_get_my_profile", {})


def approvals(c: Ctx) -> Example:
    k = c.rng.random()
    if k < 0.3:
        return "direct", c.pick([f"내가 올린 결재 다 {c.show()}", f"내 결재 목록 {c.show()}", "내가 상신한 문서들 어떻게 됐어?",
                                 "제가 올린 결재들 상태 알려 주세요"]), call("approval_list_mine", {})
    status, words = c.pick([("in_progress", ["진행 중인", "아직 결재 안 끝난", "대기 중인"]),
                            ("approved", ["승인된", "결재 끝난", "통과된"]),
                            ("rejected", ["반려된", "반려당한"]), ("withdrawn", ["회수한", "내가 거둬들인"])])
    w = c.pick(words)
    if k < 0.65:
        return "direct", c.pick([f"내가 올린 결재 중에 {w} 것만 {c.show()}", f"{w} 내 결재 {c.show()}",
                                 f"내 결재 중 {w} 거 있어?"]), call("approval_list_mine", {"status": status})
    doc = c.rid("doc")
    return "direct", c.pick([f"결재 {doc} 지금 어디까지 갔어?", f"{doc} 결재 상태 {c.show()}", f"{doc} 누가 결재 안 했어?",
                             f"문서 {doc} 진행 상황 {c.show()}"]), call("approval_get", {"documentId": doc})


def withdraw(c: Ctx) -> Example:
    k = c.rng.random()
    doc = c.rid("doc")
    if k < 0.35:
        return "direct", c.pick([f"결재 {doc} {c.do('회수')}", f"{doc} 올린 거 취소하고 싶어요", f"{doc} 결재 거둬들여 줘"]), call(
            "approval_withdraw", {"documentId": doc})
    if k < 0.5:
        reason = c.pick(["날짜를 잘못 적어서", "금액이 틀려서", "일정이 바뀌어서", "중복으로 올려서"])
        return "direct", f"{reason} {doc} 결재 {c.do('회수')}", call(
            "approval_withdraw", {"documentId": doc, "reason": reason})
    form = c.pick(list(c.forms.values()))
    when = c.pick(["지난번에", "어제", "아까", "지난주에", "오늘 아침에", ""])
    return "resolve", f"{when} 올린 {form} 결재 {c.do('회수')}".strip(), call("approval_list_mine", {})


def delegation(c: Ctx) -> Example:
    k = c.rng.random()
    p = c.other()
    word, d = c.day()
    end = d + timedelta(days=c.rng.randint(1, 6))
    reason = c.pick(DELEGATION_REASONS)
    fid, fname = c.pick(list(c.forms.items()))
    span = c.pick([f"{d.month}월 {d.day}일부터 {end.month}월 {end.day}일까지", f"{d.month}/{d.day}~{end.month}/{end.day}"])
    base = {"delegateId": p["id"], "startsAt": iso(d), "endsAt": iso(end), "formTypes": [fid], "reason": reason}
    if k < 0.25:
        return "direct", c.pick([f"{span} {fname} 결재를 {p['id']}에게 맡겨 줘. {reason} 때문이야",
                                 f"{ira(reason)} {span} {fname} 결재는 {p['id']}가 대신 하게 {c.do('설정')}",
                                 f"{p['id']}한테 {span} {fname} 결재 대결 {c.do('등록', f'사유는 {reason}')}"]), call(
            "delegation_register", base)
    if k < 0.32 and fid != "leave":
        limit = c.pick([500000, 1000000, 2000000, 3000000])
        return "direct", f"{span} {fname} 결재를 {limit // 10000}만 원 한도로 {p['id']}에게 맡겨 줘. {reason}", call(
            "delegation_register", {**base, "maxAmount": limit})
    if k < 0.47:
        title = GRADE_WORDS.get(p["grade"], "님")
        sep = "" if title == "님" else " "
        return "resolve", c.pick([f"{span} {ira(reason)} 결재를 {p['name']}{sep}{title}께 맡겨 줘",
                                  f"{reason} 가는 동안 {fname} 결재는 {p['name']}{sep}{title}한테 맡겨 줘"]), call(
            "org_search_employees", {"q": p["name"]})
    if k < 0.57:
        return "clarify", c.pick([f"{p['id']}에게 결재 좀 맡겨 줘", f"{p['id']}한테 대결 걸어 줘"]), ask("기간", "맡길 결재 종류", "사유")
    if k < 0.64:
        return "clarify", f"{span} {fname} 결재 누구한테 좀 맡겨 줘. {reason}", ask("맡을 사람")
    if k < 0.8:
        role, w = c.pick([("delegator", c.pick(["내가 맡긴", "내가 다른 사람한테 넘긴"])),
                          ("delegate", c.pick(["내가 대신 맡은", "나한테 넘어온"]))])
        return "direct", f"{w} 대결 목록 {c.show()}", call("delegation_list", {"role": role})
    if k < 0.9:
        dlg = c.rid("dlg")
        return "direct", c.pick([f"대결 {dlg} {c.do('해지')}", f"{dlg} 위임 취소할게요", f"{dlg} 대결 이제 풀어 줘"]), call(
            "delegation_revoke", {"delegationId": dlg})
    return "resolve", c.pick(["내가 맡긴 대결 취소해 줘", "걸어 둔 결재 위임 풀어 주세요", "출장 끝나서 대결 해지할게"]), call(
        "delegation_list", {"role": "delegator"})


def people(c: Ctx) -> Example:
    p = c.other()
    n = p["name"]
    return "direct", c.pick([f"{n} 사번 {c.show()}", f"{josa(n, '은는')} 어느 부서야?", f"{n} 씨 연락처 찾아 줘",
                             f"{n} 님 이메일 주소 {c.show()}", f"우리 회사에 {ira(n)}는 분 있어?", f"{n} 직급이 뭐야?"]), call(
        "org_search_employees", {"q": n})


def policy(c: Ctx) -> Example:
    q, key = c.pick(POLICY_QUESTIONS)
    return "direct", q, call("policy_search", {"question": key})


def rooms(c: Ctx) -> Example:
    k = c.rng.random()
    word, d = c.day()
    tw, h, m = c.time()
    dw, minutes = c.duration()
    start, end = slot(d, h, m, minutes)
    if k < 0.22:
        n = c.rng.randint(3, 12)
        return "direct", c.pick([f"{word} {tw}부터 {dw} 동안 {n}명 들어갈 회의실 있어?", f"{word} {tw}에 {n}명 회의할 방 찾아 줘. {dw}",
                                 f"{n}명이 {word} {tw}부터 {dw} 쓸 회의실 {c.show()}"]), call(
            "room_list_availability", {"startsAt": start, "endsAt": end, "minCapacity": n})
    if k < 0.32:
        return "direct", f"{word} {tw}부터 {dw} 비어 있는 회의실 {c.show()}", call(
            "room_list_availability", {"startsAt": start, "endsAt": end})
    room = c.pick(c.rooms)
    title = c.pick(MEETING_TITLES)
    if k < 0.5:
        return "direct", c.pick([f"{josa(room['id'])} {word} {tw}부터 {dw} {c.do('예약', title)}",
                                 f"{word} {tw}부터 {dw} {room['id']} 잡아 줘. {title} 할 거야",
                                 f"{title} 때문에 {room['id']} {word} {tw}부터 {dw} 예약할게요"]), call(
            "room_reserve", {"roomId": room["id"], "startsAt": start, "endsAt": end, "title": title})
    if k < 0.6:
        return "resolve", c.pick([f"{word} {tw}부터 {dw} {room['name']} {c.do('예약', title)}",
                                  f"{euro(room['name'])} {word} {tw}에 {dw} 잡아 줘. {title}"]), call(
            "room_list_availability", {"startsAt": start, "endsAt": end})
    if k < 0.68:
        return "clarify", c.pick([f"{word} 회의실 잡아 줘", f"{word} {title}할 회의실 필요해"]), ask("시간")
    if k < 0.74:
        return "clarify", c.pick(["회의실 하나 잡아 줘", "회의실 예약하고 싶어요", f"{title}할 방 좀 잡아 주세요"]), ask("날짜", "시간")
    if k < 0.84:
        if c.rng.random() < 0.5:
            return "direct", c.pick([f"내 회의실 예약 다 {c.show()}", "제가 잡은 회의실 목록 알려 주세요"]), call(
                "room_list_my_reservations", {})
        return "direct", f"{word} 내가 잡은 회의실 {c.show()}", call("room_list_my_reservations", {"date": d.isoformat()})
    if k < 0.92:
        rsv = c.rid("rsv")
        return "direct", c.pick([f"회의실 예약 {rsv} {c.do('취소')}", f"{rsv} 예약 필요 없어졌어. 취소해 줘"]), call(
            "room_cancel_reservation", {"reservationId": rsv})
    return "resolve", c.pick([f"{word}에 잡은 회의실 예약 {c.do('취소')}", f"{word} 회의 취소됐어. 예약한 방 빼 줘"]), call(
        "room_list_my_reservations", {"date": d.isoformat()})


def expense(c: Ctx) -> Example:
    k = c.rng.random()
    word, d = c.day(future=False)
    amount = c.pick([4500, 8000, 12500, 15000, 23000, 36000, 48000, 64000, 87000, 120000, 152000])
    m, purpose = c.pick(MERCHANTS), c.pick(EXPENSE_PURPOSES)
    args = {"amount": amount, "spent_on": d.isoformat(), "merchant": m, "purpose": purpose}
    if k < 0.4:
        return "direct", c.pick([f"{word} {m}에서 쓴 {c.won(amount)} 경비 {c.do('정산', purpose)}",
                                 f"{euro(purpose)} {word} {m}에 {c.won(amount)} 냈어. 경비 처리해 줘",
                                 f"경비 정산: {word}, {m}, {c.won(amount)}, {purpose}",
                                 f"{word} {purpose} {c.won(amount)} {m} 영수증 정산 부탁해요"]), call("expense_request", args)
    if k < 0.5:
        bno = f"{c.rng.randint(100, 999)}-{c.rng.randint(10, 99)}-{c.rng.randint(10000, 99999)}"
        return "direct", f"{word} {m}(사업자번호 {bno})에서 {c.won(amount)} 썼어요. {euro(purpose)} 정산해 주세요", call(
            "expense_request", {**args, "business_no": bno})
    if k < 0.72:
        return "clarify", c.pick([f"{word} {m}에서 {c.won(amount)} 썼는데 정산해 줘", f"{m} {c.won(amount)} 경비 올려 줘. {word}"]), ask(
            "사용 목적")
    if k < 0.85:
        return "clarify", f"{word} {m}에서 {euro(purpose)} 쓴 거 정산해 줘", ask("금액")
    return "clarify", c.pick(["경비 정산 좀 올려 줘", "영수증 처리해야 해", "법인카드 쓴 거 정산하고 싶어요"]), ask(
        "금액", "사용일", "가맹점", "사용 목적")


def purchase(c: Ctx) -> Example:
    k = c.rng.random()
    it = c.pick(c.items)
    qty = c.pick([5, 10, 20, 30, 50, 100, 200, 500])
    price = it["unit_price"]
    reason = c.pick(PURCHASE_REASONS)
    args = {"item_code": it["code"], "quantity": qty, "unit_price": price, "total_amount": qty * price, "reason": reason}
    if k < 0.4:
        return "direct", c.pick([f"{it['code']} {qty}개를 개당 {c.won(price)}에 구매 {c.do('요청', reason)}",
                                 f"{reason} 때문에 {it['code']} {qty}개 사야 해. 단가 {c.won(price)}",
                                 f"구매 요청 올려 줘: {it['code']}, {qty}개, 개당 {c.won(price)}, 사유 {reason}"]), call(
            "purchase_request", args)
    if k < 0.5:
        return "direct", f"{it['code']} {qty}개, 단가 {c.won(price)}, 총 {c.won(qty * price)}에 구매 요청해 줘. {reason}", call(
            "purchase_request", args)
    if k < 0.68:
        # 단가가 빠졌지만 품목 조회(item_search)로 찾을 수 있어 먼저 조회합니다(#466)
        return "resolve", c.pick([f"{it['code']} {qty}개 구매 요청 올려 줘. {reason}", f"{reason}용으로 {it['code']} {qty}개 사 줘"]), call(
            "item_search", {"q": it["code"]})
    if k < 0.82:
        return "direct", c.pick([f"{it['code']} 재고 몇 개 남았어?", f"{it['code']} 단가 얼마야?", f"{it['code']} 재고랑 단가 {c.show()}"]), call(
            "item_search", {"q": it["code"]})
    if k < 0.9:
        return "clarify", f"{it['code']} 개당 {c.won(price)}에 구매 요청해 줘. {reason}", ask("수량")
    return "clarify", c.pick([f"{it['name']} 좀 사야 해요", "구매 요청 하나 올려 줘", "부품 주문 좀 해 주세요"]), ask(
        "품목 코드", "수량", "단가", "사유")


def tickets(c: Ctx) -> Example:
    k = c.rng.random()
    cat, title, desc = c.pick(TICKETS)
    if k < 0.4:
        verb = "장애 접수" if cat == "incident" else "요청 접수"
        return "direct", c.pick([f"{desc}. {c.do(verb)}", f"{verb} 부탁해요. {desc}"]), call(
            "ticket_create", {"category": cat, "title": title, "description": desc})
    if k < 0.5:
        return "direct", f"급해요. {desc}. 장애 접수해 주세요", call(
            "ticket_create", {"category": cat, "title": title, "description": desc, "priority": "high"})
    if k < 0.6:
        return "clarify", c.pick(["IT 티켓 하나 만들어 줘", "장애 접수하려고요", "전산실에 요청 하나 넣어 줘"]), ask("내용")
    if k < 0.8:
        return "direct", c.pick([f"내가 올린 티켓 목록 {c.show()}", f"내 요청 처리 상황 {c.show()}", "접수한 장애 어떻게 되고 있어?"]), call(
            "ticket_list", {})
    t = c.rid("tkt")
    return "direct", c.pick([f"티켓 {t} 어떻게 됐어?", f"{t} 처리 상황 {c.show()}"]), call("ticket_get", {"ticketId": t})


MAKERS: dict[str, Maker] = {
    "leave_request": leave, "leave_get_balance": leave_balance, "hr_get_my_profile": profile,
    "approval_list_mine": approvals, "approval_withdraw": withdraw, "delegation_register": delegation,
    "org_search_employees": people, "policy_search": policy, "room_list_availability": rooms,
    "expense_request": expense, "purchase_request": purchase, "ticket_create": tickets,
}


# ---- 조립 ----

def clarify_text(labels: list[str]) -> str:
    joined = ", ".join(labels)
    return f"{josa(joined)} 알려 주세요."


def _norm(s: str) -> str:
    return re.sub(r"[\s.,!?~]+", "", s)


def _grams(s: str, n: int = 3) -> set[str]:
    t = _norm(s)
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


NEAR = 0.6  # 글자 3-gram 자카드 유사도가 이 값 이상이면 근접 중복으로 봅니다


class Excluded:
    """평가 묶음 문장과 겹치는 생성 문장을 걸러냅니다. 평가 문장은 toolcall-v1 jsonl과 시나리오 YAML(또는 그 폴더)을
    받습니다(`overlap.read_eval`).

    - exact: 공백·문장부호만 다른 같은 문장
    - near: 글자 3-gram 자카드 NEAR 이상(#544)
    - skeleton: ID·숫자·팩 이름을 바꾸고 말끝을 뗀 문장 틀이 겹침(#653, `overlap.py`의 자카드·포함 비율 기준).
      "결재 doc-1077 회수해 줘" 대 "결재 doc-6617 회수해 줘"처럼 값만 바꾼 문장을 거릅니다
    """

    def __init__(self, files: list[Path], pack: Path | None = None) -> None:
        self.texts = [text for f in files for _, text, _ in read_eval(f)]
        self.exact = {_norm(t) for t in self.texts}
        self.grams = [_grams(t) for t in self.texts]
        self.names = pack_names(pack or DEFAULT_PACK)
        self.skeletons = [skeleton(t, self.names) for t in self.texts]
        self._dropped: dict[str, set[str]] = {"exact": set(), "near": set(), "skeleton": set()}

    @property
    def dropped(self) -> dict[str, int]:
        """걸러낸 서로 다른 생성 문장 수."""
        return {k: len(v) for k, v in self._dropped.items()}

    def hit(self, text: str) -> bool:
        if _norm(text) in self.exact:
            self._dropped["exact"].add(_norm(text))
            return True
        g = _grams(text)
        if any(len(g & h) / len(g | h) >= NEAR for h in self.grams):
            self._dropped["near"].add(_norm(text))
            return True
        sk = skeleton(text, self.names)
        if any(is_overlap(*scores(sk, e)) for e in self.skeletons):
            self._dropped["skeleton"].add(_norm(text))
            return True
        return False


def load_pack(pack: Path) -> tuple[list[dict], list[dict], list[dict], dict[str, str]]:
    def rows(name: str) -> list[dict]:
        raw = json.loads((pack / "fixtures" / f"{name}.json").read_text("utf-8"))
        return raw if isinstance(raw, list) else next(v for v in raw.values() if isinstance(v, list))
    forms = yaml.safe_load((pack / "forms.yaml").read_text("utf-8"))["forms"]
    return rows("employees"), rows("rooms"), rows("items"), {f["id"]: f["name"] for f in forms}


def agent_for(reg: Registry, tool: str) -> Agent | None:
    """그 도구를 가진 첫 에이전트(등록부 순서). 여러 에이전트가 가진 도구는 앞 에이전트로 만듭니다."""
    return next((a for a in reg.agents if tool in a.tools), None)


def tool_defs(agent: Agent, tools: dict[str, dict]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": n, "description": tools[n]["description"],
                                              "parameters": tools[n]["inputSchema"]}}
            for n in tools if n in agent.tools]


def write_optional(agent: Agent, tools: dict[str, dict]) -> dict[str, list[str]]:
    return {n: optional_args(tools[n]["inputSchema"]) for n in tools
            if n in agent.tools and tools[n]["risk"] != "read" and optional_args(tools[n]["inputSchema"])}


def generate(pack: Path, per_tool: int, seed: int, stage: int = 2,
             excluded: Excluded | None = None) -> list[dict[str, Any]]:
    reg = Registry.load(pack, stage=stage)
    tools = {t["name"]: t for t in json.loads(TOOLS_JSON.read_text("utf-8"))["tools"] if t["stage"] <= stage}
    employees, rooms_, items, forms = load_pack(pack)
    excluded = excluded or Excluded([DEV_SET])
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, maker in MAKERS.items():
        agent = agent_for(reg, name)
        if agent is None:
            continue
        made, tries = 0, 0
        while made < per_tool and tries < per_tool * 20:
            tries += 1
            # 기준일은 평일 중에서 고릅니다(개발 묶음 기준일 2027-03-10과 겹쳐도 문장이 다르면 씁니다)
            today = date(2027, 1, 4) + timedelta(days=rng.randint(0, 300))
            if today.weekday() > 4:
                continue
            me = rng.choice([p for p in employees if p["grade"] != "ceo"])
            ctx = Ctx(rng, today, me, employees, rooms_, items, forms)
            kind, utterance, answer = maker(ctx)
            # 같은 문장이라도 기준일에 따라 정답(날짜)이 달라지면 따로 둡니다. 정답까지 같으면 하나만 씁니다.
            key = _norm(utterance) + json.dumps(answer, ensure_ascii=False, sort_keys=True)
            if key in seen or excluded.hit(utterance):
                continue
            target = answer.get("tool")
            if answer["type"] == "call" and target not in agent.tools:
                continue
            seen.add(key)
            made += 1
            prompt = system_prompt(agent, "full", datetime(today.year, today.month, today.day, 9, 0), True,
                                   list(agent.tools), write_optional(agent, tools))
            if answer["type"] == "call":
                reply = {"role": "assistant", "content": "",
                         "tool_calls": [{"type": "function",
                                         "function": {"name": answer["tool"], "arguments": answer["args"]}}]}
            else:
                reply = {"role": "assistant", "content": clarify_text(answer["labels"])}
            out.append({"id": "", "agent": agent.id, "kind": kind, "tool": name, "today": today.isoformat(),
                        "tools": tool_defs(agent, tools),
                        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": utterance},
                                     reply]})
    for i, ex in enumerate(out, 1):
        ex["id"] = f"lora-{i:05d}"
    return out


def digest(path: Path) -> str:
    """파일 또는 폴더(안의 jsonl·yaml 파일을 이름순으로)의 sha256 앞 16자."""
    h = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.suffix in (".jsonl", ".yaml", ".yml")) if path.is_dir() else [path]
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def split(rows: list[dict[str, Any]], valid_ratio: float, seed: int) -> tuple[list[dict], list[dict]]:
    def bucket(r: dict) -> float:
        h = hashlib.sha256(f"{seed}:{r['messages'][1]['content']}".encode()).digest()
        return int.from_bytes(h[:4], "big") / 2**32
    valid = [r for r in rows if bucket(r) < valid_ratio]
    train = [r for r in rows if bucket(r) >= valid_ratio]
    return train, valid


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack", default=str(DEFAULT_PACK))
    ap.add_argument("--per-tool", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--valid-ratio", type=float, default=0.1)
    ap.add_argument("--exclude", action="append", default=[],
                    help="겹치지 않게 할 평가 묶음(toolcall-v1 jsonl, 시나리오 YAML 또는 그 폴더). 개발 묶음은 항상 넣습니다. "
                         "여러 번 줄 수 있습니다")
    args = ap.parse_args(argv)
    ex_files = [DEV_SET, *(Path(x) for x in args.exclude)]
    excluded = Excluded(ex_files, Path(args.pack))
    rows = generate(Path(args.pack), args.per_tool, args.seed, excluded=excluded)
    train, valid = split(rows, args.valid_ratio, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("valid", valid)):
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part), "utf-8")
    kinds: dict[str, int] = {}
    tools_: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        called = r["messages"][-1].get("tool_calls", [{}])[0].get("function", {}).get("name", "(되묻기)")
        tools_[called] = tools_.get(called, 0) + 1
    # 저장소 밖 평가 묶음은 경로를 남기지 않고 이름·해시·문장 수만 남깁니다
    manifest = {"seed": args.seed, "perTool": args.per_tool, "pack": Path(args.pack).name, "train": len(train),
                "valid": len(valid), "kinds": kinds, "answers": dict(sorted(tools_.items())),
                "inputs": {TOOLS_JSON.name: hashlib.sha256(TOOLS_JSON.read_bytes()).hexdigest()[:16]},
                "excluded": [{"name": f.name, "sha256": digest(f), "utterances": sum(1 for _ in read_eval(f))}
                             for f in ex_files],
                "excludedDropped": excluded.dropped, "nearThreshold": NEAR,
                "skeletonThresholds": {"jaccard": JACCARD_NEAR, "contain": CONTAIN_NEAR}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
