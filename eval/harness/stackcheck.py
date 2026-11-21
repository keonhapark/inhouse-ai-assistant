"""띄운 스택이 설정 `stackCommit`의 소스인지 컨테이너 안 파일로 확인합니다(#449).

설정 `stackCheck.containers`의 컨테이너마다 `/repo` 아래 파일의 SHA-256을 docker exec로 구해, 저장소의 같은
경로를 `stackCommit` 시점에서 읽은 내용과 견줍니다. 가상 환경·캐시(`SKIP_PARTS`)는 보지 않고, 그 밖에 컨테이너에만
있고 그 커밋의 git에 없는 파일은 다른 파일로 셉니다. git에는 있는데 컨테이너에 없는 파일(.dockerignore로 뺀 것)은
개수만 셉니다. 소스를 `/repo`에 복사하지 않는
컨테이너(Java로 빌드한 erp 등)는 이 방법으로 확인하지 못합니다.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from harness.paths import ROOT

SKIP_PARTS = {".venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
# docker exec 한 번으로 /repo 아래 파일 해시를 모두 구합니다
LIST_CMD = ("cd {root} && find . -type f ! -path '*/.venv/*' ! -path '*/__pycache__/*' ! -path '*/node_modules/*' "
            "-exec sha256sum {{}} +")
# 확인 셋(--bundle)이면 비교한 파일에 이 모듈 폴더가 모두 있어야 합니다(#470)
REQUIRED_MODULES = ("agent", "gateway", "rag")
# 기록할 환경 변수 이름에 이 말이 들어가면 값이 비밀일 수 있어 받지 않습니다
SECRET_WORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASS", "CREDENTIAL", "URL")


class StackCheckError(RuntimeError):
    pass


@dataclass
class StackCheck:
    commit: str
    containers: list[str]
    compared: int = 0
    missing: int = 0
    mismatched: list[str] = field(default_factory=list)
    # 비교한 파일의 맨 위 폴더(agent, gateway, rag, contracts, packs …)
    modules: set[str] = field(default_factory=set)
    # 마운트 대조: "컨테이너:경로 = 저장소 경로" 설명
    mounts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.compared > 0 and not self.mismatched

    def missing_modules(self, required: tuple[str, ...] = REQUIRED_MODULES) -> list[str]:
        return [m for m in required if m not in self.modules]

    def describe(self) -> str:
        head = f"{', '.join(self.containers)} 컨테이너 소스 {self.compared}개"
        mounts = f"; 마운트 {', '.join(self.mounts)}" if self.mounts else "; 마운트(litellm 설정 등) 대조 안 함"
        if self.ok:
            return f"{head} = 스택 커밋 `{self.commit[:7]}`(컨테이너에 없는 저장소 파일 {self.missing}개){mounts}"
        return f"{head} 중 스택 커밋 `{self.commit[:7]}`과 다른 파일 {len(self.mismatched)}개{mounts}"


def container_hashes(container: str, run=subprocess.run, root: str = "/repo") -> dict[str, str]:
    """컨테이너 root 기준 상대 경로 → SHA-256."""
    if not re.fullmatch(r"/[\w./-]*", root):
        raise StackCheckError(f"컨테이너 경로가 이상합니다: {root}")
    try:
        r = run(["docker", "exec", container, "sh", "-c", LIST_CMD.format(root=root)], capture_output=True, text=True,
                timeout=300, check=True)
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
        c.modules |= {PurePosixPath(p).parts[0] for p in want}
        tracked_under = _tracked_under(commit, tops, run)
        c.missing += len(tracked_under - set(got))
    return c


def check_mounts(c: StackCheck, mounts: list[dict[str, str]], run=subprocess.run) -> StackCheck:
    """호스트 작업 트리를 마운트한 컨테이너 경로(예: litellm /cfg ← gateway/litellm)를 stackCommit과 견줍니다.
    mounts: [{container, path, repo}]. 마운트 안 파일은 모두 그 커밋의 repo 경로에 있어야 합니다."""
    for m in mounts:
        got = {f"{m['repo'].rstrip('/')}/{p}": h for p, h in container_hashes(m["container"], run, m["path"]).items()}
        want = git_hashes(c.commit, set(got), run)
        c.compared += len(want)
        c.mismatched += sorted(f"{m['container']}:{p}" for p, h in want.items() if got[p] != h)
        c.mismatched += sorted(f"{m['container']}:{p}(커밋에 없음)" for p in set(got) - set(want))
        c.mounts.append(f"{m['container']}:{m['path']} = {m['repo']}({len(want)}개)")
    return c


def container_env(container: str, names: list[str], run=subprocess.run) -> dict[str, str]:
    """컨테이너 환경 변수 중 names의 값(없으면 빈 문자열). 비밀일 수 있는 이름은 받지 않습니다."""
    bad = [n for n in names if any(w in n.upper() for w in SECRET_WORDS) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", n)]
    if bad:
        raise StackCheckError(f"기록하지 않는 환경 변수 이름: {', '.join(bad)}")
    script = "; ".join(f'printf "%s=%s\\n" {n} "${n}"' for n in names)
    try:
        r = run(["docker", "exec", container, "sh", "-c", script], capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise StackCheckError(f"{container}의 환경 변수를 읽지 못했습니다: {e}") from e
    out = {n: "" for n in names}
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        if k in out:
            out[k] = v
    return out


def _tracked_under(commit: str, tops: set[str], run=subprocess.run) -> set[str]:
    if not tops:
        return set()
    r = run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", commit, "--", *sorted(tops)],
            capture_output=True, text=True, check=True)
    return set(r.stdout.splitlines())
