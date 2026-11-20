#!/usr/bin/env bash
# 커밋 작성자 이메일이 GitHub noreply 주소인지 확인합니다(docs/conventions.md 7절).
# 설치: ln -sf ../../scripts/check-author.sh .git/hooks/pre-commit
set -euo pipefail
email=$(git config user.email || true)
case "$email" in
  *@users.noreply.github.com) exit 0 ;;
  *) echo "커밋 작성자 이메일이 noreply 주소가 아닙니다: '$email'" >&2
     echo "git config user.email \"180478650+keonhapark@users.noreply.github.com\"" >&2
     exit 1 ;;
esac
