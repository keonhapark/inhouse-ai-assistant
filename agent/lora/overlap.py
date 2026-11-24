"""학습 데이터 문장과 평가 문장의 겹침을 문장 틀 기준으로 잽니다(#653).

글자 3-gram 자카드만으로는 평가 문장을 말끝·ID·숫자만 바꾼 문장("결재 doc-1077 회수해 줘" 대 "결재 doc-6617 회수해 줘",
0.41)을 놓칩니다. 그래서 두 문장을 먼저 문장 틀로 바꾼 뒤 견줍니다.

- 문서·대결·예약 ID(`doc-1077`, `dlg-0031`, `rsv-0042`, `E0016`, `BSH-2530`)는 `#`로, 숫자(쉼표 포함)는 `0`으로 바꿉니다
- 팩의 사람 이름·회의실·품목 이름은 `@`로 바꿉니다
- 공백·문장부호를 지우고, 말끝(`해 줘`·`해 주세요`·`할게요`·`부탁해요` 등)을 떼어 냅니다

틀의 글자 3-gram으로 두 값을 봅니다. 자카드(`JACCARD_NEAR` 이상)와, 짧은 쪽 3-gram이 긴 쪽에 든 비율(`CONTAIN_NEAR` 이상,
두 틀 모두 `CONTAIN_MIN_LEN`자 이상일 때만. 짧은 틀은 어디에나 들어가 버림)입니다. 둘 중 하나라도 넘으면 겹침입니다.
기준값은 시드 7 학습 데이터와 개발 묶음 60문장의 분포를 보고 정했습니다(`lora/README.md`). 평가 문장의 정답 도구를 알면
가장 가까운 학습 문장의 정답과 같은지(`sameAnswer`)도 남깁니다. 정답까지 같은 겹침이 비교를 부풀립니다.

평가 문장은 toolcall-v1 jsonl(`utterance`)과 시나리오 YAML(사용자 턴 `content`)을 받습니다. 저장소 밖 평가 묶음(정상 셋 v2,
confirm-v1)은 eval이 원문이 있는 곳에서 이 스크립트를 돌려 대조합니다. 보고서에는 문장을 넣지 않고(`--with-text`로만)
id·유사도만 남깁니다.

    uv run python lora/overlap.py --train <생성 폴더> --against eval_dev/tool_calls.jsonl --out overlap.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE.parents[1] / "packs" / "manufacturing"

JACCARD_NEAR = 0.5
CONTAIN_NEAR = 0.75
CONTAIN_MIN_LEN = 8
CLARIFY = "(되묻기)"
ID = re.compile(r"\b[A-Za-z]{1,6}-?[A-Za-z]?\d{2,}\b|\b[a-z]+-[a-z]\b")
NUMBER = re.compile(r"\d[\d,]*")
ENDINGS = ("주실래요", "주실래", "주세요", "줄래요", "줄래", "줘요", "줘", "부탁드려요", "부탁드립니다", "부탁해요", "부탁해",
           "부탁합니다", "할게요", "할게", "해요", "하자", "해", "입니다", "습니다", "니다", "이야", "예요", "에요", "요")


def pack_names(pack: Path = DEFAULT_PACK) -> list[str]:
    """문장 틀에서 `@`로 바꿀 팩 고유명사(사람·회의실·품목 이름과 회의실 ID). 긴 것부터 바꾸도록 정렬합니다."""
    names: set[str] = set()
    for fname, keys in (("employees", ("name",)), ("rooms", ("name", "id")), ("items", ("name",))):
        path = pack / "fixtures" / f"{fname}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text("utf-8"))
        rows = raw if isinstance(raw, list) else next((v for v in raw.values() if isinstance(v, list)), [])
        for r in rows:
            names.update(str(r[k]) for k in keys if r.get(k))
    return sorted((n for n in names if len(n) >= 2), key=len, reverse=True)


def skeleton(text: str, names: Iterable[str] = ()) -> str:
    t = text
    for n in names:
        t = t.replace(n, "@")
    t = ID.sub("#", t)
    t = NUMBER.sub("0", t)
    t = re.sub(r"[\s.,!?~:;'\"()\[\]/·-]+", "", t).lower()
    changed = True
    while changed:
        changed = False
        for e in ENDINGS:
            if t.endswith(e) and len(t) > len(e) + 1:
                t, changed = t[: -len(e)], True
                break
    return t


def grams(s: str, n: int = 3) -> set[str]:
    return {s[i:i + n] for i in range(max(1, len(s) - n + 1))}


def scores(a: str, b: str) -> tuple[float, float]:
    """두 틀의 (자카드, 포함 비율). 포함 비율은 두 틀이 CONTAIN_MIN_LEN자 이상일 때만 셉니다(아니면 0)."""
    if a == b:
        return 1.0, 1.0
    ga, gb = grams(a), grams(b)
    inter = len(ga & gb)
    contain = inter / min(len(ga), len(gb)) if min(len(a), len(b)) >= CONTAIN_MIN_LEN else 0.0
    return inter / len(ga | gb), contain


def is_overlap(jaccard: float, contain: float) -> bool:
    return jaccard >= JACCARD_NEAR or contain >= CONTAIN_NEAR


def answer_of(messages: list[dict[str, Any]]) -> str:
    """학습 예시 정답: 부른 도구 이름, 도구 없이 되물으면 CLARIFY."""
    calls = messages[-1].get("tool_calls") or []
    return calls[0]["function"]["name"] if calls else CLARIFY


def read_eval(path: Path) -> Iterator[tuple[str, str, set[str] | None]]:
    """(id, 문장, 정답 도구 집합). toolcall-v1 jsonl은 utterance와 expected·alsoAcceptable(되묻기면 CLARIFY), 시나리오 YAML은 사용자 턴마다
    (id#턴 번호, 첫 턴만 expect.requiredTools를 정답으로 봄)."""
    if path.is_dir():
        for f in sorted([*path.rglob("*.jsonl"), *path.rglob("*.yaml"), *path.rglob("*.yml")]):
            yield from read_eval(f)
        return
    if path.suffix == ".jsonl":
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if line.strip():
                row = json.loads(line)
                accepted = [x for x in [row.get("expected"), *row.get("alsoAcceptable", [])] if x]
                tools = {x["tool"] if x.get("type") == "call" else CLARIFY for x in accepted}
                yield str(row.get("id") or f"{path.name}:{n}"), row["utterance"], tools or None
        return
    doc = yaml.safe_load(path.read_text("utf-8"))
    scenarios = doc if isinstance(doc, list) else doc.get("scenarios", [doc]) if isinstance(doc, dict) else []
    for s in scenarios:
        users = [t["content"] for t in s.get("turns", []) if t.get("role") == "user" and isinstance(t.get("content"), str)]
        required = set((s.get("expect") or {}).get("requiredTools") or []) or None
        for i, text in enumerate(users, 1):
            yield f"{s['id']}#{i}", text, required if i == 1 else None


def read_train(path: Path) -> list[tuple[str, str]]:
    """학습 생성 폴더(train.jsonl·valid.jsonl) 또는 jsonl 하나의 (사용자 문장, 정답)."""
    files = [path / "train.jsonl", path / "valid.jsonl"] if path.is_dir() else [path]
    out = []
    for f in files:
        if f.exists():
            for line in f.read_text("utf-8").splitlines():
                if line.strip():
                    msgs = json.loads(line)["messages"]
                    out.append((next(m["content"] for m in msgs if m["role"] == "user"), answer_of(msgs)))
    return out


def overlap(train: list[tuple[str, str]], evals: list[tuple[str, str, set[str] | None]],
            names: list[str]) -> list[dict[str, Any]]:
    """평가 문장마다 가장 가까운 학습 문장(자카드·포함 비율 중 큰 값 기준)과 겹침 여부."""
    uniq: dict[tuple[str, str], str] = {}
    for text, ans in train:
        uniq.setdefault((skeleton(text, names), ans), text)
    out = []
    for eid, text, expected in evals:
        sk = skeleton(text, names)
        best: tuple[float, float, float, str, str] | None = None
        for (tsk, ans), t in uniq.items():
            j, c = scores(sk, tsk)
            if best is None or max(j, c) > best[0]:
                best = (max(j, c), j, c, t, ans)
        top, j, c, t, ans = best or (0.0, 0.0, 0.0, None, None)
        out.append({"id": eid, "jaccard": round(j, 3), "contain": round(c, 3), "overlap": is_overlap(j, c),
                    "sameAnswer": (ans in expected) if expected and ans else None,
                    "text": text, "nearestTrain": t})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, help="make_toolcall_data.py 출력 폴더 또는 jsonl")
    ap.add_argument("--against", action="append", required=True,
                    help="평가 문장(toolcall-v1 jsonl, 시나리오 YAML 또는 그 폴더). 여러 번 줄 수 있습니다")
    ap.add_argument("--pack", default=str(DEFAULT_PACK))
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-text", action="store_true", help="보고서에 평가·학습 문장을 넣음(저장소 밖 묶음에는 쓰지 않음)")
    args = ap.parse_args(argv)
    names = pack_names(Path(args.pack))
    train = read_train(Path(args.train))
    evals = [x for p in args.against for x in read_eval(Path(p))]
    rows = overlap(train, evals, names)
    if not args.with_text:
        rows = [{k: v for k, v in r.items() if k not in ("text", "nearestTrain")} for r in rows]
    hit = [r["id"] for r in rows if r["overlap"]]
    report = {"method": "문장 틀(ID·숫자·팩 이름 바꿈, 말끝 뗌)의 글자 3-gram 자카드 또는 포함 비율",
              "jaccardNear": JACCARD_NEAR, "containNear": CONTAIN_NEAR, "containMinLen": CONTAIN_MIN_LEN,
              "trainUtterances": len(train), "evalUtterances": len(rows), "overlapping": len(hit),
              "overlappingSameAnswer": sum(1 for r in rows if r["overlap"] and r["sameAnswer"]), "overlapIds": hit,
              "rows": rows}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
