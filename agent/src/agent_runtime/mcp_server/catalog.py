"""MCP 도구 목록(contracts/mcp/tools.json)과 erp·rag OpenAPI에서 도구별 호출 방법을 만듭니다.

도구 이름·설명·입력 스키마는 tools.json 그대로 내놓습니다. 노출 범위는 팩이 정합니다:
팩 단계 이하이고, 켜진 에이전트 중 하나라도 등록부에 그 도구를 적었을 때만 노출합니다.

도구 인자를 HTTP 요청에 놓는 규칙(인자 이름으로 정함)
- operation의 path 파라미터 이름이면 경로에, query 파라미터 이름이면 쿼리에 넣습니다.
- 요청 본문 스키마의 최상위 속성이면 본문에 넣습니다.
- 본문의 객체 속성(예: 대결 위임의 `scope`) 안에 있는 속성 이름이면 그 객체 안에 넣습니다.
- 그 밖의 인자는 본문 스키마에 `fields`가 있으면 `fields` 안에 넣습니다(결재 양식 필드).
- backend.fixed 값도 같은 규칙으로 놓고, 같은 이름이면 고정값이 이깁니다(고정값 이름은 입력 스키마에 둘 수 없음).
- 경로 인자는 퍼센트 인코딩합니다(`?`, `#`, `/`가 경로를 바꾸지 못하게).
"""

from __future__ import annotations

import json
from urllib.parse import quote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from agent_runtime.registry import Registry


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Operation:
    service: Literal["erp", "rag"]
    operation_id: str
    method: str
    path: str
    path_params: frozenset[str]
    query_params: frozenset[str]
    body_props: frozenset[str]
    nested_props: tuple[tuple[str, str], ...]  # (안쪽 속성, 바깥 객체 속성)
    body_has_fields: bool
    write: bool
    human_only: bool
    required_scope: str | None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: Literal["read", "reversible_write", "irreversible"]
    trust_required: Literal["any", "user_direct"]
    required_scope: str
    stage: int
    fixed: dict[str, Any]
    operation: Operation

    @property
    def is_write(self) -> bool:
        return self.operation.write


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None


def build_request(tool: Tool, arguments: dict[str, Any]) -> Request:
    op = tool.operation
    path = op.path
    query: dict[str, Any] = {}
    body: dict[str, Any] = {}
    form_fields: dict[str, Any] = {}
    nested = dict(op.nested_props)
    merged = {**arguments, **tool.fixed}
    for name, value in merged.items():
        if name in op.path_params:
            path = path.replace("{" + name + "}", _path_segment(value))
        elif name in op.query_params:
            query[name] = _query_value(value)
        elif name in op.body_props:
            body[name] = value
        elif name in nested:
            body.setdefault(nested[name], {})[name] = value
        elif op.body_has_fields:
            form_fields[name] = value
        else:
            raise CatalogError(f"{tool.name}: 인자 '{name}'를 {op.operation_id} 요청에 놓을 곳이 없습니다")
    if form_fields:
        body["fields"] = form_fields
    has_body = op.method in ("post", "put", "patch")
    return Request(op.method, path, query, body if has_body else None)


def _path_segment(value: Any) -> str:
    s = str(value)
    if not s or s in (".", ".."):
        raise CatalogError("경로 인자 값이 올바르지 않습니다")
    return quote(s, safe="")


def _query_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


@dataclass(frozen=True)
class Catalog:
    version: str
    tools: tuple[Tool, ...]

    def get(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)

    @classmethod
    def load(cls, tools_file: Path, openapi_dir: Path, registry: Registry) -> Catalog:
        doc = json.loads(tools_file.read_text("utf-8"))
        specs = {s: _read_spec(openapi_dir / f"{s}.yaml") for s in ("erp", "rag")}
        exposed = {name for a in registry.agents for name in a.tools}
        tools = []
        for t in doc["tools"]:
            if t["name"] not in exposed:
                continue
            if t["stage"] > registry.pack_stage:
                raise CatalogError(f"{t['name']}: 단계 {t['stage']} 도구가 단계 {registry.pack_stage} 등록부에 있습니다")
            backend = t["backend"]
            clash = set(backend.get("fixed", {})) & set(t["inputSchema"].get("properties", {}))
            if clash:
                raise CatalogError(f"{t['name']}: 고정값 이름을 입력 스키마에 둘 수 없습니다: {', '.join(sorted(clash))}")
            op = _operation(specs[backend["service"]], backend["service"], backend["operationId"])
            if op.human_only:
                raise CatalogError(f"{t['name']}: 사람 화면 전용 operation({op.operation_id})은 도구로 노출하지 않습니다")
            tools.append(Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["inputSchema"],
                risk=t["risk"],
                trust_required=t["trust_required"],
                required_scope=t["required_scope"],
                stage=t["stage"],
                fixed=dict(backend.get("fixed", {})),
                operation=op,
            ))
        missing = exposed - {t["name"] for t in doc["tools"]}
        if missing:
            raise CatalogError(f"등록부에 있지만 tools.json에 없는 도구: {', '.join(sorted(missing))}")
        return cls(doc["version"], tuple(tools))


def _read_spec(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _operation(spec: dict[str, Any], service: Literal["erp", "rag"], operation_id: str) -> Operation:
    base = _base_path(spec)
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if not isinstance(op, dict) or op.get("operationId") != operation_id:
                continue
            params = [_resolve(spec, p) for p in [*item.get("parameters", []), *op.get("parameters", [])]]
            body_schema = _body_schema(spec, op)
            props = body_schema.get("properties", {}) if body_schema else {}
            nested = []
            for outer, sub in props.items():
                sub_props = _resolve(spec, sub).get("properties", {})
                nested.extend((inner, outer) for inner in sub_props)
            return Operation(
                service=service,
                operation_id=operation_id,
                method=method,
                path=base + path,
                path_params=frozenset(p["name"] for p in params if p["in"] == "path"),
                # dryRun은 도구 인자가 아니라 호출 방식으로 정합니다(service.py).
                query_params=frozenset(p["name"] for p in params if p["in"] == "query" and p["name"] != "dryRun"),
                body_props=frozenset(k for k in props if k != "fields"),
                nested_props=tuple(nested),
                body_has_fields="fields" in props,
                write=bool(op.get("x-write", False)),
                human_only=bool(op.get("x-human-only", False)),
                required_scope=op.get("x-required-scope"),
            )
    raise CatalogError(f"{service} 계약에 operationId '{operation_id}'가 없습니다")


def _base_path(spec: dict[str, Any]) -> str:
    """servers[0].url의 경로 부분(erp는 /api/v1, rag는 없음)."""
    url = spec.get("servers", [{}])[0].get("url", "")
    rest = url.split("://", 1)[-1]
    return "/" + rest.split("/", 1)[1] if "/" in rest else ""


def _resolve(spec: dict[str, Any], obj: dict[str, Any]) -> dict[str, Any]:
    ref = obj.get("$ref")
    if not ref:
        return obj
    if not ref.startswith("#/"):
        raise CatalogError(f"외부 $ref는 다루지 않습니다: {ref}")
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node[part]
    return _resolve(spec, node)


def _body_schema(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
    rb = op.get("requestBody")
    if not rb:
        return None
    schema = _resolve(spec, rb).get("content", {}).get("application/json", {}).get("schema")
    return _resolve(spec, schema) if schema else None
