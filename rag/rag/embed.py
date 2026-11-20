"""임베딩. 실제 모델은 gateway의 OpenAI 호환 `/v1/embeddings`로 부릅니다(모든 모델 호출은 gateway 한 출구).

- `GatewayEmbedder`: `RAG_EMBED_BASE_URL`(없으면 `GATEWAY_LLM_URL`, 예: http://gateway:8000/v1)과 `RAG_EMBED_MODEL`(기본 local-embed)
- `HashEmbedder`: 음절 2-gram을 해시해 고정 차원에 담는 비의미 임베딩. 시험과 모델 없는 개발용입니다.
- `CachedEmbedder`: 본문 SHA-256으로 벡터를 파일에 저장해, 재시작 때 같은 청크를 다시 보내지 않습니다.
  질의는 캐시하지 않습니다. 질의가 제한 청크와 글자까지 같으면 캐시 적중으로 응답이 빨라져, 권한 없는 사람이
  응답 시간만으로 제한 문서 문장을 맞혀 볼 수 있기 때문입니다. 캐시 파일에는 제한 청크의 해시와 벡터가 있으므로
  권한 0600으로 씁니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from rag.search import Embedder, tokenize

log = logging.getLogger(__name__)


class HashEmbedder:
    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hash-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in tokenize(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
                v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class GatewayEmbedder:
    """gateway `/v1/embeddings` 호출.

    첫 호출이 성공하기 전(시작 때 색인)에는 gateway에 닿지 못하거나 502·503·504를 받으면 `startup_wait`초까지
    다시 시도합니다. compose에서 rag가 gateway보다 먼저 뜨면 연결 거부로 종료하던 문제 때문입니다(#127).
    한 번 성공한 뒤의 질의 임베딩은 다시 시도하지 않고 바로 실패합니다(요청을 오래 붙잡지 않게).
    """

    BATCH = 32
    RETRY_STATUS = {502, 503, 504}

    def __init__(
        self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None, startup_wait: float = 120.0,
        sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
    ):
        self.name = model
        self._transport = transport
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout
        self._startup_wait = startup_wait
        self._sleep = sleep
        self._clock = clock
        self._ready = False

    def _post(self, client: httpx.Client, batch: list[str]) -> httpx.Response:
        deadline = self._clock() + (0 if self._ready else self._startup_wait)
        delay = 1.0
        while True:
            error: httpx.TransportError | None = None
            r: httpx.Response | None = None
            try:
                r = client.post(self._url, json={"model": self.name, "input": batch}, headers=self._headers)
            except httpx.TransportError as e:
                error = e
            if r is not None and r.status_code not in self.RETRY_STATUS:
                return r
            if self._clock() + delay > deadline:
                if error is not None:
                    raise error
                assert r is not None
                return r
            failure = type(error).__name__ if error is not None else f"gateway 응답 {r.status_code if r else '-'}"
            log.warning("임베딩 gateway를 기다립니다(%s), %.0f초 뒤 다시 시도", failure, delay)
            self._sleep(delay)
            delay = min(delay * 2, 10.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for i in range(0, len(texts), self.BATCH):
                batch = texts[i : i + self.BATCH]
                r = self._post(client, batch)
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                if len(data) != len(batch):
                    raise ValueError(f"임베딩 {len(batch)}개를 보냈는데 {len(data)}개가 왔습니다")
                vectors.extend(d["embedding"] for d in data)
                self._ready = True
        return vectors


class CachedEmbedder:
    def __init__(self, inner: Embedder, cache_dir: Path):
        self.inner = inner
        self.name = inner.name
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in inner.name)
        self._path = cache_dir / f"embeddings-{safe}.json"
        self._cache: dict[str, list[float]] = (
            json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        )
        # 파기가 동시에 둘 오면, 앞서 떠 둔 상태를 뒤늦게 써서 지운 벡터가 파일에 되살아날 수 있습니다.
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return self._embed(texts)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        missing = list({k: t for k, t in zip(keys, texts, strict=True) if k not in self._cache}.items())
        if missing:
            got = self.inner.embed([t for _, t in missing])
            self._cache.update({k: v for (k, _), v in zip(missing, got, strict=True)})
            self._save()
        return [self._cache[k] for k in keys]

    def forget(self, texts: set[str]) -> int:
        """글들의 캐시 항목을 지우고 파일에 바로 씁니다(파기). 지운 항목 수를 돌려줍니다."""
        with self._lock:
            keys = {hashlib.sha256(t.encode()).hexdigest() for t in texts} & self._cache.keys()
            for k in keys:
                del self._cache[k]
            if keys:
                self._save()
            return len(keys)

    def _save(self) -> None:
        """임시 파일에 쓰고 바꿔 끼웁니다. 쓰는 도중 멈춰도 지운 항목이 든 옛 파일과 반쯤 쓴 파일이 섞이지 않습니다."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._cache))
        os.replace(tmp, self._path)

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed([text])[0]


def embedder_from_env(cache_dir: Path) -> Embedder:
    """`RAG_EMBEDDER`: gateway(기본) 또는 hash. gateway면 주소와 모델 이름이 있어야 합니다."""
    kind = os.environ.get("RAG_EMBEDDER", "gateway")
    if kind == "hash":
        return HashEmbedder()
    if kind != "gateway":
        raise ValueError(f"RAG_EMBEDDER는 gateway 또는 hash입니다: {kind}")
    base = os.environ.get("RAG_EMBED_BASE_URL") or os.environ.get("GATEWAY_LLM_URL")
    model = os.environ.get("RAG_EMBED_MODEL", "local-embed")
    if not base:
        raise ValueError("RAG_EMBED_BASE_URL이나 GATEWAY_LLM_URL이 필요합니다(또는 RAG_EMBEDDER=hash)")
    wait = float(os.environ.get("RAG_EMBED_STARTUP_WAIT") or 120)
    inner = GatewayEmbedder(base, model, os.environ.get("RAG_EMBED_API_KEY"), startup_wait=wait)
    return CachedEmbedder(inner, cache_dir)
