"""도구 호출마다 무엇을 할지 정합니다: 바로 실행, 실행 후 되돌리기 안내, 미리보기 승인, 금지, 신뢰 등급으로 막음.

평가 조건(contracts/openapi/agent.yaml Condition)
- full: 에이전트 risk_policy·allowed_risk·overrides(wide_scope)와 신뢰 등급을 모두 씁니다.
- no_guard: 장치 없음. 모든 도구를 바로 실행합니다.
- write_blocked: 읽기 도구만 모델에 보이고, 쓰기 호출은 막습니다.
- approve_all, baseline_tools: 읽기는 바로, 쓰기는 모두 승인을 받습니다. 신뢰 등급은 쓰지 않습니다.
  (baseline_tools의 공용 서비스 계정·문서 ACL 끔은 gateway·rag 쪽 설정입니다.)

신뢰 등급(full만): 한 턴 안에 신뢰 불가 출력(다른 사람이 쓴 자유 문장, 신뢰 표시가 없는 문서)이
들어오면, 그 턴이 끝날 때까지 trust_required=user_direct 도구를 부르지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from agent_runtime.registry import Agent

Action = Literal["auto", "auto_with_undo", "confirm", "deny", "blocked"]
CONDITIONS = ("no_guard", "write_blocked", "approve_all", "baseline_tools", "full")


@dataclass(frozen=True)
class ToolMeta:
    name: str
    risk: Literal["read", "reversible_write", "irreversible"]
    trust_required: Literal["any", "user_direct"]


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str = ""


@dataclass(frozen=True)
class WideScope:
    """팩 org.yaml delegation_policy.wide_scope. 하나라도 맞으면 넓은 범위입니다."""

    period_days_over: float | None = None
    max_amount_over: int | None = None
    all_form_types: bool = False

    @classmethod
    def from_pack(cls, pack_dir: Path) -> WideScope:
        path = pack_dir / "org.yaml"
        if not path.is_file():
            return cls()
        org = yaml.safe_load(path.read_text("utf-8")) or {}
        ws = (org.get("delegation_policy") or {}).get("wide_scope") or {}
        return cls(ws.get("period_days_over"), ws.get("max_amount_over"), bool(ws.get("all_form_types", False)))

    def is_wide(self, args: dict[str, Any]) -> bool:
        """대결 위임 인자(startsAt, endsAt, formTypes, maxAmount)가 넓은 범위인지. 판단할 수 없으면 넓다고 봅니다."""
        try:
            if self.period_days_over is not None:
                days = (_dt(args["endsAt"]) - _dt(args["startsAt"])).total_seconds() / 86400
                if days > self.period_days_over:
                    return True
            if self.max_amount_over is not None:
                amount = args.get("maxAmount")
                if amount is None or amount > self.max_amount_over:
                    return True
            if self.all_form_types and "*" in (args.get("formTypes") or []):
                return True
        except (KeyError, TypeError, ValueError):
            return True
        return False


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def model_policy_for(agent: Agent, condition: str) -> str:
    """출구 별칭을 고를 때 쓸 모델 정책(contracts/eval/conditions.md "출구 별칭 선택").

    에이전트 정책의 로컬 강제는 이 프로젝트의 장치라 no_guard·baseline_tools에서는 모두 외부를 씁니다.
    """
    if condition in ("no_guard", "baseline_tools"):
        return "external_allowed"
    return agent.model_policy


def visible_to_model(tool: ToolMeta, condition: str) -> bool:
    return not (condition == "write_blocked" and tool.risk != "read")


def decide(agent: Agent, tool: ToolMeta, args: dict[str, Any], condition: str, tainted: bool,
           wide: WideScope) -> Decision:
    if condition not in CONDITIONS:
        raise ValueError(f"알 수 없는 조건: {condition}")
    if tool.name not in agent.tools:
        return Decision("blocked", f"{tool.name}은 이 에이전트의 도구가 아닙니다")
    if condition == "no_guard":
        return Decision("auto")
    if condition == "write_blocked":
        return Decision("auto") if tool.risk == "read" else Decision("blocked", "쓰기 도구를 쓰지 않는 조건입니다")
    if condition in ("approve_all", "baseline_tools"):
        return Decision("auto") if tool.risk == "read" else Decision("confirm")

    risk_policy = agent.raw.get("risk_policy", {})
    if tool.risk not in agent.raw.get("allowed_risk", []):
        return Decision("deny", f"{tool.risk} 등급 도구는 이 에이전트에서 쓰지 않습니다")
    if tool.trust_required == "user_direct" and tainted:
        return Decision("blocked", "신뢰할 수 없는 내용을 읽은 뒤라 사용자가 직접 요청해야 실행합니다")
    action: Action = risk_policy.get(tool.risk, "deny")
    for o in risk_policy.get("overrides", []) or []:
        if o.get("tool") != tool.name:
            continue
        if o.get("when") == "always" or (o.get("when") == "wide_scope" and wide.is_wide(args)):
            action = o["action"]
    if action == "deny":
        return Decision("deny", f"{tool.name}은 이 에이전트에서 금지된 도구입니다")
    return Decision(action)
