"""답 생성 호출 설정을 gateway 모델 프로필에서 읽습니다(#602, 결정 0009, gateway `GET /v1/model-profiles`).

호출하는 별칭(`RAG_LLM_MODEL`, 기본 `local`)의 `profile.thinking.ragAnswer`와 `profile.timeoutSeconds`를 읽어
`on`이면 `reasoning_effort: low`, `off`이면 `none`, `default`이면 보내지 않습니다(모델 기본값).

환경 변수는 값이 있을 때만 프로필을 덮어씁니다.
- `RAG_LLM_REASONING`: on·off·default 또는 reasoning_effort 값(none·minimal·low·medium·high). 빈 값은 덮지 않습니다
- `RAG_LLM_TIMEOUT_SECONDS`: 1 이상 정수

프로필을 못 읽으면(프로필 경로가 없는 gateway, 연결 실패 등) 프로필 전의 동작(생각 끔, 120초)으로 부르고
다음 호출에서 다시 읽습니다. 읽은 값은 gateway를 다시 띄울 때까지(계약) 그대로 씁니다.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace

import httpx

log = logging.getLogger("rag.profile")

# 프로필 thinking 값 → reasoning_effort(default면 보내지 않음, 모델 기본값)
EFFORT: dict[str, str | None] = {"on": "low", "off": "none", "default": None}
RAW_EFFORT = ("none", "minimal", "low", "medium", "high")


@dataclass(frozen=True)
class CallSettings:
    """답 생성 호출 한 번의 설정. source: profile(gateway 프로필) | fallback(프로필을 못 읽음) | +env(환경 변수로 덮음)."""

    reasoning_effort: str | None
    timeout_s: float
    source: str
    model: str | None = None


# 프로필을 못 읽을 때: 프로필 전의 동작(생각 끔, 120초) 그대로
FALLBACK = CallSettings("none", 120.0, "fallback")


def profile_url(llm_url: str) -> str:
    """`GATEWAY_LLM_URL`(예: http://gateway:8000/v1)에서 같은 gateway의 프로필 주소를 만듭니다."""
    base = llm_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base + "/v1/model-profiles"


def read_profile(llm_url: str, alias: str, transport: httpx.BaseTransport | None = None,
                 timeout: float = 5.0) -> CallSettings:
    """별칭의 profile.thinking.ragAnswer와 timeoutSeconds를 읽습니다. 연결·형식이 틀리면 예외입니다."""
    with httpx.Client(timeout=timeout, transport=transport) as c:
        r = c.get(profile_url(llm_url))
    r.raise_for_status()
    entry = next(a for a in r.json()["aliases"] if a["alias"] == alias)  # 없으면 StopIteration
    thinking = entry["profile"]["thinking"]["ragAnswer"]
    seconds = entry["profile"]["timeoutSeconds"]
    if thinking not in EFFORT or not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 1:
        raise ValueError(f"프로필 값이 계약과 다릅니다: thinking={thinking!r} timeoutSeconds={seconds!r}")
    return CallSettings(EFFORT[thinking], float(seconds), "profile", entry.get("model"))


def with_env(s: CallSettings, env: Mapping[str, str]) -> CallSettings:
    """RAG_LLM_REASONING, RAG_LLM_TIMEOUT_SECONDS는 값이 있을 때만 덮습니다."""
    reasoning = env.get("RAG_LLM_REASONING", "").strip().lower()
    seconds = env.get("RAG_LLM_TIMEOUT_SECONDS", "").strip()
    out = s
    if reasoning:
        if reasoning in EFFORT:
            out = replace(out, reasoning_effort=EFFORT[reasoning])
        elif reasoning in RAW_EFFORT:
            out = replace(out, reasoning_effort=reasoning)
        else:
            raise ValueError("RAG_LLM_REASONING은 on, off, default 또는 none·minimal·low·medium·high입니다")
    if seconds:
        if not seconds.isdigit() or int(seconds) < 1:
            raise ValueError("RAG_LLM_TIMEOUT_SECONDS는 1 이상 정수입니다")
        out = replace(out, timeout_s=float(seconds))
    return out if out == s else replace(out, source=s.source + "+env")


def resolve(llm_url: str, alias: str, env: Mapping[str, str] | None = None,
            transport: httpx.BaseTransport | None = None) -> CallSettings:
    """프로필 → 환경 변수 덮어쓰기. 프로필을 못 읽으면 FALLBACK에서 시작합니다."""
    try:
        base = read_profile(llm_url, alias, transport)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as e:
        log.warning("모델 프로필을 읽지 못해 기본값(생각 끔, 120초)을 씁니다: %s", type(e).__name__)
        base = FALLBACK
    return with_env(base, os.environ if env is None else env)


class ProfileCache:
    """프로필을 읽어 둡니다. 읽기에 성공한 값만 두고, 못 읽었으면 다음 호출에서 다시 읽습니다(gateway가 늦게 떠도 됨)."""

    def __init__(self, llm_url: str, alias: str, env: Mapping[str, str] | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.llm_url, self.alias, self.env, self.transport = llm_url, alias, env, transport
        self._value: CallSettings | None = None
        self._lock = threading.Lock()

    def get(self) -> CallSettings:
        with self._lock:
            if self._value is not None:
                return self._value
            s = resolve(self.llm_url, self.alias, self.env, self.transport)
            if s.source.startswith("profile"):
                self._value = s
                log.info("답 생성 모델 프로필: %s, reasoning_effort %s, %.0f초(%s)", s.model, s.reasoning_effort,
                         s.timeout_s, s.source)
            return s
