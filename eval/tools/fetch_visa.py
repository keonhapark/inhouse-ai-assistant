"""VisA(Visual Anomaly, CC BY 4.0) 불량 사진의 부분집합을 저장소 밖으로 받습니다(#386).

원본 사진은 저장소에 넣지 않습니다. 묶음 파일을 내려받으며(스트림) 범주마다 불량(Anomaly) 사진 앞 N장과
범주별 image_anno.csv만 꺼내고, 받은 목록을 manifest.jsonl로 남깁니다. 묶음 안의 경로는 쓰지 않고 파일 이름을
새로 지어 저장합니다(경로 이탈 방지).

    uv run python tools/fetch_visa.py --out ~/data/visa-subset [--per-class 5] [--classes pcb1,capsules]
    uv run python tools/fetch_visa.py --out ... --archive VisA_20220922.tar   # 이미 받은 묶음에서 꺼냄

출처: Zou et al., "SPot-the-Difference Self-Supervised Pre-training for Anomaly Detection and Segmentation"
(ECCV 2022), https://github.com/amazon-science/spot-diff . 라이선스 CC BY 4.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from collections import Counter
from pathlib import Path
from typing import IO

URL = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
IMAGE = re.compile(r"^(?:[^/]+/)?(?P<cls>[a-z0-9_]+)/Data/Images/Anomaly/(?P<name>[A-Za-z0-9_.-]+\.(?:JPG|jpg|png))$")
ANNO = re.compile(r"^(?:[^/]+/)?(?P<cls>[a-z0-9_]+)/image_anno\.csv$")


def extract(stream: IO[bytes], out: Path, per_class: int, classes: set[str] | None) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    taken: Counter[str] = Counter()
    rows = []
    with tarfile.open(fileobj=stream, mode="r|*") as tar:
        for m in tar:
            if not m.isfile():
                continue
            if (a := ANNO.match(m.name)) and (classes is None or a["cls"] in classes):
                (out / a["cls"]).mkdir(exist_ok=True)
                (out / a["cls"] / "image_anno.csv").write_bytes(tar.extractfile(m).read())
                continue
            i = IMAGE.match(m.name)
            if not i or (classes is not None and i["cls"] not in classes) or taken[i["cls"]] >= per_class:
                continue
            data = tar.extractfile(m).read()
            taken[i["cls"]] += 1
            name = f"{i['cls']}-{taken[i['cls']]:03d}{Path(i['name']).suffix.lower()}"
            (out / i["cls"]).mkdir(exist_ok=True)
            (out / i["cls"] / name).write_bytes(data)
            rows.append({"file": f"{i['cls']}/{name}", "class": i["cls"], "source": m.name,
                         "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    (out / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                        encoding="utf-8")
    (out / "LICENSE-VisA.txt").write_text(
        "VisA dataset, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).\n"
        "Source: https://github.com/amazon-science/spot-diff\n", encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="저장소 밖 폴더")
    ap.add_argument("--per-class", type=int, default=5)
    ap.add_argument("--classes", help="쉼표로 구분한 범주(기본: 전부)")
    ap.add_argument("--archive", help="이미 받은 묶음 파일 경로(없으면 내려받음)")
    ap.add_argument("--url", default=URL)
    args = ap.parse_args(argv)
    out = Path(args.out).expanduser().resolve()
    repo = Path(__file__).resolve().parents[2]
    if out == repo or repo in out.parents:
        raise SystemExit("원본 사진은 저장소 밖에 둡니다: --out을 저장소 밖으로 주세요")
    classes = set(args.classes.split(",")) if args.classes else None
    if args.archive:
        with open(args.archive, "rb") as f:
            rows = extract(f, out, args.per_class, classes)
    else:
        import httpx

        with httpx.stream("GET", args.url, timeout=None, follow_redirects=True) as r:
            r.raise_for_status()

            class _Reader:
                def __init__(self, it):
                    self.it, self.buf = it, b""

                def read(self, n=-1):
                    while n < 0 or len(self.buf) < n:
                        try:
                            self.buf += next(self.it)
                        except StopIteration:
                            break
                    data, self.buf = (self.buf, b"") if n < 0 else (self.buf[:n], self.buf[n:])
                    return data

            rows = extract(_Reader(r.iter_bytes()), out, args.per_class, classes)
    print(f"{len(rows)}장, {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
