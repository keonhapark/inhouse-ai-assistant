"""gateway FastAPI 앱. 경로는 contracts/openapi/gateway.yaml(서버 기준 `/api`)을 따릅니다.

실행(gateway/에서): uv run uvicorn --factory gateway.main:create_app --port $PORT_GATEWAY
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from gateway import redact
from gateway.alerts import Alerter
from gateway import audit_query
from gateway.chat import AgentClient, ChatService
from gateway.chat import build_router as chat_router
from gateway.audit import AuditLog, JsonlWriter
from gateway.config import Settings
from gateway.delegation import DelegationService
from gateway.confidential import Glossary
from gateway.egress import Egress, load_model_info
from gateway.pii import KoreanRedactor
from gateway.erp_client import ErpClient
from gateway.problems import ProblemError, problem_response
from gateway.registry import Registry
from gateway.relay import bearer, build_router
from gateway.tokens import DelegationTokenIssuer

log = logging.getLogger(__name__)


def _issuer(settings: Settings) -> DelegationTokenIssuer:
    if settings.delegation_private_key and settings.delegation_private_key.is_file():
        return DelegationTokenIssuer.from_pem_file(settings.delegation_private_key, settings.token_ttl_seconds)
    log.warning("위임 토큰 키 파일이 없어 임시 키를 만듭니다. scripts/dev-keys.sh로 만든 키를 주면 erp·rag·MCP 서버와 키가 맞습니다.")
    return DelegationTokenIssuer.ephemeral(settings.token_ttl_seconds)


def _relay(r: httpx.Response) -> Response:
    return Response(r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


def create_app(settings: Settings | None = None, *, erp_transport: httpx.AsyncBaseTransport | None = None,
               issuer: DelegationTokenIssuer | None = None, llm_transport: httpx.AsyncBaseTransport | None = None,
               alert_transport: httpx.AsyncBaseTransport | None = None,
               agent_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    redact.install()
    registry = Registry.load(settings.pack_dir, settings.contracts_dir)
    issuer = issuer or _issuer(settings)
    erp = ErpClient(settings.erp_base_url, transport=erp_transport)
    audit = AuditLog(settings.audit_dir)
    alerter = Alerter(settings.alert_webhook_url, transport=alert_transport)
    model_info = load_model_info(settings.litellm_config)
    egress = Egress(base_url=settings.litellm_base_url,
                    locations={alias: info["location"] for alias, info in model_info.items()},
                    registry=registry, issuer=issuer, audit=audit, alerter=alerter,
                    timeout=settings.llm_timeout_seconds, api_key=os.environ.get("LITELLM_MASTER_KEY") or None,
                    transport=llm_transport, redactor=KoreanRedactor(), glossary=Glossary.load(settings.pack_dir),
                    external_log=JsonlWriter(settings.external_log) if settings.external_log else None,
                    no_response_format=frozenset(a for a, i in model_info.items()
                                                 if i.get("supports_response_format") is False))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await erp.aclose()
        await egress.aclose()
        await agent.aclose()

    app = FastAPI(title="gateway", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = registry
    app.state.issuer = issuer
    app.state.erp = erp
    app.state.delegation = DelegationService(erp, registry, issuer)
    agent = AgentClient(settings.agent_base_url, transport=agent_transport, timeout=settings.agent_timeout_seconds)
    app.state.chat = ChatService(erp, registry, app.state.delegation, agent, audit, eval_mode=settings.eval_mode,
                                 usage=egress.usage)
    app.state.audit = audit
    app.state.alerter = alerter
    app.state.egress = egress

    @app.exception_handler(ProblemError)
    async def _problem(_: Request, e: ProblemError) -> JSONResponse:
        return problem_response(e)

    @app.get("/health")
    def root_health() -> dict:
        return {"status": "ok"}

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @api.get("/.well-known/jwks.json")
    def jwks() -> dict:
        return issuer.jwks()

    @api.post("/auth/login")
    async def login(request: Request) -> Response:
        return _relay(await erp.request("POST", "/auth/login", json=await _json(request)))

    @api.get("/me")
    async def me(request: Request) -> Response:
        return _relay(await erp.request("GET", "/me", bearer=bearer(request)))

    app.include_router(api)
    app.include_router(build_router(erp), prefix="/api")
    app.include_router(chat_router(app.state.chat), prefix="/api")
    app.include_router(audit_query.build_router(erp, audit, settings.audit_event_files), prefix="/api")

    # LLM 출구는 OpenAI 호환 경로라 /api 밖에 둡니다(agent·rag의 GATEWAY_LLM_URL=http://gateway:8000/v1).
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        return await egress.handle(request)

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> Response:
        return await egress.handle_embeddings(request)

    return app


async def _json(request: Request) -> object:
    try:
        return await request.json()
    except ValueError:
        raise ProblemError(422, "validation", "JSON 본문이 아닙니다")

