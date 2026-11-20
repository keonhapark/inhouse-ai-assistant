"""임베딩. 실제 모델은 gateway의 OpenAI 호환 `/v1/embeddings`로 부릅니다(모든 모델 호출은 gateway 한 출구).

- `GatewayEmbedder`: `RAG_EMBED_BASE_URL`(없으면 `GATEWAY_LLM_URL`, 예: http://gateway:8000/v1)과 `RAG_EMBED_MODEL`(기본 local-embed)
- `HashEmbedder`: 음절 2-gram을 해시해 고정 차원에 담는 비의미 임베딩. 시험과 모델 없는 개발용입니다.
- `CachedEmbedder`: 본문 SHA-256으로 벡터를 파일에 저장해, 재시작 때 같은 청크를 다시 보내지 않습니다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import httpx

from rag.search import Embedder, tokenize


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
    BATCH = 32

    def __init__(
        self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.name = model
        self._transport = transport
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            for i in range(0, len(texts), self.BATCH):
                batch = texts[i : i + self.BATCH]
                r = client.post(self._url, json={"model": self.name, "input": batch}, headers=self._headers)
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                if len(data) != len(batch):
                    raise ValueError(f"임베딩 {len(batch)}개를 보냈는데 {len(data)}개가 왔습니다")
                vectors.extend(d["embedding"] for d in data)
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

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        missing = list({k: t for k, t in zip(keys, texts, strict=True) if k not in self._cache}.items())
        if missing:
            got = self.inner.embed([t for _, t in missing])
            self._cache.update({k: v for (k, _), v in zip(missing, got, strict=True)})
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache), encoding="utf-8")
        return [self._cache[k] for k in keys]


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
    return CachedEmbedder(GatewayEmbedder(base, model, os.environ.get("RAG_EMBED_API_KEY")), cache_dir)
