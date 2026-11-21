"""말뭉치 규모(1·10·100배)에 따른 색인 시간·메모리·검색 지연·정확도, 동시 질의 처리량을 잽니다(#245).

늘린 문서
- 지금 문서(각 문서의 마지막 판, 2단계까지)를 바탕으로 배수마다 복제·변형한 문서를 더합니다.
- 질문 묶음(bench/scale_questions.yaml)의 정답 조문은 늘린 문서에 넣지 않습니다. 늘린 문서는 정답과 겹치지 않는
  잡음이고, 정답은 언제나 원래 문서의 그 조문 하나입니다.
- 변형: 숫자를 다른 수로 바꾸고, 줄의 20%를 빼고, 다른 문서의 줄 하나를 섞고, 절 순서를 섞습니다(난수 씨앗 고정).

재는 것
- index: 배수마다 따로 프로세스를 띄워 색인 시간(임베딩 포함·제외), 최대 RSS, 방법별 검색 지연 p50·p95,
  상위 1·5 적중률(정답 문서·조문이 상위 k 안에 있는 질문 비율)을 잽니다.
- load: HTTP /search(hybrid)를 동시 1·10·50으로 보내 처리량, 지연, 오류 수를 잽니다.

실행(rag/에서)
  uv run python -m bench.scale index --scales 1,10,100 --repeat 3 --embedder hash --out bench/results/scale-<날짜>.json
  uv run python -m bench.scale load --scale 10 --concurrency 1,10,50 --requests 200 --embedder hash --out ...
--embedder ollama는 Ollama의 OpenAI 호환 주소(기본 http://localhost:11434/v1)로 bge-m3를 바로 부릅니다(gateway를 거치지 않음).
hash는 의미 없는 해시 임베딩이라 지연·메모리 모양만 보는 시험 실행용입니다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import re
import resource
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from rag.chunk import Chunk, chunk_documents
from rag.corpus import MODULE_ROOT, Document, Section, load_documents
from rag.editions import section_key
from rag.pack import load_pack
from rag.search import SearchIndex

HERE = Path(__file__).resolve().parent
METHODS = ("bm25", "vector", "hybrid")
_NUMBER = re.compile(r"\d+")


def questions() -> list[dict[str, str]]:
    return yaml.safe_load((HERE / "scale_questions.yaml").read_text(encoding="utf-8"))["questions"]


def base_documents() -> list[Document]:
    """각 문서의 마지막 판만(옛 판은 기준일 판 선택으로 어차피 빠져 규모 비교를 흐립니다)."""
    docs = load_documents(load_pack(), stage=2)
    return [d for d in docs if d.edition is None or d.edition.effective_to is None]


def synthetic_documents(base: list[Document], scale: int, gold: set[tuple[str, str]], seed: int = 7) -> list[Document]:
    """배수 scale이 되도록 (scale-1)벌의 변형 문서를 만듭니다. 정답 조문은 넣지 않습니다."""
    rng = random.Random(seed)
    pool = [line for d in base for s in d.sections for line in s.text.split("\n") if line.strip()]
    out = []
    for k in range(1, scale):
        for d in base:
            sections = []
            for s in d.sections:
                if (d.id, section_key(s.article)) in gold:
                    continue
                lines = [x for x in s.text.split("\n") if rng.random() >= 0.2] or s.text.split("\n")[:1]
                lines.insert(rng.randrange(len(lines) + 1), rng.choice(pool))
                text = _NUMBER.sub(lambda m: str(rng.randint(1, 10 ** len(m.group(0)))), "\n".join(lines))
                sections.append(Section(s.label, s.heading, text))
            rng.shuffle(sections)
            if sections:
                out.append(replace(d, id=f"{d.id}~s{k}", title=f"{d.title} (사례 {k})", sections=tuple(sections),
                                   edition=None))
    return out


def scaled_chunks(scale: int) -> tuple[list[Chunk], int]:
    base = base_documents()
    gold = {(q["doc"], q["article"]) for q in questions()}
    docs = base + synthetic_documents(base, scale, gold)
    return chunk_documents(docs), len(docs)


def make_embedder(kind: str, base_url: str, model: str):
    from rag.embed import CachedEmbedder, GatewayEmbedder, HashEmbedder

    if kind == "hash":
        return HashEmbedder()
    return CachedEmbedder(GatewayEmbedder(base_url, model), MODULE_ROOT / ".cache" / "bench")


def all_scopes() -> set[str]:
    return {t["id"] for t in load_pack().org["access_tags"]}


def percentile(values: list[float], p: float) -> float:
    """최근접 순위 백분위: 정렬한 값의 ceil(p/100 × n)번째."""
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]


def is_gold(chunk: Chunk, q: dict[str, str]) -> bool:
    return chunk.doc_id == q["doc"] and section_key(chunk.section) == q["article"]


def measure_index(scale: int, repeat: int, embedder_kind: str, base_url: str, model: str) -> dict[str, Any]:
    """한 배수. 메모리를 따로 재려고 배수마다 새 프로세스에서 부릅니다."""
    chunks, n_docs = scaled_chunks(scale)
    t0 = time.perf_counter()
    SearchIndex(chunks, None)
    lexical = time.perf_counter() - t0
    embedder = make_embedder(embedder_kind, base_url, model)
    t0 = time.perf_counter()
    index = SearchIndex(chunks, embedder)
    build = time.perf_counter() - t0
    scopes = all_scopes()
    qs = questions()
    latency: dict[str, list[float]] = {m: [] for m in METHODS}
    hits: dict[str, dict[str, int]] = {m: {"top1": 0, "top5": 0} for m in METHODS}
    for rep in range(repeat):
        for q in qs:
            for m in METHODS:
                t0 = time.perf_counter()
                found = index.search(q["question"], scopes, m, top_k=5)  # type: ignore[arg-type]
                latency[m].append((time.perf_counter() - t0) * 1000)
                if rep == 0:
                    hits[m]["top1"] += bool(found) and is_gold(found[0].chunk, q)
                    hits[m]["top5"] += any(is_gold(h.chunk, q) for h in found)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # macOS는 바이트, 리눅스는 KB
    return {
        "scale": scale,
        "documents": n_docs,
        "chunks": len(chunks),
        "indexSecondsLexical": round(lexical, 3),
        "indexSecondsWithEmbedding": round(build, 3),
        "maxRssMb": round(rss_mb, 1),
        "latencyMs": {m: {"p50": round(statistics.median(v), 2), "p95": round(percentile(v, 95), 2),
                          "n": len(v)} for m, v in latency.items()},
        "hitRate": {m: {k: round(v / len(qs), 3) for k, v in h.items()} for m, h in hits.items()},
        "questions": len(qs),
    }


# ---------------------------------------------------------------- 동시 질의


def measure_load(scale: int, levels: list[int], requests: int, embedder_kind: str, base_url: str,
                 model: str) -> dict[str, Any]:
    import httpx
    import jwt
    import uvicorn
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from rag.app import create_app
    from rag.auth import TokenVerifier

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    chunks, n_docs = scaled_chunks(scale)
    index = SearchIndex(chunks, make_embedder(embedder_kind, base_url, model))
    app = create_app(index, TokenVerifier(key=pem))
    port = int(os.environ.get("BENCH_PORT", "18430"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    def token() -> str:
        now = int(time.time())
        claims = {"iss": "gateway", "aud": ["rag"], "sub": "E0001", "agt": "bench", "cid": "bench", "scopes": [],
                  "doc_scopes": sorted(all_scopes()), "iat": now, "exp": now + 3600, "jti": os.urandom(8).hex()}
        return jwt.encode(claims, key, algorithm="ES256")

    qs = [q["question"] for q in questions()]
    tok = token()
    results = []
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
        for level in levels:
            durations: list[float] = []
            errors: dict[str, int] = {}

            def one(i: int) -> None:
                t0 = time.perf_counter()
                try:
                    r = client.post("/search", json={"query": qs[i % len(qs)], "method": "hybrid"},
                                    headers={"X-Delegation-Token": tok})
                    if r.status_code != 200:
                        errors[str(r.status_code)] = errors.get(str(r.status_code), 0) + 1
                except httpx.HTTPError as e:
                    errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
                durations.append((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=level) as pool:
                list(pool.map(one, range(requests)))
            wall = time.perf_counter() - t0
            results.append({
                "concurrency": level, "requests": requests, "seconds": round(wall, 2),
                "throughputPerSecond": round(requests / wall, 2),
                "latencyMs": {"p50": round(statistics.median(durations), 1),
                              "p95": round(percentile(durations, 95), 1)},
                "errors": errors,
            })
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    server.should_exit = True
    thread.join(timeout=5)
    return {"scale": scale, "documents": n_docs, "chunks": len(chunks), "levels": results}


# ---------------------------------------------------------------- 실행


def _report_head(args: argparse.Namespace) -> dict[str, Any]:
    from bench.editions import corpus_state

    return {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": f"{platform.system()} {platform.machine()}" + (f", {os.environ['BENCH_DEVICE']}" if os.environ.get("BENCH_DEVICE") else ""),
        "embedder": args.embedder if args.embedder == "hash" else f"{args.embed_model} via {args.base_url}",
        "corpus": corpus_state(),
    }


def _write(report: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "corpus"}, ensure_ascii=False)[:3000])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["index", "load", "_one"])
    ap.add_argument("--scales", default="1,10,100")
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--concurrency", default="1,10,50")
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--embedder", choices=["hash", "ollama"], default="hash")
    ap.add_argument("--base-url", default=os.environ.get("BENCH_LLM_URL", "http://localhost:11434/v1"))
    ap.add_argument("--embed-model", default=os.environ.get("BENCH_EMBED_MODEL", "bge-m3"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    if args.command == "_one":  # 배수 하나를 새 프로세스에서
        print(json.dumps(measure_index(args.scale, args.repeat, args.embedder, args.base_url, args.embed_model)))
        return 0
    report = _report_head(args)
    if args.command == "index":
        report["repeat"] = args.repeat
        report["scales"] = [_child(args, int(s)) for s in args.scales.split(",")]
    else:
        levels = [int(x) for x in args.concurrency.split(",")]
        report["load"] = measure_load(args.scale, levels, args.requests, args.embedder, args.base_url,
                                      args.embed_model)
    _write(report, args.out)
    return 0


def _child(args: argparse.Namespace, scale: int) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "bench.scale", "_one", "--scale", str(scale), "--repeat", str(args.repeat),
           "--embedder", args.embedder, "--base-url", args.base_url, "--embed-model", args.embed_model]
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    done = run(cmd, cwd=MODULE_ROOT, capture_output=True, text=True, check=True)
    row = json.loads(done.stdout.strip().splitlines()[-1])
    print(json.dumps({k: row[k] for k in ("scale", "chunks", "indexSecondsWithEmbedding", "maxRssMb")}), flush=True)
    return row


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
