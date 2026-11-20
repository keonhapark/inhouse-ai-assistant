import json

import pytest
import yaml

from harness.cli import load_config, main
from harness.paths import EVAL_DIR, ROOT
from harness.runner import RunMeta, RunRow, save_run


def test_example_config_is_valid():
    cfg = load_config(EVAL_DIR / "conditions.example.yaml")
    assert set(cfg["gateway"]["conditions"]) == {"no_guard", "write_blocked", "approve_all", "baseline_tools", "full"}


@pytest.mark.parametrize("cfg, msg", [
    ({"erp": {"baseUrl": "x"}, "gateway": {"conditions": {"none": "u"}}}, "계약에 없는 조건"),
    ({"erp": {"baseUrl": "x"}, "gateway": {"conditions": {}}}, "비어 있습니다"),
    ({"erp": {}, "gateway": {"conditions": {"full": "u"}}}, "baseUrl"),
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
