"""장애 묶음으로 분석기를 잽니다(#284). 상위 1·3 정확도(원인 서비스)와 지연.

    cd incident && uv run python -m bench.rca --runs data/runs/<runId> [--llm http://localhost:8110] [--out bench/results/x.json]

- 신고 시각: 주입 45초 뒤(직원이 증상을 겪고 신고한 때로 정함). 분석 구간은 그 직전 45초, 기준 구간은 묶음 시작부터
  분석 구간 앞까지입니다(묶음의 주입 전 평소 구간이 20~45초). 정답(주입 시각)은 신고 시각을 정하는 데만 씁니다.
- 과거 티켓: 같은 묶음 모음의 다른 장애 티켓과 정답 원인(한 건씩 빼고 나머지를 과거로 씀, leave-one-out).
- 방법: logs(템플릿 변화만), logs+tickets(유사 티켓 표 더함), llm(같은 진단 텍스트를 로컬 모델에), ticket-only-llm(티켓만 모델에),
  nsigma·baro(RCAEval 계열 통계 기준선의 로그 부분, incident/rcaeval_stats.py). 같은 묶음·같은 구간·같은 잡음 처리로 잽니다.
- 세션 스택의 LiteLLM 401 잡음(외부 키 없음)은 기본으로 뺍니다. --keep-keyless-noise로 빼기 전과 비교합니다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from incident import rcaeval_stats
from incident.baseline import PastTicket, rank
from incident.llm import FALLBACK, CallSettings, analyze, diagnostics, resolve
from incident.logs import read_bundle

REPORT_DELAY = timedelta(seconds=45)
WINDOW = timedelta(seconds=45)


def load(runs: list[Path]) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for run in runs:
        for b in sorted(run.iterdir()):
            if (b / "truth.json").exists():
                out.append((b, json.loads((b / "truth.json").read_text(encoding="utf-8"))))
    return out


def ticket_text(t: dict[str, Any]) -> str:
    return f"{t['ticket']['title']} {t['ticket']['description']}"


def llm_row(gateway: str, text: str, settings: CallSettings = FALLBACK) -> dict[str, Any]:
    """실패(시간 초과 등)도 결과로 남깁니다. 후보가 없으면 맞힌 것으로 세지 않습니다."""
    t0 = time.monotonic()
    try:
        r = analyze(gateway, text, settings=settings)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:  # 연결·상태·응답 모양
        return {"ranking": [], "ms": round((time.monotonic() - t0) * 1000), "error": type(e).__name__ + " " + str(e)[:120]}
    return {"ranking": [c.service for c in r.candidates], "kinds": [c.kind for c in r.candidates],
            "ms": r.latency_ms, "raw": r.raw[:2000]}


def hit(ranked: list[str], truth: str, k: int) -> bool:
    return truth in ranked[:k]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", type=Path, required=True)
    ap.add_argument("--llm", help="gateway 주소(예: http://localhost:8110). 없으면 LLM 방법은 건너뜁니다")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--rcaeval-bin", type=int, default=rcaeval_stats.BIN_SECONDS,
                    help="nsigma·baro 칸 크기(초). RCAEval 기본 15")
    ap.add_argument("--keep-keyless-noise", action="store_true", help="LiteLLM 401 잡음을 빼지 않습니다(비교용)")
    args = ap.parse_args(argv)

    # 장애 분석 호출의 생각 단계·시간 제한: gateway 모델 프로필(결정 0009) → 환경 변수 덮어쓰기. 결과 파일에 남깁니다.
    settings = resolve(args.llm) if args.llm else None
    if settings:
        print(f"모델 프로필: {settings.model}, 생각 {settings.thinking}, {settings.timeout_s:.0f}초 ({settings.source})")
    bundles = load(args.runs)
    if not bundles:
        print("truth.json이 있는 묶음이 없습니다")
        return 1
    rows = []
    for bundle, truth in bundles:
        at = datetime.fromisoformat(truth["injectedAt"]) + REPORT_DELAY
        history = [PastTicket(t["ticket"]["id"], ticket_text(t), t["rootService"], t["kind"])
                   for b, t in bundles if b != bundle]
        lines = read_bundle(bundle, keyless_noise=not args.keep_keyless_noise)
        text = ticket_text(truth)
        row: dict[str, Any] = {"incidentId": f"{truth['runId']}/{truth['incidentId']}", "truth": truth["rootService"]}
        t0 = time.monotonic()
        since = datetime.fromisoformat(truth["window"]["start"])
        logs_only = rank(lines, at, WINDOW, since=since)
        row["logs"] = {"ranking": [s for s, _ in logs_only.ranking[:3]],
                       "ms": round((time.monotonic() - t0) * 1000)}
        t0 = time.monotonic()
        both = rank(lines, at, WINDOW, text, history, since=since)
        row["logs+tickets"] = {"ranking": [s for s, _ in both.ranking[:3]],
                               "ms": round((time.monotonic() - t0) * 1000)}
        upto = [x for x in lines if since <= x.at < at]
        for m in rcaeval_stats.SCALERS:
            t0 = time.monotonic()
            r = rcaeval_stats.rank(upto, at - WINDOW, m, args.rcaeval_bin)
            row[m] = {"ranking": r.ranking[:3], "ms": round((time.monotonic() - t0) * 1000),
                      "topColumns": r.columns[:3]}
        if args.llm:
            row["llm"] = llm_row(args.llm, diagnostics(both, text), settings)
            row["ticket-only-llm"] = llm_row(args.llm, f"[신고 티켓]\n{text}", settings)
        rows.append(row)
        print(row["incidentId"], row["truth"], {k: v["ranking"] for k, v in row.items() if isinstance(v, dict)},
              flush=True)

    methods = [m for m in ("logs", "logs+tickets", "nsigma", "baro", "llm", "ticket-only-llm") if all(m in r for r in rows)]
    summary = {}
    for m in methods:
        n = len(rows)
        summary[m] = {
            "n": n,
            "top1": round(sum(hit(r[m]["ranking"], r["truth"], 1) for r in rows) / n, 3),
            "top3": round(sum(hit(r[m]["ranking"], r["truth"], 3) for r in rows) / n, 3),
            "msMedian": statistics.median(r[m]["ms"] for r in rows),
            "errors": sum(1 for r in rows if r[m].get("error")),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": [str(r) for r in args.runs], "reportDelayS": 45, "windowS": 45,
                                        "keylessNoise": "kept" if args.keep_keyless_noise else "removed",
                                        "rcaevalBinS": args.rcaeval_bin,
                                        "llmSettings": asdict(settings) if settings else None,
                                        "summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
