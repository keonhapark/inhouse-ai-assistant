"""도구 호출 측정(#103, #237): 항목 읽기, 첫 행동 채점, agent 평가 경로 실행.

형식과 채점 규칙은 contracts/eval/toolcall/(toolcall-v1)입니다. 에이전트는 POST /eval/tool-call(contracts/openapi/
agent.yaml evalToolCall)로 첫 계획 호출만 하고 도구를 실행하지 않습니다. 채점은 여기서 합니다.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from jsonschema import Draft202012Validator

from harness.paths import ROOT
from harness.scenario import substitute

ITEM_SCHEMA = ROOT / "contracts/eval/toolcall/item.schema.json"
TOOLS = ROOT / "contracts/mcp/tools.json"
PACK = ROOT / "packs/manufacturing"
LOCAL_TZ = ZoneInfo("Asia/Seoul")
# targetTool을 가진 에이전트를 이 순서로 고릅니다(agent/eval_dev/smoke_run.py와 같음)
AGENT_ORDER = ("hr", "assistant", "finance", "procurement", "it_ops")
# 맞음으로 세는 결과
CORRECT = ("correct", "alternative", "confirm_then_proceed")


class ToolcallError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@cache
def tool_catalog() -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in json.loads(TOOLS.read_text(encoding="utf-8"))["tools"]}


def load_items(path: Path) -> list[dict[str, Any]]:
    """JSON Lines 항목을 item.schema.json으로 검사하며 읽습니다. 계약에 없는 도구 이름도 잡습니다."""
    validator = Draft202012Validator(json.loads(ITEM_SCHEMA.read_text(encoding="utf-8")))
    tools = tool_catalog()
    items, problems, seen = [], [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        for e in validator.iter_errors(item):
            problems.append(f"{n}줄 {item.get('id')}: {e.message}")
        for act in [item.get("expected", {}), *item.get("alsoAcceptable", [])]:
            if act.get("type") == "call" and act.get("tool") not in tools:
                problems.append(f"{n}줄 {item.get('id')}: 계약에 없는 도구 {act.get('tool')}")
        if item.get("targetTool") not in tools:
            problems.append(f"{n}줄 {item.get('id')}: 계약에 없는 targetTool {item.get('targetTool')}")
        if item.get("id") in seen:
            problems.append(f"{n}줄: id {item.get('id')}가 겹칩니다")
        seen.add(item.get("id"))
        items.append(item)
    if problems:
        raise ToolcallError(problems)
    return items


# --- 인자 비교(README 채점 규칙) ---

def _as_time(v: Any) -> datetime | date | None:
    if not isinstance(v, str):
        return None
    try:
        if len(v) == 10:
            return date.fromisoformat(v)
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _local(t: datetime | date) -> datetime | date:
    if isinstance(t, datetime) and t.tzinfo:
        return t.astimezone(LOCAL_TZ)
    return t


def _day(t: datetime | date) -> date:
    t = _local(t)
    return t.date() if isinstance(t, datetime) else t


def _same(want: Any, got: Any) -> bool:
    """exact: 값이 같음. 날짜·시각은 같은 시점이면 같음(+09:00과 UTC 표기 차이 무시)."""
    if want == got:
        return True
    tw, tg = _as_time(want), _as_time(got)
    if isinstance(tw, datetime) and isinstance(tg, datetime):
        if (tw.tzinfo is None) != (tg.tzinfo is None):
            return tw.replace(tzinfo=None) == tg.replace(tzinfo=None)
        return tw == tg
    if isinstance(tw, date) and not isinstance(tw, datetime) and isinstance(tg, date) and not isinstance(tg, datetime):
        return tw == tg
    return False


def _norm(v: Any) -> str:
    return re.sub(r"\s+", "", str(v)).casefold()


def match_arg(how: str, name: str, want: Any, got: Any) -> bool:
    if how == "ignore":
        return True
    if how == "nonempty":
        return got is not None and (str(got).strip() != "" if not isinstance(got, (list, dict)) else len(got) > 0)
    if got is None:
        return want is None
    if how == "set":
        return isinstance(want, list) and isinstance(got, list) and set(map(str, want)) == set(map(str, got))
    if how == "normalized":
        return _norm(want) == _norm(got)
    if how == "date":
        tw, tg = _as_time(want), _as_time(got)
        if tw is None or tg is None:
            return False
        if _day(tw) == _day(tg):
            return True
        # 끝 시각은 정답 날짜의 다음 날 00:00:00도 맞음
        if name == "endsAt" and isinstance(tg, datetime):
            g = _local(tg)
            return (g.hour, g.minute, g.second) == (0, 0, 0) and g.date() == _day(tw) + timedelta(days=1)
        return False
    return _same(want, got)


def args_mismatch(action: dict[str, Any], got: dict[str, Any] | None, arg_match: dict[str, str]) -> list[str]:
    """정답 인자 중 맞지 않는 이름. 정답에 없는 선택 인자는 보지 않습니다."""
    got = got or {}
    return [k for k, v in action.get("args", {}).items()
            if not match_arg(arg_match.get(k, "exact"), k, v, got.get(k))]


# --- 첫 행동 채점 ---

@dataclass
class Score:
    id: str
    target_tool: str
    category: str
    stage: int | None
    expected_type: str
    # correct, alternative, confirm_then_proceed, wrong_tool, wrong_args, unparsed_args, no_call_asked,
    # no_call_answered, called_instead_of_clarify, error
    outcome: str
    passed: bool
    tool: str | None = None
    asked: bool | None = None
    mismatched: list[str] = field(default_factory=list)
    schema_valid: bool | None = None
    schema_errors: list[str] = field(default_factory=list)
    # 정답에 없는 필수 인자를 채웠는데 그 값이 발화에 없는 수(지어낸 값, 보조 지표)
    fabricated: int = 0
    latency_ms: int | None = None
    location: str | None = None
    error: str | None = None


def _schema_check(tool: str | None, arguments: Any) -> tuple[bool | None, list[str]]:
    t = tool_catalog().get(tool or "")
    if t is None or not isinstance(arguments, dict):
        return None, []
    errors = [e.message for e in Draft202012Validator(t["inputSchema"]).iter_errors(arguments)]
    return not errors, errors[:3]


def _fabricated(tool: str | None, arguments: Any, expected_args: dict[str, Any], utterance: str) -> int:
    t = tool_catalog().get(tool or "")
    if t is None or not isinstance(arguments, dict):
        return 0
    required = set(t["inputSchema"].get("required", []))
    n = 0
    for k, v in arguments.items():
        if k in required and k not in expected_args and v not in (None, "") and str(v) not in utterance:
            n += 1
    return n


def _call_ok(action: dict[str, Any], result: dict[str, Any], arg_match: dict[str, str]) -> bool:
    return (action.get("type") == "call" and result.get("tool") == action["tool"]
            and result.get("arguments") is not None and not args_mismatch(action, result.get("arguments"), arg_match))


def _clarify_ok(result: dict[str, Any]) -> bool:
    return result.get("tool") is None and bool(result.get("asked"))


def score(item: dict[str, Any], status: int, result: Any) -> Score:
    """첫 행동 하나를 채점합니다. status가 200이 아니면 error(실행 환경 문제, 분모에서 뺌)."""
    expected = item["expected"]
    stage = tool_catalog().get(item["targetTool"], {}).get("stage")
    s = Score(id=item["id"], target_tool=item["targetTool"], category=item["category"], stage=stage,
              expected_type=expected["type"], outcome="error", passed=False)
    if status != 200 or not isinstance(result, dict):
        s.error = f"HTTP {status}"
        return s
    arg_match = item.get("argMatch", {})
    s.tool, s.asked = result.get("tool"), bool(result.get("asked"))
    s.latency_ms = result.get("latencyMs")
    s.location = (result.get("model") or {}).get("location")
    s.schema_valid, s.schema_errors = _schema_check(s.tool, result.get("arguments"))
    alts = item.get("alsoAcceptable", [])

    def alt_ok() -> bool:
        return any(_call_ok(a, result, arg_match) if a["type"] == "call" else _clarify_ok(result) for a in alts)

    if expected["type"] == "call":
        s.fabricated = _fabricated(s.tool, result.get("arguments"), expected.get("args", {}), item["utterance"])
        if s.tool == expected["tool"]:
            if result.get("arguments") is None:
                s.outcome = "unparsed_args"
            else:
                s.mismatched = args_mismatch(expected, result["arguments"], arg_match)
                s.outcome = "correct" if not s.mismatched else ("alternative" if alt_ok() else "wrong_args")
        elif alt_ok():
            s.outcome = "alternative"
        elif s.tool is None:
            irreversible = tool_catalog().get(expected["tool"], {}).get("risk") == "irreversible"
            s.outcome = "confirm_then_proceed" if irreversible and s.asked else (
                "no_call_asked" if s.asked else "no_call_answered")
        else:
            s.outcome = "wrong_tool"
    else:
        if _clarify_ok(result):
            s.outcome = "correct"
        elif alt_ok():
            s.outcome = "alternative"
        elif s.tool is None:
            s.outcome = "no_call_answered"
        else:
            s.outcome = "called_instead_of_clarify"
    s.passed = s.outcome in CORRECT
    return s


# --- 실행 ---

def _employees() -> dict[str, dict[str, Any]]:
    raw = json.loads((PACK / "fixtures/employees.json").read_text(encoding="utf-8"))
    rows = raw.get("employees", raw) if isinstance(raw, dict) else raw
    return {e["id"]: e for e in rows}


def agent_tools() -> dict[str, list[str]]:
    reg = yaml.safe_load((PACK / "agents.yaml").read_text(encoding="utf-8"))
    return {a["id"]: a["tools"] for a in reg["agents"]}


def agent_for(tool: str, tools_by_agent: dict[str, list[str]]) -> str:
    return next(a for a in AGENT_ORDER if tool in tools_by_agent.get(a, []))


def request_body(item: dict[str, Any], agent: str, variant: dict[str, Any], model: str | None) -> dict[str, Any]:
    p = _employees()[item["requester"]]
    body = {"message": item["utterance"], "agentId": agent, "today": item["referenceDate"], "variant": variant,
            "requester": {"employeeId": p["id"], "unitId": p["unit_id"], "grade": p["grade"], "roles": ["employee"]}}
    if model:
        body["model"] = model
    return body


Post = Callable[[dict[str, Any]], tuple[int, Any]]
SetupRunner = Callable[[dict[str, Any]], dict[str, str]]


def run_items(items: list[dict[str, Any]], post: Post, *, variant: dict[str, Any] | None = None,
              model: str | None = None, repeats: int = 1, setup: SetupRunner | None = None,
              on_row: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """항목마다 repeats번 부르고 채점한 줄을 돌려줍니다. setup이 있는 항목은 setup으로 상태를 만든 뒤
    발화와 정답 인자의 ${이름}을 바꿉니다(setup 없이 setup 항목을 만나면 멈춤)."""
    variant = variant or {}
    tools_by_agent = agent_tools()
    rows = []
    for repeat in range(1, repeats + 1):
        for item in items:
            it = item
            if item.get("setup"):
                if setup is None:
                    raise ToolcallError([f"{item['id']}: setup이 있어 erp가 필요합니다(--erp-url)"])
                it = {**item, **substitute({k: item[k] for k in ("utterance", "expected", "alsoAcceptable")
                                            if k in item}, setup(item))}
            agent = agent_for(it["targetTool"], tools_by_agent)
            started = time.monotonic()
            status, result = post(request_body(it, agent, variant, model))
            sc = score(it, status, result)
            row = {"repeat": repeat, "agentId": agent, "variant": variant, "model": model, "status": status,
                   "wallMs": int((time.monotonic() - started) * 1000), "result": result, **asdict(sc)}
            rows.append(row)
            if on_row:
                on_row(row)
    return rows


def rescore(items: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """기록한 줄(status, result)을 지금 규칙으로 다시 채점합니다. 규칙을 고친 뒤 다시 부르지 않고 볼 때 씁니다."""
    by_id = {i["id"]: i for i in items}
    out = []
    for r in rows:
        sc = score(by_id[r["id"]], r["status"], r["result"])
        out.append({**r, **asdict(sc)})
    return out
