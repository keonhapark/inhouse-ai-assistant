"""업종을 모르는 코어(erp/, gateway/, agent/, rag/)에 팩에만 있어야 할 말이 있는지 찾습니다.

찾는 말: 모든 팩의 회사 이름, 본부·팀 이름(org.yaml units.name), 하이픈이 든 조직 ID, 에이전트 이름.
시험 폴더(test, tests, src/test)는 보지 않습니다. 시험 데이터는 팩에서 읽습니다.
실행(contracts/에서): uv run python -m tools.check_core_terms
"""

from __future__ import annotations

import re
import sys

from tools.common import PACKS, ROOT, load

CORE = ["erp", "gateway", "agent", "rag"]
SKIP_DIRS = {"test", "tests", "node_modules", ".venv", "build", ".gradle", "__pycache__", "dist"}
EXTS = {".py", ".java", ".kt", ".ts", ".tsx", ".js", ".yaml", ".yml", ".json", ".properties", ".sql", ".md", ".toml"}


def terms() -> set[str]:
    out: set[str] = set()
    for pack in PACKS.iterdir():
        if not (pack / "pack.yaml").exists():
            continue
        out.add(load(pack / "pack.yaml")["company"]["name"])
        org = load(pack / "org.yaml")
        for u in org["units"]:
            out.add(u["name"])
            if "-" in u["id"]:
                out.add(u["id"])
        for a in load(pack / "agents.yaml")["agents"]:
            if len(a["name"]) >= 3:
                out.add(a["name"])
    return out


def main() -> int:
    found = []
    words = sorted(terms(), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(w) for w in words))
    for mod in CORE:
        base = ROOT / mod
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in EXTS:
                continue
            if SKIP_DIRS & set(f.relative_to(base).parts):
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                m = pattern.search(line)
                if m:
                    found.append(f"{f.relative_to(ROOT)}:{n}: '{m.group(0)}'")
    for x in found:
        print(x)
    print(f"코어 업종 용어 검사: 찾은 것 {len(found)}개(용어 {len(words)}개)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
