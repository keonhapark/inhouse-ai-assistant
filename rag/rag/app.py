"""rag 서버(contracts/openapi/rag.yaml). 실행: uv run uvicorn --factory rag.app:from_env --port $PORT_RAG"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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


def create_app(index: SearchIndex, verifier: TokenVerifier) -> FastAPI:
    api = FastAPI(title="rag", version="0.1.0")

    @api.exception_handler(AuthError)
    def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
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

    return api


def from_env() -> FastAPI:
    """환경 변수로 색인·토큰 확인을 만들어 앱을 돌려줍니다(uvicorn --factory)."""
    cache = Path(os.environ.get("RAG_CACHE_DIR", MODULE_ROOT / ".cache"))
    stage = int(os.environ["RAG_STAGE"]) if os.environ.get("RAG_STAGE") else None
    return create_app(build_index(embedder_from_env(cache), stage), TokenVerifier.from_env())
