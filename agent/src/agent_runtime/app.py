"""agent HTTP API(contracts/openapi/agent.yaml): /health, /agents, /route.

환경 변수
- PACK_DIR: 업종 팩 폴더(필수)
- AGENT_AUDIT_LOG: 감사 이벤트 JSON Lines 경로(기본 var/audit.jsonl)
- AGENT_ROUTER_MIN_CONFIDENCE: LLM 라우터 확신도 기준(기본 0.5)
- AGENT_LLM_BACKEND, GATEWAY_LLM_URL, AGENT_LLM_MODEL, AGENT_OLLAMA_BASE_URL: llm.LLMSettings 참고
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from agent_runtime import audit
from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.router import Router


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


def services_from_env() -> Services:
    pack_dir = os.environ.get("PACK_DIR")
    if not pack_dir:
        raise RuntimeError("PACK_DIR 환경 변수가 필요합니다(예: ../packs/manufacturing)")
    registry = Registry.load(Path(pack_dir))
    chat = ChatClient(LLMSettings.from_env())
    min_conf = float(os.environ.get("AGENT_ROUTER_MIN_CONFIDENCE", "0.5"))
    log = audit.AuditLog(Path(os.environ.get("AGENT_AUDIT_LOG", "var/audit.jsonl")))
    return Services(registry, Router(registry, chat, min_conf), log)


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

    return app
