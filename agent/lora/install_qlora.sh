#!/usr/bin/env bash
# QLoRA 학습 환경(#545)을 저장소 밖에 준비합니다. agent 의존성(uv.lock)에는 넣지 않습니다(torch·CUDA가 무겁고 운영 경로가 아님).
#
# - 가상환경: 기본 ~/.cache/iaa-qlora-venv. torch는 CUDA 판(QLORA_TORCH_BACKEND, 기본 auto)
# - llama.cpp: 어댑터를 GGUF로 바꾸는 convert_lora_to_gguf.py만 씁니다(빌드하지 않음). 기본 ~/.cache/iaa-llama.cpp
# - 받은 판 번호와 llama.cpp 커밋은 가상환경 안 install.json에 남깁니다
#
#   bash lora/install_qlora.sh            # 준비
#   bash lora/install_qlora.sh --dry-run  # 할 일만 출력
set -euo pipefail

VENV="${QLORA_VENV:-$HOME/.cache/iaa-qlora-venv}"
LLAMA="${QLORA_LLAMA_CPP:-$HOME/.cache/iaa-llama.cpp}"
LLAMA_REF="${QLORA_LLAMA_CPP_REF:-master}"
BACKEND="${QLORA_TORCH_BACKEND:-auto}"
# 2026-11-22 기준 PyPI 판(나온 지 몇 주 지난 것)
PKGS=("torch==2.14.1" "transformers==5.22.2" "peft==0.21.2" "bitsandbytes==0.50.2" "accelerate==1.15.0"
      "gguf==0.19.0" "sentencepiece" "safetensors")
cd "$(dirname "$0")/.."                           # agent/

echo "환경 $VENV(torch $BACKEND), llama.cpp $LLAMA($LLAMA_REF), 패키지 ${PKGS[*]}"
if [[ "${1:-}" == "--dry-run" ]]; then
  echo "dry-run: 가상환경을 만들고 패키지와 agent(편집 설치)를 넣은 뒤 llama.cpp를 받아 $VENV/install.json에 판을 적습니다"
  exit 0
fi

[[ -x "$VENV/bin/python" ]] || uv venv -q --python 3.12 "$VENV"
uv pip install -q --python "$VENV/bin/python" --torch-backend "$BACKEND" "${PKGS[@]}" -e .
if [[ ! -d "$LLAMA/.git" ]]; then
  git clone -q --filter=blob:none https://github.com/ggml-org/llama.cpp "$LLAMA"
fi
git -C "$LLAMA" fetch -q origin "$LLAMA_REF" && git -C "$LLAMA" checkout -q FETCH_HEAD
"$VENV/bin/python" - "$VENV/install.json" "$(git -C "$LLAMA" rev-parse HEAD)" <<'PY'
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version

out, llama = sys.argv[1:3]
pkgs = ["torch", "transformers", "peft", "bitsandbytes", "accelerate", "gguf"]
info = {"installedAt": datetime.now(timezone.utc).isoformat(), "versions": {p: version(p) for p in pkgs},
        "llamaCppCommit": llama}
try:
    import torch
    info["cuda"] = torch.version.cuda
    info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
except Exception as e:  # noqa: BLE001
    info["torchError"] = repr(e)
open(out, "w").write(json.dumps(info, indent=1) + "\n")
print(json.dumps(info))
PY
