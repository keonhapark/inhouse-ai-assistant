"""외부 LLM 비용 상한(팩 budgets.yaml, contracts/pack/pack.schema.json `$defs.budgets`).

LiteLLM이 응답마다 계산한 비용(`x-litellm-response-cost`, USD)을 기간(day|month, 팩 시간대)마다 에이전트와 부서에
더합니다. 부서는 요청한 직원의 소속 부서와 그 상위 부서 모두입니다. 상한을 넘은 에이전트·부서의 다음 외부 요청은
로컬 모델로 내립니다. 진행 중인 요청은 끝까지 갑니다(상한은 보내기 전에만 봅니다).

LiteLLM 예산(가상 키·팀 예산)은 Postgres와 키 발급이 필요해 쓰지 않고, gateway가 누적합니다. 누적은
`GATEWAY_AUDIT_DIR/budget.json`에 두어 다시 띄워도 이어집니다.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


@dataclass(frozen=True)
class Over:
    kind: str      # agent | unit
    id: str
    spent: float
    limit: float


class BudgetLedger:
    def __init__(self, budgets: dict[str, Any] | None, parents: dict[str, str | None], timezone: str,
                 path: Path | None = None, unit_names: dict[str, str] | None = None):
        self.unit_names = unit_names or {}
        b = budgets or {}
        self.period = b.get("period", "month")
        self.agent_limits: dict[str, float] = {k: float(v) for k, v in (b.get("agents") or {}).items()}
        self.unit_limits: dict[str, float] = {k: float(v) for k, v in (b.get("units") or {}).items()}
        self.parents = parents
        self.tz = ZoneInfo(timezone)
        self.path = path
        self._lock = threading.Lock()
        self._spent: dict[str, dict[str, dict[str, float]]] = self._read()

    @classmethod
    def load(cls, pack_dir: Path, path: Path | None) -> BudgetLedger:
        def read(p: Path) -> Any:
            return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None

        org = read(pack_dir / "org.yaml") or {}
        pack = read(pack_dir / "pack.yaml") or {}
        parents = {u["id"]: u.get("parent") for u in org.get("units", [])}
        tz = (pack.get("company") or {}).get("timezone", "UTC")
        names = {u["id"]: u.get("name", u["id"]) for u in org.get("units", [])}
        return cls(read(pack_dir / "budgets.yaml"), parents, tz, path, names)

    @property
    def enabled(self) -> bool:
        return bool(self.agent_limits or self.unit_limits)

    def period_key(self, now: datetime | None = None) -> str:
        t = (now or datetime.now(self.tz)).astimezone(self.tz)
        return t.strftime("%Y-%m-%d" if self.period == "day" else "%Y-%m")

    def period_start(self, now: datetime | None = None) -> datetime:
        t = (now or datetime.now(self.tz)).astimezone(self.tz)
        t = t.replace(hour=0, minute=0, second=0, microsecond=0)
        return t if self.period == "day" else t.replace(day=1)

    def units_of(self, unit_id: str | None) -> list[str]:
        """소속 부서와 그 상위 부서(순환 방지)."""
        out: list[str] = []
        while unit_id and unit_id not in out:
            out.append(unit_id)
            unit_id = self.parents.get(unit_id)
        return out

    def over(self, agent_id: str | None, unit_id: str | None, now: datetime | None = None) -> Over | None:
        """상한에 닿았거나 넘은 첫 항목을 돌려줍니다. 상한 0은 외부를 쓰지 않는다는 뜻입니다."""
        if not self.enabled:
            return None
        spent = self._spent.get(self.period_key(now), {})
        checks = [("agent", agent_id, self.agent_limits)] + [("unit", u, self.unit_limits)
                                                             for u in self.units_of(unit_id)]
        for kind, key, limits in checks:
            if key is None or key not in limits:
                continue
            used = spent.get(kind + "s", {}).get(key, 0.0)
            if used >= limits[key]:
                return Over(kind, key, used, limits[key])
        return None

    def add(self, agent_id: str | None, unit_id: str | None, cost: float | None,
            now: datetime | None = None) -> None:
        if not cost or not self.enabled:
            return
        with self._lock:
            bucket = self._spent.setdefault(self.period_key(now), {"agents": {}, "units": {}})
            if agent_id:
                bucket["agents"][agent_id] = bucket["agents"].get(agent_id, 0.0) + cost
            for u in self.units_of(unit_id):
                bucket["units"][u] = bucket["units"].get(u, 0.0) + cost
            self._write()

    def spent(self, now: datetime | None = None) -> dict[str, dict[str, float]]:
        return self._spent.get(self.period_key(now), {"agents": {}, "units": {}})

    def _read(self) -> dict[str, dict[str, dict[str, float]]]:
        if self.path is None or not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    def _write(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._spent, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
