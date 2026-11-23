"""팩 양식 도구(#397). 규칙은 contracts/mcp/README.md '팩 양식 도구', 참조 구현은 contracts/tools/pack_tools.py입니다.

팩 forms.yaml 양식의 `tool` 항목에서 tools.json 형식의 도구를 만듭니다. MCP 카탈로그와 평가 경로가 공용 도구와 합쳐 씁니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def strip_x(node: Any) -> Any:
    """JSON Schema에서 `x-`로 시작하는 키(화면용 이름 등)를 뺍니다."""
    if isinstance(node, dict):
        return {k: strip_x(v) for k, v in node.items() if not str(k).startswith("x-")}
    if isinstance(node, list):
        return [strip_x(v) for v in node]
    return node


def form_tools(forms_doc: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    out = []
    for f in (forms_doc or {}).get("forms", []):
        t = f.get("tool")
        if not t:
            continue
        out.append({
            "name": t["name"],
            "displayName": t.get("displayName") or f"{f['name']} 상신",  # 도구 표시 이름(#575)
            "description": t["description"],
            "inputSchema": strip_x(f["fields"]),
            "risk": t.get("risk", "reversible_write"),
            "trust_required": t.get("trust_required", "user_direct"),
            "required_scope": f"approval:request:{f['id']}",
            "backend": {"service": "erp", "operationId": "createApprovalDocument", "fixed": {"formId": f["id"]}},
            "stage": t.get("stage", f["stage"]),
        })
    return tuple(out)


def tool_labels(tools_file: Path, pack_dir: Path, pack_form_tools: tuple[dict[str, Any], ...] = ()) -> dict[str, str]:
    """도구 이름 → 직원 화면 표시 이름(#575). 순서: pack.yaml tool_display_names > 양식 tool.displayName >
    tools.json displayName(contracts/mcp/README.md '도구 표시 이름')."""
    import json

    import yaml

    labels = {t["name"]: t["displayName"] for t in json.loads(tools_file.read_text("utf-8"))["tools"]
              if t.get("displayName")}
    labels.update({t["name"]: t["displayName"] for t in pack_form_tools if t.get("displayName")})
    pack = yaml.safe_load((pack_dir / "pack.yaml").read_text("utf-8")) or {}
    labels.update(pack.get("tool_display_names") or {})
    return labels

