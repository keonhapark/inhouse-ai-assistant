"""새 팩을 더할 때 코어(erp·gateway·agent·rag) 변경 줄 수를 셉니다(#461, docs/design/stage3-and-packs.md 2절).

팩 폴더(`packs/<팩>`)를 바꾼 커밋을 그 팩의 PR 범위로 보고(squash 병합이라 커밋 하나가 PR 하나), 각 커밋에서 코어
경로의 더한 줄·뺀 줄을 셉니다. 코어 경로 안의 시험(`tests/`)은 따로 세고, 코어 폴더 안의 팩 내용(rag 문서 템플릿)은
팩으로 셉니다. 팩 폴더를 건드리지 않았지만 그 팩을
위해 들어간 코어 변경(예: gateway 출구 정책)은 `--extra`로 커밋을 더합니다.

    uv run python tools/core_lines.py --pack finance [--pack it-services] [--ref origin/develop] [--extra <커밋>...]

출력은 Markdown 표입니다. 목표는 코어 코드 0줄이고, 0이 아니면 바뀐 파일을 적어 이유를 붙일 수 있게 합니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ("erp", "gateway", "agent", "rag")
# 코어 폴더 안에 있지만 팩 내용인 곳: rag 문서 템플릿(팩 docs.yaml의 문서 본문 생성기 입력)
PACK_CONTENT_IN_CORE = ("rag/templates/",)


@dataclass
class CommitLines:
    sha: str
    subject: str
    core_code: dict[str, int] = field(default_factory=dict)  # 모듈 → 더한 줄 + 뺀 줄
    core_tests: dict[str, int] = field(default_factory=dict)
    pack: int = 0
    other: int = 0
    core_files: list[str] = field(default_factory=list)

    @property
    def core_code_total(self) -> int:
        return sum(self.core_code.values())


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def pack_commits(pack: str, ref: str, cwd: Path = ROOT) -> list[str]:
    """ref까지의 이력에서 packs/<pack>을 바꾼 커밋(오래된 것부터)."""
    out = git("log", "--format=%H", "--reverse", ref, "--", f"packs/{pack}", cwd=cwd)
    return [x for x in out.splitlines() if x]


def classify(path: str) -> tuple[str, str | None]:
    """경로 → (구분, 코어 모듈). 구분은 core_code, core_tests, pack, other."""
    top, _, rest = path.partition("/")
    if path.startswith(PACK_CONTENT_IN_CORE):
        return "pack", None
    if top in CORE:
        return ("core_tests" if "/tests/" in f"/{rest}" or rest.startswith("tests/") else "core_code"), top
    if top == "packs":
        return "pack", None
    return "other", None


def count_commit(sha: str, cwd: Path = ROOT) -> CommitLines:
    subject = git("show", "-s", "--format=%s", sha, cwd=cwd).strip()
    c = CommitLines(sha=sha, subject=subject)
    for line in git("show", "--numstat", "--format=", sha, cwd=cwd).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        n = (0 if added == "-" else int(added)) + (0 if deleted == "-" else int(deleted))  # 바이너리는 0
        kind, module = classify(path)
        if kind == "core_code":
            c.core_code[module] = c.core_code.get(module, 0) + n
            c.core_files.append(path)
        elif kind == "core_tests":
            c.core_tests[module] = c.core_tests.get(module, 0) + n
        elif kind == "pack":
            c.pack += n
        else:
            c.other += n
    return c


def render(packs: list[str], rows: list[CommitLines], ref: str) -> str:
    out = [f"# 팩 추가 때 코어 변경 줄 수({', '.join(packs)})", "",
           f"기준 이력 `{ref}`. 줄 수는 더한 줄 + 뺀 줄입니다. 코어는 {'·'.join(CORE)}이고, 코어 안 `tests/`는 따로 세며 rag 문서 템플릿(`rag/templates/`)은 팩으로 셉니다.", "",
           "| 커밋 | 제목 | 코어 코드 | 코어 시험 | 팩 | 그 밖 |", "|---|---|---|---|---|---|"]
    for r in rows:
        code = ", ".join(f"{m} {n}" for m, n in sorted(r.core_code.items())) or "0"
        tests = ", ".join(f"{m} {n}" for m, n in sorted(r.core_tests.items())) or "0"
        out.append(f"| `{r.sha[:7]}` | {r.subject.replace('|', '/')} | {code} | {tests} | {r.pack} | {r.other} |")
    total = sum(r.core_code_total for r in rows)
    out += ["", f"- 코어 코드 합계: {total}줄(목표 0)",
            f"- 코어 시험 합계: {sum(sum(r.core_tests.values()) for r in rows)}줄"]
    files = sorted({f for r in rows for f in r.core_files})
    if files:
        out += ["", "코어 코드를 바꾼 파일(이유를 적습니다):", "", *[f"- `{f}`" for f in files]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", action="append", required=True, help="packs/ 아래 팩 이름(여러 번)")
    ap.add_argument("--ref", default="origin/develop")
    ap.add_argument("--extra", action="append", default=[], help="팩 폴더를 건드리지 않은 관련 코어 커밋")
    args = ap.parse_args(argv)
    shas: list[str] = []
    for p in args.pack:
        shas += [s for s in pack_commits(p, args.ref) if s not in shas]
    shas += [git("rev-parse", s).strip() for s in args.extra if git("rev-parse", s).strip() not in shas]
    if not shas:
        raise SystemExit(f"{args.ref}에 packs/{'·'.join(args.pack)}를 바꾼 커밋이 없습니다")
    sys.stdout.write(render(args.pack, [count_commit(s) for s in shas], args.ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
