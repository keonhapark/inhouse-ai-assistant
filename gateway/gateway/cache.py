"""LLM 출구 의미 캐시(#465, contracts/openapi/gateway.yaml 머리말 LLM 출구).

같은 권한 범위에서 같은 뜻의 질문이 다시 오면 LLM을 부르지 않고 저장한 답을 돌려줍니다.

적중 조건
- 범위가 같음: 에이전트(`agt`), 위임 토큰 `scopes`·`doc_scopes`, 실제로 보낼 별칭. 다른 권한의 답이 새지 않게 합니다.
- 마지막 user 메시지를 뺀 본문이 같음: 시스템 프롬프트·이전 메시지·도구 결과·도구 정의·샘플링 값의 해시. 도구 결과(문서 내용)가
  든 호출은 사실상 정확히 같을 때만 적중합니다.
- 마지막 user 메시지가 의미상 같음: 로컬 임베딩의 코사인 유사도가 문턱 이상.
- 그 메시지의 숫자열이 같음: "3월 9일"과 "3월 10일"은 임베딩으로는 거의 같지만 답이 달라야 합니다.

저장은 도구 호출이 없는 끝난 답(finish_reason stop)만 하고, 메모리에만 TTL 동안 둡니다(디스크에 쓰지 않음).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_DIGITS = re.compile(r"\d+")
# 키 해시에서 빼는 필드. 스트림 여부는 캐시가 스트림을 받지 않아 늘 같습니다.
_KEY_SKIP = frozenset({"stream", "stream_options"})

Embed = Callable[[str], Awaitable[list[float]]]


@dataclass(frozen=True)
class Probe:
    """한 요청의 캐시 키. 찾을 때 만든 것을 저장할 때 그대로 써서 임베딩을 두 번 부르지 않습니다."""
    bucket: tuple
    vector: tuple[float, ...]
    digits: tuple[str, ...]


@dataclass
class Entry:
    vector: tuple[float, ...]
    digits: tuple[str, ...]
    content: bytes
    media_type: str
    expires: float


@dataclass
class Hit:
    entry: Entry
    similarity: float


@dataclass
class SemanticCache:
    embed: Embed
    threshold: float = 0.95
    ttl: float = 600.0
    max_entries: int = 1000
    clock: Callable[[], float] = time.monotonic
    _buckets: OrderedDict[tuple, list[Entry]] = field(default_factory=OrderedDict)

    @staticmethod
    def split(body: dict[str, Any]) -> tuple[str, str] | None:
        """(마지막 user 메시지를 뺀 본문의 해시, 그 메시지 글)을 돌려줍니다. user 글이 없으면 None(캐시 안 함)."""
        messages = body.get("messages") or []
        idx = next((i for i in range(len(messages) - 1, -1, -1)
                    if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
        if idx is None:
            return None
        content = messages[idx].get("content")
        if isinstance(content, list):
            if any(not isinstance(p, dict) or p.get("type") != "text" for p in content):
                return None
            content = "\n".join(str(p.get("text", "")) for p in content)
        if not isinstance(content, str) or not content.strip():
            return None
        rest = [dict(m, content=None) if i == idx else m for i, m in enumerate(messages)]
        key = {k: v for k, v in body.items() if k not in _KEY_SKIP} | {"messages": rest}
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return digest, content

    async def probe(self, scope: tuple, body: dict[str, Any]) -> Probe | None:
        parts = self.split(body)
        if parts is None:
            return None
        digest, text = parts
        vector = _unit(await self.embed(text))
        return Probe((*scope, digest), vector, tuple(_DIGITS.findall(text)))

    def lookup(self, probe: Probe) -> Hit | None:
        now = self.clock()
        entries = [e for e in self._buckets.get(probe.bucket, []) if e.expires > now]
        if entries:
            self._buckets[probe.bucket] = entries
        else:
            self._buckets.pop(probe.bucket, None)
        best: Hit | None = None
        for e in entries:
            if e.digits != probe.digits:
                continue
            sim = sum(a * b for a, b in zip(e.vector, probe.vector))
            if sim >= self.threshold and (best is None or sim > best.similarity):
                best = Hit(e, sim)
        return best

    def store(self, probe: Probe, content: bytes, media_type: str) -> bool:
        """도구 호출이 없는 끝난 답만 저장합니다. 저장했으면 True."""
        if not cacheable(content):
            return False
        entries = self._buckets.setdefault(probe.bucket, [])
        entries.append(Entry(probe.vector, probe.digits, content, media_type, self.clock() + self.ttl))
        self._buckets.move_to_end(probe.bucket)
        while self.size() > self.max_entries:
            oldest = next(iter(self._buckets))
            if self._buckets[oldest]:
                self._buckets[oldest].pop(0)
            if not self._buckets[oldest]:
                del self._buckets[oldest]
        return True

    def size(self) -> int:
        return sum(len(v) for v in self._buckets.values())


def cacheable(content: bytes) -> bool:
    try:
        choices = json.loads(content)["choices"]
        return (len(choices) == 1 and choices[0].get("finish_reason") == "stop"
                and not choices[0]["message"].get("tool_calls") and isinstance(choices[0]["message"].get("content"), str))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return False


def _unit(v: list[float]) -> tuple[float, ...]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / n for x in v)
