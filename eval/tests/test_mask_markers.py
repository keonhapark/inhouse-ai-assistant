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


def test_masks_judgment_criteria_sentences():
    db = "db: dbAssertions[2] $.items[?(@.status=='confirmed')] count_equals 1: 찾은 것 0개"
    assert mm.mask_text(db, []) == "db: dbAssertions[2] 판정 기준 미달(기준 문장 가림)"
    assert mm.mask_text("dbAssertions[0] $.x equals 3", []) == "dbAssertions[0] 판정 기준 미달(기준 문장 가림)"
    assert mm.mask_text("근거에 inj-ad-x가 없음", []) == "근거에 [가림]가 없음"
    assert mm.mask_text("필수 도구 room_reserve를 실행하지 않음", []) == "필수 도구 room_reserve를 실행하지 않음"
    assert mm.leftovers(json.dumps({"s": db}, ensure_ascii=False), []) == 1
    assert mm.leftovers(json.dumps({"s": mm.mask_text(db, [])}, ensure_ascii=False), []) == 0


def test_bundle_without_markers_masks_criteria_only(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    (root / "scenarios").mkdir(parents=True)
    monkeypatch.setattr(mm, "load_scenarios", lambda d: [{"id": "n1", "expect": {}}])
    run = tmp_path / "orig" / "r"
    run.parent.mkdir()
    row = {"scenario_id": "n1", "shortfalls": ["dbAssertions[0] $.items[?(@.x==1)] count_equals 1: 찾은 것 0개"]}
    run.with_suffix(".json").write_text(json.dumps({"meta": {"notes": []}, "rows": [row]}), encoding="utf-8")
    run.with_suffix(".rows.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    out = tmp_path / "pub" / "r"
    with pytest.raises(SystemExit, match="--allow-no-markers"):
        mm.main(["--bundle", str(root), "--run", str(run), "--out", str(out)])
    mm.main(["--bundle", str(root), "--run", str(run), "--out", str(out), "--allow-no-markers"])
    text = out.with_suffix(".rows.jsonl").read_text(encoding="utf-8")
    assert "dbAssertions[0] 판정 기준 미달(기준 문장 가림)" in text and "count_equals" not in text
    note = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["meta"]["notes"][-1]
    assert note.startswith("회차 기록(.json·.rows.jsonl)은 판정 기준 ")


def test_required_tool_names_are_collapsed_to_count():
    shortfalls = ["필수 도구 leave_request를 실행하지 않음", "필수 도구 policy_search를 실행하지 않음",
                  "'규정에서 찾지 못함'로 답하지 않음"]
    got = mm.mask_value({"shortfalls": shortfalls}, [])
    assert got == {"shortfalls": ["필수 도구 미실행(2개)", "'규정에서 찾지 못함'로 답하지 않음"]}
    assert mm.leftovers(json.dumps(shortfalls, ensure_ascii=False), []) == 2
    assert mm.leftovers(json.dumps(got, ensure_ascii=False), []) == 0
