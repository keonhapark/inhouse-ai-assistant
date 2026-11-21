"""도구 호출 확인 묶음(toolcall-v1) 실행 기록의 공개 사본을 만듭니다(eval/protocol.md 7절).

확인 묶음 문항은 저장소에 넣지 않습니다. 회차 기록의 `result`(모델이 만든 도구 인자), `mismatched`(틀린 인자 이름),
`schema_errors`에는 문항 내용이 드러나므로 빼고, `error`는 상태 코드만 남깁니다. 보고서(`.md`)는 집계만 남기고
"인자 틀림" 목록을 뺍니다. 가린 JSON의 `meta.notes`에 원본 두 파일의 sha256을 적고, 원본은 저장소 밖에 둡니다.

    uv run python tools/mask_toolcall.py --items <묶음>/items.jsonl --run <원본 이름> --out reports/toolcall/<이름> \\
        [--note "보고서 메모 한 줄"]...

가린 뒤 세 파일 어디에든 문항의 발화나 기대 인자·setup의 문자열 값(4자 이상)이 남으면 쓰지 않고 멈춥니다.
문항 내용은 출력하지 않습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import toolcall_report  # noqa: E402

DROP = ("result", "mismatched", "schema_errors")
MIN_LEN = 4


def public_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in DROP}
    if out.get("error") is not None:
        out["error"] = f"실행 오류(HTTP {row.get('status')})"
    return out


def item_strings(items_file: Path) -> set[str]:
    """문항에서 공개 사본에 남으면 안 되는 문자열: 발화와 기대 인자·대안·setup의 문자열 값."""
    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, str):
            if len(v) >= MIN_LEN:
                found.add(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for line in items_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        walk(item.get("utterance"))
        walk((item.get("expected") or {}).get("args"))
        walk([a.get("args") for a in item.get("alsoAcceptable") or []])
        walk(item.get("setup"))
    return found


# 공개 식별자(도구 이름, 에이전트 ID, 유형·결과 값 등)는 대조 전에 지웁니다. 기대 인자 값이 우연히 그 일부일 수
# 있어서입니다(예: 값 "purchase"와 도구 이름 "purchase_request").
PUBLIC_FIELDS = ("id", "agentId", "target_tool", "tool", "category", "expected_type", "outcome", "model", "location")


def public_tokens(rows: list[dict[str, Any]]) -> set[str]:
    from harness.paths import CONTRACTS

    tools = json.loads((CONTRACTS / "mcp" / "tools.json").read_text(encoding="utf-8"))["tools"]
    names = set(tools) if isinstance(tools, dict) else {t["name"] for t in tools}
    return names | {str(r[k]) for r in rows for k in PUBLIC_FIELDS if r.get(k) is not None}


def leftovers(text: str, strings: set[str], public: set[str] = frozenset()) -> int:
    for token in sorted(public, key=len, reverse=True):
        text = text.replace(token, " ")
    return sum(1 for s in strings if s in text or json.dumps(s)[1:-1] in text)


def without_wrong_args(md: str) -> str:
    """보고서에서 "인자 틀림" 목록(항목·도구·틀린 인자 이름) 절을 뺍니다."""
    head, sep, _ = md.partition("\n## 인자 틀림\n")
    return head.rstrip("\n") + "\n" if sep else md


def mask_run(items: Path, run: Path, out: Path, notes: list[str]) -> dict[str, str]:
    src_json, src_rows = run.with_suffix(".json"), run.with_suffix(".rows.jsonl")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (src_json, src_rows)}
    data = json.loads(src_json.read_text(encoding="utf-8"))
    meta = data["meta"]
    meta["notes"] = [*meta.get("notes", []), *notes,
                     "회차 기록(.json·.rows.jsonl)은 문항 내용이 드러나는 result·mismatched·schema_errors를 빼고 error는 "
                     "상태 코드만 남긴 공개 사본입니다(eval/tools/mask_toolcall.py). 보고서에서 인자 틀림 목록을 뺐습니다. "
                     "원본은 저장소 밖에 둡니다: " + ", ".join(f"{n} sha256 {h}" for n, h in hashes.items())]
    md = without_wrong_args(toolcall_report.render(data["rows"], meta, meta.get("title", "도구 호출 측정")))
    data["rows"] = [public_row(r) for r in data["rows"]]
    json_text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    rows_text = "".join(json.dumps(public_row(json.loads(line)), ensure_ascii=False) + "\n"
                        for line in src_rows.read_text(encoding="utf-8").splitlines() if line.strip())
    strings = item_strings(items)
    public = public_tokens(data["rows"])
    left = sum(leftovers(t, strings, public) for t in (json_text, rows_text, md))
    if left:
        raise SystemExit(f"공개 사본에 문항 문자열 {left}개가 남았습니다. 쓰지 않습니다")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json_text, encoding="utf-8")
    out.with_suffix(".rows.jsonl").write_text(rows_text, encoding="utf-8")
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    return hashes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--items", required=True, type=Path)
    ap.add_argument("--run", required=True, type=Path, help="원본 실행 기록 이름(확장자 없이)")
    ap.add_argument("--out", required=True, type=Path, help="공개 사본 이름(확장자 없이)")
    ap.add_argument("--note", action="append", default=[], help="meta.notes에 더할 한 줄")
    args = ap.parse_args(argv)
    if args.run.resolve() == args.out.resolve():
        raise SystemExit("원본과 같은 이름으로는 쓰지 않습니다")
    hashes = mask_run(args.items, args.run, args.out, args.note)
    print("공개 사본을 썼습니다. 원본 " + ", ".join(f"{n} {h}" for n, h in hashes.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
