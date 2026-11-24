"""학습한 LoRA 어댑터를 Ollama 모델로 올립니다(#545). GPU 사용권을 받은 동안에만 돌립니다.

1. PEFT 어댑터를 llama.cpp `convert_lora_to_gguf.py`로 GGUF 어댑터로 바꿉니다(기본 모델은 config만 받음)
2. Ollama HTTP API로 GGUF 파일을 blob으로 올리고(`POST /api/blobs/sha256:…`), 기존 모델 위에 어댑터를 얹은 새 모델을
   만듭니다(`POST /api/create`, `from`·`adapters`). 이 PC에는 ollama 명령이 없어 API만 씁니다

    ~/.cache/iaa-qlora-venv/bin/python lora/export_ollama.py --run <train_qlora --out> \\
        --llama-cpp ~/.cache/iaa-llama.cpp --ollama http://172.17.0.1:11434 --name qwen3.5-9b-toolcall-lora

변환기 출력(stdout·stderr)은 `<run>/convert.log`에 다 남기고, 실패하면 끝 부분을 출력한 뒤 종료 코드 2로 끝납니다
(#551 v5는 노트북이 출력 끝 15줄만 보여 변환기 오류가 가려졌습니다).

기본 `--from`은 `qwen3.5:9b`(GGUF Q4_K_M)입니다. 학습은 bf16 원본 가중치에 했고 어댑터는 양자화한 기본 모델에
얹으므로 학습 때와 수치가 조금 다릅니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ConvertError(RuntimeError):
    pass


def run_logged(cmd: list[str], log: Path, tail: int = 60) -> None:
    """명령을 돌려 stdout·stderr를 함께 log에 다 남깁니다. 실패하면 마지막 tail줄을 담은 ConvertError를 냅니다."""
    with log.open("w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        # 파이썬 자식의 stdout 버퍼 때문에 오류(stderr)가 기록 중간에 끼지 않게 버퍼를 끕니다
        code = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True,
                              env={**os.environ, "PYTHONUNBUFFERED": "1"}).returncode
    if code:
        lines = log.read_text("utf-8", errors="replace").splitlines()
        raise ConvertError(f"종료 코드 {code}, 기록 {log}(끝 {min(tail, len(lines))}줄):\n" + "\n".join(lines[-tail:]))


def convert(run: Path, llama_cpp: Path, python: str) -> Path:
    from huggingface_hub import snapshot_download

    info = json.loads((run / "run.json").read_text("utf-8"))
    base = snapshot_download(info["baseModel"], revision=info["revision"],
                             allow_patterns=["*.json", "*.jinja", "*.txt", "*.model"])
    out = run / "adapter.gguf"
    run_logged([python, str(llama_cpp / "convert_lora_to_gguf.py"), "--base", base, "--outtype", "f16",
                "--outfile", str(out), str(run / "adapter")], run / "convert.log")
    return out


def create(gguf: Path, ollama: str, name: str, base_tag: str) -> dict:
    digest = "sha256:" + sha256(gguf)
    with httpx.Client(base_url=ollama.rstrip("/"), timeout=600) as c:
        if c.head(f"/api/blobs/{digest}").status_code != 200:
            with gguf.open("rb") as f:
                c.post(f"/api/blobs/{digest}", content=f).raise_for_status()
        r = c.post("/api/create", json={"model": name, "from": base_tag, "adapters": {gguf.name: digest},
                                        "stream": False})
        r.raise_for_status()
        shown = c.post("/api/show", json={"model": name}).json()
    return {"model": name, "from": base_tag, "adapter": digest, "details": shown.get("details")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="train_qlora.py --out 폴더(adapter/, run.json)")
    ap.add_argument("--llama-cpp", required=True, help="llama.cpp 체크아웃(install_qlora.sh가 받음)")
    ap.add_argument("--ollama", required=True)
    ap.add_argument("--name", default="qwen3.5-9b-toolcall-lora")
    ap.add_argument("--from", dest="base_tag", default="qwen3.5:9b")
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)
    run = Path(args.run).expanduser().resolve()
    try:
        gguf = convert(run, Path(args.llama_cpp).expanduser(), args.python)
    except ConvertError as e:
        print(f"GGUF 변환 실패: {e}", file=sys.stderr, flush=True)
        return 2
    result = create(gguf, args.ollama, args.name, args.base_tag)
    (run / "ollama.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
