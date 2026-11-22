"""도구 호출 LoRA 학습 데이터 생성기(#469, #111). GPU 없이 돕니다. 학습은 GPU 사용권을 받아 따로 합니다(QLoRA).

학습 예시는 업무 실행의 첫 계획 호출과 같은 모양입니다: 에이전트 system 프롬프트(`run/graph.py` system_prompt), 그 에이전트가
보는 도구 정의(`contracts/mcp/tools.json`의 inputSchema, OpenAI 함수 형식), 사용자 발화 한 줄, 그리고 정답 행동 하나.

- direct: 필요한 값이 발화에 다 있어 그 도구를 바로 부름
- resolve: 값을 조회로 찾을 수 있어 조회 도구를 먼저 부름(직원 이름 → org_search_employees, 문서·예약·위임 ID 없음 → 목록)
- clarify: 필수 값이 빠져 도구 없이 빠진 값만 물음(선택 값은 묻지 않음)

값은 도구 계약과 팩 고정 데이터(직원·회의실·품목·양식)에서만 고르고, 문장 틀은 이 파일에 직접 썼습니다. 평가용 묶음과 섞이지
않게 확인 묶음은 읽지 않고, 개발 묶음(`eval_dev/tool_calls.jsonl`)과 같은 문장이 나오면 버립니다. 같은 시드면 같은 데이터입니다.

    uv run python lora/make_toolcall_data.py --out <저장소 밖 폴더> [--per-tool 40] [--seed 7] [--valid-ratio 0.1]

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOLS_JSON = ROOT / "contracts" / "mcp" / "tools.json"
DEV_SET = HERE.parent / "eval_dev" / "tool_calls.jsonl"
DEFAULT_PACK = ROOT / "packs" / "manufacturing"
WEEKDAYS = "월화수목금토일"
GRADE_WORDS = {"team_leader": "팀장님", "division_head": "본부장님", "staff": "님", "ceo": "대표님"}

# 자유 문장 값(사유·목적·제목·질문). 업종과 관계없는 말만 씁니다.
LEAVE_REASONS = ["개인 사정", "가족 행사", "병원 진료", "이사", "자녀 학교 행사", "여행", "은행 업무", "건강 검진"]
SICK_REASONS = ["감기 몸살", "병원 진료", "치과 치료", "장염"]
DELEGATION_REASONS = ["출장", "휴가", "교육 참석", "외근", "파견"]
MEETING_TITLES = ["주간 회의", "고객 미팅", "신입 면담", "분기 계획 회의", "프로젝트 점검", "업체 미팅", "교육 준비"]
MERCHANTS = ["가람식당", "온누리택시", "한빛문구", "새솔카페", "푸른주유소", "다온한식", "하늘빛편의점", "미소분식"]
EXPENSE_PURPOSES = ["팀 회의 식사", "고객사 방문 교통비", "사무용품 구입", "외근 이동", "야근 식대", "거래처 접대"]
PURCHASE_REASONS = ["재고 보충", "설비 정비", "신규 작업 준비", "소모품 교체", "시험용"]
POLICY_QUESTIONS = [("출장 일비는 하루 얼마야?", "출장 일비 기준"), ("경조사 휴가 며칠 쓸 수 있어?", "경조사 휴가 일수"),
                    ("야근 식대 한도가 얼마야?", "야근 식대 한도"), ("재택근무 신청은 어떻게 해?", "재택근무 신청 절차"),
                    ("법인카드 분실하면 어떻게 해야 돼?", "법인카드 분실 처리 절차"), ("교육비 지원 규정 알려 줘", "교육비 지원 규정"),
                    ("회의실 예약은 며칠 전까지 해야 돼?", "회의실 예약 기한"), ("명절 선물 받으면 신고해야 해?", "선물 수수 신고 규정")]
TICKETS = [("incident", "노트북이 부팅되지 않아요", "아침부터 노트북 전원이 켜지지 않습니다"),
           ("incident", "사내 메일 접속 오류", "메일에 로그인하면 계속 오류가 납니다"),
           ("access_request", "공유 폴더 권한 요청", "팀 공유 폴더 읽기 권한이 필요합니다"),
           ("incident", "프린터 인쇄 안 됨", "3층 프린터로 인쇄가 되지 않습니다"),
           ("other", "모니터 추가 요청", "작업용 모니터 한 대가 더 필요합니다")]


def josa(word: str, pair: str = "을를") -> str:
    """받침이 있으면 앞 글자(을·이·은), 없으면 뒤 글자(를·가·는)."""
    ch = word[-1]
    has = 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 != 0
    return word + (pair[0] if has else pair[1])


@dataclass
class Ctx:
    rng: random.Random
    today: date
    me: dict[str, Any]
    people: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    items: list[dict[str, Any]]
    forms: dict[str, str]  # 양식 id → 이름

    # ---- 날짜 표현(말, 값) ----
    def day(self, future: bool = True) -> tuple[str, date]:
        r = self.rng.random()
        if not future:
            d = self.today - timedelta(days=self.rng.randint(1, 10))
            return ("어제", d) if d == self.today - timedelta(days=1) else (f"{d.month}월 {d.day}일", d)
        if r < 0.25:
            n = self.rng.choice([1, 2])
            return ("내일" if n == 1 else "모레", self.today + timedelta(days=n))
        if r < 0.55:
            wd = self.rng.randint(0, 4)
            d = self.today + timedelta(days=7 - self.today.weekday() + wd)
            return f"다음 주 {WEEKDAYS[wd]}요일", d
        d = self.today + timedelta(days=self.rng.randint(3, 40))
        return f"{d.month}월 {d.day}일", d

    def hour(self) -> tuple[str, int]:
        h = self.rng.choice([9, 10, 11, 13, 14, 15, 16])
        return (f"오전 {h}시" if h < 12 else f"오후 {h - 12}시"), h

    def other(self) -> dict[str, Any]:
        return self.rng.choice([p for p in self.people if p["id"] != self.me["id"]])

    def rid(self, prefix: str) -> str:
        return f"{prefix}-{self.rng.randint(1000, 9999)}"


def iso(d: date, h: int = 0, m: int = 0) -> str:
    return datetime(d.year, d.month, d.day, h, m).isoformat() + "+09:00"


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
    if k < 0.35:
        typ, kw = c.rng.choice([("annual", "연차"), ("half_am", "오전 반차"), ("half_pm", "오후 반차")])
        reason = c.rng.choice(LEAVE_REASONS)
        return "direct", f"{word} {kw} 쓸게요. {reason} 때문이에요", call(
            "leave_request", {"leave_type": typ, "start_date": d.isoformat(), "end_date": d.isoformat(), "reason": reason})
    if k < 0.55:
        n = c.rng.randint(2, 4)
        end = d + timedelta(days=n - 1)
        reason = c.rng.choice(LEAVE_REASONS)
        return "direct", f"{d.month}월 {d.day}일부터 {end.month}월 {end.day}일까지 연차 신청해 줘. 사유는 {reason}", call(
            "leave_request", {"leave_type": "annual", "start_date": d.isoformat(), "end_date": end.isoformat(),
                              "reason": reason})
    if k < 0.65:
        reason = c.rng.choice(SICK_REASONS)
        return "direct", f"{word} 병가 하루 낼게요. {reason}", call(
            "leave_request", {"leave_type": "sick", "start_date": d.isoformat(), "end_date": d.isoformat(),
                              "reason": reason})
    if k < 0.85:
        return "clarify", f"{word} 연차 쓸게요", ask("사유")
    return "clarify", "휴가 좀 쓰려고요", ask("휴가 종류", "날짜", "사유")


def leave_balance(c: Ctx) -> Example:
    return "direct", c.rng.choice(["연차 며칠 남았어?", "남은 휴가 일수 알려 줘", "올해 쓸 수 있는 연차가 몇 개야?",
                                   "내 휴가 잔여 확인해 줘"]), call("leave_get_balance", {})


def profile(c: Ctx) -> Example:
    return "direct", c.rng.choice(["내 직급이 뭐로 돼 있어?", "내 소속이랑 입사일 알려 줘", "내 인사 정보 보여 줘"]), call(
        "hr_get_my_profile", {})


def approvals(c: Ctx) -> Example:
    k = c.rng.random()
    if k < 0.3:
        return "direct", c.rng.choice(["내가 올린 결재 다 보여 줘", "내 결재 목록 보여 줘"]), call("approval_list_mine", {})
    status, word = c.rng.choice([("in_progress", "진행 중인"), ("approved", "승인된"), ("rejected", "반려된"),
                                 ("withdrawn", "회수한")])
    if k < 0.7:
        return "direct", f"내가 올린 결재 중에 {word} 것만 보여 줘", call("approval_list_mine", {"status": status})
    doc = c.rid("doc")
    return "direct", c.rng.choice([f"결재 {doc} 지금 어디까지 갔어?", f"{doc} 결재 상태 알려 줘"]), call(
        "approval_get", {"documentId": doc})


def withdraw(c: Ctx) -> Example:
    k = c.rng.random()
    doc = c.rid("doc")
    if k < 0.5:
        return "direct", c.rng.choice([f"결재 {doc} 회수해 줘", f"{doc} 올린 거 취소하고 싶어요"]), call(
            "approval_withdraw", {"documentId": doc})
    form = c.rng.choice(list(c.forms.values()))
    return "resolve", f"지난번에 올린 {form} 결재 회수해 줘", call("approval_list_mine", {})


def delegation(c: Ctx) -> Example:
    k = c.rng.random()
    p = c.other()
    word, d = c.day()
    end = d + timedelta(days=c.rng.randint(1, 5))
    reason = c.rng.choice(DELEGATION_REASONS)
    fid, fname = c.rng.choice(list(c.forms.items()))
    if k < 0.3:
        return "direct", f"{d.month}월 {d.day}일부터 {end.month}월 {end.day}일까지 {fname} 결재를 {p['id']}에게 맡겨 줘. {reason} 때문이야", call(
            "delegation_register", {"delegateId": p["id"], "startsAt": iso(d), "endsAt": iso(end), "formTypes": [fid],
                                    "reason": reason})
    if k < 0.5:
        title = GRADE_WORDS.get(p["grade"], "님")
        sep = "" if title == "님" else " "
        return "resolve", f"{d.month}월 {d.day}일부터 {end.month}월 {end.day}일까지 {reason}이라 결재를 {p['name']}{sep}{title}께 맡겨 줘", call(
            "org_search_employees", {"q": p["name"]})
    if k < 0.7:
        return "clarify", f"{p['id']}에게 결재 좀 맡겨 줘", ask("기간", "맡길 결재 종류", "사유")
    if k < 0.88:
        role, w = c.rng.choice([("delegator", "내가 맡긴"), ("delegate", "내가 대신 맡은")])
        return "direct", f"{w} 대결 목록 보여 줘", call("delegation_list", {"role": role})
    dlg = c.rid("dlg")
    return "direct", f"대결 {dlg} 해지해 줘", call("delegation_revoke", {"delegationId": dlg})


def people(c: Ctx) -> Example:
    p = c.other()
    return "direct", c.rng.choice([f"{p['name']} 사번 알려 줘", f"{p['name']} 씨 연락처 찾아 줘", f"{p['name']} 어느 부서야?"]), call(
        "org_search_employees", {"q": p["name"]})


def policy(c: Ctx) -> Example:
    q, key = c.rng.choice(POLICY_QUESTIONS)
    return "direct", q, call("policy_search", {"question": key})


def rooms(c: Ctx) -> Example:
    k = c.rng.random()
    word, d = c.day()
    hw, h = c.hour()
    hours = c.rng.choice([1, 2])
    if k < 0.25:
        n = c.rng.randint(3, 10)
        return "direct", f"{word} {hw}부터 {hours}시간 동안 {n}명 들어갈 회의실 있어?", call(
            "room_list_availability", {"startsAt": iso(d, h), "endsAt": iso(d, h + hours), "minCapacity": n})
    if k < 0.45:
        room = c.rng.choice(c.rooms)
        title = c.rng.choice(MEETING_TITLES)
        return "direct", f"{room['id']}를 {word} {hw}부터 {hours}시간 예약해 줘. {title}", call(
            "room_reserve", {"roomId": room["id"], "startsAt": iso(d, h), "endsAt": iso(d, h + hours), "title": title})
    if k < 0.6:
        room = c.rng.choice(c.rooms)
        title = c.rng.choice(MEETING_TITLES)
        return "resolve", f"{word} {hw}부터 한 시간 {room['name']} 예약해 줘. {title}", call(
            "room_list_availability", {"startsAt": iso(d, h), "endsAt": iso(d, h + 1)})
    if k < 0.75:
        if c.rng.random() < 0.5:
            return "clarify", f"{word} 회의실 잡아 줘", ask("시간")
        return "clarify", c.rng.choice(["회의실 하나 잡아 줘", "회의실 예약하고 싶어요"]), ask("날짜", "시간")
    if k < 0.9:
        rsv = c.rid("rsv")
        return "direct", f"회의실 예약 {rsv} 취소해 줘", call("room_cancel_reservation", {"reservationId": rsv})
    return "resolve", f"{word}에 잡은 회의실 예약 취소해 줘", call("room_list_my_reservations", {"date": d.isoformat()})


def expense(c: Ctx) -> Example:
    k = c.rng.random()
    word, d = c.day(future=False)
    amount = c.rng.choice([8000, 12500, 15000, 23000, 36000, 48000, 64000, 120000])
    m, purpose = c.rng.choice(MERCHANTS), c.rng.choice(EXPENSE_PURPOSES)
    if k < 0.5:
        return "direct", f"{word} {m}에서 쓴 {amount:,}원 경비 정산해 줘. {purpose}", call(
            "expense_request", {"amount": amount, "spent_on": d.isoformat(), "merchant": m, "purpose": purpose})
    if k < 0.8:
        return "clarify", f"{word} {m}에서 {amount:,}원 썼는데 정산해 줘", ask("사용 목적")
    return "clarify", c.rng.choice(["경비 정산 좀 올려 줘", "영수증 처리해야 해"]), ask("금액", "사용일", "가맹점", "사용 목적")


def purchase(c: Ctx) -> Example:
    k = c.rng.random()
    it = c.rng.choice(c.items)
    qty = c.rng.choice([10, 20, 50, 100, 200, 500])
    price = it["unit_price"]
    reason = c.rng.choice(PURCHASE_REASONS)
    if k < 0.5:
        return "direct", f"{it['code']} {qty}개를 개당 {price:,}원에 구매 요청해 줘. {reason}", call(
            "purchase_request", {"item_code": it["code"], "quantity": qty, "unit_price": price,
                                 "total_amount": qty * price, "reason": reason})
    if k < 0.75:
        # 단가가 빠졌지만 품목 조회(item_search)로 찾을 수 있어 먼저 조회합니다(#466)
        return "resolve", f"{it['code']} {qty}개 구매 요청 올려 줘. {reason}", call("item_search", {"q": it["code"]})
    return "clarify", f"{it['name']} 좀 사야 해요", ask("품목 코드", "수량", "단가", "사유")


def tickets(c: Ctx) -> Example:
    k = c.rng.random()
    cat, title, desc = c.rng.choice(TICKETS)
    if k < 0.5:
        return "direct", f"{desc}. 장애 접수해 줘" if cat == "incident" else f"{desc}. 요청 접수해 줘", call(
            "ticket_create", {"category": cat, "title": title, "description": desc})
    if k < 0.8:
        return "direct", c.rng.choice(["내가 올린 티켓 목록 보여 줘", "내 요청 처리 상황 보여 줘"]), call("ticket_list", {})
    t = c.rid("tkt")
    return "direct", f"티켓 {t} 어떻게 됐어?", call("ticket_get", {"ticketId": t})


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
    return re.sub(r"\s+", "", s)


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


def generate(pack: Path, per_tool: int, seed: int, stage: int = 2) -> list[dict[str, Any]]:
    reg = Registry.load(pack, stage=stage)
    tools = {t["name"]: t for t in json.loads(TOOLS_JSON.read_text("utf-8"))["tools"] if t["stage"] <= stage}
    employees, rooms_, items, forms = load_pack(pack)
    dev = {_norm(json.loads(line)["utterance"]) for line in DEV_SET.read_text("utf-8").splitlines() if line.strip()}
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
            if _norm(utterance) in dev or key in seen:
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
    ap.add_argument("--per-tool", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--valid-ratio", type=float, default=0.1)
    args = ap.parse_args(argv)
    rows = generate(Path(args.pack), args.per_tool, args.seed)
    train, valid = split(rows, args.valid_ratio, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("valid", valid)):
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part), "utf-8")
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    manifest = {"seed": args.seed, "perTool": args.per_tool, "pack": Path(args.pack).name, "train": len(train),
                "valid": len(valid), "kinds": kinds,
                "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in (TOOLS_JSON, DEV_SET)}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
