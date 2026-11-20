"""개정 전후 질문에서 옛 판 인용 수를 잽니다(기획서 우려 5).

조건
- all: 판을 가리지 않고 모든 판을 검색 후보로 둡니다(판 메타 없는 RAG의 기준선).
- as_of: 질문의 기준일에 시행 중인 판만 후보로 둡니다(이 모듈 기본값).

셈
- 옛 판 인용: 대조를 통과한 인용 중, 기준일에 시행 중이 아닌 판의 청크를 인용했고 그 조문 글이
  기준일 판과 다른 것. 글이 같은 판(타법개정으로 본문이 그대로인 판)은 내용이 같아 세지 않고 따로 적습니다.
- 찾은 답(found): 답이 "규정에서 찾지 못했습니다."가 아닌 수. 대조를 통과한 신뢰 근거 인용이 하나 이상 있고
  답의 숫자가 인용한 근거에 있을 때만 찾은 답이 됩니다(rag/answer.py). 답 내용이 맞는지는 세지 않습니다.
- revisions 표시: 답에 다른 판의 바뀐 조문을 함께 돌려준 답의 수.

실행(rag/에서, 로컬 Ollama에 qwen3.5:9b와 bge-m3이 있어야 합니다):
  uv run python -m bench.editions --repeat 3 --out bench/results/editions-<날짜>.json

LLM과 임베딩은 gateway를 거치지 않고 Ollama의 OpenAI 호환 주소를 바로 부릅니다(gateway 별칭 local과 같은 모델).
위임 토큰은 쓰지 않으므로 문서 범위는 모든 공개·정책 태그로 둡니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from rag.answer import Answerer, GatewayChat
from rag.app import build_index
from rag.corpus import MODULE_ROOT
from rag.editions import section_key
from rag.embed import CachedEmbedder, GatewayEmbedder
from rag.search import today_kst

HERE = Path(__file__).resolve().parent
SCOPES = {"public", "finance-policy", "hr-policy"}


def section_texts(chunks) -> dict[tuple[str, str], dict[date, str]]:
    """(문서, 조문 번호) → {판 시행일: 조문 글}."""
    out: dict[tuple[str, str], dict[date, str]] = {}
    for c in chunks:
        if c.edition is not None and c.section:
            texts = out.setdefault((c.doc_id, section_key(c.section)), {})
            start = c.edition.effective_from
            texts[start] = f"{texts[start]}\n{c.text}" if start in texts else c.text
    return out


def in_force_start(starts, on: date) -> date | None:
    live = [s for s in sorted(starts) if s <= on]
    return live[-1] if live else None


def run(questions: list[dict], editions: str, repeat: int, chat: GatewayChat, embedder, today: date) -> dict:
    index = build_index(embedder, stage=1, editions=editions)  # type: ignore[arg-type]
    texts = section_texts(index.chunks)
    answerer = Answerer(index, chat)
    rows = []
    for rep in range(repeat):
        for q in questions:
            on = date.fromisoformat(q["asOf"]) if q.get("asOf") else today
            started = time.monotonic()
            result = answerer.answer(q["question"], SCOPES, "bench", on)
            took = time.monotonic() - started
            stale = same_text = 0
            cited = []
            for cit in result.citations:
                if "edition" not in cit:
                    continue
                start = date.fromisoformat(cit["edition"]["effectiveFrom"])
                by_start = texts[(cit["docId"], section_key(cit["article"]))]
                right = in_force_start(by_start, on)
                cited.append({"article": cit["article"], "effectiveFrom": start.isoformat(), "inForce": start == right})
                if start == right:
                    continue
                if right is not None and by_start[start] == by_start[right]:
                    same_text += 1
                else:
                    stale += 1
            rows.append({
                "id": q["id"], "rep": rep, "asOf": on.isoformat(), "found": result.found,
                "cited": cited, "staleCitations": stale, "sameTextOtherEdition": same_text,
                "revisions": [r["edition"]["effectiveFrom"] for r in result.revisions],
                "seconds": round(took, 2), "detail": result.detail,
            })
            print(f"[{editions}] {q['id']} rep{rep} found={result.found} stale={stale} "
                  f"revisions={len(result.revisions)} {took:.1f}s", flush=True)
    total: Counter[str] = Counter()
    for r in rows:
        total["answers"] += 1
        total["found"] += r["found"]
        total["citations"] += len(r["cited"])
        total["staleCitations"] += r["staleCitations"]
        total["answersWithStale"] += r["staleCitations"] > 0
        total["sameTextOtherEdition"] += r["sameTextOtherEdition"]
        total["answersWithRevisions"] += bool(r["revisions"])
    return {"condition": editions, "summary": dict(total), "rows": rows}


def corpus_state() -> dict:
    """측정한 말뭉치 판. 저장소 커밋과, 법령 고정본·템플릿 파일마다의 SHA-256(커밋에 없는 변경도 드러나게)."""
    root = MODULE_ROOT
    files = sorted([*(root / "corpus" / "law").glob("*.json"), *(root / "templates").glob("*.md")])
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "corpus", "templates"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    return {
        "gitCommit": commit,
        "uncommittedCorpusChanges": dirty,
        "files": {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--conditions", default="all,as_of")
    ap.add_argument("--base-url", default=os.environ.get("BENCH_LLM_URL", "http://localhost:11434/v1"))
    ap.add_argument("--model", default=os.environ.get("BENCH_LLM_MODEL", "qwen3.5:9b"))
    ap.add_argument("--embed-model", default=os.environ.get("BENCH_EMBED_MODEL", "bge-m3"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    questions = yaml.safe_load((HERE / "edition_questions.yaml").read_text(encoding="utf-8"))["questions"]
    chat = GatewayChat(args.base_url, args.model)
    embedder = CachedEmbedder(GatewayEmbedder(args.base_url, args.embed_model), MODULE_ROOT / ".cache" / "bench")
    today = today_kst()
    report = {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "today": today.isoformat(),
        "llm": {"model": args.model, "via": args.base_url, "reasoning_effort": chat.reasoning_effort,
                "temperature": 0},
        "embedding": args.embed_model,
        "method": "hybrid", "topK": 5, "repeat": args.repeat, "questions": len(questions),
        "machine": f"{platform.system()} {platform.machine()}",
        "corpus": corpus_state(),
        "conditions": [run(questions, c, args.repeat, chat, embedder, today) for c in args.conditions.split(",")],
    }
    for c in report["conditions"]:
        print(c["condition"], json.dumps(c["summary"], ensure_ascii=False))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
