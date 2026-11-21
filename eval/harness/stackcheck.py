"""띄운 스택이 설정 `stackCommit`의 소스인지 컨테이너 안 파일로 확인합니다(#449).

설정 `stackCheck.containers`의 컨테이너마다 `/repo` 아래 파일의 SHA-256을 docker exec로 구해, 저장소의 같은
경로를 `stackCommit` 시점에서 읽은 내용과 견줍니다. 가상 환경·캐시(`SKIP_PARTS`)는 보지 않고, 그 밖에 컨테이너에만
있고 그 커밋의 git에 없는 파일은 다른 파일로 셉니다. git에는 있는데 컨테이너에 없는 파일(.dockerignore로 뺀 것)은
개수만 셉니다. 소스를 `/repo`에 복사하지 않는
컨테이너(Java로 빌드한 erp 등)는 이 방법으로 확인하지 못합니다.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from harness.paths import ROOT

SKIP_PARTS = {".venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
# docker exec 한 번으로 /repo 아래 파일 해시를 모두 구합니다
LIST_CMD = ("cd /repo && find . -type f ! -path '*/.venv/*' ! -path '*/__pycache__/*' ! -path '*/node_modules/*' "
            "-exec sha256sum {} +")


class StackCheckError(RuntimeError):
    pass


@dataclass
class StackCheck:
    commit: str
    containers: list[str]
    compared: int = 0
    missing: int = 0
    mismatched: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.compared > 0 and not self.mismatched

    def describe(self) -> str:
        head = f"{', '.join(self.containers)} 컨테이너 소스 {self.compared}개"
        if self.ok:
            return f"{head} = 스택 커밋 `{self.commit[:7]}`(컨테이너에 없는 저장소 파일 {self.missing}개)"
        return f"{head} 중 스택 커밋 `{self.commit[:7]}`과 다른 파일 {len(self.mismatched)}개"


def container_hashes(container: str, run=subprocess.run) -> dict[str, str]:
    """컨테이너 /repo 기준 상대 경로 → SHA-256."""
    try:
        r = run(["docker", "exec", container, "sh", "-c", LIST_CMD], capture_output=True, text=True, timeout=300,
                check=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise StackCheckError(f"{container}의 파일 해시를 구하지 못했습니다: {e}") from e
    out = {}
    for line in r.stdout.splitlines():
        sha, _, path = line.partition("  ")
        if len(sha) == 64 and path.startswith("./"):
            out[path[2:]] = sha
    return out


def git_hashes(commit: str, paths: set[str], run=subprocess.run) -> dict[str, str]:
    """commit 시점에 git에 있는 paths의 내용 SHA-256. git에 없는 경로는 빠집니다."""
    try:
        tracked = run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", commit], capture_output=True,
                      text=True, check=True).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as e:
        raise StackCheckError(f"git에서 {commit}을 읽지 못했습니다: {e}") from e
    wanted = [p for p in tracked if p in paths]
    if not wanted:
        return {}
    batch = run(["git", "-C", str(ROOT), "cat-file", "--batch"], input="".join(f"{commit}:{p}\n" for p in wanted)
                .encode(), capture_output=True, check=True).stdout
    out, pos = {}, 0
    for p in wanted:
        header_end = batch.index(b"\n", pos)
        size = int(batch[pos:header_end].split()[2])
        body = batch[header_end + 1:header_end + 1 + size]
        out[p] = hashlib.sha256(body).hexdigest()
        pos = header_end + 1 + size + 1
    return out


def check_stack(containers: list[str], commit: str, run=subprocess.run) -> StackCheck:
    c = StackCheck(commit=commit, containers=list(containers))
    for name in containers:
        got = {p: h for p, h in container_hashes(name, run).items()
               if not SKIP_PARTS & set(PurePosixPath(p).parts)}
        want = git_hashes(commit, set(got), run)
        c.compared += len(want)
        c.mismatched += sorted(f"{name}:{p}" for p, h in want.items() if got[p] != h)
        c.mismatched += sorted(f"{name}:{p}(커밋에 없음)" for p in set(got) - set(want))
        tops = {PurePosixPath(p).parts[0] for p in got}
        tracked_under = _tracked_under(commit, tops, run)
        c.missing += len(tracked_under - set(got))
    return c


def _tracked_under(commit: str, tops: set[str], run=subprocess.run) -> set[str]:
    if not tops:
        return set()
    r = run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", commit, "--", *sorted(tops)],
            capture_output=True, text=True, check=True)
    return set(r.stdout.splitlines())
