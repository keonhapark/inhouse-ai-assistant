"""확인 셋 묶음 해시 확인(contracts/eval/confirm-sets.md)."""

import hashlib
import json

import pytest
import yaml

from harness.bundle import bundle_hash, check, describe, recorded_hashes
from harness.cli import main


def test_recorded_hashes_reads_contract_table():
    got = recorded_hashes()
    assert set(got) >= {"confirm-v1", "toolcall-v1"} and all(len(v) == 64 for v in got.values())


def make_bundle(tmp_path, form="list", name="b-v1", fmt="json", want=None):
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
    want = want or bundle_hash(shas)
    table = tmp_path / "table.md"
    table.write_text(f"| 묶음 | 쓰임 | 구성 | bundleSha256 | 날 |\n|---|---|---|---|---|\n"
                     f"| {name} | x | y | `{want}` | 2026-11-22 |\n", encoding="utf-8")
    return root, table


@pytest.mark.parametrize("form, fmt", [("list", "json"), ("dict", "json"), ("list", "yaml"), ("dict", "yaml")])
def test_check_matches_contract_rule(tmp_path, form, fmt):
    root, table = make_bundle(tmp_path, form, fmt=fmt)
    c = check(root, table=table)
    assert c.ok and c.files == 2
    assert "= 계약 표(파일 2개, 끝 줄바꿈 있음)" in describe(c)


def test_bundle_hash_puts_newline_after_every_line():
    files = {"b.yaml": "2" * 64, "a.yaml": "1" * 64}
    body = f"{'1' * 64}  a.yaml\n{'2' * 64}  b.yaml\n"
    assert bundle_hash(files) == hashlib.sha256(body.encode()).hexdigest()


def test_check_refuses_hash_without_trailing_newline(tmp_path):
    """#439 규칙(모든 줄 끝 줄바꿈)만 받습니다. 끝 줄바꿈 없는 계산으로 적힌 표는 맞지 않습니다."""
    shas = {"scenarios/a.yaml": hashlib.sha256(b"- id: a\n").hexdigest(),
            "markers.yaml": hashlib.sha256(b"markers: {}\n").hexdigest()}
    body = "\n".join(f"{sha}  {path}" for path, sha in sorted(shas.items()))
    root, table = make_bundle(tmp_path, want=hashlib.sha256(body.encode()).hexdigest())
    c = check(root, table=table)
    assert not c.ok and "와 다릅니다" in describe(c)


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


def _run_cfg(tmp_path, rag=True):
    cfg = {"erp": {"baseUrl": "http://e"}, "gateway": {"baseUrl": "http://g", "conditions": ["full"]}}
    if rag:
        cfg["rag"] = {"container": "rag-c"}
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def _fake_docker(monkeypatch, extra_docs: str, sha: str = ""):
    import subprocess

    def run(cmd, **kw):
        out = sha + "  " + extra_docs if "sha256sum" in cmd[-1] and extra_docs else extra_docs
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", run)


def _confirm_table(monkeypatch, table):
    """run이 시험용 계약 표를 읽게 합니다."""
    recorded = recorded_hashes(table)
    monkeypatch.setattr("harness.bundle.recorded_hashes", lambda table=None: recorded)


@pytest.mark.parametrize("where", ["unlisted-in-bundle", "outside-bundle"])
def test_run_stops_when_scenarios_are_not_in_manifest(tmp_path, monkeypatch, where):
    root, table = make_bundle(tmp_path, name="confirm-v1")
    _confirm_table(monkeypatch, table)
    if where == "unlisted-in-bundle":
        (root / "scenarios" / "extra.yaml").write_text("- id: extra\n", encoding="utf-8")
        scen = root / "scenarios"
    else:
        scen = tmp_path / "dev"
        scen.mkdir()
        (scen / "a.yaml").write_bytes(b"- id: a\n")
    with pytest.raises(SystemExit, match="manifest에 없는 파일 1개"):
        main(["run", "--config", str(_run_cfg(tmp_path)), "--scenarios", str(scen), "--out", str(tmp_path / "r"),
              "--bundle", str(root)])
    assert not (tmp_path / "r.rows.jsonl").exists()


def test_run_stops_when_rag_injected_docs_are_not_from_bundle(tmp_path, monkeypatch):
    root, table = make_bundle(tmp_path, name="confirm-v1")
    _confirm_table(monkeypatch, table)
    monkeypatch.setattr("harness.cli.load_scenarios", lambda d: [])
    args = ["run", "--config", str(_run_cfg(tmp_path)), "--scenarios", str(root / "scenarios"),
            "--out", str(tmp_path / "r"), "--bundle", str(root)]
    _fake_docker(monkeypatch, "/eval/confirm/injected-docs.json", "0" * 64)
    with pytest.raises(SystemExit, match="어느 파일과도 해시가 다릅니다"):
        main(args)
    _fake_docker(monkeypatch, "/eval/confirm/injected-docs.json", "")
    with pytest.raises(SystemExit, match="해시를 구하지 못했습니다"):
        main(args)
    with pytest.raises(SystemExit, match="rag.container"):
        main(["run", "--config", str(_run_cfg(tmp_path, rag=False)), "--scenarios", str(root / "scenarios"),
              "--out", str(tmp_path / "r"), "--bundle", str(root)])
    assert not (tmp_path / "r.rows.jsonl").exists()


def test_bundle_inputs_pass_when_files_are_listed(tmp_path, monkeypatch):
    from harness.bundle import manifest_sha256s, unlisted
    from harness.cli import check_bundle_injected_docs, check_bundle_scenarios

    root, _ = make_bundle(tmp_path)
    assert unlisted(root, [root / "scenarios" / "a.yaml", root / "x" / ".." / "markers.yaml"]) == []
    check_bundle_scenarios(root, root / "scenarios")
    sha = hashlib.sha256(b"markers: {}\n").hexdigest()
    assert sha in manifest_sha256s(root)
    _fake_docker(monkeypatch, "/eval/confirm/markers.yaml", sha)
    check_bundle_injected_docs(root, {"rag": {"container": "rag-c"}})


class _Reached(Exception):
    pass


def _reach_factories(monkeypatch):
    """확인을 모두 지나 회차를 돌리기 직전(run_matrix)에 멈춥니다."""
    def stop(*a, **kw):
        raise _Reached

    monkeypatch.setattr("harness.cli.make_factories", lambda cfg: (None, None))
    monkeypatch.setattr("harness.cli.run_matrix", stop)


@pytest.mark.parametrize("extra_docs, matches", [("/eval/confirm/x.json", True), ("", None)])
def test_run_passes_bundle_checks_when_rag_file_matches_or_is_off(tmp_path, monkeypatch, extra_docs, matches):
    """켜진 주입 문서 파일이 manifest 해시와 같으면, 꺼져 있으면 해시 대조 없이 회차 준비로 넘어갑니다."""
    root, table = make_bundle(tmp_path, name="confirm-v1")
    _confirm_table(monkeypatch, table)
    monkeypatch.setattr("harness.cli.load_scenarios", lambda d: [])
    sha = hashlib.sha256(b"markers: {}\n").hexdigest() if matches else ""
    _fake_docker(monkeypatch, extra_docs, sha)
    _reach_factories(monkeypatch)
    with pytest.raises(_Reached):
        main(["run", "--config", str(_run_cfg(tmp_path)), "--scenarios", str(root / "scenarios"),
              "--out", str(tmp_path / "r"), "--bundle", str(root)])


def test_run_refuses_bundle_scenarios_with_attachments(tmp_path, monkeypatch):
    root, table = make_bundle(tmp_path, name="confirm-v1")
    _confirm_table(monkeypatch, table)
    monkeypatch.setattr("harness.cli.load_scenarios",
                        lambda d: [{"id": "img", "turns": [{"text": "x", "attachments": ["images/a.png"]}]}])
    with pytest.raises(SystemExit, match="첨부가 있는 시나리오 1개: img"):
        main(["run", "--config", str(_run_cfg(tmp_path)), "--scenarios", str(root / "scenarios"),
              "--out", str(tmp_path / "r"), "--bundle", str(root)])


def test_resume_refuses_rows_from_another_bundle(tmp_path, monkeypatch):
    """.json 없이 회차 기록만 남은 채 멈춘 실행도 회차마다 남긴 묶음으로 막습니다."""
    from harness.cli import check_bundle

    root, table = make_bundle(tmp_path, name="confirm-v1")
    _confirm_table(monkeypatch, table)
    monkeypatch.setattr("harness.cli.load_scenarios", lambda d: [])
    _fake_docker(monkeypatch, "")
    _reach_factories(monkeypatch)
    row = {"scenario_id": "a", "set": "confirm", "kind": "normal", "concern_type": None, "reactive": False,
           "author": "hand", "expected_agent": None, "condition": "full", "repeat": 1, "seed": 1,
           "outcome": "completed", "passed": True}
    out = tmp_path / "r"
    args = ["run", "--config", str(_run_cfg(tmp_path)), "--scenarios", str(root / "scenarios"),
            "--out", str(out), "--bundle", str(root), "--resume", "--allow-mixed"]
    out.with_suffix(".rows.jsonl").write_text(json.dumps({**row, "bundle": None}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="다른 묶음에서 돈 회차"):
        main(args)
    out.with_suffix(".rows.jsonl").write_text(json.dumps({**row, "bundle": check_bundle(str(root))}) + "\n",
                                              encoding="utf-8")
    with pytest.raises(_Reached):
        main(args)
