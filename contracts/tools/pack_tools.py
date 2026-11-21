"""팩 양식 도구(#397): forms.yaml 양식의 `tool` 항목에서 tools.json 형식의 도구를 만듭니다.

규칙(contracts/mcp/README.md '팩 양식 도구'와 같음). agent MCP 카탈로그와 gateway 위임 토큰 계산이 같은 규칙을 씁니다.
- name·description: 양식 `tool`의 값
- inputSchema: 양식 `fields`(JSON Schema)에서 `x-`로 시작하는 키를 뺀 것
- risk: `tool.risk`(기본 reversible_write), trust_required: `tool.trust_required`(기본 user_direct)
- required_scope: `approval:request:<양식 id>`
- backend: erp `createApprovalDocument`, fixed `{formId: <양식 id>}`
- stage: `tool.stage`, 없으면 양식 stage
"""

from __future__ import annotations

from typing import Any


def strip_x(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: strip_x(v) for k, v in node.items() if not str(k).startswith("x-")}
    if isinstance(node, list):
        return [strip_x(v) for v in node]
    return node


def form_tools(forms_doc: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in forms_doc.get("forms", []):
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
    return out
