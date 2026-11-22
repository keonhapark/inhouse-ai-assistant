"""이미지 읽기 실측(#382): 업무 실행과 같은 읽기 코드로 도면·불량 사진을 읽고 eval 채점기로 셉니다. 개발용입니다.

읽기는 agent의 `ImageReader.read`(팩 `image_reading` 항목, json_schema 출력, 생각 끔)를 그대로 쓰고, gateway·라우터를
거치지 않고 모델 서버(OpenAI 호환)를 바로 부릅니다. 도면은 제조 팩 `rnd`, 불량 사진은 `quality` 에이전트의 읽을 항목입니다.
채점은 eval `harness/vision.py`의 `score`(표기 차이 허용)를 쓰고, 읽은 값을 줄마다 이어 붙인 글을 답 본문으로 봅니다.
숨은 지시가 든 그림은 읽기 점수에서 뺍니다(지시를 따랐는지는 eval 시나리오가 봄).

    # 1) 읽기(agent 환경). --images는 truth.jsonl이 있는 폴더이고 여러 번 줄 수 있습니다
    uv run python eval_dev/vision_read_run.py read --base-url <모델 서버>/v1 --model qwen3.5:9b-q4_K_M \\
        --images ../eval/images --images <2단계 폴더> --out eval_dev/runs/<이름>.jsonl
    # 2) 채점(eval 환경)
    cd ../eval && uv run python ../agent/eval_dev/vision_read_run.py score ../agent/eval_dev/runs/<이름>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AGENT_FOR = {"drawing": "rnd", "defect": "quality"}


def _truths(folder: Path) -> list[dict[str, Any]]:
    out = []
    for line in (folder / "truth.jsonl").read_text("utf-8").splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        # 1단계 정답은 eval 폴더 기준(images/drawings/...), 2·3단계는 그 폴더 기준(drawings/...)입니다.
        path = folder / t["file"].removeprefix("images/")
        t["_path"] = str(path)
        t["level"] = int(t["id"].split("-l")[1][0]) if "-l" in t["id"] else 1
        out.append(t)
    return out


def _answer(kind: str, read: dict[str, Any] | None) -> str:
    if read is None:
        return ""
    keys = ("part_no", "title", "dimensions", "notes") if kind == "drawing" else ("item_code", "defect_type")
    lines: list[str] = []
    for k in keys:
        v = read.get(k)
        lines += [str(x) for x in v] if isinstance(v, list) else [str(v)] if v is not None else []
    return "\n".join(lines)


async def read(args: argparse.Namespace) -> None:
    from agent_runtime.llm import ChatClient, LLMSettings
    from agent_runtime.registry import Registry
    from agent_runtime.run.image_reading import ImageReader, ImageSpec

    reg = Registry.load(ROOT / "packs" / "manufacturing", stage=3)
    specs = {kind: ImageSpec.from_agent(reg.get(aid)) for kind, aid in AGENT_FOR.items()}
    reader = ImageReader(ChatClient(LLMSettings(base_url=args.base_url.rstrip("/"), model=args.model,
                                                timeout_s=args.timeout)), args.model)
    items = [t for folder in args.images for t in _truths(Path(folder).resolve())]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for t in items:
            data_url = "data:image/png;base64," + base64.b64encode(Path(t["_path"]).read_bytes()).decode()
            started = time.monotonic()
            got = await reader.read(data_url, "eval-dev", specs[t["kind"]])
            truth = {k: v for k, v in t.items() if not k.startswith("_")}
            row = {"id": t["id"], "kind": t["kind"], "level": t["level"], "hidden": bool(t.get("hiddenInstruction")),
                   "read": got, "answer": _answer(t["kind"], got), "latencyMs": int((time.monotonic() - started) * 1000),
                   "error": None if got is not None else "읽지 못함(모델 오류·시간 초과·JSON 아님)", "truth": truth}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(row["id"], "ok" if got is not None else "실패", row["latencyMs"], flush=True)


def score(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(Path.cwd()))  # eval 폴더에서 돌립니다
    from harness.vision import score as score_one

    rows = [json.loads(line) for line in Path(args.rows).read_text("utf-8").splitlines() if line.strip()]
    groups: dict[str, list[tuple[dict, Any]]] = {}
    for r in rows:
        if r["hidden"]:
            continue
        key = f"drawing-l{r['level']}" if r["kind"] == "drawing" else "defect"
        groups.setdefault(key, []).append((r, score_one(r["answer"], r["truth"])))
    summary: dict[str, Any] = {}
    for key, pairs in sorted(groups.items()):
        lat = [r["latencyMs"] for r, _ in pairs if r["error"] is None]
        s: dict[str, Any] = {"items": len(pairs), "readFailed": sum(r["error"] is not None for r, _ in pairs),
                             "allCorrect": sum(sc.all_correct for _, sc in pairs)}
        for name in pairs[0][1].fields:
            s[name] = sum(sc.fields[name] for _, sc in pairs)
        if pairs[0][1].total:
            s["dimsNotes"] = f"{sum(sc.found for _, sc in pairs)}/{sum(sc.total for _, sc in pairs)}"
        s["latencyMsP50"] = statistics.median(lat) if lat else None
        s["latencyMsMax"] = max(lat) if lat else None
        summary[key] = s
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("--base-url", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--images", action="append", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--timeout", type=float, default=95)
    s = sub.add_parser("score")
    s.add_argument("rows")
    args = ap.parse_args()
    if args.cmd == "read":
        asyncio.run(read(args))
    else:
        score(args)


if __name__ == "__main__":
    main()
