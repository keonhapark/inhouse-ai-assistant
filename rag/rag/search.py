"""BM25·벡터·하이브리드 검색. 문서 ACL은 검색 전에 적용합니다.

권한 밖 청크는 점수 계산에도 넣지 않습니다. BM25의 문서 빈도도 허용된 청크만으로 셉니다.
전체 말뭉치로 세면 같은 질의의 점수가 제한 문서의 유무에 따라 달라져, 점수만 보고도
제한 문서에 어떤 말이 있는지 짐작할 수 있기 때문입니다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Protocol

from rag.chunk import Chunk

Method = Literal["hybrid", "bm25", "vector"]

_HANGUL = re.compile(r"[가-힣]+")
_OTHER = re.compile(r"[A-Za-z]+|\d+")


def tokenize(text: str) -> list[str]:
    """한글은 음절 2-gram, 영문·숫자는 단어 하나를 토큰으로 씁니다.

    형태소 분석기 없이 조사·어미가 붙은 말("연가를", "연가는")이 같은 토큰("연가")을 갖게 하려는 것입니다.
    한 음절 낱말은 그 음절 하나를 토큰으로 씁니다.
    """
    tokens: list[str] = []
    for word in _HANGUL.findall(text):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    tokens.extend(w.lower() for w in _OTHER.findall(text))
    return tokens


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def _index_text(chunk: Chunk) -> str:
    """색인할 글. 문서 제목과 조문 표시를 앞에 붙여 "여비 규정 제16조" 같은 질의도 맞게 합니다."""
    return " ".join(x for x in (chunk.title, chunk.article or "", chunk.text) if x)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SearchIndex:
    K1 = 1.2
    B = 0.75
    RRF_K = 60  # Reciprocal Rank Fusion 상수(Cormack 외 2009)

    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None):
        self.chunks = chunks
        self.embedder = embedder
        self._tf = [Counter(tokenize(_index_text(c))) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._vectors = embedder.embed([_index_text(c) for c in chunks]) if embedder else None

    def allowed(self, doc_scopes: set[str]) -> list[int]:
        """토큰의 doc_scopes와 문서 ACL 태그가 하나라도 겹치는 청크 번호."""
        return [i for i, c in enumerate(self.chunks) if c.acl_tags & doc_scopes]

    def bm25(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        terms = set(tokenize(query))
        if not ids or not terms:
            return []
        n = len(ids)
        avg = sum(self._len[i] for i in ids) / n
        df = {t: sum(1 for i in ids if t in self._tf[i]) for t in terms}
        scored = []
        for i in ids:
            tf, dl, s = self._tf[i], self._len[i], 0.0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * dl / avg))
            if s > 0:
                scored.append((i, s))
        return sorted(scored, key=lambda x: (-x[1], x[0]))

    def vector(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        if self.embedder is None or self._vectors is None:
            raise RuntimeError("임베딩 모델이 설정되지 않았습니다")
        if not ids:
            return []
        q = self.embedder.embed([query])[0]
        scored = [(i, _cosine(q, self._vectors[i])) for i in ids]
        return sorted(scored, key=lambda x: (-x[1], x[0]))

    def hybrid(self, query: str, ids: list[int], depth: int = 50) -> list[tuple[int, float]]:
        """BM25와 벡터 순위를 Reciprocal Rank Fusion으로 합칩니다. 점수 크기가 달라 순위만 씁니다."""
        fused: dict[int, float] = {}
        for ranking in (self.bm25(query, ids)[:depth], self.vector(query, ids)[:depth]):
            for rank, (i, _) in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1 / (self.RRF_K + rank)
        return sorted(fused.items(), key=lambda x: (-x[1], x[0]))

    def search(self, query: str, doc_scopes: set[str], method: Method = "hybrid", top_k: int = 5) -> list[Hit]:
        ids = self.allowed(doc_scopes)
        ranked = {"bm25": self.bm25, "vector": self.vector, "hybrid": self.hybrid}[method](query, ids)
        return [Hit(self.chunks[i], round(s, 6)) for i, s in ranked[:top_k]]
