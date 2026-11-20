#!/usr/bin/env bash
# 세션 동시 실행 메모리를 잽니다(docs/measurements/0-memory.md).
# 재는 것: 시스템 메모리(vm_stat), Claude Code 세션 프로세스 RSS, Ollama 모델 상주 크기와
# 동시 요청 N개 중 최대 사용량, Docker VM 컨테이너 사용량.
# 사용: bash scripts/measure-memory.sh [동시 요청 수=5] [모델=qwen3.5:9b]
set -euo pipefail
N=${1:-5}; MODEL=${2:-qwen3.5:9b}
page=$(sysctl -n hw.pagesize)
mem_used_gb() {
  vm_stat | awk -v p="$page" '/Pages active/{a=$3}/Pages wired down/{w=$4}/occupied by compressor/{c=$5}
    END{gsub("\\.","",a);gsub("\\.","",w);gsub("\\.","",c); printf "%.1f", (a+w+c)*p/1024/1024/1024}'
}
rss_gb() { ps -axo rss=,command= | awk -v pat="$1" '$0 ~ pat {s+=$1; n++} END{printf "%.2f %d", s/1024/1024, n}'; }

echo "기기: $(sysctl -n machdep.cpu.brand_string), 메모리 $(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))GB"
echo "시각: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "모델 내리기 전 사용: $(mem_used_gb)GB"
read -r crss cn <<<"$(rss_gb '[c]laude')"
echo "Claude Code 프로세스: ${cn}개, RSS 합 ${crss}GB"

curl -s localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"keep_alive\":0}" >/dev/null || true
sleep 3
base=$(mem_used_gb)
echo "모델 없음 기준: ${base}GB"

curl -s localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"안녕\",\"stream\":false,\"keep_alive\":\"10m\",\"options\":{\"num_predict\":8}}" >/dev/null
echo "모델 1회 적재 뒤: $(mem_used_gb)GB"
ollama ps | sed 's/^/  /'

peak=0
prompt='사내 휴가 규정에서 반차 사용 조건을 세 문장으로 설명해 주세요.'
start=$(date +%s)
for i in $(seq 1 "$N"); do
  curl -s localhost:11434/api/generate -d "{\"model\":\"$MODEL\",\"prompt\":\"$prompt\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":256}}" \
    -o "/tmp/iaa-mem-$i.json" &
done
while jobs -r | grep -q .; do
  m=$(mem_used_gb); awk -v m="$m" -v p="$peak" 'BEGIN{exit !(m>p)}' && peak=$m
  sleep 1
done
wait
echo "동시 요청 ${N}개: $(( $(date +%s) - start ))초, 최대 사용 ${peak}GB"
for i in $(seq 1 "$N"); do python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(f'  요청 {sys.argv[2]}: 출력 {d.get(\"eval_count\")}토큰, {d.get(\"eval_count\",0)/max(d.get(\"eval_duration\",1),1)*1e9:.1f} tok/s')" "/tmp/iaa-mem-$i.json" "$i"; done
echo "Docker 컨테이너:"
docker stats --no-stream --format '  {{.Name}} {{.MemUsage}}' 2>/dev/null || echo "  (Docker 꺼짐)"
