import importlib.util
import subprocess
import sys

from harness.paths import EVAL_DIR

spec = importlib.util.spec_from_file_location("core_lines", EVAL_DIR / "tools" / "core_lines.py")
cl = importlib.util.module_from_spec(spec)
sys.modules["core_lines"] = cl  # dataclass가 모듈을 찾습니다
spec.loader.exec_module(cl)


def test_classify():
    assert cl.classify("gateway/gateway/egress.py") == ("core_code", "gateway")
    assert cl.classify("agent/tests/test_tools.py") == ("core_tests", "agent")
    assert cl.classify("rag/templates/fin-work-rules.md") == ("pack", None)
    assert cl.classify("packs/finance/org.yaml") == ("pack", None)
    assert cl.classify("contracts/mcp/tools.json") == ("other", None)


def _repo(tmp_path):
    def run(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")

    def commit(files: dict[str, str], msg: str):
        for path, text in files.items():
            p = tmp_path / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", msg)
    return commit


def test_counts_core_lines_in_pack_commits(tmp_path):
    commit = _repo(tmp_path)
    commit({"gateway/app.py": "a\n"}, "core only")
    commit({"packs/bank/org.yaml": "x\ny\n", "rag/templates/bank-a.md": "t\n"}, "pack: 뼈대")
    commit({"packs/bank/agents.yaml": "z\n", "agent/runtime.py": "1\n2\n", "agent/tests/test_x.py": "t\n"}, "pack: 도구")
    shas = cl.pack_commits("bank", "HEAD", cwd=tmp_path)
    assert len(shas) == 2
    rows = [cl.count_commit(s, cwd=tmp_path) for s in shas]
    assert rows[0].core_code_total == 0 and rows[0].pack == 3
    assert rows[1].core_code == {"agent": 2} and rows[1].core_tests == {"agent": 1} and rows[1].pack == 1
    md = cl.render(["bank"], rows, "HEAD")
    assert "코어 코드 합계: 2줄(목표 0)" in md and "- `agent/runtime.py`" in md


def test_extra_commit_must_be_in_ref(tmp_path, monkeypatch):
    import pytest

    commit = _repo(tmp_path)
    commit({"packs/bank/org.yaml": "x\n"}, "pack: 뼈대")
    subprocess.run(["git", "-C", str(tmp_path), "switch", "-q", "-c", "side"], check=True)
    commit({"rag/templates/bank-a.md": "t\n"}, "작업 브랜치 커밋")
    side = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(cl, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="이력에 없습니다"):
        cl.main(["--pack", "bank", "--ref", "main", "--extra", side])
    assert cl.main(["--pack", "bank", "--ref", "side", "--extra", side]) == 0
