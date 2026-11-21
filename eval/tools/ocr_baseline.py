"""영수증 전통 기준선 실행: OCR + 정규식 → 필드 완전 일치(#463, #100).

    uv run python tools/ocr_baseline.py --images <영수증 묶음 폴더> --engine tesseract --out <결과 이름>
    uv run python tools/ocr_baseline.py --images <폴더> --engine oracle --out <결과 이름>   # 정규식 상한

엔진:
- `tesseract`: `tesseract` 명령(한국어 학습 데이터 `kor`)을 부릅니다. 설치는 따로 합니다(Apache-2.0).
- `rapidocr`: `rapidocr` 패키지(Apache-2.0, PaddleOCR 모델의 ONNX, onnxruntime)의 한국어 인식 모델(기본 PP-OCRv5 mobile).
  저장소 밖 가상환경에 설치합니다: `uv venv ~/.cache/iaa-ocr-venv && uv pip install --python ~/.cache/iaa-ocr-venv/bin/python
  rapidocr onnxruntime pillow pyyaml httpx jsonschema python-jsonpath`, 실행은 그 파이썬으로 합니다.
- `oracle`: OCR을 건너뛰고 생성기가 그린 줄 텍스트를 그대로 씁니다. OCR이 완벽할 때 정규식이 낼 수 있는 상한입니다.

묶음 폴더에는 `tools/make_receipts.py`가 만든 그림과 `truth.jsonl`이 있어야 합니다. 결과는 `<이름>.rows.jsonl`(항목마다
뽑은 값·필드별 맞음·OCR 시간), `<이름>.json`(실행 정보·요약), `<이름>.md`입니다. 확인 묶음 결과를 저장소에 넣을 때는
뽑은 값(가맹점·사업자번호 등 문항 내용)을 빼는 사본을 따로 만듭니다.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.receipt_baseline import extract_fields  # noqa: E402
from harness.receipts import FIELDS, load_truth, score_rows, summarize  # noqa: E402
from harness.report import rate_text  # noqa: E402

Engine = Callable[[Path, dict[str, Any]], list[str]]


def tesseract_engine(lang: str = "kor") -> Engine:
    def run(image: Path, truth: dict[str, Any]) -> list[str]:
        r = subprocess.run(["tesseract", str(image), "-", "-l", lang, "--psm", "6"], capture_output=True, text=True,
                           check=True)
        return [ln for ln in r.stdout.splitlines() if ln.strip()]
    return run


def rapidocr_engine(version: str = "PPOCRV5", model: str = "MOBILE") -> Engine:
    """RapidOCR(`rapidocr` 패키지, Apache-2.0)의 한국어 인식 모델. 모델은 처음 부를 때 내려받습니다."""
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR  # 선택 의존성(저장소 밖 가상환경)

    ocr = RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": getattr(OCRVersion, version),
                           "Rec.model_type": getattr(ModelType, model)})

    def run(image: Path, truth: dict[str, Any]) -> list[str]:
        r = ocr(str(image))
        boxes = sorted(zip(r.boxes if r.boxes is not None else [], r.txts or ()),
                       key=lambda b: (float(b[0][0][1]), float(b[0][0][0])))
        lines: list[str] = []
        last_y = None
        for box, text in boxes:  # 위→아래로, 윗변 높이가 가까우면(20px 안) 같은 줄로 붙입니다
            y = float(box[0][1])
            if last_y is not None and abs(y - last_y) < 20 and lines:
                lines[-1] += " " + text
            else:
                lines.append(text)
                last_y = y
        return lines
    return run


def oracle_engine() -> Engine:
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_receipts", Path(__file__).with_name("make_receipts.py"))
    mr = importlib.util.module_from_spec(spec)
    sys.modules["make_receipts"] = mr
    spec.loader.exec_module(mr)

    def run(image: Path, truth: dict[str, Any]) -> list[str]:
        return [text.replace("|", " ") for _, text in mr.receipt_lines(truth)]
    return run


def run_baseline(images: Path, engine: Engine) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    truths = load_truth(images / "truth.jsonl")
    preds, ocr_ms = {}, {}
    for t in truths:
        start = time.perf_counter()
        lines = engine(images / f"{t['id']}.png", t)
        ocr_ms[t["id"]] = round((time.perf_counter() - start) * 1000)
        preds[t["id"]] = extract_fields(lines)
    rows = score_rows(preds, truths)
    for r in rows:
        r["prediction"] = preds[r["id"]]
        r["ocrMs"] = ocr_ms[r["id"]]
    return rows, truths


def render(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    out = [f"# 영수증 전통 기준선({meta['engine']})", "", "| 항목 | 값 |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in meta.items() if k != "notes"]
    out += [*(f"- {n}" for n in meta.get("notes", [])), "", "## 필드 완전 일치", "", "| 필드 | 맞음 |", "|---|---|"]
    rate = lambda r: rate_text(r)  # noqa: E731
    out += [f"| {f} | {rate(summary['fields'][f])} |" for f in FIELDS]
    out += [f"| 네 필드 모두 | {rate(summary['allFields'])} |", "", "## 묶음별(네 필드 모두)", "", "| 구분 | 맞음 |",
            "|---|---|"]
    out += [f"| {k} | {rate(v)} |" for k, v in summary.get("groups", {}).items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--engine", choices=["tesseract", "rapidocr", "oracle"], required=True)
    ap.add_argument("--lang", default="kor", help="tesseract 언어")
    ap.add_argument("--rapidocr-version", default="PPOCRV5", help="rapidocr 인식 모델 판(PPOCRV4·PPOCRV5)")
    ap.add_argument("--rapidocr-model", default="MOBILE", help="rapidocr 인식 모델 크기(MOBILE·SERVER)")
    ap.add_argument("--out", required=True, type=Path, help="결과 이름(확장자 없이)")
    ap.add_argument("--note", action="append", default=[])
    args = ap.parse_args(argv)
    engine = {"tesseract": lambda: tesseract_engine(args.lang), "rapidocr": lambda: rapidocr_engine(args.rapidocr_version, args.rapidocr_model),
              "oracle": oracle_engine}[args.engine]()
    rows, truths = run_baseline(args.images, engine)
    summary = summarize(_scores(rows), truths)
    ms = sorted(r["ocrMs"] for r in rows)
    meta = {"engine": args.engine, "images": args.images.name, "items": len(rows),
            "ocrMsP50": ms[len(ms) // 2] if ms else None, "machine": f"{platform.platform()} {platform.machine()}",
            "notes": list(args.note)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                   encoding="utf-8")
    args.out.with_suffix(".json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False,
                                                        indent=1) + "\n", encoding="utf-8")
    args.out.with_suffix(".md").write_text(render(meta, summary), encoding="utf-8")
    print(f"네 필드 모두 {rate_text(summary['allFields'])}")
    return 0


def _scores(rows: list[dict[str, Any]]):
    from harness.receipts import ReceiptScore

    return [ReceiptScore(id=r["id"], **{f: r[f] for f in FIELDS}) for r in rows]


if __name__ == "__main__":
    sys.exit(main())
