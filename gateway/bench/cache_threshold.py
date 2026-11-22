"""의미 캐시 문턱 측정(#465·#484): 달라야 하는 문장 쌍(음성)이 하나도 적중하지 않는 가장 낮은 문턱과, 그 문턱에서 같은 뜻 쌍(양성) 적중률.

임베딩은 bge-m3(Ollama `/api/embed`)이고 gateway 캐시처럼 단위 벡터의 내적(코사인)을 씁니다. 숫자열 조건(gateway/cache.py)을
적용한 경우와 임베딩만 본 경우를 둘 다 적습니다. 문장은 지어낸 것입니다(bench/cache_pairs.jsonl).

    cd gateway && uv run python bench/cache_threshold.py [--base-url URL] [--device "코랩 T4, 터널 경유"]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

import httpx

from colab import base_url, meta, save

PAIRS = Path(__file__).resolve().parent / "cache_pairs.jsonl"
DIGITS = re.compile(r"\d+")


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--device", default="코랩 T4, 터널 경유")
    ap.add_argument("--model", default="bge-m3")
    args = ap.parse_args()
    pairs = [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line.strip()]
    texts = sorted({t for p in pairs for t in (p["a"], p["b"])})
    t0 = time.monotonic()
    r = httpx.post(base_url(args.base_url) + "/api/embed", json={"model": args.model, "input": texts}, timeout=300)
    r.raise_for_status()
    vec = dict(zip(texts, (unit(v) for v in r.json()["embeddings"])))
    embed_s = time.monotonic() - t0
    rows = []
    for p in pairs:
        sim = sum(x * y for x, y in zip(vec[p["a"]], vec[p["b"]]))
        same_digits = DIGITS.findall(p["a"]) == DIGITS.findall(p["b"])
        rows.append({**p, "similarity": round(sim, 4), "sameDigits": same_digits})
    pos = [x for x in rows if x["kind"] == "pos"]
    neg = [x for x in rows if x["kind"] == "neg"]

    def at(threshold, digits_rule):
        hit = lambda x: x["similarity"] >= threshold and (x["sameDigits"] or not digits_rule)  # noqa: E731
        return {"threshold": threshold, "posHit": sum(map(hit, pos)), "negHit": sum(map(hit, neg)),
                "negHitIds": [f'{x.get("cat")}: {x["a"]} / {x["b"]}' for x in neg if hit(x)]}

    def safe_threshold(digits_rule):
        worst = max((x["similarity"] for x in neg if x["sameDigits"] or not digits_rule), default=0.0)
        return round(math.floor(worst * 1000) / 1000 + 0.001, 3)   # 가장 비슷한 음성 쌍보다 조금 위

    out = {
        "meta": meta(args.device, model=args.model, pairs=str(PAIRS.name), nPos=len(pos), nNeg=len(neg),
                     embedSeconds=round(embed_s, 2), nTexts=len(texts)),
        "safe": {"digitsRule": at(safe_threshold(True), True), "embeddingOnly": at(safe_threshold(False), False)},
        "grid": [at(t, True) for t in (0.80, 0.85, 0.88, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98)],
        "rows": sorted(rows, key=lambda x: (x["kind"], -x["similarity"])),
    }
    path = save("cache-threshold.json", out)
    s = out["safe"]["digitsRule"]
    print(f"음성 적중 0인 문턱(숫자 조건 적용) {s['threshold']}: 양성 {s['posHit']}/{len(pos)} 적중")
    e = out["safe"]["embeddingOnly"]
    print(f"음성 적중 0인 문턱(임베딩만) {e['threshold']}: 양성 {e['posHit']}/{len(pos)} 적중")
    for g in out["grid"]:
        print(f"  문턱 {g['threshold']:.2f}: 양성 {g['posHit']}/{len(pos)}, 음성 {g['negHit']}/{len(neg)}")
    print("가장 비슷한 음성 쌍:", [(x["cat"], x["similarity"]) for x in out["rows"] if x["kind"] == "neg"][:5])
    print("가장 덜 비슷한 양성 쌍:", [x["similarity"] for x in out["rows"] if x["kind"] == "pos"][-5:])
    print("저장:", path.relative_to(Path(__file__).resolve().parents[2]))


if __name__ == "__main__":
    main()
