import importlib.util
import sys

from harness.nightly import compare, latest_run, read_subset, render
from harness.paths import EVAL_DIR
from harness.runner import RunMeta, RunRow
from harness.scenario import has_document_injection, load_scenarios

spec = importlib.util.spec_from_file_location("nightly_tool", EVAL_DIR / "tools" / "nightly.py")
nt = importlib.util.module_from_spec(spec)
sys.modules["nightly_tool"] = nt
spec.loader.exec_module(nt)


def row(sid, cond, outcome, passed, stack="aaaaaaa1"):
    return RunRow(scenario_id=sid, set="dev", kind="concern", concern_type="leak", reactive=None, author="hand",
                  expected_agent=None, condition=cond, repeat=1, seed=1, outcome=outcome, passed=passed,
                  stack_commit=stack)


def meta(at, commit):
    return RunMeta(commit=commit, dirty=False, machine="m", started_at=at)


def test_subset_is_dev_only_and_runs_without_injected_docs():
    ids = read_subset(EVAL_DIR / "nightly" / "subset.txt")
    by_id = {s["id"]: s for s in load_scenarios(EVAL_DIR / "scenarios")}
    assert len(ids) == len(set(ids)) >= 10 and all(i in by_id for i in ids)
    assert all(by_id[i]["set"] == "dev" and by_id[i]["pack"] == "manufacturing" for i in ids)
    assert not any(has_document_injection(by_id[i]) for i in ids)


def test_compare_lists_changed_runs_and_tallies():
    prev = ([row("a", "full", "blocked", True), row("b", "full", "blocked", True), row("c", "no_guard", "incident", False)],
            meta("2027-03-01T03:30:00+09:00", "1111111aaaa"))
    cur = ([row("a", "full", "incident", False, "bbbbbbb2"), row("b", "full", "blocked", True),
            row("d", "no_guard", "blocked", True, "bbbbbbb2")], meta("2027-03-02T03:30:00+09:00", "2222222bbbb"))
    diff = compare(prev, cur)
    assert diff["changed"] == [{"scenario": "a", "condition": "full", "before": "blocked", "after": "incident"}]
    assert diff["tally_before"]["full"] == {"incident": 0, "passed": 2, "runs": 2}
    assert diff["tally_after"]["full"]["incident"] == 1
    assert diff["only_before"] == ["c no_guard"] and diff["only_after"] == ["d no_guard"]
    md = render(diff)
    assert "| a | full | blocked | incident |" in md and "스택 `aaaaaaa`" in md and "bbbbbbb" in md


def test_latest_run_skips_compare_files_and_current(tmp_path):
    for name in ("2027-03-01-0330.json", "2027-03-02-0330.json", "2027-03-02-0330-compare.json"):
        (tmp_path / name).write_text("{}")
    assert latest_run(tmp_path).name == "2027-03-02-0330.json"
    assert latest_run(tmp_path, exclude=tmp_path / "2027-03-02-0330.json").name == "2027-03-01-0330.json"
    assert latest_run(tmp_path / "none") is None


def test_skips_when_gpu_is_taken(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(nt, "lease", lambda *a: calls.append(a) or 1)
    monkeypatch.setattr(nt, "run_harness", lambda *a: (_ for _ in ()).throw(AssertionError("돌면 안 됨")))
    assert nt.main(["--config", "c.yaml", "--state", str(tmp_path)]) == 0
    assert "사용 중이라 건너뜁니다" in capsys.readouterr().out and calls[0][0] == "take"


def test_runs_compares_and_releases(tmp_path, monkeypatch):
    from harness.runner import save_run

    calls = []
    monkeypatch.setattr(nt, "lease", lambda *a: calls.append(a[0]) or 0)
    save_run([row("a", "full", "blocked", True)], meta("2027-03-01T03:30:00+09:00", "1111111"),
             tmp_path / "2027-03-01-0330.json")

    def fake_run(config, ids, out):
        save_run([row("a", "full", "incident", False)], meta("2027-03-02T03:30:00+09:00", "2222222"),
                 out.with_suffix(".json"))
        return 0

    monkeypatch.setattr(nt, "run_harness", fake_run)
    assert nt.main(["--config", "c.yaml", "--state", str(tmp_path)]) == 0
    compare_md = next(tmp_path.glob("*-compare.md")).read_text(encoding="utf-8")
    assert "결과가 바뀐 회차 1개" in compare_md
    assert calls == ["take", "release"]
