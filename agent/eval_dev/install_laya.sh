#!/usr/bin/env bash
# Laya(convaiinnovations/laya-multilingual, Apache-2.0)를 라우터 비교(#303)용으로 준비합니다.
#
# agent 의존성(uv.lock)에는 넣지 않습니다. torch가 함께 깔려 무겁고 운영 경로가 아니기 때문입니다.
# 저장소 밖에 따로 가상환경을 만들고(기본 ~/.cache/iaa-laya-venv) laya와 agent 패키지(편집 설치)를 넣습니다.
# GPU는 평가 측정이 쓰므로 기본은 torch CPU 판입니다(LAYA_TORCH_BACKEND로 바꿈).
# 모델 가중치는 Hugging Face 캐시(HF_HOME)에 받고, 리비전을 eval_dev/runs/laya-install.json에 남깁니다.
#
#   bash eval_dev/install_laya.sh            # 준비
#   bash eval_dev/install_laya.sh --dry-run  # 할 일만 출력
#   CUDA_VISIBLE_DEVICES= ~/.cache/iaa-laya-venv/bin/python eval_dev/router_compare.py --methods laya ...
set -euo pipefail

LAYA_VERSION="${LAYA_VERSION:-0.5.0}"            # PyPI laya, 2026-11-19 배포(Apache-2.0)
MODEL_ID="${LAYA_MODEL_ID:-convaiinnovations/laya-multilingual}"
VENV="${LAYA_VENV:-$HOME/.cache/iaa-laya-venv}"
BACKEND="${LAYA_TORCH_BACKEND:-cpu}"
cd "$(dirname "$0")/.."                           # agent/
OUT=eval_dev/runs/laya-install.json

echo "laya==$LAYA_VERSION, torch $BACKEND, 환경 $VENV, 모델 $MODEL_ID, 캐시 ${HF_HOME:-~/.cache/huggingface}"
if [[ "${1:-}" == "--dry-run" ]]; then
  echo "dry-run: 환경을 만들고 laya·agent를 넣은 뒤 가중치를 받고 $OUT 에 리비전을 적습니다"
  exit 0
fi

[[ -x "$VENV/bin/python" ]] || uv venv -q --python 3.12 "$VENV"
uv pip install -q --python "$VENV/bin/python" --torch-backend "$BACKEND" "laya==$LAYA_VERSION" -e .
mkdir -p eval_dev/runs
CUDA_VISIBLE_DEVICES="" USE_TF=0 "$VENV/bin/python" - "$MODEL_ID" "$LAYA_VERSION" "$OUT" <<'PY'
import json
import sys
from datetime import datetime, timezone

import torch
from huggingface_hub import HfApi, snapshot_download

model_id, version, out = sys.argv[1:4]
info = HfApi().model_info(model_id)
snapshot_download(model_id, revision=info.sha)
# 로컬 경로는 남기지 않습니다(개인 경로가 커밋되지 않게).
record = {"package": f"laya=={version}", "torch": torch.__version__, "model": model_id, "revision": info.sha,
          "license": (info.card_data or {}).get("license") if info.card_data else None,
          "downloadedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
with open(out, "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=1)
    f.write("\n")
print(json.dumps(record, ensure_ascii=False))
PY
