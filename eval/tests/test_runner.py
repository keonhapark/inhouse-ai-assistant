"""조건 실행기: 가짜 erp(회차마다 새 인스턴스)와 조건별 계약 스텁으로 돌립니다."""

import pytest

from harness.erp import ErpClient
from harness.paths import ROOT
from harness.runner import CONDITIONS, load_run, run_matrix, save_run
from harness.scenario import load_scenario
from tests.conftest import PASSWORD, new_fake_erp
from tests.stub_system import ScriptedChat

SCEN = ROOT / "packs/manufacturing/scenarios"


@pytest.fixture
def erp_factory():
    """회차마다 새 가짜 erp. 실제 실행에서는 erp 초기화 훅이 이 자리에 옵니다."""
    clients = []

    def make():
        clients.append(new_fake_erp())
        return ErpClient(clients[-1], password=PASSWORD)

    yield make
    for c in clients:
        c.close()


def leaky_unless_full(cost=0.01):
    def make(condition, seed):
        text = "알려 드릴 수 없습니다." if condition == "full" else "기준은 DEV-MARKER-SALARY-7Q2 입니다."
        return ScriptedChat(None, [f"say:{text}"], external=[], cost_usd=cost)
    return make


def test_matrix_order_seed_and_outcomes(erp_factory):
    s = load_scenario(SCEN / "dev-concern-cross-dept-salary.json")
    rows, meta = run_matrix([s], leaky_unless_full(), erp_factory, repeats=2, base_seed=100, model="stub")
    assert [(r.repeat, r.condition) for r in rows] == [(rep, c) for rep in (1, 2) for c in CONDITIONS]
    assert {r.seed for r in rows if r.repeat == 1} == {101}
    assert {r.condition: r.outcome for r in rows if r.repeat == 1} == {
        "no_guard": "incident", "write_blocked": "incident", "approve_all": "incident",
        "baseline_tools": "incident", "full": "blocked"}
    assert meta.complete and meta.done_runs == meta.planned_runs == 10
    assert meta.cost_spent_usd == pytest.approx(0.1)
    assert meta.commit and meta.model == "stub" and meta.pack == "manufacturing"


def test_cost_cap_stops_between_scenarios(erp_factory):
    a = load_scenario(SCEN / "dev-concern-cross-dept-salary.json")
    b = {**a, "id": "dev-concern-copy"}
    rows, meta = run_matrix([a, b], leaky_unless_full(cost=0.03), erp_factory, repeats=3, cost_cap_usd=0.1)
    # 시나리오 a의 다섯 조건(0.15달러) 뒤에 상한을 넘겨, b 앞에서 멈춥니다
    assert len(rows) == 5 and {r.scenario_id for r in rows} == {a["id"]}
    assert not meta.complete and "비용 상한" in meta.stopped_reason


def test_setup_failure_is_failed_row(erp_factory):
    s = load_scenario(SCEN / "dev-normal-leave-half-day.json")
    s = {**s, "setup": [{"as": "E0016", "operation": "createApprovalDocument", "body": {"formId": "nope",
                                                                                       "fields": {}}}]}
    rows, meta = run_matrix([s], lambda c, seed: ScriptedChat(None, []), erp_factory, conditions=["full"],
                            repeats=1)
    assert rows[0].outcome == "failed" and "ErpCallError" in rows[0].error
    assert any("비용을 알 수 없는" in n for n in meta.notes)


def test_unknown_condition():
    with pytest.raises(ValueError, match="계약에 없는 조건"):
        run_matrix([], lambda c, s: None, lambda: None, conditions=["none"])


def test_save_and_load(tmp_path, erp_factory):
    s = load_scenario(SCEN / "dev-concern-cross-dept-salary.json")
    rows, meta = run_matrix([s], leaky_unless_full(), erp_factory, conditions=["full"], repeats=1)
    save_run(rows, meta, tmp_path / "run.json")
    rows2, meta2 = load_run(tmp_path / "run.json")
    assert rows2 == rows and meta2 == meta


def test_resume_skips_done_and_max_runs_splits(erp_factory, tmp_path):
    from harness.runner import load_rows_jsonl
    import json
    from dataclasses import asdict

    s = load_scenario(SCEN / "dev-concern-cross-dept-salary.json")
    b = {**s, "id": "dev-concern-copy"}
    first, meta1 = run_matrix([s, b], leaky_unless_full(), erp_factory, conditions=["no_guard", "full"],
                              repeats=1, max_runs=3)
    assert len(first) == 3 and not meta1.complete and "나눠 돌리기" in meta1.stopped_reason
    # 회차 기록 파일: 하나는 하네스 오류로 바꿔 다시 돌게 합니다
    f = tmp_path / "r.rows.jsonl"
    broken = asdict(first[2]) | {"error": "ConnectError: x"}
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [asdict(first[0]), asdict(first[1]), broken]),
                 encoding="utf-8")
    done = load_rows_jsonl(f)
    assert len(done) == 2
    rows, meta = run_matrix([s, b], leaky_unless_full(), erp_factory, conditions=["no_guard", "full"], repeats=1,
                            done_rows=done, started_at="earlier")
    assert meta.complete and meta.done_runs == 4 and meta.started_at == "earlier"
    assert sorted((r.scenario_id, r.condition) for r in rows) == sorted(
        (x, c) for x in (s["id"], b["id"]) for c in ("no_guard", "full"))
    assert meta.cost_spent_usd == pytest.approx(0.04)
