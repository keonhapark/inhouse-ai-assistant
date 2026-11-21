import json

import pytest
import yaml

from harness.cli import load_config, main
from harness.paths import EVAL_DIR, ROOT
from harness.runner import RunMeta, RunRow, save_run


def test_example_config_is_valid():
    cfg = load_config(EVAL_DIR / "conditions.example.yaml")
    assert set(cfg["gateway"]["conditions"]) == {"no_guard", "write_blocked", "approve_all", "baseline_tools", "full"}
    assert cfg["erp"]["reset"] is True


@pytest.mark.parametrize("cfg, msg", [
    ({"erp": {"baseUrl": "x"}, "gateway": {"baseUrl": "g", "conditions": ["none"]}}, "계약에 없는 조건"),
    ({"erp": {"baseUrl": "x"}, "gateway": {"baseUrl": "g", "conditions": []}}, "비어 있습니다"),
    ({"erp": {"baseUrl": "x"}, "gateway": {"conditions": ["full"]}}, "gateway.baseUrl"),
    ({"erp": {}, "gateway": {"baseUrl": "g", "conditions": ["full"]}}, "erp.baseUrl"),
])
def test_bad_config(tmp_path, cfg, msg):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        load_config(p)


def test_validate_command(tmp_path, capsys):
    assert main(["validate", str(ROOT / "packs/manufacturing/scenarios")]) == 0
    assert "통과" in capsys.readouterr().out
    (tmp_path / "bad.json").write_text(json.dumps({"id": "x"}), encoding="utf-8")
    assert main(["validate", str(tmp_path)]) == 1


def test_report_command(tmp_path):
    meta = RunMeta(commit="c", dirty=False, machine="m", started_at="s", finished_at="f", conditions=["full"],
                   repeats=1, planned_runs=1, done_runs=1, complete=True)
    row = RunRow(scenario_id="a", set="dev", kind="concern", concern_type="leak", reactive=None, author="hand",
                 expected_agent=None, condition="full", repeat=1, seed=1, outcome="blocked", passed=True)
    save_run([row], meta, tmp_path / "r.json")
    assert main(["report", str(tmp_path / "r.json"), "-o", str(tmp_path / "r.md"), "--title", "시험"]) == 0
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# 시험")


def test_resume_refuses_mixed_systems_unless_allowed(tmp_path):
    from dataclasses import asdict

    cfg = {"repeats": 1, "packStage": 1, "erp": {"baseUrl": "http://erp.invalid"},
           "gateway": {"baseUrl": "http://gw.invalid", "conditions": ["full"]}}
    (tmp_path / "c.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    sid = "dev-concern-cross-dept-salary"
    old = RunRow(scenario_id=sid, set="dev", kind="concern", concern_type="cross_dept_bypass", reactive=None,
                 author="hand", expected_agent=None, condition="full", repeat=1, seed=1, outcome="blocked",
                 passed=True, cost_usd=0.0, commit="0ldc0mmit", pack_stage=1)
    out = tmp_path / "r"
    (tmp_path / "r.rows.jsonl").write_text(json.dumps(asdict(old), ensure_ascii=False) + "\n", encoding="utf-8")
    args = ["run", "--config", str(tmp_path / "c.yaml"), "--scenarios", str(ROOT / "packs/manufacturing/scenarios"),
            "--only", sid, "--out", str(out), "--resume"]
    with pytest.raises(SystemExit, match="다른 \\(하네스 커밋"):
        main(args)
    # 끝난 회차뿐이라 새로 돌 것이 없고, 보고서에 회차별 실행 시스템이 나옵니다
    assert main([*args, "--allow-mixed"]) == 0
    assert "하네스 `0ldc0mm`, 단계 1 1회차" in (tmp_path / "r.md").read_text(encoding="utf-8")


def _fake_rag(monkeypatch, value):
    import subprocess

    def run(cmd, **kw):
        assert cmd[:3] == ["docker", "exec", "rag-c"]
        return subprocess.CompletedProcess(cmd, 0, stdout=value, stderr="")

    monkeypatch.setattr(subprocess, "run", run)


def test_rag_injected_docs_check(monkeypatch):
    from harness.cli import rag_injected_docs

    assert rag_injected_docs({}) is None
    _fake_rag(monkeypatch, "/data/injected.yaml")
    assert rag_injected_docs({"rag": {"container": "rag-c"}}) is True
    _fake_rag(monkeypatch, "")
    assert rag_injected_docs({"rag": {"container": "rag-c"}}) is False


def test_injected_docs_split_refuses_mismatched_stack(tmp_path, monkeypatch):
    cfg = {"repeats": 1, "rag": {"container": "rag-c"}, "erp": {"baseUrl": "http://erp.invalid"},
           "gateway": {"baseUrl": "http://gw.invalid", "conditions": ["full"]}}
    (tmp_path / "c.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    _fake_rag(monkeypatch, "")
    args = ["run", "--config", str(tmp_path / "c.yaml"), "--scenarios", str(EVAL_DIR / "scenarios"), "--set", "dev",
            "--out", str(tmp_path / "r"), "--injected-docs", "only"]
    with pytest.raises(SystemExit, match="꺼져 있습니다"):
        main(args)


def test_run_json_carries_summary_via_report_update(tmp_path):
    meta = RunMeta(commit="c", dirty=False, machine="m", started_at="s", finished_at="f", conditions=["full"],
                   repeats=1, planned_runs=1, done_runs=1, complete=True)
    row = RunRow(scenario_id="a", set="dev", kind="concern", concern_type="leak", reactive=None, author="hand",
                 expected_agent=None, condition="full", repeat=1, seed=1, outcome="blocked", passed=True)
    save_run([row], meta, tmp_path / "r.json")
    assert "summary" not in json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert main(["report", str(tmp_path / "r.json"), "--update-json", "-o", str(tmp_path / "r.md")]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["summary"]["passK"] == 1 and data["summary"]["sets"][0]["set"] == "dev"
