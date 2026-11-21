"""확인 셋 실행 기록에서 표지 문자열을 가린 사본을 만듭니다(eval/protocol.md 7절).

확인 셋 내용은 저장소에 넣지 않습니다. 그런데 사고 기록(`incidents`)에는 찾은 표지 문자열이 그대로 남습니다.
이 스크립트는 `<이름>.json`·`<이름>.rows.jsonl`의 모든 문자열 값에서 표지를 `[표지 <sha256 앞 12자>]`로 바꾸고,
시나리오 판정 기준이 문장으로 남는 곳(dbAssertions 미달의 경로·값, 근거 문서 ID, 필수 도구 이름)도 가린 사본을 씁니다. 가린 JSON의 `meta.notes`에는 원본 두 파일의 sha256을 적습니다. 원본은 저장소 밖에 둡니다.

    uv run python tools/mask_markers.py --bundle <묶음 폴더> --run <원본 이름> --out reports/<이름> \\
        [--note "보고서 메모 한 줄"]...

이름은 확장자를 뺀 경로입니다(예: `reports/2026-11-22-confirm-v1`). 표지는 묶음 시나리오의 `expect.markers`와
묶음의 표지 파일(`markers.json`·`markers.yaml`)에서 모읍니다. 가린 뒤 파일 어디에든 표지가 남으면 쓰지 않고
멈춥니다. 표지 문자열은 출력하지 않습니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.scenario import load_scenarios  # noqa: E402

MARKER_FILES = ("markers.json", "markers.yaml", "markers.yml")
# 판정 기준이 문장으로 남는 곳(harness/judge.py): dbAssertions 미달("dbAssertions[0] <경로> <비교> <값>: ...")과
# 근거 문서 미달("근거에 <문서 ID>가 없음"). 항목 번호만 남깁니다.
CRITERIA = ((re.compile(r"dbAssertions\[(\d+)\] .*", re.S), r"dbAssertions[\1] 판정 기준 미달(기준 문장 가림)"),
            (re.compile(r"근거에 .+가 없음$", re.S), "근거에 [가림]가 없음"))
# 필수 도구 미달("필수 도구 <이름>를 실행하지 않음")은 기대 도구를 드러내므로 목록마다 개수만 남깁니다(#512)
REQUIRED_TOOL = re.compile(r"필수 도구 \S+를 실행하지 않음")
CRITERIA_LEFT = re.compile(r"dbAssertions\[\d+\] (?!판정 기준 미달\(기준 문장 가림\))|근거에 (?!\[가림\]가 없음)"
                           r"|필수 도구 \S+를 실행하지 않음")


def token(marker: str) -> str:
    return f"[표지 {hashlib.sha256(marker.encode()).hexdigest()[:12]}]"


def collect_markers(bundle: Path) -> list[str]:
    """긴 표지부터 바꾸도록 길이 내림차순으로 돌려줍니다(다른 표지를 품은 표지)."""
    import yaml

    found: set[str] = set()
    for s in load_scenarios(bundle / "scenarios"):
        found.update(s.get("expect", {}).get("markers", []))
    for name in MARKER_FILES:
        p = bundle / name
        if p.is_file():
            data = yaml.safe_load(p.read_text(encoding="utf-8"))  # JSON도 YAML로 읽힘
            for values in data.get("markers", {}).values():
                found.update(values)
    return sorted(found, key=lambda m: (-len(m), m))


def mask_text(text: str, markers: list[str]) -> str:
    for m in markers:
        text = text.replace(m, token(m))
    for pattern, repl in CRITERIA:
        text = pattern.sub(repl, text)
    return text


def mask_value(value: Any, markers: list[str]) -> Any:
    if isinstance(value, str):
        return mask_text(value, markers)
    if isinstance(value, list):
        n = sum(1 for v in value if isinstance(v, str) and REQUIRED_TOOL.fullmatch(v))
        out = [mask_value(v, markers) for v in value if not (isinstance(v, str) and REQUIRED_TOOL.fullmatch(v))]
        return ([f"필수 도구 미실행({n}개)"] if n else []) + out
    if isinstance(value, dict):
        return {mask_text(k, markers): mask_value(v, markers) for k, v in value.items()}
    return value


def leftovers(text: str, markers: list[str]) -> int:
    """원문 그대로나 JSON 이스케이프된 꼴로 남은 표지 수와 가리지 않은 판정 기준 문장 수."""
    return (sum(1 for m in markers if m in text or json.dumps(m)[1:-1] in text)
            + len(CRITERIA_LEFT.findall(text)))


def mask_run(bundle: Path, run: Path, out: Path, notes: list[str], allow_no_markers: bool = False) -> dict[str, str]:
    markers = collect_markers(bundle)
    if not markers and not allow_no_markers:
        raise SystemExit("묶음에서 표지를 하나도 찾지 못했습니다(표지가 없는 정상 셋 묶음이면 --allow-no-markers)")
    src_json, src_rows = run.with_suffix(".json"), run.with_suffix(".rows.jsonl")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (src_json, src_rows)}
    data = mask_value(json.loads(src_json.read_text(encoding="utf-8")), markers)
    data["meta"]["notes"] = [*data["meta"].get("notes", []), *notes,
                             ("회차 기록(.json·.rows.jsonl)은 확인 셋 표지 문자열을 `[표지 <sha256 앞 12자>]`로, 판정 기준 "
                              if markers else "회차 기록(.json·.rows.jsonl)은 판정 기준 ")
                             + "문장(dbAssertions 미달, 근거 문서 ID, 필수 도구 이름)을 항목 번호·개수만 남겨 가린 사본입니다"
                             "(eval/tools/mask_markers.py). 가리지 않은 원본은 저장소 밖에 둡니다: "
                             + ", ".join(f"{n} sha256 {h}" for n, h in hashes.items())]
    json_text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    rows_text = "".join(json.dumps(mask_value(json.loads(line), markers), ensure_ascii=False) + "\n"
                        for line in src_rows.read_text(encoding="utf-8").splitlines() if line.strip())
    left = leftovers(json_text, markers) + leftovers(rows_text, markers)
    if left:
        raise SystemExit(f"가린 뒤에도 표지 {left}개가 남았습니다. 쓰지 않습니다")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json_text, encoding="utf-8")
    out.with_suffix(".rows.jsonl").write_text(rows_text, encoding="utf-8")
    return hashes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--run", required=True, type=Path, help="원본 실행 기록 이름(확장자 없이)")
    ap.add_argument("--out", required=True, type=Path, help="가린 사본 이름(확장자 없이)")
    ap.add_argument("--note", action="append", default=[], help="meta.notes에 더할 한 줄")
    ap.add_argument("--allow-no-markers", action="store_true", help="표지가 없는 묶음(정상 셋 v2 등): 판정 기준 문장만 가림")
    args = ap.parse_args(argv)
    if args.run.resolve() == args.out.resolve():
        raise SystemExit("원본과 같은 이름으로는 쓰지 않습니다")
    hashes = mask_run(args.bundle, args.run, args.out, args.note, args.allow_no_markers)
    print(f"표지 {len(collect_markers(args.bundle))}개를 가렸습니다. 원본 " +
          ", ".join(f"{n} {h}" for n, h in hashes.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
