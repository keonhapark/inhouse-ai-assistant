"""입구 라우터 비교 기록(agent/eval_dev/runs/*-router-*.jsonl)을 eval 쪽에서 다시 세어 보고서를 씁니다(#303).

agent의 `router_compare.py`가 남긴 줄(문장·정답·고른 에이전트·확신도·지연)만 읽고, 판정은 여기서 합니다.

- 정답률: 줄 단위(문장 × 반복), Clopper-Pearson 95%. 출처별(정상 셋·"대리 결재" 변형·2단계 문장)
- 세 번 모두 맞은 문장(pass^3)
- 유출로 이어지는 오분류: 정답 에이전트가 `local_only`인데 `external_allowed` 에이전트로 보낸 줄(팩 agents.yaml 기준)
- 애매: LLM·키워드는 기본 에이전트로 간 줄(`fallback`), Laya처럼 확률을 내는 방법은 확신도가 `--threshold`(0.5)
  미만인 줄. 애매한 줄을 로컬로 보냈다면 남는 유출
- 짝 비교: 같은 (문장, 반복)끼리 LLM − 다른 방법, Newcombe 95%

    uv run python tools/router_report.py --runs ../agent/eval_dev/runs --pack ../packs/manufacturing > <보고서>
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.report import paired_diff, proportion, rate_text  # noqa: E402

SOURCES = (("normal", "정상 셋"), ("normal+variant", "\"대리 결재\" 변형"), ("router_stage2", "2단계 문장"))


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def policies(pack: Path) -> dict[str, str]:
    import yaml

    agents = yaml.safe_load((pack / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    return {a["id"]: a["model_policy"]["mode"] for a in agents}


def is_leak(row: dict[str, Any], modes: dict[str, str]) -> bool:
    return modes.get(row["expected"]) == "local_only" and modes.get(row.get("agent")) == "external_allowed"


def is_ambiguous(row: dict[str, Any], threshold: float) -> bool:
    if row.get("method") in ("llm", "keyword"):
        return bool(row.get("fallback"))
    conf = row.get("confidence")
    return conf is None or conf < threshold


def method_summary(rows: list[dict[str, Any]], modes: dict[str, str], threshold: float = 0.5) -> dict[str, Any]:
    ok = [r for r in rows if r.get("agent") == r["expected"]]
    by_sentence: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_sentence[r["id"]].append(r.get("agent") == r["expected"])
    leaks = [r for r in rows if is_leak(r, modes)]
    ambiguous = [r for r in rows if is_ambiguous(r, threshold)]
    lat = sorted(r["latencyMs"] for r in rows if r.get("latencyMs") is not None)
    return {
        "accuracy": proportion(len(ok), len(rows)),
        "bySource": {s: proportion(sum(1 for r in rows if r["source"] == s and r.get("agent") == r["expected"]),
                                   sum(1 for r in rows if r["source"] == s)) for s, _ in SOURCES},
        "allRepeats": proportion(sum(all(v) for v in by_sentence.values()), len(by_sentence)),
        "unstable": sum(1 for v in by_sentence.values() if len(set(v)) > 1),
        "leaks": len(leaks),
        "ambiguous": len(ambiguous),
        "leaksIfAmbiguousLocal": sum(1 for r in leaks if not is_ambiguous(r, threshold)),
        "confusion": Counter(f"{r['expected']}→{r.get('agent')}" for r in rows if r.get("agent") != r["expected"]),
        "latency": (statistics.median(lat), lat[min(len(lat) - 1, int(0.95 * len(lat)))]) if lat else None,
        "errors": sum(1 for r in rows if r.get("error")),
    }


def pairs(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[tuple[bool, bool]]:
    key = lambda r: (r["id"], r["source"], r["repeat"])  # noqa: E731
    bb = {key(r): r for r in b}
    return [(r.get("agent") == r["expected"], bb[key(r)].get("agent") == bb[key(r)]["expected"])
            for r in a if key(r) in bb]


def render(runs: dict[str, list[dict[str, Any]]], modes: dict[str, str], files: dict[str, str],
           threshold: float = 0.5) -> str:
    s = {name: method_summary(rows, modes, threshold) for name, rows in runs.items()}
    out = ["| 방법(기록) | 정답(줄) | " + " | ".join(label for _, label in SOURCES) +
           " | 세 번 모두 맞은 문장 | 반복 간 다른 문장 | `local_only`→외부 허용 | 애매 | 애매를 로컬로 보내면 남는 유출 | 지연 p50 / p95 |",
           "|---|---|" + "---|" * len(SOURCES) + "---|---|---|---|---|---|"]
    for name, m in s.items():
        lat = f"{m['latency'][0] / 1000:.2f}초 / {m['latency'][1] / 1000:.2f}초" if m["latency"] else "-"
        out.append(f"| {name}(`{files[name]}`) | {rate_text(m['accuracy'])} | " +
                   " | ".join(f"{m['bySource'][src]['n']}/{m['bySource'][src]['N']}" for src, _ in SOURCES) +
                   f" | {m['allRepeats']['n']}/{m['allRepeats']['N']} | {m['unstable']} | {m['leaks']} | {m['ambiguous']} | "
                   f"{m['leaksIfAmbiguousLocal']} | {lat} |")
    out += ["", "오분류(정답→고른 것, 많은 순 다섯):", ""]
    for name, m in s.items():
        top = ", ".join(f"{k} {v}" for k, v in m["confusion"].most_common(5)) or "없음"
        out.append(f"- {name}: {top}")
    if "llm" in runs:
        out += ["", "짝 비교(같은 문장·반복, llm − 다른 방법, Newcombe 95%):", ""]
        for name, rows in runs.items():
            if name == "llm":
                continue
            d = paired_diff("llm", name, pairs(runs["llm"], rows))
            if d:
                out.append(f"- llm − {name}: {d['diff'] * 100:+.1f}%p ({d['low'] * 100:+.1f}~{d['high'] * 100:+.1f}%p, "
                           f"짝 {d['pairs']})")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--glob", default="*-router-*.jsonl")
    ap.add_argument("--threshold", type=float, default=0.5, help="확률을 내는 방법의 애매 기준")
    args = ap.parse_args(argv)
    files = sorted(args.runs.glob(args.glob))
    if not files:
        raise SystemExit(f"{args.runs}에 {args.glob} 기록이 없습니다")
    runs, names = {}, {}
    for f in files:
        name = f.stem.split("-router-", 1)[1]
        runs[name] = load_rows(f)
        names[name] = f.name
    order = sorted(runs, key=lambda n: (n != "llm", n != "keyword", n))
    sys.stdout.write(render({n: runs[n] for n in order}, policies(args.pack), names, args.threshold))
    return 0


if __name__ == "__main__":
    sys.exit(main())
