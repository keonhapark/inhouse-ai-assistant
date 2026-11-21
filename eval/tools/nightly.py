"""야간 회귀(#464): 고정한 개발 셋 부분집합을 돌리고 바로 앞 실행과 견줍니다.

GPU 사용권(`scripts/gpu-lease.sh`)이 비어 있을 때만 돕니다. 사용 중이면 아무것도 하지 않고 끝냅니다(코드 0).
실행 동안 사용권을 30분마다 늘리고, 끝나면(실패해도) 반납합니다. 공식 평가 셋은 쓰지 않습니다(`nightly/subset.txt`).

    uv run python tools/nightly.py --config <조건 설정(conditions.local.yaml 등)> [--state ~/.local/share/inhouse-ai/nightly]

스택은 미리 띄워 둡니다(설정의 gateway·erp 주소). 결과는 state 폴더에 `<시각>.{json,md,rows.jsonl}`와
`<시각>-compare.md`로 남고, 저장소에는 쓰지 않습니다. 타이머 예시는 `nightly/inhouse-eval-nightly.{service,timer}`입니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_DIR))

from harness.nightly import compare_files, latest_run, read_subset  # noqa: E402

LEASE = EVAL_DIR.parent / "scripts" / "gpu-lease.sh"
WHO = "eval-nightly"


def lease(*args: str) -> int:
    return subprocess.run(["bash", str(LEASE), *args], capture_output=True, text=True).returncode


def run_harness(config: Path, ids: list[str], out: Path) -> int:
    cmd = [sys.executable, "-m", "harness.cli", "run", "--config", str(config.resolve()), "--scenarios", str(EVAL_DIR / "scenarios"),
           "--set", "dev", "--only", ",".join(ids), "--out", str(out.resolve()), "--title", "야간 회귀(개발 셋 부분집합)"]
    return subprocess.run(cmd, cwd=EVAL_DIR).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--subset", type=Path, default=EVAL_DIR / "nightly" / "subset.txt")
    ap.add_argument("--state", type=Path, default=Path.home() / ".local/share/inhouse-ai/nightly")
    ap.add_argument("--gpu", default="desktop")
    ap.add_argument("--minutes", type=int, default=60, help="처음 잡는 사용권 시간(분)")
    args = ap.parse_args(argv)
    ids = read_subset(args.subset)
    if lease("take", args.gpu, WHO, str(args.minutes), "야간 회귀(개발 셋 부분집합)") != 0:
        print(f"{args.gpu} GPU 사용 중이라 건너뜁니다")
        return 0
    stop = threading.Event()

    def keep() -> None:
        while not stop.wait(30 * 60):
            lease("extend", args.gpu, WHO, "60")

    threading.Thread(target=keep, daemon=True).start()
    try:
        args.state.mkdir(parents=True, exist_ok=True)
        out = args.state / datetime.now().strftime("%Y-%m-%d-%H%M")
        rc = run_harness(args.config, ids, out)
        cur = out.with_suffix(".json")
        if not cur.exists():
            print(f"실행 결과가 없습니다(코드 {rc})")
            return rc or 1
        prev = latest_run(args.state, exclude=cur)
        if prev is None:
            print(f"첫 실행입니다: {cur}")
            return rc
        _, md = compare_files(prev, cur)
        (args.state / f"{out.name}-compare.md").write_text(md, encoding="utf-8")
        print(md)
        return rc
    finally:
        stop.set()
        lease("release", args.gpu, WHO)


if __name__ == "__main__":
    sys.exit(main())
