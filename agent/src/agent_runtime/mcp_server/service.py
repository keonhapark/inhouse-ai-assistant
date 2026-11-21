"""MCP 도구 호출 처리. MCP 프로토콜과 떼어 두어 가짜 erp로 바로 시험합니다.

호출 순서
1. 노출된 도구인지(팩 단계·등록부)
2. 위임 토큰 확인(서명·aud=mcp·만료)
3. 토큰의 tools에 있고, 토큰의 에이전트(agt) 등록부에도 있는 도구인지
4. 신뢰 요구: trust_required=user_direct 도구는 요청 _meta.trustLevel이 user_direct일 때만 부릅니다
5. 입력 스키마 검사
6. erp·rag 호출. 위임 토큰은 erp에는 Authorization, rag에는 X-Delegation-Token 헤더로만 넘깁니다.
   쓰기 도구는 _meta.dryRun=true면 미리보기, 아니면 _meta.idempotencyKey를 Idempotency-Key로 넘겨 실행합니다.

호출마다 감사 이벤트(tool.called, 막으면 tool.blocked)를 남깁니다. 인자는 해시만 남깁니다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from agent_runtime.audit import AuditLog
from agent_runtime.mcp_server.catalog import Catalog, CatalogError, Tool, build_request
from agent_runtime.mcp_server.tokens import Delegation, TokenError, TokenVerifier
from agent_runtime.registry import Registry

TRUST_LEVELS = ("trusted", "untrusted", "user_direct")


@dataclass(frozen=True)
class CallMeta:
    dry_run: bool = False
    idempotency_key: str | None = None
    trust_level: str | None = None

    @classmethod
    def from_meta(cls, meta: dict[str, Any] | None) -> CallMeta:
        meta = meta or {}
        trust = meta.get("trustLevel")
        key = meta.get("idempotencyKey")
        return cls(
            dry_run=meta.get("dryRun") is True,
            idempotency_key=key if isinstance(key, str) else None,
            trust_level=trust if trust in TRUST_LEVELS else None,
        )


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    problem: dict[str, Any] | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return self.data if self.ok else {"problem": self.problem}


class Blocked(Exception):
    def __init__(self, code: str, detail: str, result: str = "denied", audit_detail: str | None = None,
                 errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.result = result
        self.audit_detail = audit_detail  # 감사 기록용(인자 값 없이 이름과 규칙만)
        self.errors = errors


class ToolService:
    def __init__(self, catalog: Catalog, registry: Registry, verifier: TokenVerifier,
                 backends: dict[str, httpx.AsyncClient], audit_log: AuditLog) -> None:
        self.catalog = catalog
        self.registry = registry
        self.verifier = verifier
        self.backends = backends
        self.audit_log = audit_log

    def visible_tools(self, token: str | None) -> list[Tool]:
        """토큰이 맞으면 그 토큰으로 부를 수 있는 도구만, 토큰이 없거나 틀리면 노출된 도구 전부(설명용)."""
        try:
            d = self.verifier.verify(token)
        except TokenError:
            return list(self.catalog.tools)
        return [t for t in self.catalog.tools if self._allowed(d, t.name)]

    async def call(self, name: str, arguments: dict[str, Any] | None, token: str | None,
                   meta: CallMeta) -> ToolResult:
        arguments = arguments or {}
        tool = self.catalog.get(name)
        delegation: Delegation | None = None
        try:
            if tool is None:
                raise Blocked("unknown-tool", f"노출되지 않은 도구입니다: {name}")
            try:
                # JWKS 조회가 동기 HTTP라 이벤트 루프를 막지 않게 스레드에서 합니다.
                delegation = await asyncio.to_thread(self.verifier.verify, token)
            except TokenError as e:
                raise Blocked("unauthorized", str(e)) from None
            if not self._allowed(delegation, name):
                raise Blocked("tool-not-allowed", f"위임 토큰으로 부를 수 없는 도구입니다: {name}")
            if tool.trust_required == "user_direct" and meta.trust_level != "user_direct":
                raise Blocked("trust-required", f"{name}은 사용자가 직접 요청한 경우에만 부릅니다")
            errors = sorted(Draft202012Validator(tool.input_schema, format_checker=FormatChecker())
                            .iter_errors(arguments), key=lambda e: list(e.path))
            if errors:
                found = [_schema_error(e) for e in errors[:10]]
                raise Blocked("validation", "; ".join(e.message for e in errors[:5]), "error",
                              _validation_detail(found), found)
            try:
                req = build_request(tool, arguments)
            except CatalogError as e:
                raise Blocked("validation", str(e), "error") from None
        except Blocked as b:
            problem = {"type": f"urn:problem:{b.code}", "status": 403 if b.result == "denied" else 422,
                       "detail": b.detail}
            if b.errors:
                problem["errors"] = b.errors
            self._audit("tool.blocked", name, tool, arguments, delegation, meta, b.result, problem["type"], None,
                        b.audit_detail)
            return ToolResult(False, problem=problem)

        result = await self._send(tool, req, token or "", meta)
        action_id = result.data.get("actionId") if result.ok else None
        outcome = "ok" if result.ok else _result_for(result.problem)
        self._audit("tool.called", name, tool, arguments, delegation, meta, outcome,
                    None if result.ok else result.problem.get("type"), action_id,
                    None if result.ok else _backend_error_detail(result.problem))
        return result

    def _allowed(self, d: Delegation, name: str) -> bool:
        if name not in d.tools or self.catalog.get(name) is None:
            return False
        try:
            agent = self.registry.get(d.agent_id)
        except KeyError:
            return False
        return name in agent.tools

    async def _send(self, tool: Tool, req, token: str, meta: CallMeta) -> ToolResult:
        op = tool.operation
        headers = {"Authorization": f"Bearer {token}"} if op.service == "erp" else {"X-Delegation-Token": token}
        query = dict(req.query)
        if tool.is_write:
            if meta.dry_run:
                query["dryRun"] = "true"
            elif meta.idempotency_key:
                headers["Idempotency-Key"] = meta.idempotency_key
        try:
            resp = await self.backends[op.service].request(req.method.upper(), req.path, params=query,
                                                           json=req.body, headers=headers)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            return ToolResult(False, problem={"type": "urn:problem:backend-unavailable", "status": 502,
                                              "detail": f"{op.service} 호출 실패({type(e).__name__})"})
        try:
            body = resp.json()
        except ValueError:
            body = None
        if 200 <= resp.status_code < 300:
            return ToolResult(True, data=body if isinstance(body, dict) else {"result": body})
        problem = {k: body[k] for k in ("type", "title", "status", "detail", "errors") if k in body} \
            if isinstance(body, dict) else {}
        problem.setdefault("type", "urn:problem:backend-error")
        problem.setdefault("status", resp.status_code)
        return ToolResult(False, problem=problem)

    def _audit(self, kind: str, name: str, tool: Tool | None, arguments: dict[str, Any],
               d: Delegation | None, meta: CallMeta, result: str, problem_type: str | None,
               action_id: str | None, detail: str | None = None) -> None:
        self.audit_log.write({
            "eventId": str(uuid.uuid4()),
            "occurredAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": "mcp",
            "kind": kind,
            "actor": {
                "employeeId": d.employee_id if d else None,
                "viaDelegationToken": d is not None,
                "delegationTokenId": d.jti if d else None,
                "agentId": d.agent_id if d else None,
            },
            "conversationId": d.conversation_id if d else None,
            "actionId": action_id,
            "operation": name,
            "argsHash": args_hash(arguments),
            "riskLevel": tool.risk if tool else None,
            "trustLevel": meta.trust_level,
            "result": result,
            "problemType": problem_type,
            "detail": "; ".join(x for x in ("dryRun" if (tool and tool.is_write and meta.dry_run) else None, detail)
                                if x) or None,
        })


def args_hash(arguments: dict[str, Any]) -> str:
    raw = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_for(problem: dict[str, Any] | None) -> str:
    status = (problem or {}).get("status")
    if status in (401, 403):
        return "denied"
    if status == 409:
        return "conflict"
    return "error"


def _schema_error(e: Any) -> dict[str, str]:
    """입력 검증 오류 하나를 {field, rule}로. 인자 값은 넣지 않습니다(#426)."""
    field = "/".join(str(p) for p in e.absolute_path) or "(root)"
    if e.validator == "required" and isinstance(e.validator_value, list) and isinstance(e.instance, dict):
        missing = [k for k in e.validator_value if k not in e.instance]
        field = ",".join(missing) or field
    elif e.validator == "additionalProperties" and isinstance(e.instance, dict):
        allowed = set((e.schema or {}).get("properties", {}))
        field = ",".join(sorted(k for k in e.instance if k not in allowed)) or field
    return {"field": field, "rule": str(e.validator)}


def _validation_detail(errors: list[dict[str, str]]) -> str:
    return "입력 검증 실패: " + ", ".join(f"{x['field']}({x['rule']})" for x in errors)


def _backend_error_detail(problem: dict[str, Any] | None) -> str | None:
    """erp·rag 문제 응답의 errors에서 항목 이름만 감사 기록에 남깁니다(값·문장은 넣지 않음)."""
    errors = (problem or {}).get("errors")
    if not isinstance(errors, list):
        return None
    fields = [str(x.get("field")) for x in errors if isinstance(x, dict) and x.get("field")]
    return ("백엔드 검증 실패: " + ", ".join(fields[:10])) if fields else None

