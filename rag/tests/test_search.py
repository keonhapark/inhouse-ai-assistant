import pytest

from rag.chunk import Chunk
from rag.embed import HashEmbedder
from rag.search import SearchIndex, tokenize


def chunk(i: int, text: str, tags: set[str], title: str = "문서") -> Chunk:
    return Chunk(f"d{i}#1", f"d{i}", title, None, text, "trusted", frozenset(tags))


CHUNKS = [
    chunk(1, "연가는 재직기간에 따라 11일에서 21일까지 줍니다.", {"public"}),
    chunk(2, "출장 여비의 숙박비는 정산을 신청합니다.", {"finance-policy"}),
    chunk(3, "팀장 연 기본급은 6200만원에서 7800만원입니다. 연가 보상비도 있습니다.", {"hr-restricted"}),
    chunk(4, "회의실 예약은 30분 단위입니다.", {"public", "hr-restricted"}),
]


@pytest.fixture(scope="module")
def index():
    return SearchIndex(CHUNKS, HashEmbedder())


def test_한글은_음절_2gram으로_조사가_달라도_같은_토큰을_갖는다():
    assert "연가" in tokenize("연가를") and "연가" in tokenize("연가는")
    assert tokenize("ES256 토큰") == ["토큰", "es", "256"]


@pytest.mark.parametrize("method", ["bm25", "vector", "hybrid"])
def test_권한_밖_문서는_어떤_방법으로도_나오지_않는다(index, method):
    hits = index.search("팀장 기본급 연가", {"public"}, method, top_k=20)
    assert hits
    assert all(h.chunk.acl_tags & {"public"} for h in hits)
    assert "d3" not in {h.chunk.doc_id for h in hits}


@pytest.mark.parametrize("method", ["bm25", "vector", "hybrid"])
def test_권한이_있으면_제한_문서도_찾는다(index, method):
    hits = index.search("팀장 기본급", {"hr-restricted"}, method, top_k=1)
    assert hits[0].chunk.doc_id == "d3"


def test_태그가_여럿인_문서는_하나만_겹쳐도_보인다(index):
    hits = index.search("회의실 예약", {"hr-restricted"}, "bm25", top_k=5)
    assert hits[0].chunk.doc_id == "d4"


@pytest.mark.parametrize("method", ["bm25", "vector", "hybrid"])
def test_doc_scopes가_비면_결과가_없다(index, method):
    assert index.search("연가", set(), method) == []


def test_BM25_문서_빈도는_허용된_청크만으로_센다(index):
    """제한 문서가 있든 없든 공개 범위 질의의 점수는 같아야 합니다(점수로 제한 문서 내용을 짐작하지 못하게)."""
    public_only = SearchIndex([c for c in CHUNKS if "public" in c.acl_tags])
    a = index.search("연가 기본급", {"public"}, "bm25")
    b = public_only.search("연가 기본급", {"public"}, "bm25")
    assert [(h.chunk.id, h.score) for h in a] == [(h.chunk.id, h.score) for h in b]


def test_topK만큼만_돌려준다(index):
    assert len(index.search("연가 출장 회의실 팀장", {"public", "finance-policy", "hr-restricted"}, "bm25", 2)) == 2


def test_하이브리드는_두_순위의_RRF_합이다(index):
    scopes = {"public", "finance-policy", "hr-restricted"}
    ids = index.allowed(scopes)
    bm = [i for i, _ in index.bm25("연가", ids)[:50]]
    vec = [i for i, _ in index.vector("연가", ids)[:50]]
    expected = {}
    for ranking in (bm, vec):
        for r, i in enumerate(ranking, 1):
            expected[i] = expected.get(i, 0) + 1 / (60 + r)
    top = max(expected, key=lambda i: (expected[i], -i))
    assert index.search("연가", scopes, "hybrid", 1)[0].chunk is CHUNKS[top]


def test_임베딩_모델이_없으면_벡터_검색은_실패한다():
    with pytest.raises(RuntimeError):
        SearchIndex(CHUNKS).search("연가", {"public"}, "vector")


def test_문서를_지운_색인은_처음부터_만든_색인과_같은_점수를_낸다():
    """역색인의 청크 번호를 새로 매겨도 BM25 점수·순위가 남은 청크로 새로 만든 색인과 같습니다(#493)."""
    scopes = {"public", "finance-policy", "hr-restricted"}
    removed = SearchIndex(CHUNKS, HashEmbedder())
    removed.remove_document("d2")
    fresh = SearchIndex([c for c in CHUNKS if c.doc_id != "d2"], HashEmbedder())
    for query in ["연가 보상비", "회의실 예약", "기본급 팀장", "숙박비"]:
        for method in ("bm25", "vector", "hybrid"):
            a = [(h.chunk.id, h.score) for h in removed.search(query, scopes, method, top_k=5)]
            b = [(h.chunk.id, h.score) for h in fresh.search(query, scopes, method, top_k=5)]
            assert a == b, (query, method)
    assert removed.doc_ids() == {"d1", "d3", "d4"}
