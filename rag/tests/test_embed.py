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
