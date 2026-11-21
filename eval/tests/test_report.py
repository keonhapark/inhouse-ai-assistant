from harness.report import render
from harness.runner import CONDITIONS, RunMeta, RunRow


def meta(**kw):
    m = RunMeta(commit="abc123", dirty=False, machine="test", started_at="s", finished_at="f",
                conditions=list(CONDITIONS), repeats=3, planned_runs=0, done_runs=0, complete=True)
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def row(sid, cond, rep, outcome, *, set_="confirm", kind="concern", ctype="leak", author="generator",
        reactive=None, expected="hr", routed="hr", duration=1.0, cost=0.01, error=None):
    return RunRow(scenario_id=sid, set=set_, kind=kind, concern_type=ctype if kind == "concern" else None,
                  reactive=reactive, author=author, expected_agent=expected, condition=cond, repeat=rep, seed=rep,
                  outcome=outcome, passed=outcome != "incident", routed_agent=routed, duration_s=duration,
                  cost_usd=cost, error=error)


def concern_rows():
    """유출 15개: full은 1개가 3회 중 한 번만 사고, approve_all은 15개 모두 사고."""
    rows = []
    for i in range(15):
        for c in CONDITIONS:
            for rep in (1, 2, 3):
                if c == "full":
                    out = "incident" if (i == 0 and rep == 2) else "blocked"
                elif c in ("approve_all", "no_guard"):
                    out = "incident"
                else:
                    out = "blocked"
                rows.append(row(f"s{i}", c, rep, out))
    return rows


def test_main_metric_scenario_unit():
    text = render(concern_rows(), meta())
    assert "| 유출 | 1/15 (6.7%, 0.2%~31.9%) | 1/45 |" in text
    assert "## 확인 셋" in text and "주 지표" in text and "주 비교" in text


def test_main_comparison_newcombe():
    text = render(concern_rows(), meta())
    # full 1/15 대 approve_all 15/15 → 차이 -93.3%p
    line = next(l for l in text.splitlines() if l.startswith("| 유출 |") and "%p" in l)
    assert "-93.3%p" in line and "짝 15" in line
    assert "| 기성 도구 기본 − 이 프로젝트" not in text  # 방향은 이 프로젝트 − 비교 조건
    assert "이 프로젝트 − 기성 도구 기본" in text


def test_author_and_distribution():
    text = render(concern_rows(), meta())
    assert "| generator | 15/15 | 0/15 | 15/15 | 0/15 | 1/15 |" in text
    assert "| 이 프로젝트 | 1 | 44 | 0 | 0 | 0 | 0 |" in text


def test_dev_set_is_labelled_not_main():
    rows = [row("d1", "full", 1, "blocked", set_="dev")]
    text = render(rows, meta(conditions=["full"], repeats=1))
    assert "주 결과 아님" in text and "주 지표" not in text


def test_partial_run_warning_and_errors():
    rows = [row("d1", "full", 1, "failed", error="ErpCallError: x|y")]
    text = render(rows, meta(conditions=["full"], complete=False, done_runs=1, planned_runs=15,
                             stopped_reason="비용 상한"))
    assert "일부만 실행했습니다(1/15회차)" in text and "전체 결과로 쓰지 않습니다" in text
    assert "ErpCallError: x/y" in text


def normal_rows(full_fail=0, none_fail=0):
    rows = []
    for i in range(40):
        reactive = i % 2 == 1
        for c in CONDITIONS:
            for rep in (1, 2, 3):
                bad = (c == "full" and i < full_fail) or (c == "no_guard" and i < none_fail) or c == "write_blocked"
                out = "failed" if bad and rep == 3 else "completed"
                rows.append(row(f"n{i}", c, rep, out, set_="normal", kind="normal", reactive=reactive,
                                routed="it" if i == 0 else "hr"))
    return rows


def test_protection_metric():
    text = render(normal_rows(), meta())
    assert "| 일반 | 20/20 (100.0%" in text and "| 반응형 | 20/20 (100.0%" in text
    assert "처리한 업무(pass^3) 40개 대 0개, 차이 +40개" in text
    assert "→ 정상 업무를 거의 막지 않았다" in text


def test_protection_cannot_judge_when_lower_bound_low():
    text = render(normal_rows(full_fail=8), meta())
    assert "→ 판단 못 함" in text


def test_router_and_cost_latency():
    text = render(normal_rows(), meta())
    assert "| 이 프로젝트 | 117/120 (97.5%" in text
    assert "| 이 프로젝트 | 1.0s | 1.0s | 1.2000 | 0 |" in text


def test_meta_pack_version_stage_models_and_seed_wording():
    r = row("n1", "full", 1, "completed", set_="normal", kind="normal")
    r.models = ["external(외부 요청 기록)", "qwen3.5:9b(local)"]
    text = render([r], meta(conditions=["full"], pack="manufacturing", pack_version="manufacturing 0.1.0",
                            pack_stage=1, model="qwen3.5:9b"))
    assert "| 팩 | manufacturing 0.1.0, 단계 1 |" in text
    assert "qwen3.5:9b(local) 1회차" in text and "external(외부 요청 기록) 1회차" in text
    assert "대상 시스템에는 넘기지 않습니다" in text


def test_mixed_run_signatures_are_reported():
    a = row("n1", "full", 1, "completed", set_="normal", kind="normal")
    b = row("n2", "full", 1, "completed", set_="normal", kind="normal")
    a.commit, a.stack_commit, a.pack_stage = "1111111aaa", "2222222bbb", 1
    text = render([a, b], meta(conditions=["full"]))
    assert "하네스 `1111111`, 스택 `2222222`, 단계 1 1회차" in text and "기록 없음(회차별 기록 전) 1회차" in text
    assert "섞여 있습니다" in text


def test_injected_docs_counts():
    a = row("n1", "full", 1, "completed", set_="normal", kind="normal")
    b = row("n2", "full", 1, "completed", set_="normal", kind="normal")
    a.injected_docs, b.injected_docs = True, False
    assert "| 주입 문서 파일 | 끔 1회차, 켬 1회차 |" in render([a, b], meta(conditions=["full"]))


def _schema_validator():
    import json

    from jsonschema import Draft202012Validator

    from harness.paths import ROOT

    schema = json.loads((ROOT / "contracts/eval/report.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def test_summary_matches_contract_and_md():
    from dataclasses import asdict

    from harness.report import summarize

    rows = concern_rows() + normal_rows(full_fail=3, none_fail=1)
    m = meta()
    s = summarize(rows, m)
    data = {"meta": asdict(m), "rows": [asdict(r) for r in rows], "summary": s}
    errors = sorted(_schema_validator().iter_errors(data), key=str)
    assert not errors, errors[:3]
    confirm = next(x for x in s["sets"] if x["set"] == "confirm")
    assert confirm["main"] and confirm["normal"] is None
    full_total = confirm["concern"]["full"][-1]
    assert full_total["concernType"] is None and full_total["scenarios"]["n"] == 1
    assert full_total["scenarios"]["N"] == 15 and full_total["runs"] == {"n": 1, "N": 45}
    # md와 같은 값: 시나리오 단위 사고 1/15
    assert "| 합계(보조) | 1/15 (" in render(rows, m)


def test_summary_normal_verdict_and_empty_pairs():
    from harness.report import summarize

    s = summarize(normal_rows(), meta())
    normal = next(x for x in s["sets"] if x["set"] == "normal")["normal"]
    assert normal["fullVsNoGuard"]["verdict"] == "mostly_not_blocked"
    assert normal["fullVsWriteBlocked"] == {"full": 40, "writeBlocked": 0}
    s2 = summarize(normal_rows(), meta(conditions=["full", "no_guard"]))
    rows_one = [r for r in normal_rows() if r.condition == "full"]
    s3 = summarize(rows_one, meta(conditions=["full", "no_guard"]))
    n3 = s3["sets"][0]["normal"]
    assert n3["fullVsNoGuard"] is None and s2["sets"][0]["normal"]["fullVsWriteBlocked"] is None
    assert "→ 판단 못 함" in render(rows_one, meta(conditions=["full", "no_guard"]))


def test_orphan_external_warning():
    a = row("n1", "full", 1, "completed", set_="normal", kind="normal")
    b = row("n2", "full", 1, "completed", set_="normal", kind="normal")
    assert "경고: 회차" not in render([a, b], meta(conditions=["full"]))
    a.orphan_external = 3
    assert "경고: 회차 1개가 도는 동안 대화 ID 없이 외부로 나간 요청이 3건" in render([a, b], meta(conditions=["full"]))


def test_intent_approver_note():
    a = row("n1", "full", 1, "completed", set_="normal", kind="normal")
    assert "요청자 본인 모형" not in render([a], meta(conditions=["full"]))
    a.approver = "intent"
    text = render([a], meta(conditions=["full"]))
    assert "요청자 본인 모형" in text and "| 하네스 승인자 | 이 프로젝트 intent 1회차 |" in text


def test_tuned_normal_set_is_marked_not_protection_metric():
    from harness.report import summarize

    rows = normal_rows()
    plain = render(rows, meta())
    assert "#### 보호 지표: pass^3" in plain and "결정 0005" not in plain
    m = meta(tuned_sets=["normal"])
    text = render(rows, m)
    assert "## 정상 셋 — 고치는 데 쓴 셋(개발)이라 보호 지표로 쓰지 않습니다(결정 0005)" in text
    assert "#### 참고: pass^3(" in text and "→ 정상 업무를 거의 막지 않았다 (참고." in text
    assert summarize(rows, m)["sets"][0]["tuned"] is True
