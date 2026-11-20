#!/usr/bin/env bash
# erp 모듈 시험(Gradle + JUnit + Testcontainers)이 쓰는 메모리를 잽니다.
# 재는 것: 1초마다 gradlew 아래 프로세스 트리(Gradle·시험 JVM) RSS 합의 최댓값,
#         시험 중 PostgreSQL 컨테이너(postgres 이미지) 메모리 최댓값.
# 사용(erp/에서): bash scripts/measure-test-memory.sh
set -euo pipefail
cd "$(dirname "$0")/.."
tree_rss() {  # $1 아래 모든 자손 프로세스 RSS 합(KB)
  ps -axo pid=,ppid=,rss= | awk -v root="$1" '{p[$1]=$2; r[$1]=$3} END{
    for (x in p) { y=x; while (y in p && y!=root && y>1) y=p[y]; if (y==root) s+=r[x] } print s+0 }'
}
./gradlew --no-daemon -q cleanTest test > build/measure-test.log 2>&1 &
pid=$!
peak_java=0; peak_pg=0; start=$(date +%s)
while kill -0 "$pid" 2>/dev/null; do
  j=$(tree_rss "$pid")
  if (( j > peak_java )); then peak_java=$j; fi
  ids=$(docker ps -q --filter ancestor=postgres:16-alpine 2>/dev/null || true)
  pg=""
  [ -n "$ids" ] && pg=$(docker stats --no-stream --format '{{.MemUsage}}' $ids 2>/dev/null | awk '{print $1}' | head -1 || true)
  if [ -n "$pg" ]; then
    mb=$(echo "$pg" | awk '{v=$1; if (v ~ /GiB/) {sub("GiB","",v); v*=1024} else if (v ~ /MiB/) {sub("MiB","",v)} else if (v ~ /kB/) {sub("kB","",v); v/=1024}; printf "%d", v}')
    if (( mb > peak_pg )); then peak_pg=$mb; fi
  fi
  sleep 1
done
code=0; wait "$pid" || code=$?
echo "시각: $(date '+%Y-%m-%d %H:%M %Z'), 기기: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
echo "걸린 시간: $(( $(date +%s) - start ))초, 종료 코드: $code"
echo "Gradle·시험 JVM RSS 합 최댓값: $(( peak_java / 1024 ))MB"
echo "PostgreSQL 컨테이너 최댓값: ${peak_pg}MB"
