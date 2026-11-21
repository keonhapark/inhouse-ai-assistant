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
    assert cl.classify("agent/README.md") == ("core_docs", "agent")
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


def test_counts_core_lines_per_pack_with_related_commits(tmp_path, monkeypatch):
    commit = _repo(tmp_path)
    commit({"gateway/app.py": "a\nb\n", "gateway/README.md": "d\n", "gateway/tests/test_a.py": "t\n"}, "관련 코어 (#10)")
    commit({"packs/bank/org.yaml": "x\ny\n", "rag/templates/bank-a.md": "t\n"}, "pack: 뼈대 (#11)")
    commit({"packs/shop/org.yaml": "z\n"}, "pack: 두 번째 팩 (#12)")
    monkeypatch.setattr(cl, "ROOT", tmp_path)
    related = subprocess.run(["git", "-C", str(tmp_path), "rev-list", "--max-parents=0", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
    cfg = tmp_path / "core_lines.yaml"
    cfg.write_text(f"bank:\n  extra:\n    - commit: {related[:7]}\n      pr: 10\n      reason: 첫 팩에 필요한 일반 기능\n"
                   "shop:\n  extra: []\n", encoding="utf-8")
    out = []
    monkeypatch.setattr(cl.sys.stdout, "write", out.append)
    assert cl.main(["--ref", "HEAD", "--config", str(cfg)]) == 0
    md = "".join(out)
    assert "| bank | 2 | 1 | 1 |" in md and "| shop | 0 | 0 | 0 |" in md
    assert "#10 첫 팩에 필요한 일반 기능" in md and "| 관련 커밋 |" in md and "- `gateway/app.py`" in md


def test_extra_commit_must_be_in_ref(tmp_path, monkeypatch):
    import pytest

    commit = _repo(tmp_path)
    commit({"packs/bank/org.yaml": "x\n"}, "pack: 뼈대")
    subprocess.run(["git", "-C", str(tmp_path), "switch", "-q", "-c", "side"], check=True)
    commit({"gateway/x.py": "t\n"}, "작업 브랜치 커밋")
    side = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(cl, "ROOT", tmp_path)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"bank:\n  extra:\n    - commit: {side}\n      reason: r\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="이력에 없습니다"):
        cl.main(["--ref", "main", "--config", str(cfg)])


def test_suggest_finds_core_prs_linked_through_pack_pr_issues(tmp_path, monkeypatch):
    commit = _repo(tmp_path)
    commit({"packs/bank/org.yaml": "x\n"}, "pack: 뼈대 (#11)")
    monkeypatch.setattr(cl, "ROOT", tmp_path)
    answers = {
        ("pr", "view", "11"): {"body": "#5 팩 단위 기능이 필요합니다"},
        ("pr", "list", "#5 in:body"): [
            {"number": 20, "title": "feat(gateway): 일반 기능", "mergeCommit": {"oid": "abc1234ff"},
             "files": [{"path": "gateway/egress.py"}]},
            {"number": 21, "title": "docs: 설명", "mergeCommit": {"oid": "def"}, "files": [{"path": "docs/a.md"}]},
            {"number": 11, "title": "pack", "mergeCommit": {"oid": "x"}, "files": [{"path": "packs/bank/org.yaml"}]}],
    }

    def run(cmd, **kw):
        key = tuple(cmd[1:4]) if cmd[2] == "view" else ("pr", "list", cmd[cmd.index("--search") + 1])
        return subprocess.CompletedProcess(cmd, 0, stdout=__import__("json").dumps(answers[key]), stderr="")

    got = cl.suggest("bank", "HEAD", run=run)
    assert got == [{"pr": 20, "title": "feat(gateway): 일반 기능", "commit": "abc1234", "issues": [5]}]
