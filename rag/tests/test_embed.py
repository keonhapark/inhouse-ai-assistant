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


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def __call__(self):
        return self.now


def flaky(fail_times: int, failure):
    state = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= fail_times:
            if isinstance(failure, int):
                return httpx.Response(failure, json={})
            raise failure
        body = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0]} for i, _ in enumerate(body["input"])]})

    return httpx.MockTransport(handle), state


@pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), 503, 502])
def test_시작_때는_gateway를_기다렸다가_색인한다(failure):
    """compose에서 rag가 gateway보다 먼저 떠도 종료하지 않아야 합니다(#127)."""
    transport, state = flaky(3, failure)
    clock = FakeClock()
    emb = GatewayEmbedder("http://gw/v1", "m", transport=transport, startup_wait=60, sleep=clock.sleep, clock=clock)
    assert emb.embed(["a", "b"]) == [[1.0], [1.0]]
    assert state["n"] == 4 and clock.sleeps == [1.0, 2.0, 4.0]


def test_시작_대기_시간을_넘기면_실패한다():
    transport, _ = flaky(100, httpx.ConnectError("refused"))
    clock = FakeClock()
    emb = GatewayEmbedder("http://gw/v1", "m", transport=transport, startup_wait=20, sleep=clock.sleep, clock=clock)
    with pytest.raises(httpx.ConnectError):
        emb.embed(["a"])
    assert sum(clock.sleeps) <= 20


def test_한_번_성공한_뒤에는_다시_시도하지_않는다():
    transport, _ = flaky(0, None)
    clock = FakeClock()
    emb = GatewayEmbedder("http://gw/v1", "m", transport=transport, startup_wait=60, sleep=clock.sleep, clock=clock)
    emb.embed(["a"])
    emb._transport = flaky(5, httpx.ConnectError("down"))[0]  # 이제 gateway가 내려감
    with pytest.raises(httpx.ConnectError):
        emb.embed(["q"])
    assert clock.sleeps == []


def test_재시도하지_않는_오류는_바로_돌려준다():
    transport, state = flaky(1, 422)
    clock = FakeClock()
    emb = GatewayEmbedder("http://gw/v1", "m", transport=transport, startup_wait=60, sleep=clock.sleep, clock=clock)
    with pytest.raises(httpx.HTTPStatusError):
        emb.embed(["a"])
    assert state["n"] == 1 and clock.sleeps == []
