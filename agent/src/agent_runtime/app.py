"""agent HTTP API(contracts/openapi/agent.yaml): /health, /agents, /route, /run, /resume.

환경 변수
- PACK_DIR: 업종 팩 폴더(필수)
- AGENT_AUDIT_LOG: 감사 이벤트 JSON Lines 경로(기본 var/audit.jsonl)
- AGENT_ROUTER_MIN_CONFIDENCE: LLM 라우터 확신도 기준(기본 0.5)
- AGENT_LLM_BACKEND, GATEWAY_LLM_URL, AGENT_LLM_MODEL, AGENT_OLLAMA_BASE_URL: llm.LLMSettings 참고
- AGENT_MCP_URL: 업무 실행이 부르는 MCP 서버(기본 http://localhost:$MCP_PORT/mcp, MCP_PORT 기본 8001)
- DELEGATION_TOKEN_PUBLIC_KEY 또는 DELEGATION_JWKS_URL: 있으면 /run·/resume에서 토큰의 에이전트·요청자·대화를 대조
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from agent_runtime import audit
from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.router import Router
from agent_runtime.run.graph import Deps, build_graph
from agent_runtime.run.policy import WideScope
from agent_runtime.run.runner import Conflict, Runner
from agent_runtime.run.tools import McpToolCaller
from agent_runtime.run.trust import trusted_docs


class RequesterIn(BaseModel):
    employeeId: str
    unitId: str
    grade: str
    roles: list[str]

    def to_domain(self) -> Requester:
        return Requester(self.employeeId, self.unitId, self.grade, tuple(self.roles))


class RouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    requester: RequesterIn
    method: Literal["llm", "keyword"] = "llm"


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    modelPolicy: Literal["external_allowed", "local_only"]


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str
    agentId: str
    message: str
    requester: RequesterIn
    condition: Literal["no_guard", "write_blocked", "approve_all", "baseline_tools", "full"] = "full"


class ResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str
    approvalId: str
    decision: Literal["approve", "reject"]
    comment: str | None = None


class RouteOut(BaseModel):
    agentId: str
    method: Literal["llm", "keyword", "fallback", "explicit"]
    reason: str
    confidence: float | None = None
    suggestedAgentId: str | None = None


@dataclass
class Services:
    registry: Registry
    router: Router
    audit_log: audit.AuditLog
    runner: Runner | None = None


def services_from_env() -> Services:
    pack_dir = os.environ.get("PACK_DIR")
    if not pack_dir:
        raise RuntimeError("PACK_DIR 환경 변수가 필요합니다(예: ../packs/manufacturing)")
    registry = Registry.load(Path(pack_dir))
    chat = ChatClient(LLMSettings.from_env())
    min_conf = float(os.environ.get("AGENT_ROUTER_MIN_CONFIDENCE", "0.5"))
    log = audit.AuditLog(Path(os.environ.get("AGENT_AUDIT_LOG", "var/audit.jsonl")))
    mcp_url = os.environ.get("AGENT_MCP_URL", f"http://localhost:{os.environ.get('MCP_PORT', '8001')}/mcp")
    deps = Deps(llm=chat, caller=McpToolCaller(mcp_url), audit=log, wide=WideScope.from_pack(Path(pack_dir)),
                trusted_docs=trusted_docs(Path(pack_dir)))
    try:
        verifier: TokenVerifier | None = TokenVerifier.from_env()
    except RuntimeError:
        verifier = None
    runner = Runner(registry, build_graph(deps), deps.caller, verifier)
    return Services(registry, Router(registry, chat, min_conf), log, runner)


def create_app(services: Services | None = None) -> FastAPI:
    svc = services or services_from_env()
    app = FastAPI(title="agent", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agents")
    def list_agents() -> dict[str, list[AgentInfo]]:
        return {"items": [
            AgentInfo(id=a.id, name=a.name, description=a.description, modelPolicy=a.model_policy)
            for a in svc.registry.agents
        ]}

    @app.post("/route", response_model=RouteOut)
    def route(body: RouteIn) -> RouteOut:
        requester = body.requester.to_domain()
        decision = svc.router.route(body.message, requester, body.method)
        svc.audit_log.write(audit.route_decided(decision, requester))
        return RouteOut(**decision.to_api())

    def _runner() -> Runner:
        if svc.runner is None:
            raise HTTPException(503, "업무 실행이 설정되지 않았습니다")
        return svc.runner

    @app.post("/run")
    async def run(body: RunIn, x_delegation_token: str = Header(...)) -> dict:
        return await _runner().run(x_delegation_token, body.conversationId, body.agentId, body.message,
                                   body.requester.to_domain(), body.condition)

    @app.post("/resume")
    async def resume(body: ResumeIn, x_delegation_token: str = Header(...)) -> dict:
        try:
            return await _runner().resume(x_delegation_token, body.conversationId, body.approvalId, body.decision)
        except Conflict as e:
            raise HTTPException(409, str(e)) from None

    return app
