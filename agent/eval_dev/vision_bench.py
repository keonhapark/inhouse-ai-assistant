"""영수증·VisA 불량 사진 비전 실측(#549, #100·#110). 개발용 측정이고, 채점은 eval의 채점기를 씁니다.

읽기는 업무 실행과 같은 `ImageReader.read`(json_schema 출력, 생각 끔)로 모델 서버(OpenAI 호환)를 바로 부릅니다.
gateway·라우터·대화는 거치지 않습니다(#521과 같은 방식).

- receipts: eval 가짜 영수증 개발 묶음(#462). 읽을 항목은 제조 팩 경비 에이전트의 `image_reading`(금액·사용일·가맹점·
  사업자번호) 그대로이고, 채점은 `eval/harness/receipts.py`(필드 완전 일치, 표기 정규화)입니다. 기준선은 RapidOCR+정규식(#508)
- visa: VisA candle·pcb1 부분집합(#509). CPU 기준선(`eval/tools/visa_baseline.py`)과 같은 시험 절반(기준선 결과 JSON의 사진
  목록)을 쓰고, 기준선 1-NN처럼 범주의 불량 유형 목록에서 고르게 합니다(닫힌 선택). 한 번 호출로 불량 여부와 유형을 함께 읽습니다

    # 읽기(agent 환경)
    uv run python eval_dev/vision_bench.py receipts --base-url <서버>/v1 --images ~/data/receipts-dev --out eval_dev/runs/<이름>.jsonl
    uv run python eval_dev/vision_bench.py visa --base-url <서버>/v1 --data ~/data/visa-subset \\
        --baseline ../eval/reports/vision/2026-11-22-visa-baseline-candle-pcb1.json --out eval_dev/runs/<이름>.jsonl
    # 영수증 채점(eval 환경)
    cd ../eval && uv run python ../agent/eval_dev/vision_bench.py score-receipts ../agent/eval_dev/runs/<이름>.jsonl
    # VisA 채점(agent 환경)
    uv run python eval_dev/vision_bench.py score-visa eval_dev/runs/<이름>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL = "qwen3.5:9b-q4_K_M"
# 영수증 읽기 항목 이름 → eval 채점기 필드
RECEIPT_FIELDS = {"amount": "amount", "spent_on": "date", "merchant": "merchant", "business_no": "bizNo"}


def data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def reader(base_url: str, model: str, timeout: float):
    from agent_runtime.llm import ChatClient, LLMSettings
    from agent_runtime.run.image_reading import ImageReader

    return ImageReader(ChatClient(LLMSettings(base_url=base_url.rstrip("/"), model=model, timeout_s=timeout)), model)


def receipt_spec():
    from agent_runtime.registry import Registry
    from agent_runtime.run.image_reading import ImageSpec

    reg = Registry.load(ROOT / "packs" / "manufacturing", stage=2)
    agent = next(a for a in reg.agents if (a.raw.get("image_reading") or {}).get("draft_tool") == "expense_request")
    return ImageSpec.from_agent(agent)


def visa_spec(cls: str, types: list[str]):
    from agent_runtime.run.image_reading import FieldSpec, ImageSpec

    return ImageSpec(f"{cls} 제품 검사 사진", (
        FieldSpec("has_defect", "string", "불량이 보이면 yes, 정상이면 no", enum=("yes", "no")),
        FieldSpec("defect_type", "string", "보이는 불량 유형(정상이면 none)", enum=(*types, "none")),
    ))


async def _read_all(items: list[dict[str, Any]], read, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for it in items:
            started = time.monotonic()
            got = await read(it)
            row = {**{k: v for k, v in it.items() if not k.startswith("_")}, "read": got,
                   "latencyMs": int((time.monotonic() - started) * 1000),
                   "error": None if got is not None else "읽지 못함(모델 오류·시간 초과·JSON 아님)"}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(it["id"], "ok" if got is not None else "실패", row["latencyMs"], flush=True)


def cmd_receipts(args: argparse.Namespace) -> None:
    images = Path(args.images).expanduser()
    manifest = json.loads((images / "manifest.json").read_text("utf-8"))
    r, spec = reader(args.base_url, args.model, args.timeout), receipt_spec()
    items = [{"id": Path(name).stem, "file": name, "_path": images / name} for name in sorted(manifest["files"])]

    async def read(it: dict[str, Any]) -> dict[str, Any] | None:
        return await r.read(data_url(it["_path"]), "eval-dev", spec)

    asyncio.run(_read_all(items, read, Path(args.out)))


def load_visa(data: Path) -> list[dict[str, Any]]:
    """`eval/tools/visa_baseline.py` load_items와 같은 규칙(그 모듈은 eval 하네스를 불러 agent 환경에서 못 씀).
    manifest.jsonl 사진마다 범주·정상 여부·불량 유형(image_anno.csv label의 첫째)."""
    import csv

    labels: dict[str, str] = {}
    for anno in data.glob("*/image_anno.csv"):
        with anno.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                labels[r["image"].strip()] = (r.get("label") or "").strip()
    items = []
    for line in (data / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        label = labels.get(m["source"]) or labels.get(m["source"].split("/", 1)[-1]) or ""
        kind = m.get("kind") or ("normal" if label == "normal" else "anomaly")
        defect = None if kind == "normal" else (label.split(",")[0].strip() or "unknown")
        items.append({"file": m["file"], "class": m["class"], "kind": kind, "defect": defect})
    return items


def visa_items(data: Path, baseline: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """기준선의 시험 절반(이상 탐지 과제 사진 = 정상 40 + 불량 40)과 범주별 불량 유형 목록(기준선 표와 같은 유형)."""
    all_items = {it["file"]: it for it in load_visa(data)}
    types: dict[str, list[str]] = {}
    for it in all_items.values():
        if it["defect"]:
            types.setdefault(it["class"], [])
            if it["defect"] not in types[it["class"]]:
                types[it["class"]].append(it["defect"])
    test = [p["file"] for p in baseline["predictions"] if p["task"] == "anomaly"]
    items = [{"id": Path(f).stem, "file": f, "class": all_items[f]["class"], "kind": all_items[f]["kind"],
              "defect": all_items[f]["defect"], "_path": data / f} for f in test]
    return items, {k: sorted(v) for k, v in types.items()}


def cmd_visa(args: argparse.Namespace) -> None:
    data = Path(args.data).expanduser()
    baseline = json.loads(Path(args.baseline).read_text("utf-8"))
    items, types = visa_items(data, baseline)
    r = reader(args.base_url, args.model, args.timeout)
    specs = {cls: visa_spec(cls, ts) for cls, ts in types.items()}

    async def read(it: dict[str, Any]) -> dict[str, Any] | None:
        return await r.read(data_url(it["_path"]), "eval-dev", specs[it["class"]])

    asyncio.run(_read_all(items, read, Path(args.out)))


def proportion(k: int, n: int) -> str:
    """k/n (비율%, Clopper-Pearson 95%). scipy 없이 베타 분포 역함수를 이분법으로 구합니다."""
    if n == 0:
        return "0/0"

    def cdf(x: float, a: float, b: float) -> float:  # 정칙 불완전 베타(이항 합으로)
        # P(Beta(a,b) <= x) = P(Binom(a+b-1, x) >= a)  (a, b 정수)
        m = int(a + b - 1)
        return sum(math.comb(m, j) * x ** j * (1 - x) ** (m - j) for j in range(int(a), m + 1))

    def inv(p: float, a: float, b: float) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if cdf(mid, a, b) < p else (lo, mid)
        return (lo + hi) / 2

    low = 0.0 if k == 0 else inv(0.025, k, n - k + 1)
    high = 1.0 if k == n else inv(0.975, k + 1, n - k)
    return f"{k}/{n} ({100 * k / n:.1f}%, {100 * low:.1f}%~{100 * high:.1f}%)"


def score_visa(rows: list[dict[str, Any]]) -> dict[str, Any]:
    anomalies = [r for r in rows if r["kind"] == "anomaly"]
    def said_defect(r: dict) -> bool:
        return (r["read"] or {}).get("has_defect") == "yes"
    tp = sum(said_defect(r) for r in anomalies)
    fp = sum(said_defect(r) for r in rows if r["kind"] == "normal")
    normals = len(rows) - len(anomalies)
    type_ok = sum((r["read"] or {}).get("defect_type") == r["defect"] for r in anomalies)
    by_class: dict[str, Any] = {}
    for cls in sorted({r["class"] for r in rows}):
        a = [r for r in anomalies if r["class"] == cls]
        by_class[cls] = proportion(sum((r["read"] or {}).get("defect_type") == r["defect"] for r in a), len(a))
    lat = [r["latencyMs"] for r in rows if r["error"] is None]
    return {"items": len(rows), "readFailed": sum(r["error"] is not None for r in rows),
            "defectType": proportion(type_ok, len(anomalies)), "defectTypeByClass": by_class,
            "recall": proportion(tp, len(anomalies)), "falseAlarm": proportion(fp, normals),
            "accuracy": proportion(tp + normals - fp, len(rows)),
            "latencyMsP50": statistics.median(lat) if lat else None}


def cmd_score_visa(args: argparse.Namespace) -> None:
    rows = [json.loads(x) for x in Path(args.rows).read_text("utf-8").splitlines() if x.strip()]
    print(json.dumps(score_visa(rows), ensure_ascii=False, indent=1))


def cmd_score_receipts(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(Path.cwd()))  # eval 폴더에서 돌립니다
    from harness.receipts import load_truth, score, summarize

    rows = [json.loads(x) for x in Path(args.rows).read_text("utf-8").splitlines() if x.strip()]
    truths = load_truth(ROOT / "eval" / "receipts" / "dev-truth.jsonl")
    preds = {r["id"]: ({RECEIPT_FIELDS[k]: v for k, v in r["read"].items() if k in RECEIPT_FIELDS}
                       if r["read"] else None) for r in rows}
    scores = [score(preds.get(t["id"]), t) for t in truths]
    lat = [r["latencyMs"] for r in rows if r["error"] is None]
    out = summarize(scores, truths) | {"readFailed": sum(r["error"] is not None for r in rows),
                                        "latencyMsP50": statistics.median(lat) if lat else None,
                                        "wrong": {s.id: [f for f in RECEIPT_FIELDS.values() if not getattr(s, f)]
                                                  for s in scores if not s.all_correct}}
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("receipts", "visa"):
        p = sub.add_parser(name)
        p.add_argument("--base-url", required=True)
        p.add_argument("--model", default=MODEL)
        p.add_argument("--out", required=True)
        p.add_argument("--timeout", type=float, default=95)
        if name == "receipts":
            p.add_argument("--images", required=True, help="make_receipts.py 출력 폴더(manifest.json)")
        else:
            p.add_argument("--data", required=True, help="fetch_visa.py 출력 폴더")
            p.add_argument("--baseline", required=True, help="visa_baseline.py 결과 JSON(시험 사진 목록)")
    sub.add_parser("score-receipts").add_argument("rows")
    sub.add_parser("score-visa").add_argument("rows")
    args = ap.parse_args(argv)
    {"receipts": cmd_receipts, "visa": cmd_visa, "score-receipts": cmd_score_receipts,
     "score-visa": cmd_score_visa}[args.cmd](args)


if __name__ == "__main__":
    main()
