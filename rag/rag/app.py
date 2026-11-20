"""rag 서버(contracts/openapi/rag.yaml). 실행: uv run uvicorn --factory rag.app:from_env --port $PORT_RAG"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from rag.answer import Answerer, GatewayChat, LLMError
from rag.audit import AuditLog
from rag.auth import AuthError, TokenVerifier
from rag.chunk import chunk_documents
from rag.corpus import MODULE_ROOT, load_documents
from rag.embed import embedder_from_env
from rag.pack import load_pack
from rag.search import Embedder, Hit, SearchIndex

log = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(max_length=500)
    topK: int = Field(default=5, ge=1, le=20)
    method: Literal["hybrid", "bm25", "vector"] = "hybrid"


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(max_length=500)
    conversationId: str | None = None


def problem(status: int, code: str, title: str, detail: str | None = None) -> JSONResponse:
    body = {"type": f"urn:problem:{code}", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def passage(hit: Hit) -> dict:
    c = hit.chunk
    return {
        "docId": c.doc_id,
        "title": c.title,
        "article": c.article,
        "text": c.text,
        "score": hit.score,
        "trust": c.trust,
    }


def build_index(embedder: Embedder | None, stage: int | None = None) -> SearchIndex:
    pack = load_pack()
    chunks = chunk_documents(load_documents(pack, stage=stage))
    return SearchIndex(chunks, embedder)


def create_app(
    index: SearchIndex, verifier: TokenVerifier, answerer: Answerer | None = None, audit: AuditLog | None = None,
) -> FastAPI:
    api = FastAPI(title="rag", version="0.1.0")

    def record(kind: str, result: str, claims: dict | None, operation: str, **kw) -> None:
        if audit:
            audit.write(kind, result, claims, operation, **kw)

    @api.exception_handler(AuthError)
    def _auth_error(request: Request, exc: AuthError) -> JSONResponse:
        record("rag.access_denied", "denied", None, request.url.path.lstrip("/"), problem="unauthorized",
               detail=str(exc))
        return problem(401, "unauthorized", "인증 실패", str(exc))

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @api.post("/search")
    def search(
        body: SearchRequest,
        x_delegation_token: Annotated[str | None, Header()] = None,
    ) -> dict:
        claims = verifier.verify(x_delegation_token)
        hits = index.search(body.query, set(claims["doc_scopes"]), body.method, body.topK)
        log.info("search jti=%s agt=%s method=%s hits=%d", claims["jti"], claims["agt"], body.method, len(hits))
        return {"hits": [passage(h) for h in hits]}

    @api.post("/answer", response_model=None)
    def answer(
        body: AnswerRequest,
        x_delegation_token: Annotated[str | None, Header()] = None,
    ) -> dict | JSONResponse:
        claims = verifier.verify(x_delegation_token)
        if answerer is None:
            return problem(503, "llm-unavailable", "답 생성을 쓸 수 없습니다", "GATEWAY_LLM_URL이 없습니다")
        assert x_delegation_token is not None  # verify가 통과했으면 있습니다.
        try:
            result = answerer.answer(body.question, set(claims["doc_scopes"]), x_delegation_token)
        except LLMError as e:
            model = {"name": answerer.llm.model, "location": answerer.llm.location}
            record("rag.answered", "error", claims, "answer", model=model, problem="llm-unavailable", detail=e.detail)
            return problem(502, "llm-unavailable", "답을 만들지 못했습니다", e.detail)
        except Exception as e:  # 예기치 않은 실패도 감사에서 빠지지 않게 합니다.
            log.exception("answer 실패 jti=%s", claims["jti"])
            record("rag.answered", "error", claims, "answer", problem="internal", detail=type(e).__name__)
            return problem(502, "internal", "답을 만들지 못했습니다")
        if result.withheld:
            record("rag.access_denied", "denied", claims, "answer", problem="forbidden",
                   detail="권한 밖이라 근거에서 뺀 문서(전체 검색 1위): " + ", ".join(result.withheld))
        model = dict(result.model, externalSent=result.model["location"] == "external") if result.model else None
        record("rag.answered", "ok", claims, "answer", model=model, detail=f"found={result.found}; {result.detail}")
        log.info("answer jti=%s agt=%s found=%s", claims["jti"], claims["agt"], result.found)
        return result.body()

    return api


def from_env() -> FastAPI:
    """환경 변수로 색인·토큰 확인을 만들어 앱을 돌려줍니다(uvicorn --factory)."""
    cache = Path(os.environ.get("RAG_CACHE_DIR", MODULE_ROOT / ".cache"))
    stage = int(os.environ["RAG_STAGE"]) if os.environ.get("RAG_STAGE") else None
    index = build_index(embedder_from_env(cache), stage)
    llm_url = os.environ.get("GATEWAY_LLM_URL")
    chat = GatewayChat(llm_url, os.environ.get("RAG_LLM_MODEL", "local"),
                       reasoning_effort=os.environ.get("RAG_LLM_REASONING", "none") or None) if llm_url else None
    answerer = Answerer(index, chat) if chat else None
    audit = AuditLog(Path(os.environ.get("RAG_AUDIT_LOG", MODULE_ROOT / ".data" / "audit.jsonl")))
    return create_app(index, TokenVerifier.from_env(), answerer, audit)
