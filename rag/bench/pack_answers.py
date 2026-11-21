"""업종 팩 생성 문서의 답 시험(#408·#459 후속). 로컬 모델(Ollama)로 /answer 경로(Answerer)를 직접 돌립니다.

질문마다 본 것
- found: 대조를 통과한 근거 인용이 있어 답을 낸 수(rag/answer.py)
- citedDoc / citedArticle: 정답 문서·조문(조문 머리가 article로 시작)이 인용에 있는지
- mustInAnswer: 답 본문에 정답 값(must)이 있는지(공백은 무시)
- deny 질문(문서 태그가 없는 범위): 그 문서가 인용에 나오거나 정답 값이 답에 나오면 leak입니다.

실행(rag/에서, Ollama에 qwen3.5:9b와 bge-m3, GPU 사용권을 받은 뒤)
  RAG_PACK=finance uv run python -m bench.pack_answers --pack finance --base-url <Ollama /v1 주소> --repeat 3 --out bench/results/pack-answers-finance-<날짜>.json
금융 팩은 외부 LLM을 쓰지 않으므로(model_policy_override local_only) 로컬 모델만 부릅니다. 위임 토큰은 쓰지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

import yaml

from bench.editions import corpus_state
from rag.answer import Answerer, GatewayChat
from rag.app import build_index
from rag.corpus import MODULE_ROOT
from rag.embed import CachedEmbedder, GatewayEmbedder
from rag.search import today_kst

HERE = Path(__file__).resolve().parent


def squash(text: str) -> str:
    """띄어쓰기 차이("8 시간"과 "8시간")는 같은 값으로 봅니다."""
    return "".join(text.split())


def run(pack: str, repeat: int, chat: GatewayChat, embedder) -> dict:
    questions = yaml.safe_load((HERE / "pack_questions.yaml").read_text(encoding="utf-8"))[pack]
    index = build_index(embedder)
    answerer = Answerer(index, chat)
    rows = []
    for rep in range(repeat):
        for q in questions:
            started = time.monotonic()
            result = answerer.answer(q["question"], set(q["scope"]), "bench", today_kst())
            took = round(time.monotonic() - started, 2)
            cited = [(c["docId"], (c.get("article") or "")) for c in result.citations]
            doc_cited = any(d == q["doc"] for d, _ in cited)
            has_must = squash(q["must"]) in squash(result.answer)
            row = {"id": q["id"], "rep": rep, "deny": bool(q.get("deny")), "found": result.found, "seconds": took,
                   "cited": [f"{d} {a}" for d, a in cited], "answer": result.answer, "detail": result.detail}
            if q.get("deny"):
                row["leak"] = doc_cited or has_must
            else:
                row["citedDoc"] = doc_cited
                row["citedArticle"] = any(d == q["doc"] and a.startswith(q["article"]) for d, a in cited)
                row["mustInAnswer"] = has_must
                row["ok"] = result.found and row["citedArticle"] and has_must
            rows.append(row)
            print(f"{q['id']} rep{rep} found={result.found} "
                  f"{'leak=' + str(row['leak']) if q.get('deny') else 'ok=' + str(row['ok'])} {took}s", flush=True)
    normal = [r for r in rows if not r["deny"]]
    deny = [r for r in rows if r["deny"]]
    secs = sorted(r["seconds"] for r in rows)
    return {
        "pack": pack,
        "summary": {
            "normalAnswers": len(normal), "found": sum(r["found"] for r in normal),
            "citedDoc": sum(r["citedDoc"] for r in normal), "citedArticle": sum(r["citedArticle"] for r in normal),
            "mustInAnswer": sum(r["mustInAnswer"] for r in normal), "ok": sum(r["ok"] for r in normal),
            "denyAnswers": len(deny), "denyLeaks": sum(r["leak"] for r in deny),
            "denyFound": sum(r["found"] for r in deny),
            "secondsP50": secs[len(secs) // 2], "secondsMax": secs[-1],
        },
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, choices=["finance", "it-services"])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--base-url", default=os.environ.get("BENCH_LLM_URL", "http://localhost:11434/v1"))
    ap.add_argument("--model", default=os.environ.get("BENCH_LLM_MODEL", "qwen3.5:9b"))
    ap.add_argument("--embed-model", default=os.environ.get("BENCH_EMBED_MODEL", "bge-m3"))
    ap.add_argument("--device", default=os.environ.get("BENCH_DEVICE", ""))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if os.environ.get("RAG_PACK") != args.pack:
        print(f"RAG_PACK={args.pack} 환경 변수가 필요합니다", file=sys.stderr)
        return 2
    chat = GatewayChat(args.base_url, args.model)
    embedder = CachedEmbedder(GatewayEmbedder(args.base_url, args.embed_model), MODULE_ROOT / ".cache" / "bench")
    result = run(args.pack, args.repeat, chat, embedder)
    report = {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "today": today_kst().isoformat(),
        "llm": {"model": args.model, "reasoning_effort": chat.reasoning_effort, "temperature": 0},
        "embedding": args.embed_model, "method": "hybrid", "topK": 5, "repeat": args.repeat,
        "device": args.device, "machine": f"{platform.system()} {platform.machine()}", "corpus": corpus_state(), **result,
    }
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
