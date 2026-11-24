#!/usr/bin/env bash
# QLoRA 학습 환경(#545, #551)을 저장소 밖에 준비합니다. agent 의존성(uv.lock)에는 넣지 않습니다(torch·CUDA가 무겁고 운영 경로가 아님).
#
# - 기본: 가상환경 ~/.cache/iaa-qlora-venv에 torch(CUDA 판, QLORA_TORCH_BACKEND 기본 auto)와 학습 패키지, agent(편집 설치)
# - QLORA_SYSTEM=1(Kaggle 등): 새 가상환경 없이 지금 파이썬(QLORA_PYTHON, 기본 python3)에 학습 패키지만 넣습니다.
#   이미 깔린 torch를 그대로 쓰고 agent는 넣지 않습니다(데이터 생성은 agent 폴더에서 uv run으로)
# - llama.cpp: 어댑터를 GGUF로 바꾸는 convert_lora_to_gguf.py와 그 체크아웃의 gguf-py만 씁니다(빌드하지 않음).
#   PyPI gguf는 변환 스크립트보다 늦을 수 있어 같은 커밋의 gguf-py를 넣습니다. 기본 ~/.cache/iaa-llama.cpp
# - 받은 판 번호와 llama.cpp 커밋을 install.json(가상환경 안, 시스템 모드는 llama.cpp 폴더 안)에 남깁니다
#
#   bash lora/install_qlora.sh            # 준비
#   bash lora/install_qlora.sh --dry-run  # 할 일만 출력
set -euo pipefail

VENV="${QLORA_VENV:-$HOME/.cache/iaa-qlora-venv}"
LLAMA="${QLORA_LLAMA_CPP:-$HOME/.cache/iaa-llama.cpp}"
LLAMA_REF="${QLORA_LLAMA_CPP_REF:-master}"
BACKEND="${QLORA_TORCH_BACKEND:-auto}"
SYSTEM="${QLORA_SYSTEM:-}"
# 2026-11-22 기준 PyPI 판(나온 지 몇 주 지난 것). flash-linear-attention(#618)은 Qwen3.5의 Gated DeltaNet 층(32층 중 24층)
# 학습 커널입니다. 없으면 transformers가 파이썬 반복문 대체 구현을 써서 느립니다. 요구 패키지는 einops뿐이라 torch를 바꾸지 않습니다
TORCH="torch==2.14.1"
PKGS=("transformers==5.22.2" "peft==0.21.2" "bitsandbytes==0.50.2" "accelerate==1.15.0" "flash-linear-attention==0.6.0"
      "sentencepiece" "safetensors" "httpx" "huggingface_hub")
cd "$(dirname "$0")/.."                           # agent/

if [[ -n "$SYSTEM" ]]; then
  PY="${QLORA_PYTHON:-python3}"
  echo "시스템 파이썬 $PY(torch 그대로), llama.cpp $LLAMA($LLAMA_REF), 패키지 ${PKGS[*]}"
else
  PY="$VENV/bin/python"
  echo "환경 $VENV($TORCH, $BACKEND), llama.cpp $LLAMA($LLAMA_REF), 패키지 ${PKGS[*]}"
fi
if [[ "${1:-}" == "--dry-run" ]]; then
  echo "dry-run: llama.cpp를 받고 패키지와 gguf-py를 넣은 뒤 install.json에 판을 적습니다"
  exit 0
fi

if [[ ! -d "$LLAMA/.git" ]]; then
  git clone -q --filter=blob:none https://github.com/ggml-org/llama.cpp "$LLAMA"
fi
git -C "$LLAMA" fetch -q origin "$LLAMA_REF" && git -C "$LLAMA" checkout -q FETCH_HEAD

if [[ -n "$SYSTEM" ]]; then
  "$PY" -m pip install -q "${PKGS[@]}" -e "$LLAMA/gguf-py"
  OUT="$LLAMA/install.json"
else
  [[ -x "$PY" ]] || uv venv -q --python 3.12 "$VENV"
  uv pip install -q --python "$PY" --torch-backend "$BACKEND" "$TORCH" "${PKGS[@]}" -e "$LLAMA/gguf-py" -e .
  OUT="$VENV/install.json"
fi
"$PY" - "$OUT" "$(git -C "$LLAMA" rev-parse HEAD)" <<'PY'
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version

out, llama = sys.argv[1:3]
pkgs = ["torch", "transformers", "peft", "bitsandbytes", "accelerate", "flash-linear-attention", "gguf"]
info = {"installedAt": datetime.now(timezone.utc).isoformat(), "python": sys.version.split()[0],
        "versions": {p: version(p) for p in pkgs}, "llamaCppCommit": llama}
try:
    import torch
    info["cuda"] = torch.version.cuda
    info["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
except Exception as e:  # noqa: BLE001
    info["torchError"] = repr(e)
open(out, "w").write(json.dumps(info, indent=1) + "\n")
print(json.dumps(info))
PY
