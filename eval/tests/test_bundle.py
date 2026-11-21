"""확인 셋 묶음 해시 확인(contracts/eval/confirm-sets.md)."""

import hashlib
import json

import pytest
import yaml

from harness.bundle import bundle_hashes, check, describe, recorded_hashes
from harness.cli import main


def test_recorded_hashes_reads_contract_table():
    got = recorded_hashes()
    assert set(got) >= {"confirm-v1", "toolcall-v1"} and all(len(v) == 64 for v in got.values())


def make_bundle(tmp_path, form="list", newline=True, name="b-v1", fmt="json"):
    root = tmp_path / "bundle"
    (root / "scenarios").mkdir(parents=True)
    files = {"scenarios/a.yaml": b"- id: a\n", "markers.yaml": b"markers: {}\n"}
    shas = {}
    for path, data in files.items():
        (root / path).write_bytes(data)
        shas[path] = hashlib.sha256(data).hexdigest()
    listed = [{"path": p, "sha256": s} for p, s in shas.items()] if form == "list" else shas
    manifest = {"name": name, "files": listed}
    if fmt == "json":
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (root / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    want = bundle_hashes(shas)["있음" if newline else "없음"]
    table = tmp_path / "table.md"
    table.write_text(f"| 묶음 | 쓰임 | 구성 | bundleSha256 | 날 |\n|---|---|---|---|---|\n"
                     f"| {name} | x | y | `{want}` | 2026-11-22 |\n", encoding="utf-8")
    return root, table


@pytest.mark.parametrize("form, newline, fmt", [("list", True, "json"), ("dict", False, "json"),
                                                ("list", False, "yaml"), ("dict", True, "yaml")])
def test_check_matches_either_form_and_newline(tmp_path, form, newline, fmt):
    root, table = make_bundle(tmp_path, form, newline, fmt=fmt)
    c = check(root, table=table)
    assert c.ok and c.files == 2 and c.newline == ("있음" if newline else "없음")
    assert "= 계약 표(파일 2개, 끝 줄바꿈 " in describe(c)


def test_check_finds_changed_file_and_wrong_table(tmp_path):
    root, table = make_bundle(tmp_path)
    (root / "markers.yaml").write_bytes(b"changed\n")
    c = check(root, table=table)
    assert not c.ok and c.mismatched_files == ["markers.yaml"] and "다른 파일 1개" in describe(c)
    root2, _ = make_bundle(tmp_path / "x", name="other")
    c = check(root2, table=table)
    assert not c.ok and "계약 표에 이 묶음이 없습니다" in describe(c)


def test_check_rejects_paths_outside_bundle(tmp_path):
    root, table = make_bundle(tmp_path)
    (tmp_path / "secret").write_bytes(b"x")
    m = json.loads((root / "manifest.json").read_text())
    m["files"].append({"path": "../secret", "sha256": hashlib.sha256(b"x").hexdigest()})
    (root / "manifest.json").write_text(json.dumps(m))
    assert "../secret" in check(root, table=table).mismatched_files


def test_run_stops_on_bundle_mismatch(tmp_path, capsys):
    root, _ = make_bundle(tmp_path, name="confirm-v1")
    cfg = {"erp": {"baseUrl": "http://e"}, "gateway": {"baseUrl": "http://g", "conditions": ["full"]}}
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(SystemExit, match="계약과 맞지 않습니다"):
        main(["run", "--config", str(p), "--scenarios", str(root / "scenarios"), "--out", str(tmp_path / "r"),
              "--bundle", str(root)])
    assert not (tmp_path / "r.rows.jsonl").exists()
    with pytest.raises(SystemExit, match="계약과 맞지 않습니다"):
        main(["bundle-check", str(root)])
