"""모델 프로필(결정 0009, #601): gateway `GET /v1/model-profiles`에서 agent가 부르는 별칭의 실행 설정을 읽습니다.

- 계획 호출(로컬로 가는 것): 별칭 `local`의 `profile.thinking.plan`
- 이미지 읽기: 이미지가 가는 별칭 `local-vision`(없으면 `local`)의 `profile.thinking.imageRead`
- 호출 시간 제한: 별칭 `local`의 `profile.timeoutSeconds`

thinking 값은 on → reasoning_effort low, off → none, default → 보내지 않음(모델 기본값)입니다.
`AGENT_PLAN_REASONING_EFFORT`(none·low 등 그대로 보냄), `AGENT_LLM_TIMEOUT_S`는 값이 있을 때만 프로필을 덮습니다.
프로필을 못 읽으면 프로필 전의 동작(계획 생각 모델 기본, 이미지 읽기 생각 끔, 120초)을 쓰고, 다음 호출에서 다시 읽습니다
(gateway가 agent보다 늦게 떠도 됨). 프로필은 gateway를 다시 띄워야 바뀌므로(계약) 읽은 값은 다시 읽지 않습니다.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace

import httpx

log = logging.getLogger(__name__)

EFFORT: dict[str, str | None] = {"on": "low", "off": "none", "default": None}


@dataclass(frozen=True)
class RunProfile:
    plan_effort: str | None   # 로컬 계획 호출의 reasoning_effort(None이면 보내지 않음)
    image_effort: str | None  # 이미지 읽기의 reasoning_effort
    timeout_s: float          # LLM 호출 한 번의 시간 제한
    source: str               # profile | fallback, 환경 변수로 덮으면 +env


FALLBACK = RunProfile(None, "none", 120.0, "fallback")


def read_profile(llm_base_url: str, transport: httpx.BaseTransport | None = None, timeout: float = 5.0) -> RunProfile:
    """`llm_base_url`은 gateway OpenAI 호환 주소(…/v1)입니다. 연결·형식이 틀리면 예외입니다."""
    with httpx.Client(timeout=timeout, transport=transport) as c:
        r = c.get(llm_base_url.rstrip("/") + "/model-profiles")
    r.raise_for_status()
    entries = {a["alias"]: a for a in r.json()["aliases"]}
    local = entries["local"]["profile"]
    vision = (entries.get("local-vision") or entries["local"])["profile"]
    plan, image, seconds = local["thinking"]["plan"], vision["thinking"]["imageRead"], local["timeoutSeconds"]
    if plan not in EFFORT or image not in EFFORT or not isinstance(seconds, int) or isinstance(seconds, bool) \
            or seconds < 1:
        raise ValueError(f"프로필 값이 계약과 다릅니다: plan={plan!r} imageRead={image!r} timeoutSeconds={seconds!r}")
    return RunProfile(EFFORT[plan], EFFORT[image], float(seconds), "profile")


def with_env(p: RunProfile, env: Mapping[str, str]) -> RunProfile:
    effort = env.get("AGENT_PLAN_REASONING_EFFORT", "").strip()
    seconds = env.get("AGENT_LLM_TIMEOUT_S", "").strip()
    out = p
    if effort:
        out = replace(out, plan_effort=effort)
    if seconds:
        out = replace(out, timeout_s=float(seconds))
    return out if out == p else replace(out, source=p.source + "+env")


class ProfileCache:
    """프로필을 처음 필요할 때 읽어 둡니다. 읽기에 실패하면 FALLBACK(+env)을 쓰고 다음 호출에서 다시 읽습니다."""

    def __init__(self, llm_base_url: str, env: Mapping[str, str] | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.llm_base_url, self.transport = llm_base_url, transport
        self.env = dict(os.environ if env is None else env)
        self._value: RunProfile | None = None
        self._lock = threading.Lock()

    def get(self) -> RunProfile:
        with self._lock:
            if self._value is not None:
                return self._value
            try:
                self._value = with_env(read_profile(self.llm_base_url, self.transport), self.env)
                log.info("모델 프로필: %s", self._value)
                return self._value
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
                log.warning("모델 프로필을 읽지 못해 기본값을 씁니다: %s", type(e).__name__)
                return with_env(FALLBACK, self.env)


class StaticProfile:
    """gateway 없이 도는 경로(ollama 개발 백엔드·시험)용. 환경 변수만 반영합니다."""

    def __init__(self, profile: RunProfile = FALLBACK, env: Mapping[str, str] | None = None) -> None:
        self._value = with_env(profile, dict(os.environ if env is None else env))

    def get(self) -> RunProfile:
        return self._value
