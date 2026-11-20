"""numpy 검색(#277)이 바꾸기 전의 순수 Python 계산과 같은 점수·순위를 내는지 봅니다.

기준 구현은 바꾸기 전 rag/search.py의 BM25와 코사인을 그대로 옮긴 것입니다.
"""

import math
from collections import Counter

import pytest

from bench.scale import all_scopes, questions, scaled_chunks
from rag.embed import HashEmbedder
from rag.search import SearchIndex, index_text, tokenize

K1, B = 1.2, 0.75


def ref_bm25(tfs, lens, query, ids):
    terms = set(tokenize(query))
    n = len(ids)
    avg = sum(lens[i] for i in ids) / n
    df = {t: sum(1 for i in ids if t in tfs[i]) for t in terms}
    out = []
    for i in ids:
        s = 0.0
        for t in terms:
            f = tfs[i].get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * lens[i] / avg))
        if s > 0:
            out.append((i, s))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def ref_cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@pytest.fixture(scope="module")
def setup():
    chunks, _ = scaled_chunks(3)
    emb = HashEmbedder()
    index = SearchIndex(chunks, emb)
    tfs = [Counter(tokenize(index_text(c))) for c in chunks]
    lens = [sum(t.values()) for t in tfs]
    vectors = emb.embed([index_text(c) for c in chunks])
    return index, tfs, lens, vectors, emb


SCOPES = [None, {"public"}, {"public", "hr-policy", "finance-policy"}]


@pytest.mark.parametrize("scopes", SCOPES, ids=["전체", "공개만", "정책"])
def test_BM25_점수와_순위가_같다(setup, scopes):
    index, tfs, lens, _, _ = setup
    ids = index.allowed(scopes or all_scopes())
    for q in questions():
        got = index.bm25(q["question"], ids)
        want = ref_bm25(tfs, lens, q["question"], ids)
        assert [i for i, _ in got] == [i for i, _ in want], q["id"]
        assert all(abs(a - b) < 1e-9 for (_, a), (_, b) in zip(got, want, strict=True))


@pytest.mark.parametrize("scopes", SCOPES, ids=["전체", "공개만", "정책"])
def test_벡터_점수가_같고_순위는_동점_차이만_있다(setup, scopes):
    index, _, _, vectors, emb = setup
    ids = index.allowed(scopes or all_scopes())
    for q in questions():
        qv = emb.embed([q["question"]])[0]
        want = dict((i, ref_cosine(qv, vectors[i])) for i in ids)
        got = index.vector(q["question"], ids)
        assert {i for i, _ in got} == set(ids)
        assert all(abs(s - want[i]) < 1e-5 for i, s in got)  # float32 행렬
        scores = [s for _, s in got]
        assert all(a >= b - 1e-6 for a, b in zip(scores, scores[1:]))


def test_권한_밖_청크는_벡터_후보에_없다(setup):
    index, *_ = setup
    ids = index.allowed({"public"})
    got = {i for i, _ in index.vector("기본급", ids)}
    assert got == set(ids) and all(index.chunks[i].acl_tags & {"public"} for i in got)


def test_파기_뒤에도_벡터와_역색인이_청크와_맞는다(setup):
    _, _, _, _, emb = setup
    chunks, _ = scaled_chunks(2)
    index = SearchIndex(chunks, emb)
    index.remove_document("gen-room-guide")
    ids = index.allowed(all_scopes())
    for i, _ in index.bm25("회의실 예약", ids) + index.vector("회의실 예약", ids):
        assert index.chunks[i].doc_id != "gen-room-guide"
    want = emb.embed([index_text(index.chunks[0])])[0]
    norm = math.sqrt(sum(x * x for x in want))
    assert index._state.vectors.shape[0] == len(index.chunks)
    assert abs(float(index._state.vectors[0][0]) - want[0] / norm) < 1e-6
