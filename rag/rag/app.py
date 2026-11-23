"""rag 서버(contracts/openapi/rag.yaml). 실행: uv run uvicorn --factory rag.app:from_env --port $PORT_RAG"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from rag.answer import Answerer, GatewayChat, LLMError
from rag.audit import AuditLog
from rag.auth import AuthError, TokenVerifier
from rag.corpus import MODULE_ROOT, load_documents
from rag.editions import edition_body
from rag.embed import EmbedError, embedder_from_env
from rag.evaldocs import apply_eval_files
from rag.pack import load_pack
from rag.profile import FALLBACK, ProfileCache, with_env
from rag.purge import PurgeList, purge_document
from rag.search import EditionPolicy, Embedder, Hit, SearchIndex

log = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(max_length=500)
    topK: int = Field(default=5, ge=1, le=20)
    method: Literal["hybrid", "bm25", "vector"] = "hybrid"
    asOf: date | None = None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(max_length=500)
    conversationId: str | None = None
    asOf: date | None = None


def problem(status: int, code: str, title: str, detail: str | None = None) -> JSONResponse:
    body = {"type": f"urn:problem:{code}", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def passage(hit: Hit, today: date) -> dict:
    c = hit.chunk
    out = {
        "docId": c.doc_id,
        "title": c.title,
        "article": c.article,
        "text": c.text,
        "score": hit.score,
        "trust": c.trust,
    }
    if c.edition is not None:
        out["edition"] = edition_body(c.edition, today)
    return out


def build_index(
    embedder: Embedder | None,
    stage: int | None = None,
    editions: EditionPolicy = "as_of",
    purged: set[str] | None = None,
) -> SearchIndex:
    """`purged`(파기 목록)의 문서는 임베딩하기 전에 뺍니다."""
    pack = load_pack()
    chunks = apply_eval_files(load_documents(pack, stage=stage), pack)
    chunks = [c for c in chunks if c.doc_id not in (purged or set())]
    return SearchIndex(chunks, embedder, editions=editions)


def edition_policy(env: dict[str, str]) -> EditionPolicy:
    value = env.get("RAG_EDITIONS", "").strip() or "as_of"
    if value not in ("as_of", "all"):
        raise ValueError(f"RAG_EDITIONS는 as_of 또는 all입니다: {value}")
    return value  # type: ignore[return-value]


def create_app(
    index: SearchIndex, verifier: TokenVerifier, answerer: Answerer | None = None, audit: AuditLog | None = None,
    admin_token: str | None = None, purge_list: PurgeList | None = None,
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

    @api.post("/search", response_model=None)
    def search(
        body: SearchRequest,
        x_delegation_token: Annotated[str | None, Header()] = None,
    ) -> dict | JSONResponse:
        claims = verifier.verify(x_delegation_token)
        try:
            hits = index.search(body.query, set(claims["doc_scopes"]), body.method, body.topK, body.asOf,
                                x_delegation_token)
        except EmbedError as e:
            # 계약: gateway가 오류를 돌려주면 502, gateway에 닿지 못하면 503
            return problem(503 if e.unreachable else 502, "embedding-unavailable", "질의를 임베딩하지 못했습니다",
                           e.detail)
        log.info("search jti=%s agt=%s method=%s hits=%d", claims["jti"], claims["agt"], body.method, len(hits))
        today = index.today()
        return {"hits": [passage(h, today) for h in hits]}

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
            result = answerer.answer(body.question, set(claims["doc_scopes"]), x_delegation_token, body.asOf)
        except EmbedError as e:
            status = 503 if e.unreachable else 502
            record("rag.answered", "error", claims, "answer", problem="embedding-unavailable", detail=e.detail)
            return problem(status, "embedding-unavailable", "질의를 임베딩하지 못했습니다", e.detail)
        except LLMError as e:
            model = {"name": answerer.llm.model, "location": answerer.llm.location}
            # 계약: gateway가 오류를 돌려주면 502, gateway에 닿지 못하면 503
            status = 503 if e.unreachable else 502
            record("rag.answered", "error", claims, "answer", model=model, problem="llm-unavailable", detail=e.detail)
            return problem(status, "llm-unavailable", "답을 만들지 못했습니다", e.detail)
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

    if admin_token and purge_list is not None:
        # 운영자 키가 없으면 경로를 두지 않아 404입니다(계약).
        # 감사에는 운영자 키의 지문(SHA-256 앞 12자)을 남깁니다. 키 하나를 운영자들이 같이 쓰면 사람까지는
        # 가리지 못하지만, 운영자마다 키를 따로 주면 어느 키로 파기했는지가 사건 재구성의 근거가 됩니다.
        operator = "operatorKey=" + hashlib.sha256(admin_token.encode()).hexdigest()[:12]
        @api.delete("/documents/{doc_id}", status_code=204, response_model=None)
        def purge(doc_id: str, authorization: Annotated[str | None, Header()] = None) -> JSONResponse | None:
            scheme, _, given = (authorization or "").partition(" ")
            if scheme != "Bearer" or not given or not hmac.compare_digest(given.encode(), admin_token.encode()):
                record("rag.access_denied", "denied", None, "purge", problem="unauthorized", detail="운영자 키 불일치")
                return problem(401, "unauthorized", "인증 실패", "운영자 키가 맞지 않습니다")
            result = purge_document(index, doc_id, purge_list)
            if result is None:
                return problem(404, "not-found", "문서가 없습니다", doc_id)
            record("rag.document_purged", "ok", None, "purge", detail=f"{operator}; {result.detail()}")
            log.info("purge %s", result.detail())
            return None

    return api


def from_env() -> FastAPI:
    """환경 변수로 색인·토큰 확인을 만들어 앱을 돌려줍니다(uvicorn --factory)."""
    cache = Path(os.environ.get("RAG_CACHE_DIR", MODULE_ROOT / ".cache"))
    stage = int(os.environ["RAG_STAGE"]) if os.environ.get("RAG_STAGE") else None
    purge_list = PurgeList(Path(os.environ.get("RAG_PURGE_FILE") or cache / "purged.txt"))
    index = build_index(embedder_from_env(cache), stage, edition_policy(dict(os.environ)), purge_list.ids())
    llm_url = os.environ.get("GATEWAY_LLM_URL")
    alias = os.environ.get("RAG_LLM_MODEL", "local")
    with_env(FALLBACK, os.environ)  # 덮어쓰기 값이 틀리면 첫 질문이 아니라 시작할 때 알립니다
    chat = GatewayChat(llm_url, alias, settings=ProfileCache(llm_url, alias).get) if llm_url else None
    answerer = Answerer(index, chat) if chat else None
    audit = AuditLog(Path(os.environ.get("RAG_AUDIT_LOG", MODULE_ROOT / ".data" / "audit.jsonl")))
    admin = os.environ.get("RAG_ADMIN_TOKEN", "").strip() or None
    return create_app(index, TokenVerifier.from_env(), answerer, audit, admin, purge_list)
