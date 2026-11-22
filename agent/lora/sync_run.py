"""원격(Kaggle·코랩) 학습 폴더를 데스크탑으로 주기적으로 가져옵니다(#587). 세션이 끊겨도 어댑터·기록이 남게 하려는 것입니다.

원격에서는 학습 결과 폴더(`train_qlora.py --out`)만 읽기 전용 HTTP로 내보냅니다(`python -m http.server --directory <out>`
와 터널). 이 스크립트는 그 목록을 따라 내려가며, 크기가 바뀌었거나 없는 파일만 받습니다. 비밀값이 든 폴더를 내보내지 않습니다.

    uv run python lora/sync_run.py --url "$KAGGLE_RUN_URL" --to ~/.local/share/inhouse-ai/runs/551/kaggle-sync --every 900

주소는 환경 변수로 받고 출력·기록에 남기지 않습니다. `--every`가 0이면 한 번만 가져옵니다.
"""

from __future__ import annotations

import argparse
import html
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx

LINK = re.compile(r'<a href="([^"]+)">')
SKIP = ("../", "?", "/")  # 위 폴더·정렬 링크·절대 경로는 따라가지 않습니다


def listing(c: httpx.Client, url: str) -> list[str]:
    """http.server 목록 페이지의 링크(폴더는 '/'로 끝남)."""
    r = c.get(url)
    r.raise_for_status()
    return [html.unescape(h) for h in LINK.findall(r.text) if not h.startswith(SKIP)]


def walk(c: httpx.Client, base: str, rel: str = "") -> list[str]:
    out = []
    for h in listing(c, urljoin(base, rel)):
        if ".." in h or h.startswith(("http:", "https:")):
            continue
        path = rel + h
        out += walk(c, base, path) if h.endswith("/") else [path]
    return out


def sync_once(c: httpx.Client, base: str, dest: Path) -> dict[str, int]:
    got = same = 0
    for rel in walk(c, base):
        local = dest / unquote(rel)
        head = c.head(urljoin(base, rel))
        size = int(head.headers.get("content-length", -1))
        if local.exists() and local.stat().st_size == size:
            same += 1
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".part")
        with c.stream("GET", urljoin(base, rel)) as r, tmp.open("wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.replace(local)
        got += 1
    return {"downloaded": got, "unchanged": same}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="내보낸 학습 폴더의 HTTP 주소(환경 변수로 넘김)")
    ap.add_argument("--to", required=True)
    ap.add_argument("--every", type=float, default=900, help="초. 0이면 한 번만")
    args = ap.parse_args(argv)
    base = args.url.rstrip("/") + "/"
    dest = Path(args.to).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        while True:
            try:
                print(datetime.now().strftime("%H:%M"), sync_once(c, base, dest), flush=True)
            except httpx.HTTPError as e:
                # 주소가 출력에 나오지 않게 종류만 적습니다
                print(datetime.now().strftime("%H:%M"), "가져오기 실패:", type(e).__name__, flush=True)
            if not args.every:
                return 0
            time.sleep(args.every)


if __name__ == "__main__":
    raise SystemExit(main())
