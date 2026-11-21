"""모델이 낸 도구 인자를 입력 스키마에 맞게 가볍게 정리합니다(#426).

- 필수가 아닌 항목이 null이거나 빈 문자열이면 뺍니다(모델이 모르는 선택 항목을 ""로 채워 형식 검사에 막히던 것)
- 정수 항목에 "15,000"·"15000원"처럼 숫자만 든 문자열이 오면 정수로 바꿉니다
최상위 항목만 봅니다. 그 밖의 형식 오류는 MCP 입력 검증이 잡아 모델에 돌려줍니다.
"""

from __future__ import annotations

import re
from typing import Any

_INT_TEXT = re.compile(r"^\s*-?\d{1,3}(,\d{3})+\s*(원)?\s*$|^\s*-?\d+\s*(원)?\s*$")


def normalize_args(args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k not in required and (v is None or (isinstance(v, str) and not v.strip())):
            continue
        if _is_integer(props.get(k)) and isinstance(v, str) and _INT_TEXT.match(v):
            v = int(re.sub(r"[^\d-]", "", v))
        out[k] = v
    return out


def optional_args(schema: dict[str, Any]) -> list[str]:
    required = set(schema.get("required") or [])
    return [k for k in (schema.get("properties") or {}) if k not in required]


def _is_integer(prop: Any) -> bool:
    if not isinstance(prop, dict):
        return False
    t = prop.get("type")
    return t == "integer" or (isinstance(t, list) and "integer" in t)
