"""계약 검사 도구가 같이 쓰는 경로와 읽기 함수."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CONTRACTS = Path(__file__).resolve().parents[1]
ROOT = CONTRACTS.parent
PACKS = ROOT / "packs"


def load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def openapi_operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ops: dict[str, dict[str, Any]] = {}
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if isinstance(op, dict) and "operationId" in op:
                ops[op["operationId"]] = {**op, "_path": path, "_method": method}
    return ops
