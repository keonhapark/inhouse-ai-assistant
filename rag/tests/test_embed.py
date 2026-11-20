import json

import httpx
import pytest

from rag.embed import CachedEmbedder, GatewayEmbedder, HashEmbedder, embedder_from_env


def fake_gateway(calls: list, shuffle: bool = True, drop: bool = False):
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        data = [{"index": i, "embedding": [float(len(t)), 1.0]} for i, t in enumerate(body["input"])]
        if shuffle:
            data.reverse()
        if drop:
            data = data[:-1]
        return httpx.Response(200, json={"data": data})

    return httpx.MockTransport(handle)


def test_gateway_임베딩은_묶어_보내고_index_순서로_맞춘다():
    calls: list = []
    emb = GatewayEmbedder("http://gw/v1", "local-embed", transport=fake_gateway(calls))
    emb.BATCH = 2
    out = emb.embed(["a", "bb", "ccc"])
    assert out == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert [c["input"] for c in calls] == [["a", "bb"], ["ccc"]]
    assert all(c["model"] == "local-embed" for c in calls)


def test_gateway가_개수를_다르게_주면_실패한다():
    emb = GatewayEmbedder("http://gw/v1", "m", transport=fake_gateway([], drop=True))
    with pytest.raises(ValueError):
        emb.embed(["a", "b"])


def test_캐시는_같은_본문을_다시_보내지_않는다(tmp_path):
    calls: list = []
    inner = GatewayEmbedder("http://gw/v1", "m", transport=fake_gateway(calls))
    first = CachedEmbedder(inner, tmp_path).embed(["a", "bb"])
    again = CachedEmbedder(inner, tmp_path).embed(["bb", "a", "ccc"])
    assert again == [first[1], first[0], [3.0, 1.0]]
    assert [c["input"] for c in calls] == [["a", "bb"], ["ccc"]]


def test_해시_임베딩은_결정적이고_단위_길이다():
    a, b = HashEmbedder(64).embed(["연가 일수", "연가 일수"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_환경_변수가_모자라면_알린다(monkeypatch, tmp_path):
    monkeypatch.delenv("RAG_EMBEDDER", raising=False)
    monkeypatch.delenv("RAG_EMBED_BASE_URL", raising=False)
    monkeypatch.delenv("GATEWAY_LLM_URL", raising=False)
    with pytest.raises(ValueError):
        embedder_from_env(tmp_path)
    monkeypatch.setenv("RAG_EMBEDDER", "hash")
    assert isinstance(embedder_from_env(tmp_path), HashEmbedder)


def test_질의는_캐시를_거치지_않는다(tmp_path):
    """질의가 캐시에 맞으면 응답이 빨라져 제한 청크 문장을 응답 시간으로 맞혀 볼 수 있습니다."""
    from rag.chunk import Chunk
    from rag.search import SearchIndex

    calls: list = []
    emb = CachedEmbedder(GatewayEmbedder("http://gw/v1", "m", transport=fake_gateway(calls)), tmp_path)
    chunk = Chunk("d#1", "d", "문서", None, "급여 인상률", "trusted", frozenset({"hr-restricted"}))
    index = SearchIndex([chunk], emb)
    calls.clear()
    for _ in range(2):
        index.search("문서 급여 인상률", {"hr-restricted"}, "vector")
    assert len(calls) == 2
    cached = json.loads(next(tmp_path.glob("embeddings-*.json")).read_text())
    assert len(cached) == 1  # 색인할 때 넣은 청크 하나뿐


def test_캐시_파일은_주인만_읽는다(tmp_path):
    CachedEmbedder(HashEmbedder(8), tmp_path).embed(["a"])
    assert next(tmp_path.glob("embeddings-*.json")).stat().st_mode & 0o777 == 0o600
