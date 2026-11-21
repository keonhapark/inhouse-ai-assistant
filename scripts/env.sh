#!/usr/bin/env bash
# 세션 번호로 포트와 compose 프로젝트 이름을 정합니다(docs/ports.md).
# 사용: source scripts/env.sh [세션 번호]   (생략하면 .env의 SESSION_NO, 없으면 0)
_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
if [ -f "$_root/.env" ]; then set -a; . "$_root/.env"; set +a; fi
SESSION_NO=${1:-${SESSION_NO:-0}}
PORT_BASE=$((8000 + 100 * SESSION_NO))
export SESSION_NO PORT_BASE
export COMPOSE_PROJECT_NAME="iaa-s${SESSION_NO}"
export PORT_WEB=$((PORT_BASE + 0))
export PORT_GATEWAY=$((PORT_BASE + 10))
export PORT_AGENT=$((PORT_BASE + 20))
export PORT_MCP=$((PORT_BASE + 21))
export PORT_RAG=$((PORT_BASE + 30))
export PORT_ERP=$((PORT_BASE + 40))
export PORT_FAKE_ERP=$((PORT_BASE + 41))
export PORT_LITELLM=$((PORT_BASE + 50))
export PORT_POSTGRES=$((PORT_BASE + 60))
export PORT_INCIDENT=$((PORT_BASE + 70))
echo "세션 S${SESSION_NO}: PORT_BASE=${PORT_BASE}, compose 프로젝트 ${COMPOSE_PROJECT_NAME}"
