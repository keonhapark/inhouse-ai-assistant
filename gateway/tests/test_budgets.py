from datetime import datetime
from zoneinfo import ZoneInfo

from gateway.budgets import BudgetLedger

from .conftest import PACK

KST = ZoneInfo("Asia/Seoul")
PARENTS = {"team": "div", "div": "top", "top": None, "other": "top"}


def _ledger(tmp_path=None, period="month", **limits):
    b = {"period": period, "agents": limits.get("agents", {}), "units": limits.get("units", {})}
    return BudgetLedger(b, PARENTS, "Asia/Seoul", tmp_path / "budget.json" if tmp_path else None)


def test_units_include_ancestors():
    assert _ledger().units_of("team") == ["team", "div", "top"]
    assert _ledger().units_of(None) == []


def test_agent_and_unit_limits():
    led = _ledger(agents={"a": 1.0}, units={"div": 0.5})
    assert led.over("a", "team") is None
    led.add("a", "team", 0.4)
    assert led.over("a", "team") is None
    led.add("a", "other", 0.2)                               # 다른 부서: div에는 안 더함
    assert led.over("b", "team") is None
    led.add("b", "team", 0.2)                                # div 0.6 ≥ 0.5
    o = led.over("x", "team")
    assert o.kind == "unit" and o.id == "div" and abs(o.spent - 0.6) < 1e-9
    assert led.over("a", "other") is None                    # a는 0.6 < 1.0, other·top에는 상한 없음
    led.add("a", None, 0.5)
    assert led.over("a", None).kind == "agent"


def test_zero_limit_means_no_external():
    assert _ledger(agents={"a": 0}).over("a", None).limit == 0


def test_period_rollover():
    led = _ledger(agents={"a": 1.0})
    nov = datetime(2026, 11, 30, 23, 0, tzinfo=KST)
    dec = datetime(2026, 12, 1, 0, 10, tzinfo=KST)
    led.add("a", None, 1.0, now=nov)
    assert led.over("a", None, now=nov) is not None
    assert led.over("a", None, now=dec) is None              # 달이 바뀌면 0부터
    day = _ledger(period="day")
    assert day.period_key(nov) == "2026-11-30"


def test_persists_across_restart(tmp_path):
    led = _ledger(tmp_path, agents={"a": 1.0})
    led.add("a", None, 1.5)
    again = _ledger(tmp_path, agents={"a": 1.0})
    assert again.over("a", None) is not None


def test_no_budgets_file_disables(tmp_path):
    import shutil

    pack = tmp_path / "p"
    shutil.copytree(PACK, pack)
    (pack / "budgets.yaml").unlink(missing_ok=True)
    led = BudgetLedger.load(pack, None)
    assert not led.enabled and led.over("assistant", "hr") is None
    led.add("assistant", "hr", 9.0)
    assert led.spent() == {"agents": {}, "units": {}}


def test_pack_budgets_load():
    led = BudgetLedger.load(PACK, None)
    assert led.enabled and led.period in ("day", "month")
