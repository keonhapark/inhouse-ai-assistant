"""응답 본문을 OpenAPI 3.1 컴포넌트 스키마(JSON Schema 2020-12)로 검사합니다."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tools.common import CONTRACTS, load

BASE = "https://inhouse-ai-assistant.invalid/contracts/"


def _registry() -> Registry:
    reg = Registry()
    for rel in ["openapi/erp.yaml", "openapi/gateway.yaml", "openapi/agent.yaml", "openapi/rag.yaml",
                "events/audit.schema.json", "events/trace.schema.json", "auth/delegation-token.schema.json",
                "eval/scenario.schema.json", "eval/report.schema.json", "pack/pack.schema.json", "mcp/tools.schema.json"]:
        doc = load(CONTRACTS / rel)
        reg = reg.with_resource(BASE + rel, Resource.from_contents(doc, default_specification=DRAFT202012))
    return reg


REGISTRY = _registry()


def validate(spec: str, schema_name: str, instance: Any) -> None:
    """spec 예: 'openapi/erp.yaml', schema_name 예: 'ApprovalDocument'. 틀리면 AssertionError."""
    ref = {"$ref": f"{BASE}{spec}#/components/schemas/{schema_name}"}
    errors = list(Draft202012Validator(ref, registry=REGISTRY).iter_errors(instance))
    assert not errors, f"{schema_name} 스키마 위반: " + "; ".join(
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:5])


def validate_file(rel: str, instance: Any) -> None:
    errors = list(Draft202012Validator({"$ref": BASE + rel}, registry=REGISTRY).iter_errors(instance))
    assert not errors, f"{rel} 위반: " + "; ".join(e.message for e in errors[:5])
