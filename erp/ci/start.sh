#!/usr/bin/env bash
# erp를 띄우고 건강해질 때까지 기다립니다(docs/workflow.md 6절). CI의 행동 계약 시험이 씁니다.
# PostgreSQL은 도커 컨테이너로 띄우고, erp는 bootJar로 실행합니다.
# 환경 변수: ERP_PORT(기본 8040), ERP_PG_PORT(기본 55432), PACK_DIR(기본 packs/manufacturing),
#           ERP_JWT_SECRET, ERP_DEMO_PASSWORD, DELEGATION_TOKEN_PUBLIC_KEY, ERP_SERVICE_LOGIN_SECRET
# 끄기: bash erp/ci/stop.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
ERP_PORT=${ERP_PORT:-8040}
ERP_PG_PORT=${ERP_PG_PORT:-55432}
name="iaa-erp-pg-${ERP_PORT}"
pg_password="$(openssl rand -hex 12)"

docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d --name "$name" -e POSTGRES_DB=erp -e POSTGRES_USER=iaa -e POSTGRES_PASSWORD="$pg_password" \
  -p "127.0.0.1:${ERP_PG_PORT}:5432" postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  docker exec "$name" pg_isready -U iaa -d erp >/dev/null 2>&1 && break
  sleep 1
done

(cd "$root/erp" && ./gradlew --no-daemon -q bootJar -x test)
jar="$(ls "$root"/erp/build/libs/erp-*.jar | head -1)"

export PORT="$ERP_PORT"
export SPRING_DATASOURCE_URL="jdbc:postgresql://127.0.0.1:${ERP_PG_PORT}/erp"
export SPRING_DATASOURCE_USERNAME=iaa
export SPRING_DATASOURCE_PASSWORD="$pg_password"
export PACK_DIR="${PACK_DIR:-$root/packs/manufacturing}"
# 행동 계약 시험의 서비스 로그인 비밀값(contracts/tests/conftest.py 기본값과 같음). 시험 전용 값입니다.
export ERP_SERVICE_LOGIN_SECRET="${ERP_SERVICE_LOGIN_SECRET:-test-only-service-login-secret}"
log="$root/erp/build/erp-${ERP_PORT}.log"
nohup java -jar "$jar" > "$log" 2>&1 &
echo $! > "$root/erp/build/erp-${ERP_PORT}.pid"

for _ in $(seq 1 120); do
  if curl -fsS "http://localhost:${ERP_PORT}/api/v1/health" >/dev/null 2>&1; then
    echo "erp가 ${ERP_PORT}에서 떴습니다(로그 $log)"
    exit 0
  fi
  if ! kill -0 "$(cat "$root/erp/build/erp-${ERP_PORT}.pid")" 2>/dev/null; then
    echo "erp가 시작 중에 끝났습니다" >&2
    tail -50 "$log" >&2
    exit 1
  fi
  sleep 1
done
echo "erp가 120초 안에 건강해지지 않았습니다" >&2
tail -50 "$log" >&2
exit 1
