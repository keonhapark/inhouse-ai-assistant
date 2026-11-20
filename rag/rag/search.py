"""BM25·벡터·하이브리드 검색. 문서 ACL과 판 선택은 검색 전에 적용합니다.

권한 밖 청크는 점수 계산에도 넣지 않습니다. BM25의 문서 빈도도 허용된 청크만으로 셉니다.
전체 말뭉치로 세면 같은 질의의 점수가 제한 문서의 유무에 따라 달라져, 점수만 보고도
제한 문서에 어떤 말이 있는지 짐작할 수 있기 때문입니다.

판이 여럿인 법령은 기준일(`as_of`, 없으면 오늘 KST)에 시행 중인 판만 후보로 둡니다(`editions="as_of"`).
옛 판과 현행판의 같은 조문은 글이 거의 같아 점수로는 가려지지 않고, 옛 판을 인용한 답이 나오기 때문입니다.
`editions="all"`은 판을 가리지 않는 기준선 비교용입니다.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
from typing import Literal, Protocol

from rag.chunk import Chunk

Method = Literal["hybrid", "bm25", "vector"]
EditionPolicy = Literal["as_of", "all"]
KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()

_HANGUL = re.compile(r"[가-힣]+")
_ARTICLE_REF = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_OTHER = re.compile(r"[A-Za-z]+|\d+")


def tokenize(text: str) -> list[str]:
    """한글은 음절 2-gram, 영문·숫자는 단어 하나를 토큰으로 씁니다.

    형태소 분석기 없이 조사·어미가 붙은 말("연가를", "연가는")이 같은 토큰("연가")을 갖게 하려는 것입니다.
    한 음절 낱말은 그 음절 하나를 토큰으로 씁니다. "제16조", "제13조의2" 같은 조문 번호는 통째로 토큰 하나를
    더합니다. 2-gram만으로는 "제", "조"가 거의 모든 조문에 있어 조문 번호 질의를 가려내지 못합니다.
    """
    tokens: list[str] = [
        f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "") for m in _ARTICLE_REF.finditer(text)
    ]
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


def embed_query(embedder: Embedder, query: str, delegation_token: str | None = None) -> list[float]:
    """질의 임베딩. 캐시가 있는 임베더라도 질의는 캐시를 거치지 않습니다(`CachedEmbedder.embed_query`).

    `delegation_token`은 요청한 대화의 위임 토큰입니다. gateway가 같은 대화의 조건과 감사(conversationId)를
    적용하도록 임베딩 요청에도 붙입니다(contracts/eval/conditions.md).
    """
    if fn := getattr(embedder, "embed_query", None):
        return fn(query, delegation_token)
    return embedder.embed([query])[0]


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


def index_text(chunk: Chunk) -> str:
    """색인할 글. 문서 제목과 조문 표시를 앞에 붙여 "여비 규정 제16조" 같은 질의도 맞게 합니다."""
    return " ".join(x for x in (chunk.title, chunk.article or "", chunk.text) if x)


def _unit_rows(vectors: list[list[float]]) -> np.ndarray:
    """행마다 길이 1로 맞춘 float32 행렬. 길이 0인 행은 0으로 둡니다(코사인 0)."""
    m = np.asarray(vectors, dtype=np.float32)
    if m.ndim != 2:
        m = m.reshape(len(vectors), -1)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return np.divide(m, norms, out=np.zeros_like(m), where=norms > 0)


def _postings(tf: tuple[Counter[str], ...]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """토큰 → (그 토큰이 있는 청크 번호, 빈도). BM25가 질의 토큰이 든 청크만 보게 합니다."""
    acc: dict[str, tuple[list[int], list[int]]] = {}
    for i, counts in enumerate(tf):
        for t, f in counts.items():
            ids, freqs = acc.setdefault(t, ([], []))
            ids.append(i)
            freqs.append(f)
    return {t: (np.asarray(ids, dtype=np.int64), np.asarray(fs, dtype=np.float64)) for t, (ids, fs) in acc.items()}


@dataclass(frozen=True)
class _State:
    """색인 한 벌. 파기는 새 벌을 만들어 통째로 바꿉니다. 검색은 시작할 때 잡은 한 벌만 써서,
    검색 도중 파기가 끼어도 청크 번호가 어긋나지 않습니다."""

    chunks: tuple[Chunk, ...]
    tf: tuple[Counter[str], ...]
    lens: np.ndarray  # 청크마다 토큰 수(int64)
    postings: dict[str, tuple[np.ndarray, np.ndarray]]
    vectors: np.ndarray | None  # 행마다 길이 1인 float32 (청크 수 × 차원)

    @classmethod
    def build(cls, chunks: tuple[Chunk, ...], tf: tuple[Counter[str], ...], vectors: np.ndarray | None) -> _State:
        lens = np.asarray([sum(t.values()) for t in tf], dtype=np.int64)
        return cls(chunks, tf, lens, _postings(tf), vectors)


class SearchIndex:
    K1 = 1.2
    B = 0.75
    RRF_K = 60  # Reciprocal Rank Fusion 상수(Cormack 외 2009)

    def __init__(
        self,
        chunks: list[Chunk],
        embedder: Embedder | None = None,
        *,
        editions: EditionPolicy = "as_of",
        today: Callable[[], date] = today_kst,
    ):
        self.embedder = embedder
        self.editions = editions
        self.today = today
        tf = tuple(Counter(tokenize(index_text(c))) for c in chunks)
        vectors = _unit_rows(embedder.embed([index_text(c) for c in chunks])) if embedder and chunks else None
        if embedder and not chunks:
            vectors = np.zeros((0, 0), dtype=np.float32)
        self._state = _State.build(tuple(chunks), tf, vectors)
        self._lock = threading.Lock()
        self.version = 0  # 파기할 때마다 1씩 늘어, 색인에서 따로 만든 것(판 대조표)을 다시 만들 때를 알립니다.

    @property
    def chunks(self) -> tuple[Chunk, ...]:
        return self._state.chunks

    def remove_document(self, doc_id: str) -> list[Chunk]:
        """문서의 모든 판의 청크와 벡터를 색인에서 지우고, 지운 청크를 돌려줍니다."""
        with self._lock:
            st = self._state
            keep = [i for i, c in enumerate(st.chunks) if c.doc_id != doc_id]
            removed = [c for c in st.chunks if c.doc_id == doc_id]
            if removed:
                self._state = _State.build(
                    tuple(st.chunks[i] for i in keep),
                    tuple(st.tf[i] for i in keep),
                    st.vectors[np.asarray(keep, dtype=np.int64)] if st.vectors is not None else None,
                )
                self.version += 1
            return removed

    def doc_ids(self) -> set[str]:
        """색인에 남은 문서 ID."""
        return {c.doc_id for c in self._state.chunks}

    def indexed_texts(self) -> set[str]:
        """색인에 남은 청크의 임베딩 입력 글."""
        return {index_text(c) for c in self._state.chunks}

    def allowed(self, doc_scopes: set[str], as_of: date | None = None) -> list[int]:
        """토큰의 doc_scopes와 문서 ACL 태그가 하나라도 겹치고, 기준일에 시행 중인 판의 청크 번호."""
        return self._allowed(self._state, doc_scopes, as_of)

    def _allowed(self, st: _State, doc_scopes: set[str], as_of: date | None) -> list[int]:
        on = as_of or self.today()
        return [i for i, c in enumerate(st.chunks) if c.acl_tags & doc_scopes and self._in_force(c, on)]

    def _in_force(self, chunk: Chunk, on: date) -> bool:
        return self.editions == "all" or chunk.edition is None or chunk.edition.in_force(on)

    def top_ignoring_acl(self, query: str, n: int = 1) -> list[Chunk]:
        """ACL과 판을 보지 않은 BM25 상위 청크. 감사 기록(권한 밖 1위)에만 씁니다."""
        st = self._state
        return [st.chunks[i] for i, _ in self._bm25(st, query, list(range(len(st.chunks))))[:n]]

    def bm25(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        return self._bm25(self._state, query, ids)

    def _bm25(self, st: _State, query: str, ids: list[int]) -> list[tuple[int, float]]:
        terms = set(tokenize(query))
        if not ids or not terms:
            return []
        allowed = np.asarray(ids, dtype=np.int64)
        mask = np.zeros(len(st.chunks), dtype=bool)
        mask[allowed] = True
        n = len(ids)
        avg = int(st.lens[allowed].sum()) / n
        scores = np.zeros(len(st.chunks), dtype=np.float64)
        # 문서 빈도는 허용된 청크만으로 셉니다(권한 밖 문서가 점수에 영향을 주지 않게).
        for t in terms:
            if t not in st.postings:
                continue
            post, freq = st.postings[t]
            keep = mask[post]
            idx, f = post[keep], freq[keep]
            df = len(idx)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            dl = st.lens[idx]
            scores[idx] += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * dl / avg))
        hit = np.flatnonzero(scores > 0)
        order = np.lexsort((hit, -scores[hit]))
        return [(int(i), float(scores[i])) for i in hit[order]]

    def vector(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        return self._vector(self._state, query, ids)

    def _vector(
        self, st: _State, query: str, ids: list[int], token: str | None = None
    ) -> list[tuple[int, float]]:
        if self.embedder is None or st.vectors is None:
            raise RuntimeError("임베딩 모델이 설정되지 않았습니다")
        if not ids:
            return []
        q = np.asarray(embed_query(self.embedder, query, token), dtype=np.float32)
        norm = float(np.linalg.norm(q))
        allowed = np.asarray(ids, dtype=np.int64)
        # 권한 밖 청크의 행은 꺼내지도 않습니다(ACL은 점수 계산 전).
        sims = st.vectors[allowed] @ (q / norm) if norm else np.zeros(len(allowed), dtype=np.float32)
        order = np.lexsort((allowed, -sims))
        return [(int(allowed[k]), float(sims[k])) for k in order]

    def hybrid(self, query: str, ids: list[int], depth: int = 50) -> list[tuple[int, float]]:
        return self._hybrid(self._state, query, ids, depth)

    def _hybrid(
        self, st: _State, query: str, ids: list[int], depth: int = 50, token: str | None = None
    ) -> list[tuple[int, float]]:
        """BM25와 벡터 순위를 Reciprocal Rank Fusion으로 합칩니다. 점수 크기가 달라 순위만 씁니다."""
        fused: dict[int, float] = {}
        for ranking in (self._bm25(st, query, ids)[:depth], self._vector(st, query, ids, token)[:depth]):
            for rank, (i, _) in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1 / (self.RRF_K + rank)
        return sorted(fused.items(), key=lambda x: (-x[1], x[0]))

    def search(
        self,
        query: str,
        doc_scopes: set[str],
        method: Method = "hybrid",
        top_k: int = 5,
        as_of: date | None = None,
        delegation_token: str | None = None,
    ) -> list[Hit]:
        if not tokenize(query):
            return []  # 빈 질의나 기호뿐인 질의에 벡터 유사도만으로 아무 조문이나 내지 않습니다.
        st = self._state
        ids = self._allowed(st, doc_scopes, as_of)
        if method == "bm25":
            ranked = self._bm25(st, query, ids)
        elif method == "vector":
            ranked = self._vector(st, query, ids, delegation_token)
        else:
            ranked = self._hybrid(st, query, ids, token=delegation_token)
        ranked = self._articles_first(st, query, ranked)
        return [Hit(st.chunks[i], round(s, 6)) for i, s in ranked[:top_k]]

    def _articles_first(self, st: _State, query: str, ranked: list[tuple[int, float]]) -> list[tuple[int, float]]:
        """질의에 "제16조"처럼 조문 번호가 있으면, 그 번호가 자기 조문 표시인 청크를 순서를 지킨 채 앞에 둡니다.

        본문 속 참조("제16조에 따라")와 그 조문 자체를 BM25 점수로는 가려낼 수 없기 때문입니다.
        """
        refs = {t for t in tokenize(query) if t.startswith("제") and t[-1] in "조0123456789"}
        if not refs:
            return ranked

        def own(i: int) -> bool:
            return (st.chunks[i].article or "").split("(")[0].split(" ")[0] in refs

        return [x for x in ranked if own(x[0])] + [x for x in ranked if not own(x[0])]
