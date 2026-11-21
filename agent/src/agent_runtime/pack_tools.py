"""팩 양식 도구(#397). 규칙은 contracts/mcp/README.md '팩 양식 도구', 참조 구현은 contracts/tools/pack_tools.py입니다.

팩 forms.yaml 양식의 `tool` 항목에서 tools.json 형식의 도구를 만듭니다. MCP 카탈로그와 평가 경로가 공용 도구와 합쳐 씁니다.
"""

from __future__ import annotations

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
            "description": t["description"],
            "inputSchema": strip_x(f["fields"]),
            "risk": t.get("risk", "reversible_write"),
            "trust_required": t.get("trust_required", "user_direct"),
            "required_scope": f"approval:request:{f['id']}",
            "backend": {"service": "erp", "operationId": "createApprovalDocument", "fixed": {"formId": f["id"]}},
            "stage": t.get("stage", f["stage"]),
        })
    return tuple(out)
