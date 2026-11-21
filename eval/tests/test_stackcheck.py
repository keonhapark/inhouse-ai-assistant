import hashlib
import subprocess

from harness.paths import ROOT
from harness.stackcheck import check_stack

PATH = "eval/pyproject.toml"


def head() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def blob_sha(commit: str, path: str) -> str:
    data = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{path}"], capture_output=True,
                          check=True).stdout
    return hashlib.sha256(data).hexdigest()


def fake_run(listing: dict[str, str]):
    """docker exec는 listing(경로→해시)을 돌려주고, git은 실제로 부릅니다."""
    def run(cmd, **kw):
        if cmd[0] == "docker":
            out = "".join(f"{h}  ./{p}\n" for p, h in listing.items())
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        return subprocess.run(cmd, **kw)
    return run


def test_matches_when_container_files_equal_commit():
    c = head()
    got = check_stack(["svc"], c, run=fake_run({PATH: blob_sha(c, PATH), ".venv/x.py": "0" * 64}))
    assert got.ok and got.compared == 1 and got.missing > 0
    assert "컨테이너 소스 1개 = 스택 커밋" in got.describe()


def test_reports_changed_and_untracked_files():
    c = head()
    got = check_stack(["svc"], c, run=fake_run({PATH: "0" * 64, "eval/not-in-git.py": "1" * 64}))
    assert not got.ok
    assert got.mismatched == [f"svc:{PATH}", "svc:eval/not-in-git.py(커밋에 없음)"]
    assert "다른 파일 2개" in got.describe()


def test_nothing_compared_is_not_ok():
    assert not check_stack(["svc"], head(), run=fake_run({})).ok
