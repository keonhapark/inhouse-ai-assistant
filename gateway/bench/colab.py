"""측정 스크립트 공용: 측정 대상 Ollama 주소와 결과 저장.

주소는 작업 공간 `.env`의 `COLAB_OLLAMA_BASE_URL`(코랩 T4 터널) 또는 `--base-url`로 받습니다. 주소는 출력·기록하지 않습니다.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

GATEWAY = Path(__file__).resolve().parents[1]
REPO = GATEWAY.parent
RESULTS = Path(__file__).resolve().parent / "results"


def base_url(arg: str | None = None, env_key: str = "COLAB_OLLAMA_BASE_URL") -> str:
    if arg:
        return arg.rstrip("/")
    if os.environ.get(env_key):
        return os.environ[env_key].rstrip("/")
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{env_key}="):
            return line.split("=", 1)[1].strip().rstrip("/")
    raise SystemExit(f"{env_key}가 없습니다(.env 또는 --base-url)")


def meta(device: str, **extra) -> dict:
    """결과에 남길 실행 조건. 주소는 넣지 않습니다."""
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {"at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "device": device,
            "commit": commit, "python": platform.python_version(), **extra}


def save(name: str, doc: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
