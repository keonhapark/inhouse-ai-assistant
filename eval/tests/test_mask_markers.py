import hashlib
import importlib.util
import json

import pytest

from harness.paths import EVAL_DIR

spec = importlib.util.spec_from_file_location("mask_markers", EVAL_DIR / "tools" / "mask_markers.py")
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    (root / "scenarios").mkdir(parents=True)
    (root / "markers.json").write_text(json.dumps({"markers": {"gen-a": ["코드명 파랑새-91"]}}), encoding="utf-8")
    monkeypatch.setattr(mm, "load_scenarios",
                        lambda d: [{"id": "s1", "expect": {"markers": ["RND-DWG-2217", "DWG-2217"]}}, {"id": "s2"}])
    return root


def write_run(tmp_path):
    run = tmp_path / "orig" / "r"
    run.parent.mkdir()
    row = {"scenario_id": "s1", "incidents": [{"kind": "marker", "detail": "RND-DWG-2217 in answer"}],
           "notes": ["코드명 파랑새-91 in external"], "models": ["local(local)"]}
    run.with_suffix(".json").write_text(json.dumps({"meta": {"notes": ["원래 메모"]}, "rows": [row]},
                                                   ensure_ascii=False), encoding="utf-8")
    run.with_suffix(".rows.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return run


def test_masks_markers_longest_first_and_records_original_hashes(tmp_path, bundle):
    run = write_run(tmp_path)
    out = tmp_path / "masked" / "r"
    mm.main(["--bundle", str(bundle), "--run", str(run), "--out", str(out), "--note", "504 한 건"])
    text = out.with_suffix(".json").read_text(encoding="utf-8") + out.with_suffix(".rows.jsonl").read_text("utf-8")
    assert "RND-DWG-2217" not in text and "DWG-2217" not in text and "파랑새" not in text
    assert mm.token("RND-DWG-2217") in text and mm.token("코드명 파랑새-91") in text
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["meta"]
    want = hashlib.sha256(run.with_suffix(".rows.jsonl").read_bytes()).hexdigest()
    assert meta["notes"][:2] == ["원래 메모", "504 한 건"] and f"r.rows.jsonl sha256 {want}" in meta["notes"][2]
    row = json.loads(out.with_suffix(".rows.jsonl").read_text(encoding="utf-8"))
    assert row["scenario_id"] == "s1" and row["models"] == ["local(local)"]


def test_refuses_same_output_and_empty_markers(tmp_path, bundle, monkeypatch):
    run = write_run(tmp_path)
    with pytest.raises(SystemExit, match="같은 이름"):
        mm.main(["--bundle", str(bundle), "--run", str(run), "--out", str(run)])
    (bundle / "markers.json").unlink()
    monkeypatch.setattr(mm, "load_scenarios", lambda d: [])
    with pytest.raises(SystemExit, match="표지를 하나도"):
        mm.main(["--bundle", str(bundle), "--run", str(run), "--out", str(tmp_path / "x" / "r")])


def test_leftovers_sees_json_escaped_markers():
    assert mm.leftovers(json.dumps('a"b\\c'), ['a"b\\c']) == 1
    assert mm.leftovers("없음", ["표지"]) == 0
