"""도면 OCR + BM25 기준선(#496, #110): 글자 읽기 엔진이 뽑은 글로 부품 번호·치수 질의에 답합니다.

학습한 비전 모델이 없는 전통 방법의 바닥값입니다. 비전 모델 실측과 견주려는 기준선입니다.

흐름
1. 도면 N장을 만듭니다(eval/tools/make_images.py의 생성기, 시드 고정, 숨은 지시 없음). 정답은 생성기가 압니다.
2. OCR 엔진이 도면마다 글자를 뽑습니다(rapidocr, CPU). `oracle`은 OCR 없이 정답 글자를 그대로 써서
   OCR이 완벽할 때의 상한을 보입니다.
3. 도면 한 장의 OCR 글을 청크 하나로 만들어 BM25로 색인합니다(임베딩 없음).
4. 질의 두 가지를 도면마다 보냅니다.
   - part: "부품 번호 <번호> 도면의 치수를 알려 줘" → 정답 도면이 상위 1·5에 나오는지
   - dims: "<도면 이름> <치수 전부>" → 같은 확인
5. part 질의의 상위 1건 OCR 글을 "답"으로 보고 eval/harness/vision.py의 채점기(score_drawing, #420/#386)로
   부품 번호·도면 이름·치수 4·주기 2를 대조합니다(찾기가 틀리면 다른 도면 글이라 틀림).
   OCR만 본 점수(자기 도면 글 그대로)도 함께 냅니다.

실행(rag/에서)
  uv run --group ocr python -m bench.drawing_ocr --drawings 60 --engine rapidocr --out bench/results/drawing-ocr-<날짜>
  uv run python -m bench.drawing_ocr --drawings 60 --engine oracle --out bench/results/drawing-ocr-oracle-<날짜>
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rag.chunk import Chunk
from rag.pack import REPO_ROOT
from rag.search import SearchIndex

EVAL_DIR = REPO_ROOT / "eval"
sys.path.insert(0, str(EVAL_DIR))  # 채점기와 도면 생성기를 읽기만 합니다(eval/ 파일은 고치지 않음)

Engine = Callable[[Path, dict[str, Any]], list[str]]


def make_drawings(n: int, out: Path, seed: int = 7) -> list[dict[str, Any]]:
    """eval의 생성기로 도면 n장을 만들고 정답 목록을 돌려줍니다."""
    sys.path.insert(0, str(EVAL_DIR / "tools"))
    import make_images  # type: ignore[import-not-found]

    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    truths = []
    for k in range(1, n + 1):
        img, truth = make_images.drawing(rng, k, None)
        name = f"dwg-{k:03d}.png"
        img.save(out / name)
        truths.append({"id": f"dwg-{k:03d}", "file": name, "kind": "drawing", **truth, "hiddenInstruction": None})
    return truths


def rapidocr_engine() -> Engine:
    from rapidocr_onnxruntime import RapidOCR  # 선택 의존성(--group ocr)

    ocr = RapidOCR()

    def run(image: Path, truth: dict[str, Any]) -> list[str]:
        result, _ = ocr(str(image))
        boxes = sorted(result or [], key=lambda b: (round(b[0][0][1] / 20), b[0][0][0]))  # 위→아래, 왼→오
        lines: list[str] = []
        last_row = None
        for box, text, _conf in boxes:
            row = round(box[0][1] / 20)
            if row == last_row and lines:
                lines[-1] += " " + text
            else:
                lines.append(text)
            last_row = row
        return lines

    return run


def oracle_engine() -> Engine:
    def run(image: Path, truth: dict[str, Any]) -> list[str]:
        return [*truth["dimensions"], f"PART NO. {truth['part_no']}", f"TITLE  {truth['title']}",
                *(f"{i + 1}. {note}" for i, note in enumerate(truth["notes"])), "UNIT mm   SCALE 1:1"]

    return run


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.4999) - 1))]


def run_baseline(truths: list[dict[str, Any]], image_dir: Path, engine: Engine) -> dict[str, Any]:
    from harness.vision import score_drawing  # eval/harness

    texts: dict[str, str] = {}
    ocr_ms: list[float] = []
    for t in truths:
        start = time.perf_counter()
        lines = engine(image_dir / t["file"], t)
        ocr_ms.append((time.perf_counter() - start) * 1000)
        texts[t["id"]] = "\n".join(lines)
    chunks = [Chunk(f"{i}#1", i, f"도면 {i}", None, text, "trusted", frozenset({"public"})) for i, text in texts.items()]
    index = SearchIndex(chunks)
    scope = {"public"}

    def top(query: str, k: int) -> list[str]:
        return [h.chunk.doc_id for h in index.search(query, scope, "bm25", top_k=k)]

    rows = []
    for t in truths:
        part_q = f"부품 번호 {t['part_no']} 도면의 치수를 알려 줘"
        dims_q = f"{t['title']} " + " ".join(t["dimensions"])
        part5, dims5 = top(part_q, 5), top(dims_q, 5)
        found = part5[0] if part5 else None
        answer = texts[found] if found else ""
        e2e, own = score_drawing(answer, t), score_drawing(texts[t["id"]], t)
        rows.append({
            "id": t["id"], "partTop1": bool(part5) and part5[0] == t["id"], "partTop5": t["id"] in part5,
            "dimsTop1": bool(dims5) and dims5[0] == t["id"], "dimsTop5": t["id"] in dims5,
            "endToEndAllCorrect": e2e.all_correct, "endToEndFound": e2e.found, "ocrOnlyAllCorrect": own.all_correct,
            "ocrOnlyFound": own.found, "partNoRead": own.fields["part_no"], "titleRead": own.fields["title"],
            "total": own.total,
        })
    n = len(rows)
    total_items = sum(r["total"] for r in rows)
    summary = {
        "drawings": n,
        "partTop1": sum(r["partTop1"] for r in rows), "partTop5": sum(r["partTop5"] for r in rows),
        "dimsTop1": sum(r["dimsTop1"] for r in rows), "dimsTop5": sum(r["dimsTop5"] for r in rows),
        "endToEndAllCorrect": sum(r["endToEndAllCorrect"] for r in rows),
        "endToEndItems": f"{sum(r['endToEndFound'] for r in rows)}/{total_items}",
        "ocrOnlyAllCorrect": sum(r["ocrOnlyAllCorrect"] for r in rows),
        "ocrOnlyItems": f"{sum(r['ocrOnlyFound'] for r in rows)}/{total_items}",
        "partNoRead": sum(r["partNoRead"] for r in rows), "titleRead": sum(r["titleRead"] for r in rows),
        "ocrMs": {"p50": round(statistics.median(ocr_ms)), "p95": round(percentile(ocr_ms, 95))},
    }
    return {"summary": summary, "rows": rows, "ocrTexts": texts}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drawings", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--engine", choices=["rapidocr", "oracle"], required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    engine = rapidocr_engine() if args.engine == "rapidocr" else oracle_engine()
    with tempfile.TemporaryDirectory() as tmp:
        truths = make_drawings(args.drawings, Path(tmp), args.seed)
        result = run_baseline(truths, Path(tmp), engine)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    report = {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "engine": args.engine, "seed": args.seed,
        "machine": f"{platform.system()} {platform.machine()}, CPU", "gitCommit": commit, **result,
    }
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.with_suffix(".json").write_text(text, encoding="utf-8")
    print(json.dumps({"engine": args.engine, **result["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
