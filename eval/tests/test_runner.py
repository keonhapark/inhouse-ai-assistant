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
    broken = asdict(first[2]) | {"error": "ConnectError: x", "retry": True}
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in [asdict(first[0]), asdict(first[1]), broken]),
                 encoding="utf-8")
    resume = load_rows_jsonl(f)
    assert len(resume.done) == 2 and resume.prior_cost_usd == pytest.approx(0.01)
    rows, meta = run_matrix([s, b], leaky_unless_full(), erp_factory, conditions=["no_guard", "full"], repeats=1,
                            done_rows=resume.done, started_at="earlier", prior_cost_usd=resume.prior_cost_usd)
    assert meta.complete and meta.done_runs == 4 and meta.started_at == "earlier"
    assert sorted((r.scenario_id, r.condition) for r in rows) == sorted(
        (x, c) for x in (s["id"], b["id"]) for c in ("no_guard", "full"))
    # 다시 돌린 시도의 비용도 셉니다: 끝난 3회차 + 버린 시도 1번 + 새로 돈 2회차
    assert meta.cost_spent_usd == pytest.approx(0.05)


def _row_dict(**kw):
    from harness.runner import RunRow

    base = RunRow(scenario_id="a", set="normal", kind="normal", concern_type=None, reactive=False, author="hand",
                  expected_agent=None, condition="full", repeat=1, seed=1, outcome="failed", passed=False,
                  cost_usd=0.01)
    from dataclasses import asdict
    return asdict(base) | kw


def _write(path, rows):
    import json
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_resume_does_not_rerun_plain_errors(tmp_path):
    """agent 오류·시간 초과처럼 retry 표시가 없는 오류 회차는 실패로 남고 다시 돌지 않습니다."""
    from harness.runner import load_rows_jsonl

    f = tmp_path / "r.rows.jsonl"
    _write(f, [_row_dict(error="ReadTimeout: x")])
    resume = load_rows_jsonl(f)
    assert len(resume.done) == 1 and resume.done[0].outcome == "failed" and resume.prior_cost_usd == 0


def test_resume_retry_cap_confirms_failure(tmp_path):
    from harness.runner import MAX_RETRIES, count_retries, load_rows_jsonl

    f = tmp_path / "r.rows.jsonl"
    env = _row_dict(error="ConnectError: x", retry=True)
    _write(f, [env] * MAX_RETRIES)
    # 다시 돈 횟수가 상한보다 적으면 한 번 더 돕니다
    assert load_rows_jsonl(f).done == [] and count_retries(f) == MAX_RETRIES - 1
    _write(f, [env] * (MAX_RETRIES + 1))
    resume = load_rows_jsonl(f)
    assert len(resume.done) == 1 and not resume.done[0].retry
    assert any("실패로 확정" in x for x in resume.done[0].shortfalls)
    assert resume.prior_cost_usd == pytest.approx(0.01 * MAX_RETRIES)
    assert count_retries(f) == MAX_RETRIES


def _retryable_chat(condition, seed):
    class Flaky(ScriptedChat):
        def send(self, cid, text):
            return [self._ev("error", error={"message": "upstream 500", "retryable": True}), self._done()]

    return Flaky(None, [])


@pytest.mark.parametrize("healthy, retry", [(None, False), (True, False), (False, True)])
def test_retryable_error_reruns_only_when_model_server_down(erp_factory, healthy, retry):
    s = load_scenario(SCEN / "dev-normal-leave-half-day.json")
    check = None if healthy is None else (lambda: healthy)
    rows, _ = run_matrix([s], _retryable_chat, erp_factory, conditions=["full"], repeats=1, health_check=check)
    assert rows[0].outcome == "failed" and rows[0].retry is retry


def test_used_models_and_pack_version():
    from harness.runner import pack_versions, used_models

    events = [{"type": "message", "model": {"name": "qwen3.5:9b", "location": "local"}},
              {"type": "done", "model": {"name": "qwen3.5:9b", "location": "local"}}, {"type": "route"}]
    assert used_models(events, ["external"]) == ["external(외부 요청 기록)", "qwen3.5:9b(local)"]
    assert pack_versions(["manufacturing"]).startswith("manufacturing ") and "모름" not in pack_versions(
        ["manufacturing"])
    assert pack_versions(["nope"]) == "nope 버전 모름"


def test_matrix_meta_has_pack_version_and_stage(erp_factory):
    s = load_scenario(SCEN / "dev-concern-cross-dept-salary.json")
    _, meta = run_matrix([s], leaky_unless_full(), erp_factory, conditions=["full"], repeats=1, pack_stage=1)
    assert meta.pack_version.startswith("manufacturing ") and meta.pack_stage == 1
