#!/usr/bin/env bash
# GPU 사용권. GPU마다 사용권 파일 하나를 두고, 비었거나 만료됐을 때만 가져갑니다.
#   bash scripts/gpu-lease.sh status
#   bash scripts/gpu-lease.sh take <gpu> <모듈> <분> <목적>   # 성공 0, 사용 중이면 1
#   bash scripts/gpu-lease.sh extend <gpu> <모듈> <분>
#   bash scripts/gpu-lease.sh release <gpu> <모듈>
# gpu: desktop(이 PC의 Ollama), colab(코랩 T4 터널). 파일 위치는 GPU_LEASE_DIR(기본 ~/.local/share/inhouse-ai/gpu).
set -euo pipefail
DIR=${GPU_LEASE_DIR:-$HOME/.local/share/inhouse-ai/gpu}
mkdir -p "$DIR"
GPUS=(desktop colab)
now() { date +%s; }

valid_gpu() {
  local g
  for g in "${GPUS[@]}"; do [[ $1 == "$g" ]] && return 0; done
  echo "알 수 없는 GPU: $1 (${GPUS[*]})" >&2; exit 2
}

# 사용권 파일 형식: <모듈>\t<만료 epoch>\t<가져간 시각>\t<목적>
read_lease() { [[ -s $DIR/$1.lease ]] && cat "$DIR/$1.lease" || true; }

holder_of() {
  local line; line=$(read_lease "$1")
  [[ -z $line ]] && return 0
  local who exp; IFS=$'\t' read -r who exp _ <<<"$line"
  (( exp > $(now) )) && echo "$who"
  return 0
}

with_lock() { local g=$1; shift; exec 9>"$DIR/$g.lock"; flock -w 10 9; "$@"; }

do_take() {
  local g=$1 who=$2 min=$3 why=$4 cur
  cur=$(holder_of "$g")
  if [[ -n $cur && $cur != "$who" ]]; then echo "사용 중: $(read_lease "$g")"; return 1; fi
  printf '%s\t%s\t%s\t%s\n' "$who" $(( $(now) + min * 60 )) "$(date '+%F %T')" "$why" > "$DIR/$g.lease"
  echo "가져감: $g → $who (${min}분)"
}

do_extend() {
  local g=$1 who=$2 min=$3 cur why
  cur=$(holder_of "$g")
  if [[ $cur != "$who" ]]; then echo "가진 사람이 아닙니다: $(read_lease "$g")"; return 1; fi
  why=$(read_lease "$g" | cut -f4)
  printf '%s\t%s\t%s\t%s\n' "$who" $(( $(now) + min * 60 )) "$(date '+%F %T')" "$why" > "$DIR/$g.lease"
  echo "늘림: $g → $who (${min}분)"
}

do_release() {
  local g=$1 who=$2 cur
  cur=$(holder_of "$g")
  if [[ -n $cur && $cur != "$who" ]]; then echo "가진 사람이 아닙니다: $(read_lease "$g")"; return 1; fi
  : > "$DIR/$g.lease"; echo "반납: $g"
}

case ${1:-status} in
  status)
    for g in "${GPUS[@]}"; do
      line=$(read_lease "$g"); who=$(holder_of "$g")
      if [[ -n $who ]]; then
        IFS=$'\t' read -r _ exp since why <<<"$line"
        echo "$g: $who 사용 중(시작 $since, 남은 $(( (exp - $(now)) / 60 ))분) $why"
      else echo "$g: 비어 있음"; fi
    done ;;
  take) [[ $# -eq 5 ]] || { echo "take <gpu> <모듈> <분> <목적>" >&2; exit 2; }; valid_gpu "$2"; with_lock "$2" do_take "$2" "$3" "$4" "$5" ;;
  extend) [[ $# -eq 4 ]] || { echo "extend <gpu> <모듈> <분>" >&2; exit 2; }; valid_gpu "$2"; with_lock "$2" do_extend "$2" "$3" "$4" ;;
  release) [[ $# -eq 3 ]] || { echo "release <gpu> <모듈>" >&2; exit 2; }; valid_gpu "$2"; with_lock "$2" do_release "$2" "$3" ;;
  *) echo "status | take | extend | release" >&2; exit 2 ;;
esac
