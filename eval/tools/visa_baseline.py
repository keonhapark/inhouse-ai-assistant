"""VisA 부분집합으로 불량 사진 전통 기준선을 냅니다(#495, #110). CPU만 씁니다.

`tools/fetch_visa.py --per-class N --normal-per-class M`으로 저장소 밖에 받은 폴더를 읽습니다.

- 불량 유형 분류(지도 분류기): 불량 사진을 범주마다 학습·시험으로 나눠, 그림 특징의 최근접 이웃(1-NN)으로 유형을
  맞힙니다. 유형은 VisA `image_anno.csv`의 `label`(여러 개면 첫째)입니다. 비교용으로 가장 흔한 유형 하나만 답하는
  기준(다수 유형)도 냅니다.
- 이상 탐지: 정상 사진 절반으로 정상 특징을 모으고, 시험 사진의 점수를 가장 가까운 정상 특징까지 거리로 둡니다.
  AUROC와, 학습 정상끼리 거리(한 장 뺀 거리)의 95번째 백분위를 문턱으로 쓴 정상·불량 판정을 냅니다.
- 그림 특징: 64×64 회색 화소(표준화), 색 히스토그램(채널마다 8칸), 기울기 크기 히스토그램(8칸). 학습 없는 손 특징이라
  딥러닝 기준선보다 약한 하한입니다.

    uv run --group tools python tools/visa_baseline.py --data <받은 폴더> --out <결과 이름> [--seed 7]

결과는 `<이름>.json`(설정·요약·항목별 예측)과 `<이름>.md`입니다. VisA는 CC BY 4.0이고 사진은 저장소에 넣지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.report import proportion, rate_text  # noqa: E402

SIZE = 64


def load_items(data: Path) -> list[dict[str, Any]]:
    """manifest.jsonl의 사진마다 범주·정상 여부·불량 유형(VisA label)을 붙입니다."""
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
        # 묶음 안 경로는 맨 앞에 묶음 폴더가 붙기도 합니다(VisA_20220922/candle/...). 둘 다 찾아봅니다
        label = labels.get(m["source"]) or labels.get(m["source"].split("/", 1)[-1]) or ""
        kind = m.get("kind") or ("normal" if label == "normal" else "anomaly")
        defect = None if kind == "normal" else (label.split(",")[0].strip() or "unknown")
        items.append({"file": m["file"], "class": m["class"], "kind": kind, "defect": defect})
    return items


def features(path: Path):
    import numpy as np
    from PIL import Image

    img = Image.open(path).convert("RGB").resize((SIZE, SIZE))
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    gray = rgb.mean(axis=2)
    pix = (gray - gray.mean()) / (gray.std() + 1e-6)
    hist = np.concatenate([np.histogram(rgb[..., c], bins=8, range=(0, 1))[0] for c in range(3)]) / (SIZE * SIZE)
    gy, gx = np.gradient(gray)
    mag = np.hypot(gx, gy)
    ghist = np.histogram(mag, bins=8, range=(0, 0.5))[0] / (SIZE * SIZE)
    return np.concatenate([pix.ravel() / SIZE, hist * 4, ghist * 4])


def auroc(normal: list[float], anomaly: list[float]) -> float | None:
    """불량 점수가 정상 점수보다 클 확률(같으면 반). Mann-Whitney U."""
    if not normal or not anomaly:
        return None
    wins = sum((a > n) + 0.5 * (a == n) for a in anomaly for n in normal)
    return wins / (len(normal) * len(anomaly))


def run(data: Path, seed: int = 7) -> dict[str, Any]:
    import numpy as np

    items = load_items(data)
    rng = random.Random(seed)
    feats = {it["file"]: features(data / it["file"]) for it in items}
    by_class: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_class[it["class"]].append(it)
    out: dict[str, Any] = {"seed": seed, "classes": {}, "predictions": []}
    cls_ok = cls_n = maj_ok = 0
    det_tp = det_fn = det_fp = det_tn = 0
    for cls, group in sorted(by_class.items()):
        group = sorted(group, key=lambda x: x["file"])
        rng.shuffle(group)
        normals = [x for x in group if x["kind"] == "normal"]
        anomalies = [x for x in group if x["kind"] == "anomaly"]
        n_train, n_test = normals[: len(normals) // 2], normals[len(normals) // 2:]
        a_train, a_test = anomalies[: len(anomalies) // 2], anomalies[len(anomalies) // 2:]
        info: dict[str, Any] = {"normal": len(normals), "anomaly": len(anomalies)}
        # 불량 유형 분류(1-NN)
        if a_train and a_test:
            train = np.stack([feats[x["file"]] for x in a_train])
            majority = Counter(x["defect"] for x in a_train).most_common(1)[0][0]
            ok = 0
            for x in a_test:
                d = np.linalg.norm(train - feats[x["file"]], axis=1)
                pred = a_train[int(d.argmin())]["defect"]
                ok += pred == x["defect"]
                maj_ok += majority == x["defect"]
                out["predictions"].append({"file": x["file"], "task": "defect_type", "truth": x["defect"], "pred": pred})
            cls_ok, cls_n = cls_ok + ok, cls_n + len(a_test)
            info["defectTypes"] = dict(Counter(x["defect"] for x in anomalies))
            info["typeAccuracy"] = proportion(ok, len(a_test))
        # 이상 탐지(정상 특징까지 최근접 거리)
        if len(n_train) >= 2 and n_test and anomalies:
            bank = np.stack([feats[x["file"]] for x in n_train])

            def score(f, exclude: int | None = None) -> float:
                d = np.linalg.norm(bank - f, axis=1)
                if exclude is not None:
                    d = np.delete(d, exclude)
                return float(d.min())

            loo = [score(bank[i], exclude=i) for i in range(len(bank))]
            threshold = float(np.percentile(loo, 95))
            sn = [score(feats[x["file"]]) for x in n_test]
            test_anoms = a_test or anomalies
            sa = [score(feats[x["file"]]) for x in test_anoms]
            info["auroc"] = auroc(sn, sa)
            info["threshold"] = threshold
            det_tn += sum(s <= threshold for s in sn)
            det_fp += sum(s > threshold for s in sn)
            det_tp += sum(s > threshold for s in sa)
            det_fn += sum(s <= threshold for s in sa)
            for x, s in [*zip(n_test, sn), *zip(test_anoms, sa)]:
                out["predictions"].append({"file": x["file"], "task": "anomaly", "truth": x["kind"], "score": s,
                                           "pred": "anomaly" if s > threshold else "normal"})
        out["classes"][cls] = info
    out["summary"] = {
        "typeAccuracy": proportion(cls_ok, cls_n),
        "typeMajority": proportion(maj_ok, cls_n),
        "detectionRecall": proportion(det_tp, det_tp + det_fn),
        "detectionFalsePositive": proportion(det_fp, det_fp + det_tn),
        "detectionAccuracy": proportion(det_tp + det_tn, det_tp + det_tn + det_fp + det_fn),
    }
    return out


def render(result: dict[str, Any], data_name: str) -> str:
    s = result["summary"]
    out = [f"# VisA 불량 사진 전통 기준선({data_name})", "",
           "CPU 손 특징(회색 화소·색·기울기 히스토그램) + 최근접 이웃입니다. 학습·시험은 범주마다 반씩, 시드 "
           f"{result['seed']}.", "", "| 지표 | 값 |", "|---|---|",
           f"| 불량 유형 분류(1-NN) | {rate_text(s['typeAccuracy'])} |",
           f"| 참고: 가장 흔한 유형만 답함 | {rate_text(s['typeMajority'])} |",
           f"| 이상 탐지 재현율(불량을 불량으로) | {rate_text(s['detectionRecall'])} |",
           f"| 이상 탐지 거짓 경보(정상을 불량으로) | {rate_text(s['detectionFalsePositive'])} |",
           f"| 이상 탐지 정확도 | {rate_text(s['detectionAccuracy'])} |", "",
           "| 범주 | 정상 | 불량 | 불량 유형 | 유형 분류 | AUROC |", "|---|---|---|---|---|---|"]
    for cls, i in result["classes"].items():
        types = ", ".join(f"{k} {v}" for k, v in sorted(i.get("defectTypes", {}).items()))
        acc = rate_text(i["typeAccuracy"]) if "typeAccuracy" in i else "-"
        au = f"{i['auroc']:.3f}" if i.get("auroc") is not None else "-"
        out.append(f"| {cls} | {i['normal']} | {i['anomaly']} | {types or '-'} | {acc} | {au} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="결과 이름(확장자 없이)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    result = run(args.data, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    args.out.with_suffix(".md").write_text(render(result, args.data.name), encoding="utf-8")
    print(f"불량 유형 {rate_text(result['summary']['typeAccuracy'])}, "
          f"이상 탐지 정확도 {rate_text(result['summary']['detectionAccuracy'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
