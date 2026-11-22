"""PR이 브랜치 담당 경로 밖을 고쳤는지 봅니다(docs/workflow.md 담당 경로 표).

사용: python3 scripts/ci/check_paths.py <브랜치 이름> <바뀐 파일 목록 파일>
- feat|fix|test|refactor|perf/<모듈>-<주제>: <모듈>/ 안과 공용 허용 파일만
- contract/*, pack/*, chore/*, docs/*, ci/*, release/*, hotfix/*, develop(릴리즈 PR): 프로젝트 리드(S0) 브랜치라 검사하지 않음
"""

from __future__ import annotations

import re
import sys

MODULE_PATHS = {
    "erp": ["erp/"],
    "gateway": ["gateway/"],
    "agent": ["agent/"],
    "rag": ["rag/"],
    "eval": ["eval/"],
    "web": ["web/"],
    "incident": ["incident/"],
    "slack": ["channels/slack/"],
    "ux": ["ux/"],
}
# 모듈 세션도 고칠 수 있는 공용 파일
SHARED_OK = ["docs/contract-requests.md"]
LEAD_PREFIXES = ("contract/", "pack/", "chore/", "docs/", "ci/", "release/", "hotfix/", "develop")


def main() -> int:
    branch, files_path = sys.argv[1], sys.argv[2]
    files = [x.strip() for x in open(files_path, encoding="utf-8") if x.strip()]
    if branch.startswith(LEAD_PREFIXES):
        print(f"{branch}: 프로젝트 리드 브랜치라 담당 경로 검사를 건너뜁니다")
        return 0
    m = re.match(r"^(feat|fix|test|refactor|perf)/([a-z]+)-[a-z0-9-]+$", branch)
    if not m or m.group(2) not in MODULE_PATHS:
        print(f"브랜치 이름이 규칙에 맞지 않습니다: {branch} (docs/conventions.md 2절)")
        return 1
    allowed = MODULE_PATHS[m.group(2)]
    bad = [f for f in files if not any(f.startswith(p) for p in allowed) and f not in SHARED_OK]
    for f in bad:
        print(f"담당 경로 밖 변경: {f} (브랜치 {branch}, 허용 {', '.join(allowed + SHARED_OK)})")
    print(f"바뀐 파일 {len(files)}개, 담당 경로 밖 {len(bad)}개")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
