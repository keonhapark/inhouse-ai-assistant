#!/usr/bin/env bash
# Laya(convaiinnovations/laya-multilingual, Apache-2.0)를 라우터 비교(#303)용으로 준비합니다.
#
# agent 의존성(uv.lock)에는 넣지 않습니다. torch가 함께 깔려 무겁고 운영 경로가 아니기 때문입니다.
# 비교를 돌릴 때는 uv의 임시 환경으로 얹습니다:
#   uv run --with "laya==$LAYA_VERSION" python eval_dev/router_compare.py --methods laya ...
#
# 이 스크립트는 패키지를 받아 두고, 모델 가중치를 Hugging Face 캐시에 내려받고(HF_HOME으로 위치 지정),
# 받은 모델의 리비전(커밋 해시)을 eval_dev/runs/laya-install.json에 남깁니다. GPU에 올리지는 않습니다.
#
#   bash eval_dev/install_laya.sh            # 받기
#   bash eval_dev/install_laya.sh --dry-run  # 할 일만 출력
set -euo pipefail

LAYA_VERSION="${LAYA_VERSION:-0.5.0}"           # PyPI laya, 2026-11-19 배포(Apache-2.0)
MODEL_ID="${LAYA_MODEL_ID:-convaiinnovations/laya-multilingual}"
cd "$(dirname "$0")/.."                          # agent/
OUT=eval_dev/runs/laya-install.json

echo "laya==$LAYA_VERSION, 모델 $MODEL_ID, 캐시 ${HF_HOME:-~/.cache/huggingface}"
if [[ "${1:-}" == "--dry-run" ]]; then
  echo "dry-run: uv run --with laya==$LAYA_VERSION 로 가중치를 받고 $OUT 에 리비전을 적습니다"
  exit 0
fi

mkdir -p eval_dev/runs
uv run --with "laya==$LAYA_VERSION" python - "$MODEL_ID" "$LAYA_VERSION" "$OUT" <<'PY'
import json
import sys
from datetime import datetime, timezone

from huggingface_hub import HfApi, snapshot_download

model_id, version, out = sys.argv[1:4]
info = HfApi().model_info(model_id)
snapshot_download(model_id, revision=info.sha)
# 로컬 경로는 남기지 않습니다(개인 경로가 커밋되지 않게).
record = {"package": f"laya=={version}", "model": model_id, "revision": info.sha,
          "license": (info.card_data or {}).get("license") if info.card_data else None,
          "downloadedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
with open(out, "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=1)
    f.write("\n")
print(json.dumps(record, ensure_ascii=False))
PY
