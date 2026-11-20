"""dbAssertions 판정: 대화 직후, 되돌리기 전 erp 상태를 조회해 봅니다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonpath

from harness.erp import ErpClient
from harness.scenario import substitute


@dataclass
class AssertionResult:
    index: int
    ok: bool
    detail: str


def evaluate(op: str, matches: list[Any], value: Any = None) -> bool:
    """jsonPath가 찾은 값 목록(matches)에 연산을 적용합니다.

    - equals: 하나 이상 찾았고 모두 value와 같음
    - not_equals: 찾은 값 중 value와 같은 것이 없음(못 찾으면 참)
    - exists / not_exists: 찾은 것이 있음 / 없음
    - count_equals / count_gte: 찾은 개수. 목록 원소를 세려면 `$.items[*]`처럼 씁니다
    """
    if op == "equals":
        return bool(matches) and all(m == value for m in matches)
    if op == "not_equals":
        return all(m != value for m in matches)
    if op == "exists":
        return bool(matches)
    if op == "not_exists":
        return not matches
    if op == "count_equals":
        return len(matches) == value
    if op == "count_gte":
        return len(matches) >= value
    raise ValueError(f"모르는 연산: {op}")


def check_db(assertions: list[dict[str, Any]], erp: ErpClient,
             variables: dict[str, str] | None = None) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for i, a in enumerate(assertions):
        a = substitute(a, variables or {})
        r = erp.call(a["as"], a["operation"], a.get("params"))
        if r.status_code == 404 and a["op"] == "not_exists":
            results.append(AssertionResult(i, True, "404: 없음"))
            continue
        if r.status_code >= 300:
            results.append(AssertionResult(i, False, f"{a['operation']} 조회 실패 {r.status_code}"))
            continue
        matches = jsonpath.findall(a["jsonPath"], r.json())
        ok = evaluate(a["op"], matches, a.get("value"))
        results.append(AssertionResult(i, ok, f"{a['jsonPath']} {a['op']} {a.get('value')!r}: "
                                              f"찾은 것 {len(matches)}개"))
    return results
