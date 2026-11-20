"""/search 시험. 실제 고정본·생성 문서 색인에 시험용 ES256 키와 해시 임베딩을 씁니다."""

import time
import uuid
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from rag.app import build_index, create_app
from rag.auth import TokenVerifier
from rag.embed import HashEmbedder
from rag.pack import REPO_ROOT

KEY = ec.generate_private_key(ec.SECP256R1())
PUBLIC_PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
STAFF = ["finance-policy", "hr-policy", "public"]
HR = STAFF + ["hr-restricted"]
RESTRICTED_DOCS = {"gen-hr-notice", "gen-salary-standard"}


def token(doc_scopes, key=KEY, **over) -> str:
    now = int(time.time())
    claims = {
        "iss": "gateway", "aud": ["erp", "rag", "mcp"], "sub": "E0012", "agt": "hr-agent", "cid": "c1",
        "scopes": [], "doc_scopes": doc_scopes, "iat": now, "exp": now + 600, "jti": uuid.uuid4().hex,
    }
    claims.update(over)
    return jwt.encode(claims, key, algorithm="ES256")


@pytest.fixture(scope="module")
def client():
    index = build_index(HashEmbedder(), stage=1)
    return TestClient(create_app(index, TokenVerifier(key=PUBLIC_PEM)))


@pytest.fixture(scope="module")
def response_schema():
    spec = yaml.safe_load((REPO_ROOT / "contracts/openapi/rag.yaml").read_text(encoding="utf-8"))
    ref = "#/paths/~1search/post/responses/200/content/application~1json/schema"
    return Draft202012Validator({**spec, "$ref": ref})


def post(client, body, tok):
    headers = {"X-Delegation-Token": tok} if tok else {}
    return client.post("/search", json=body, headers=headers)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("method", ["hybrid", "bm25", "vector"])
def test_응답이_계약_스키마를_따른다(client, response_schema, method):
    r = post(client, {"query": "연가 일수", "method": method, "topK": 3}, token(STAFF))
    assert r.status_code == 200
    response_schema.validate(r.json())
    assert len(r.json()["hits"]) == 3


@pytest.mark.parametrize("method", ["hybrid", "bm25", "vector"])
def test_제한_문서는_권한_없는_토큰의_결과에_없다(client, method):
    for q in ["직급별 기본급과 성과급 지급률", "승진 심사 결과 내정자", "급여 기준 직책수당"]:
        r = post(client, {"query": q, "method": method, "topK": 20}, token(STAFF))
        assert r.status_code == 200
        assert not {h["docId"] for h in r.json()["hits"]} & RESTRICTED_DOCS, q


@pytest.mark.parametrize("method", ["hybrid", "bm25", "vector"])
def test_인사_제한_권한이_있으면_급여_기준을_찾는다(client, method):
    r = post(client, {"query": "직급별 기본급과 성과급 지급률", "method": method, "topK": 3}, token(HR))
    assert "gen-salary-standard" in {h["docId"] for h in r.json()["hits"]}


def test_공개만_가진_토큰은_인사_규정도_못_본다(client):
    r = post(client, {"query": "반차 휴가 신청 회수", "method": "bm25", "topK": 20}, token(["public"]))
    tags = {h["docId"] for h in r.json()["hits"]}
    assert "gen-leave-guide" not in tags and "admrul-duty-discipline" not in tags


def test_결과에_신뢰_등급과_조문_표시가_있다(client):
    r = post(client, {"query": "연가 일수 재직기간", "method": "bm25", "topK": 5}, token(STAFF))
    hits = [h for h in r.json()["hits"] if h["docId"] == "law-civil-service-duty"]
    assert hits, r.json()
    hit = hits[0]
    assert hit["trust"] == "trusted"
    assert hit["article"].startswith("제15조(연가 일수)")


@pytest.mark.parametrize(
    "tok",
    [
        None,
        "not-a-jwt",
        token(STAFF, key=ec.generate_private_key(ec.SECP256R1())),  # 다른 키
        token(STAFF, aud=["erp"]),  # rag 대상 아님
        token(STAFF, iss="someone"),
        token(STAFF, exp=int(time.time()) - 60),  # 만료
        jwt.encode({"iss": "gateway", "aud": ["rag"], "doc_scopes": HR}, None, algorithm="none"),
        jwt.encode({"iss": "gateway", "aud": ["rag"], "doc_scopes": HR}, "x" * 32, algorithm="HS256"),
    ],
    ids=["없음", "형식", "서명", "aud", "iss", "만료", "alg-none", "HS256"],
)
def test_토큰이_없거나_틀리면_401_problem_json(client, tok):
    r = post(client, {"query": "연가"}, tok)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "urn:problem:unauthorized"


@pytest.mark.parametrize("method", ["hybrid", "bm25", "vector"])
@pytest.mark.parametrize(
    "query,doc_id,label",
    [("여비 규정 제16조", "law-travel-expense", "제16조"), ("제13조의2에 따른 허가권자", "law-civil-service-duty", "제13조의2")],
)
def test_조문_번호_질의는_그_조문을_상위에_둔다(client, method, query, doc_id, label):
    r = post(client, {"query": query, "method": method, "topK": 2}, token(STAFF))
    assert any(h["docId"] == doc_id and h["article"].startswith(label + "(") for h in r.json()["hits"])


@pytest.mark.parametrize("method", ["hybrid", "bm25", "vector"])
@pytest.mark.parametrize("query", ["", "   ", "!!!"])
def test_말이_없는_질의는_빈_결과다(client, method, query):
    r = post(client, {"query": query, "method": method}, token(STAFF))
    assert r.status_code == 200 and r.json()["hits"] == []


def test_말뭉치_조문_범위는_한_종류이고_오름차순이다(client):
    import re

    from rag.chunk import chunk_documents
    from rag.corpus import load_documents
    from rag.pack import load_pack

    for c in chunk_documents(load_documents(load_pack())):
        m = re.search(r"(제(\d+)항|\((\d+)\))~(제(\d+)항|\((\d+)\))$", c.article or "")
        if m:
            assert bool(m.group(2)) == bool(m.group(5)), c.article
            assert int(m.group(2) or m.group(3)) < int(m.group(5) or m.group(6)), c.article


def test_doc_scopes가_없는_토큰은_401(client):
    now = int(time.time())
    bad = jwt.encode({"iss": "gateway", "aud": ["rag"], "sub": "E1", "agt": "a", "cid": "c", "iat": now,
                      "exp": now + 60, "jti": "j"}, KEY, algorithm="ES256")
    assert post(client, {"query": "연가"}, bad).status_code == 401


def test_요청_형식이_틀리면_422(client):
    assert post(client, {"query": "연가", "topK": 0}, token(STAFF)).status_code == 422
    assert post(client, {"query": "연가", "extra": 1}, token(STAFF)).status_code == 422


def test_공개_키_파일_경로로도_만든다(tmp_path: Path, monkeypatch):
    p = tmp_path / "pub.pem"
    p.write_text(PUBLIC_PEM, encoding="utf-8")
    monkeypatch.setenv("DELEGATION_TOKEN_PUBLIC_KEY", str(p))
    assert TokenVerifier.from_env().verify(token(STAFF))["doc_scopes"] == STAFF


def test_법령_근거에는_판_정보가_있고_기준일로_옛_판을_고른다(client):
    q = {"query": "여비 규정 제18조 근무지 내 국내 출장", "method": "bm25", "topK": 3}
    now = post(client, q, token(STAFF)).json()["hits"][0]
    assert now["article"].startswith("제18조") and now["edition"]["current"] is True
    old = post(client, {**q, "asOf": "2026-03-01"}, token(STAFF)).json()["hits"][0]
    assert old["edition"] == {"effectiveFrom": "2026-01-02", "effectiveTo": "2026-06-30", "current": False,
                              "promulgation": "대통령령 제36013호, 2026. 1. 2., 타법개정"}
    assert old["text"] != now["text"]


def test_생성_문서_근거에는_판_정보가_없다(client):
    hits = post(client, {"query": "회의실 예약", "method": "bm25", "topK": 5}, token(STAFF)).json()["hits"]
    assert any(h["docId"].startswith("gen-") for h in hits)
    assert all(("edition" in h) == (not h["docId"].startswith("gen-")) for h in hits)


def test_asOf_형식이_틀리면_422(client):
    assert post(client, {"query": "연가", "asOf": "2026-13-01"}, token(STAFF)).status_code == 422


def test_별표_표의_행을_찾는다(client):
    q = {"query": "국내 출장 제2호 숙박비 상한액 서울특별시", "method": "bm25", "topK": 3}
    hits = post(client, q, token(STAFF)).json()["hits"]
    top = hits[0]
    assert top["docId"] == "law-travel-expense" and top["article"].startswith("별표 2(")
    assert "숙박비 (1박당): 실비 (상한액: 서울특별시 100,000" in top["text"]


# ---------------------------------------------------------------- 질의 임베딩(#167)


class RecordingEmbedder:
    """색인은 해시 임베딩으로 하고, 질의 임베딩에 붙은 위임 토큰을 적어 둡니다. fail을 주면 질의 임베딩이 실패합니다."""

    name = "rec"

    def __init__(self, fail=None):
        from rag.embed import HashEmbedder

        self.inner = HashEmbedder()
        self.tokens = []
        self.fail = fail

    def embed(self, texts):
        return self.inner.embed(texts)

    def embed_query(self, text, delegation_token=None):
        self.tokens.append(delegation_token)
        if self.fail:
            raise self.fail
        return self.inner.embed([text])[0]


def _app_with(embedder):
    index = build_index(embedder, stage=1)
    return TestClient(create_app(index, TokenVerifier(key=PUBLIC_PEM)))


@pytest.mark.parametrize("method", ["hybrid", "vector"])
def test_질의_임베딩에_요청의_위임_토큰을_붙인다(method):
    emb = RecordingEmbedder()
    tok = token(STAFF)
    assert post(_app_with(emb), {"query": "연가 일수", "method": method}, tok).status_code == 200
    assert emb.tokens == [tok]


def test_bm25는_질의를_임베딩하지_않는다():
    emb = RecordingEmbedder()
    post(_app_with(emb), {"query": "연가 일수", "method": "bm25"}, token(STAFF))
    assert emb.tokens == []


@pytest.mark.parametrize("unreachable,status", [(True, 503), (False, 502)])
def test_질의_임베딩이_실패하면_계약의_502_503(unreachable, status):
    from rag.embed import EmbedError

    spec = yaml.safe_load((REPO_ROOT / "contracts/openapi/rag.yaml").read_text(encoding="utf-8"))
    assert str(status) in spec["paths"]["/search"]["post"]["responses"]
    client = _app_with(RecordingEmbedder(fail=EmbedError("x", unreachable=unreachable)))
    r = post(client, {"query": "연가 일수"}, token(STAFF))
    assert r.status_code == status and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "urn:problem:embedding-unavailable"


def test_GatewayEmbedder는_질의에_위임_토큰_헤더를_붙인다():
    import httpx

    from rag.embed import GatewayEmbedder

    seen = []

    def handler(request):
        seen.append(request.headers.get("x-delegation-token"))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    emb = GatewayEmbedder("http://gw/v1", "m", transport=httpx.MockTransport(handler))
    emb.embed(["색인"])
    emb.embed_query("질의", "tok")
    assert seen == [None, "tok"]


def test_답의_질의_임베딩이_실패하면_503이고_감사에_남긴다(tmp_path):
    import json

    from rag.answer import Answerer
    from rag.audit import AuditLog
    from rag.embed import EmbedError

    index = build_index(RecordingEmbedder(fail=EmbedError("down", unreachable=True)), stage=1)
    audit = AuditLog(tmp_path / "audit.jsonl")
    client = TestClient(create_app(index, TokenVerifier(key=PUBLIC_PEM), Answerer(index, llm=None), audit))
    r = client.post("/answer", json={"question": "연가 일수"}, headers={"X-Delegation-Token": token(STAFF)})
    assert r.status_code == 503 and r.json()["type"] == "urn:problem:embedding-unavailable"
    [event] = [json.loads(x) for x in audit.path.read_text(encoding="utf-8").splitlines()]
    assert event["kind"] == "rag.answered" and event["result"] == "error"
