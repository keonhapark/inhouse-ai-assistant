import hashlib
import subprocess

from harness.paths import ROOT
import pytest

from harness.stackcheck import StackCheckError, check_mounts, check_stack, container_env

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
    assert got.ok and got.compared == 1 and got.missing > 0 and got.modules == {"eval"}
    assert got.missing_modules() == ["agent", "gateway", "rag"]
    assert "컨테이너 소스 1개 = 스택 커밋" in got.describe() and "마운트(litellm 설정 등) 대조 안 함" in got.describe()


def test_reports_changed_and_untracked_files():
    c = head()
    got = check_stack(["svc"], c, run=fake_run({PATH: "0" * 64, "eval/not-in-git.py": "1" * 64}))
    assert not got.ok
    assert got.mismatched == [f"svc:{PATH}", "svc:eval/not-in-git.py(커밋에 없음)"]
    assert "다른 파일 2개" in got.describe()


def test_nothing_compared_is_not_ok():
    assert not check_stack(["svc"], head(), run=fake_run({})).ok


def test_mount_files_are_compared_under_repo_path():
    c = head()
    listing = {"pyproject.toml": blob_sha(c, PATH)}  # 마운트 경로(/cfg) 기준 → 저장소 eval/pyproject.toml
    got = check_mounts(check_stack(["svc"], c, run=fake_run({PATH: blob_sha(c, PATH)})),
                       [{"container": "litellm", "path": "/cfg", "repo": "eval"}], run=fake_run(listing))
    assert got.ok and got.compared == 2 and "litellm:/cfg = eval(1개)" in got.describe()
    bad = check_mounts(check_stack(["svc"], c, run=fake_run({PATH: blob_sha(c, PATH)})),
                       [{"container": "litellm", "path": "/cfg", "repo": "eval"}],
                       run=fake_run({"pyproject.toml": "0" * 64}))
    assert not bad.ok and bad.mismatched == ["litellm:eval/pyproject.toml"]


def test_container_env_refuses_secret_names_and_reads_values():
    with pytest.raises(StackCheckError, match="기록하지 않는"):
        container_env("gw", ["LITELLM_MASTER_KEY"])
    with pytest.raises(StackCheckError, match="기록하지 않는"):
        container_env("gw", ["COLAB_OLLAMA_BASE_URL"])

    def run(cmd, **kw):
        assert cmd[:3] == ["docker", "exec", "gw"]
        return subprocess.CompletedProcess(cmd, 0, stdout="GATEWAY_LOCAL_REASONING_EFFORT=none\nRAG_EXTRA_DOCS=\n",
                                           stderr="")
    got = container_env("gw", ["GATEWAY_LOCAL_REASONING_EFFORT", "RAG_EXTRA_DOCS", "PACK_STAGE"], run=run)
    assert got == {"GATEWAY_LOCAL_REASONING_EFFORT": "none", "RAG_EXTRA_DOCS": "", "PACK_STAGE": ""}
