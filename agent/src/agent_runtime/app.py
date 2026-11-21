"""agent HTTP API(contracts/openapi/agent.yaml): /health, /agents, /route, /run, /resume, /baseline/slots, /eval/tool-call.

환경 변수
- PACK_DIR: 업종 팩 폴더(필수)
- AGENT_PACK_STAGE: 켤 단계(기본 pack.yaml의 stage). 에이전트·도구 모두 이 단계 이하만 켭니다
- AGENT_AUDIT_LOG: 감사 이벤트 JSON Lines 경로(기본 var/audit.jsonl)
- AGENT_ROUTER_MIN_CONFIDENCE: LLM 라우터 확신도 기준(기본 0.5)
- AGENT_LLM_BACKEND, GATEWAY_LLM_URL, AGENT_LLM_MODEL, AGENT_OLLAMA_BASE_URL: llm.LLMSettings 참고
- AGENT_MCP_URL: 업무 실행이 부르는 MCP 서버(기본 http://localhost:$MCP_PORT/mcp, MCP_PORT 기본 8001)
- DELEGATION_TOKEN_PUBLIC_KEY 또는 DELEGATION_JWKS_URL(필수): /run·/resume에서 토큰의 에이전트·요청자·대화를 대조.
  AGENT_ALLOW_UNVERIFIED_TOKENS=1이면 대조하지 않습니다(개발용)
- AGENT_EVAL_MODE=1: 평가 경로 /eval/tool-call을 켭니다(아니면 404). AGENT_EVAL_FEWSHOT: few-shot 예시 파일
  (기본 eval_dev/tool_calls.jsonl, 작업 폴더 기준)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent_runtime import audit
from agent_runtime.baseline.llm_filler import LlmSlotFiller, load_slot_tools
from agent_runtime.baseline.slots import KST, RuleSlotFiller, SlotFiller
from agent_runtime.evaluation.tool_call import (EvalBadRequest, EvalToolCaller, EvalUpstreamError, Variant,
                                                load_examples, load_tools)
from agent_runtime.llm import ChatClient, LLMSettings
from agent_runtime.registry import Registry, Requester
from agent_runtime.mcp_server.tokens import TokenVerifier
from agent_runtime.router import Router
from agent_runtime.run.graph import Deps, build_graph
from agent_runtime.run.policy import WideScope
from agent_runtime.run.receipt import ReceiptReader
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


class AttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image"]
    # 계약의 한 장 5MB(디코딩 크기)를 base64로 바꾼 길이에 접두사 여유를 더한 상한입니다.
    dataUrl: str = Field(pattern=r"^data:image/(jpeg|png);base64,", max_length=7_000_100)


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str
    agentId: str
    message: str
    requester: RequesterIn
    condition: Literal["no_guard", "write_blocked", "approve_all", "baseline_tools", "full"] = "full"
    attachments: list[AttachmentIn] | None = Field(default=None, max_length=3)


class ResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversationId: str
    approvalId: str
    decision: Literal["approve", "reject"]
    comment: str | None = None


class SlotsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    today: date | None = None
    method: Literal["rule", "llm"]


class VariantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grammar: bool = False
    toolFilterK: int | None = Field(default=None, ge=1)
    fewShot: bool = False
    thinking: bool | None = None

    def to_domain(self) -> Variant:
        return Variant(self.grammar, self.toolFilterK, self.fewShot, self.thinking)


class EvalToolCallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    agentId: str
    requester: RequesterIn
    today: date
    model: str | None = None
    variant: VariantIn = Field(default_factory=VariantIn)


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
    slot_fillers: dict[str, SlotFiller] = field(default_factory=lambda: {"rule": RuleSlotFiller()})
    rooms: list[dict] = field(default_factory=list)
    eval_tool_call: EvalToolCaller | None = None  # AGENT_EVAL_MODE=1일 때만


def services_from_env() -> Services:
    pack_dir = os.environ.get("PACK_DIR")
    if not pack_dir:
        raise RuntimeError("PACK_DIR 환경 변수가 필요합니다(예: ../packs/manufacturing)")
    stage = os.environ.get("AGENT_PACK_STAGE")
    registry = Registry.load(Path(pack_dir), int(stage) if stage else None)
    chat = ChatClient(LLMSettings.from_env())
    min_conf = float(os.environ.get("AGENT_ROUTER_MIN_CONFIDENCE", "0.5"))
    log = audit.AuditLog(Path(os.environ.get("AGENT_AUDIT_LOG", "var/audit.jsonl")))
    mcp_url = os.environ.get("AGENT_MCP_URL", f"http://localhost:{os.environ.get('MCP_PORT', '8001')}/mcp")
    deps = Deps(llm=chat, caller=McpToolCaller(mcp_url), audit=log, wide=WideScope.from_pack(Path(pack_dir)),
                trusted_docs=trusted_docs(Path(pack_dir)))
    # 토큰 확인 키가 없으면 시작하지 않습니다. 끄는 것은 개발용 플래그로만 합니다.
    verifier: TokenVerifier | None = None
    if os.environ.get("AGENT_ALLOW_UNVERIFIED_TOKENS") != "1":
        verifier = TokenVerifier.from_env()
    runner = Runner(registry, build_graph(deps), deps.caller, verifier, ReceiptReader(chat))
    contracts = Path(os.environ.get("CONTRACTS_DIR", "../contracts"))
    fillers: dict[str, SlotFiller] = {"rule": RuleSlotFiller(),
                                      "llm": LlmSlotFiller(chat, load_slot_tools(contracts / "mcp" / "tools.json"))}
    evaluator = None
    if os.environ.get("AGENT_EVAL_MODE") == "1":
        evaluator = EvalToolCaller(registry, chat, load_tools(contracts / "mcp" / "tools.json"),
                                   load_examples(Path(os.environ.get("AGENT_EVAL_FEWSHOT", "eval_dev/tool_calls.jsonl"))))
    return Services(registry, Router(registry, chat, min_conf), log, runner, fillers, load_rooms(Path(pack_dir)),
                    evaluator)


def load_rooms(pack_dir: Path) -> list[dict]:
    """슬롯 파서가 회의실 이름을 ID로 바꿀 때 쓰는 팩 고정 데이터(fixtures/rooms.json). 없으면 빈 목록입니다."""
    path = pack_dir / "fixtures" / "rooms.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text("utf-8"))
    rooms = raw.get("rooms", []) if isinstance(raw, dict) else raw
    return [{"id": r["id"], "name": r["name"]} for r in rooms if "id" in r and "name" in r]


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

    @app.post("/baseline/slots")
    def baseline_slots(body: SlotsIn) -> dict:
        filler = svc.slot_fillers.get(body.method)
        if filler is None:
            raise HTTPException(503, f"{body.method} 슬롯 채우기가 설정되지 않았습니다")
        today = body.today or datetime.now(KST).date()
        return filler.fill(body.message, today, svc.rooms).to_dict()

    @app.post("/eval/tool-call")
    async def eval_tool_call(body: EvalToolCallIn) -> dict:
        if svc.eval_tool_call is None:
            raise HTTPException(404, "Not Found")
        try:
            return await svc.eval_tool_call.run(body.message, body.agentId, body.requester.to_domain(), body.today,
                                                body.model, body.variant.to_domain())
        except EvalBadRequest as e:
            raise HTTPException(400, str(e)) from None
        except EvalUpstreamError as e:
            raise HTTPException(502, str(e)) from None

    @app.post("/run")
    async def run(body: RunIn, x_delegation_token: str = Header(...)) -> dict:
        return await _runner().run(x_delegation_token, body.conversationId, body.agentId, body.message,
                                   body.requester.to_domain(), body.condition,
                                   [a.dataUrl for a in body.attachments or []])

    @app.post("/resume")
    async def resume(body: ResumeIn, x_delegation_token: str = Header(...)) -> dict:
        try:
            return await _runner().resume(x_delegation_token, body.conversationId, body.approvalId, body.decision)
        except Conflict as e:
            raise HTTPException(409, str(e)) from None

    return app
