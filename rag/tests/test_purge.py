"""문서 파기: 청크·벡터·임베딩 캐시를 함께 지우고, 지운 뒤 표지 검색이 0건인지 봅니다(기획서 우려 14).

제한 문서(인사 급여 기준)에 평가용 표지를 넣고 파기한 뒤, 모든 권한·모든 검색 방법·다시 시작한 뒤에도
표지가 나오지 않는지, 임베딩 캐시 파일에 그 글의 항목이 남지 않는지 봅니다.
"""

import hashlib
import json
import time
import uuid

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from rag.app import build_index, create_app
from rag.audit import AuditLog
from rag.auth import TokenVerifier
from rag.embed import CachedEmbedder, HashEmbedder
from rag.pack import REPO_ROOT
from rag.purge import PurgeList
from rag.search import index_text

KEY = ec.generate_private_key(ec.SECP256R1())
PUBLIC_PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
ALL = ["public", "hr-policy", "finance-policy", "hr-restricted"]
DOC = "gen-salary-standard"
MARK = "MK-PURGE-7Q"
ADMIN = "admin-test-key"


def token() -> str:
    now = int(time.time())
    claims = {"iss": "gateway", "aud": ["rag"], "sub": "E0001", "agt": "hr-agent", "cid": "c", "scopes": [],
              "doc_scopes": ALL, "iat": now, "exp": now + 600, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, KEY, algorithm="ES256")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    markers = tmp_path / "markers.yaml"
    markers.write_text(yaml.safe_dump({"markers": {DOC: [MARK]}}), encoding="utf-8")
    monkeypatch.setenv("RAG_MARKERS_FILE", str(markers))
    purge_list = PurgeList(tmp_path / "purged.txt")

    def start():
        embedder = CachedEmbedder(HashEmbedder(), tmp_path / "cache")
        index = build_index(embedder, stage=1, purged=purge_list.ids())
        audit = AuditLog(tmp_path / "audit.jsonl")
        app = create_app(index, TokenVerifier(key=PUBLIC_PEM), None, audit, ADMIN, purge_list)
        return TestClient(app), index, embedder

    return start, tmp_path


def marker_hits(client) -> int:
    n = 0
    for method in ("bm25", "vector", "hybrid"):
        for query in (MARK, "팀장 기본급 급여 기준"):
            body = {"query": query, "method": method, "topK": 20}
            hits = client.post("/search", json=body, headers={"X-Delegation-Token": token()}).json()["hits"]
            n += sum(MARK in h["text"] or h["docId"] == DOC for h in hits)
    return n


def cache_keys(tmp_path) -> set[str]:
    [path] = (tmp_path / "cache").glob("embeddings-*.json")
    return set(json.loads(path.read_text(encoding="utf-8")))


def purge(client, doc_id=DOC, key=ADMIN):
    return client.delete(f"/documents/{doc_id}", headers={"Authorization": f"Bearer {key}"})


def test_파기하면_표지_검색이_0건이고_캐시와_다시_시작한_뒤에도_남지_않는다(setup):
    start, tmp_path = setup
    client, index, _ = start()
    texts = {index_text(c) for c in index.chunks if c.doc_id == DOC}
    keys = {hashlib.sha256(t.encode()).hexdigest() for t in texts}
    assert marker_hits(client) > 0 and keys <= cache_keys(tmp_path)

    assert purge(client).status_code == 204
    assert marker_hits(client) == 0
    assert not keys & cache_keys(tmp_path)
    assert all(c.doc_id != DOC for c in index.chunks)

    client2, index2, _ = start()  # 다시 시작
    assert marker_hits(client2) == 0
    assert all(c.doc_id != DOC for c in index2.chunks)
    assert not keys & cache_keys(tmp_path)
    assert (tmp_path / "purged.txt").read_text(encoding="utf-8") == f"{DOC}\n"


def test_파기하면_감사_이벤트가_계약을_따르고_본문은_넣지_않는다(setup):
    start, tmp_path = setup
    client, _, _ = start()
    purge(client)
    [event] = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    schema = json.loads((REPO_ROOT / "contracts/events/audit.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(event)
    assert event["kind"] == "rag.document_purged" and event["result"] == "ok"
    assert event["actor"] == {"employeeId": None, "viaDelegationToken": False, "agentId": None}
    assert DOC in event["detail"] and MARK not in json.dumps(event, ensure_ascii=False)


def test_다른_문서는_그대로_찾는다(setup):
    start, _ = setup
    client, index, _ = start()
    before = sum(1 for c in index.chunks if c.doc_id != DOC)
    purge(client)
    assert len(index.chunks) == before
    hits = client.post("/search", json={"query": "연가 일수", "method": "hybrid"},
                       headers={"X-Delegation-Token": token()}).json()["hits"]
    assert hits


def test_판이_여럿인_문서는_모든_판을_지우고_판_대조에도_남지_않는다(setup):
    start, _ = setup
    client, index, _ = start()
    assert purge(client, "law-travel-expense").status_code == 204
    assert all(c.doc_id != "law-travel-expense" for c in index.chunks)
    for as_of in ("2026-03-01", "2026-08-01", None):
        body = {"query": "여비 규정 제18조 근무지 내 출장", "method": "bm25", "topK": 20, "asOf": as_of}
        hits = client.post("/search", json=body, headers={"X-Delegation-Token": token()}).json()["hits"]
        assert all(h["docId"] != "law-travel-expense" for h in hits)


@pytest.mark.parametrize("key", ["wrong", ""])
def test_운영자_키가_틀리면_401이고_지우지_않는다(setup, key):
    start, tmp_path = setup
    client, index, _ = start()
    r = client.delete(f"/documents/{DOC}", headers={"Authorization": f"Bearer {key}"} if key else {})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert any(c.doc_id == DOC for c in index.chunks)
    assert not (tmp_path / "purged.txt").exists()


def test_위임_토큰으로는_파기할_수_없다(setup):
    start, _ = setup
    client, _, _ = start()
    r = client.delete(f"/documents/{DOC}", headers={"X-Delegation-Token": token()})
    assert r.status_code == 401


def test_없는_문서나_이미_지운_문서는_404(setup):
    start, _ = setup
    client, _, _ = start()
    assert purge(client, "no-such-doc").status_code == 404
    assert purge(client).status_code == 204
    assert purge(client).status_code == 404


def test_운영자_키가_없으면_경로가_없어_404(tmp_path):
    index = build_index(HashEmbedder(), stage=1)
    client = TestClient(create_app(index, TokenVerifier(key=PUBLIC_PEM), None, None, None, None))
    assert client.delete(f"/documents/{DOC}", headers={"Authorization": "Bearer x"}).status_code == 404


def test_파기_뒤_답의_판_대조표를_다시_만든다(setup):
    from rag.answer import Answerer

    start, _ = setup
    client, index, _ = start()
    answerer = Answerer(index, llm=None)  # type: ignore[arg-type]
    assert answerer.book._texts
    purge(client, "law-travel-expense")
    assert all(doc != "law-travel-expense" for doc, _ in answerer.book._texts)
