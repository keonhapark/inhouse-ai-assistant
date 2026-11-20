#!/usr/bin/env bash
# erp/ci/start.sh로 띄운 erp와 PostgreSQL을 끕니다.
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
ERP_PORT=${ERP_PORT:-8040}
pid_file="$root/erp/build/erp-${ERP_PORT}.pid"
[ -f "$pid_file" ] && kill "$(cat "$pid_file")" 2>/dev/null && rm -f "$pid_file"
docker rm -f "iaa-erp-pg-${ERP_PORT}" >/dev/null 2>&1 || true
echo "erp(${ERP_PORT})를 껐습니다"
