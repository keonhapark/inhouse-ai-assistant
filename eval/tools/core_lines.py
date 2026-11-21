"""새 팩을 더할 때 코어(erp·gateway·agent·rag) 변경 줄 수를 팩별로 셉니다(#461, #483, docs/design/stage3-and-packs.md 2절).

팩 하나의 범위는 두 가지 커밋입니다.
- 팩 폴더(`packs/<팩>`)를 바꾼 커밋(squash 병합이라 커밋 하나가 PR 하나)
- 팩 폴더는 건드리지 않았지만 그 팩을 위해 들어간 커밋: `core_lines.yaml`에 팩마다 커밋·PR·이유를 적습니다.
  찾는 방법은 `--suggest <팩>`입니다. 그 팩 PR들이 본문에서 건 이슈를 본문에 건 다른 병합 PR 중 코어를 바꾼 것을
  후보로 냅니다(gh 필요). 후보를 보고 고른 것만 설정에 적고, 처음 그 기능이 필요했던 팩에 넣습니다.

코어 안 `tests/`는 코어 시험, `*.md`는 코어 문서로 따로 셉니다. rag 문서 템플릿(`rag/templates/`)은 팩 내용입니다.

    uv run python tools/core_lines.py [--pack finance] [--ref origin/develop] [--config core_lines.yaml]
    uv run python tools/core_lines.py --suggest finance

출력은 팩별 Markdown 표와 넣은 관련 커밋·이유입니다. 목표는 코어 코드 0줄이고, 0이 아니면 이유를 적습니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).resolve().parents[1] / "core_lines.yaml"
CORE = ("erp", "gateway", "agent", "rag")
# 코어 폴더 안에 있지만 팩 내용인 곳: rag 문서 템플릿(팩 docs.yaml의 문서 본문 생성기 입력)
PACK_CONTENT_IN_CORE = ("rag/templates/",)


@dataclass
class CommitLines:
    sha: str
    subject: str
    core_code: dict[str, int] = field(default_factory=dict)  # 모듈 → 더한 줄 + 뺀 줄
    core_tests: dict[str, int] = field(default_factory=dict)
    core_docs: int = 0
    pack: int = 0
    other: int = 0
    core_files: list[str] = field(default_factory=list)

    @property
    def core_code_total(self) -> int:
        return sum(self.core_code.values())


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", "-C", str(cwd or ROOT), *args], capture_output=True, text=True, check=True).stdout


def pack_commits(pack: str, ref: str, cwd: Path | None = None) -> list[str]:
    """ref까지의 이력에서 packs/<pack>을 바꾼 커밋(오래된 것부터)."""
    out = git("log", "--format=%H", "--reverse", ref, "--", f"packs/{pack}", cwd=cwd)
    return [x for x in out.splitlines() if x]


def classify(path: str) -> tuple[str, str | None]:
    """경로 → (구분, 코어 모듈). 구분은 core_code, core_tests, core_docs, pack, other."""
    top, _, rest = path.partition("/")
    if path.startswith(PACK_CONTENT_IN_CORE):
        return "pack", None
    if top in CORE and path.endswith(".md"):
        return "core_docs", top
    if top in CORE:
        return ("core_tests" if "/tests/" in f"/{rest}" or rest.startswith("tests/") else "core_code"), top
    if top == "packs":
        return "pack", None
    return "other", None


def count_commit(sha: str, cwd: Path | None = None) -> CommitLines:
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
        elif kind == "core_docs":
            c.core_docs += n
        elif kind == "pack":
            c.pack += n
        else:
            c.other += n
    return c


def table(rows: list[CommitLines], reasons: dict[str, str]) -> list[str]:
    out = ["| 커밋 | 제목 | 범위 | 코어 코드 | 코어 시험 | 코어 문서 | 팩 | 그 밖 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        code = ", ".join(f"{m} {n}" for m, n in sorted(r.core_code.items())) or "0"
        tests = ", ".join(f"{m} {n}" for m, n in sorted(r.core_tests.items())) or "0"
        how = "관련 커밋" if r.sha in reasons else "팩 폴더"
        out.append(f"| `{r.sha[:7]}` | {r.subject.replace('|', '/')} | {how} | {code} | {tests} | {r.core_docs} | "
                   f"{r.pack} | {r.other} |")
    return out


def render_pack(pack: str, rows: list[CommitLines], reasons: dict[str, str]) -> str:
    total = sum(r.core_code_total for r in rows)
    out = [f"## {pack}", "", *table(rows, reasons), "",
           f"- 코어 코드 {total}줄(목표 0), 코어 시험 {sum(sum(r.core_tests.values()) for r in rows)}줄, "
           f"코어 문서 {sum(r.core_docs for r in rows)}줄"]
    if reasons:
        out += ["", "넣은 관련 커밋(팩 폴더 밖)과 이유:", ""]
        out += [f"- `{sha[:7]}`: {why}" for sha, why in reasons.items()]
    files = sorted({f for r in rows for f in r.core_files})
    if files:
        out += ["", "코어 코드를 바꾼 파일:", "", *[f"- `{f}`" for f in files]]
    return "\n".join(out) + "\n"


def render(ref: str, sections: list[tuple[str, list[CommitLines], dict[str, str]]]) -> str:
    out = ["# 팩 추가 때 코어 변경 줄 수", "",
           f"기준 이력 `{ref}`. 줄 수는 더한 줄 + 뺀 줄입니다. 코어는 {'·'.join(CORE)}이고, 코어 안 `tests/`는 코어 시험, "
           "`*.md`는 코어 문서로 따로 세며 rag 문서 템플릿(`rag/templates/`)은 팩으로 셉니다. 범위는 팩 폴더를 바꾼 커밋과 "
           "`eval/core_lines.yaml`에 이유와 함께 적은 관련 커밋입니다.", "",
           "| 팩 | 코어 코드 | 코어 시험 | 코어 문서 |", "|---|---|---|---|"]
    for pack, rows, _ in sections:
        out.append(f"| {pack} | {sum(r.core_code_total for r in rows)} | {sum(sum(r.core_tests.values()) for r in rows)} | "
                   f"{sum(r.core_docs for r in rows)} |")
    out.append("")
    for pack, rows, reasons in sections:
        out.append(render_pack(pack, rows, reasons))
    return "\n".join(out)


def load_config(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def resolve(ref_sha: str, ref: str) -> str:
    sha = git("rev-parse", ref_sha).strip()
    if subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", sha, ref], capture_output=True).returncode:
        raise SystemExit(f"{ref_sha}가 {ref} 이력에 없습니다(작업 브랜치 커밋이 아니라 병합된 커밋을 줍니다)")
    return sha


def pack_section(pack: str, ref: str, extras: list[dict[str, Any]]) -> tuple[str, list[CommitLines], dict[str, str]]:
    shas = pack_commits(pack, ref)
    reasons: dict[str, str] = {}
    for e in extras:
        sha = resolve(str(e["commit"]), ref)
        reasons[sha] = f"#{e['pr']} {e['reason']}" if e.get("pr") else str(e["reason"])
        if sha not in shas:
            shas.append(sha)
    if not shas:
        raise SystemExit(f"{ref}에 packs/{pack}를 바꾼 커밋이 없습니다")
    return pack, [count_commit(s) for s in shas], reasons


def gh_json(args: list[str], run=subprocess.run) -> Any:
    return json.loads(run(["gh", *args], capture_output=True, text=True, check=True).stdout)


def suggest(pack: str, ref: str, run=subprocess.run) -> list[dict[str, Any]]:
    """팩 PR들이 본문에서 건 이슈를 본문에 건 다른 병합 PR 중 코어 코드를 바꾸고 팩 폴더는 건드리지 않은 것."""
    import re

    pack_prs = set()
    for sha in pack_commits(pack, ref):
        m = re.search(r"\(#(\d+)\)\s*$", git("show", "-s", "--format=%s", sha))
        if m:
            pack_prs.add(int(m.group(1)))
    issues = set()
    for n in pack_prs:
        body = gh_json(["pr", "view", str(n), "--json", "body"], run)["body"] or ""
        issues |= {int(x) for x in re.findall(r"#(\d+)", body)}
    found: dict[int, dict[str, Any]] = {}
    for issue in sorted(issues - pack_prs):
        try:
            prs = gh_json(["pr", "list", "--state", "merged", "--search", f"#{issue} in:body", "--limit", "30",
                           "--json", "number,title,mergeCommit,files"], run)
        except subprocess.CalledProcessError as e:
            print(f"이슈 #{issue} 검색 실패, 건너뜀: {(e.stderr or '').strip()[:120]}", file=sys.stderr)
            continue
        for pr in prs:
            paths = [f["path"] for f in pr.get("files") or []]
            if pr["number"] in pack_prs or any(p.startswith(f"packs/{pack}/") for p in paths):
                continue
            if any(classify(p)[0] == "core_code" for p in paths):
                found.setdefault(pr["number"], {"pr": pr["number"], "title": pr["title"],
                                                "commit": (pr.get("mergeCommit") or {}).get("oid", "")[:7],
                                                "issues": []})["issues"].append(issue)
    return sorted(found.values(), key=lambda x: x["pr"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", action="append", help="packs/ 아래 팩 이름(여러 번). 없으면 설정의 팩 전부")
    ap.add_argument("--ref", default="origin/develop")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--suggest", metavar="PACK", help="그 팩의 관련 코어 PR 후보를 냅니다(gh 필요)")
    args = ap.parse_args(argv)
    if args.suggest:
        for c in suggest(args.suggest, args.ref):
            print(f"#{c['pr']} {c['commit']} {c['title']} (이슈 {', '.join(f'#{i}' for i in c['issues'])})")
        return 0
    config = load_config(args.config)
    packs = args.pack or list(config)
    sections = [pack_section(p, args.ref, (config.get(p) or {}).get("extra") or []) for p in packs]
    sys.stdout.write(render(args.ref, sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
