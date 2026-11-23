"""LLM 분석기(기획서 표 ③의 비교 대상): 기준선이 모은 진단 텍스트를 로컬 모델에 주고 원인 후보 3개를 받습니다.

RCACopilot처럼 "모아 주는 코드"가 핵심이라, 원문 로그를 통째로 주지 않고 기준선의 템플릿 변화·컨테이너 이벤트·
티켓·유사 과거 티켓만 짧게 정리해 줍니다(로컬 모델 문맥과 60초 시간 제한 안).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import httpx

from incident.baseline import BaselineResult
from incident.stack import SERVICES

KINDS = ("dependency_down", "lock_contention", "resource_exhaustion", "dependency_timeout", "data_corruption",
         "bad_config")

SYSTEM = (
    "당신은 사내 시스템의 장애 원인을 찾는 운영 엔지니어입니다. 아래 진단 자료만 근거로, 원인일 가능성이 높은 "
    "서로 다른 서비스 3개를 가능성이 높은 순서대로 고릅니다(같은 서비스를 두 번 쓰지 않음). "
    "증상이 보이는 서비스와 원인 서비스는 다를 수 있습니다(예: 앱 오류의 원인이 DB). "
    "\"<로그가 끊김>\"은 그 서비스가 멈추거나 죽어 로그를 못 남긴 것입니다. "
    "서비스 구성: web → gateway(인증·정책, LLM 출구 앞단) → agent(도구 호출) → erp(Java, PostgreSQL 사용)·rag(규정 검색, "
    "임베딩 캐시 파일). gateway와 rag는 litellm(LLM 프록시)을 거쳐 로컬 모델을 부릅니다.\n"
    f"service는 {', '.join(SERVICES)} 중 하나, kind는 {', '.join(KINDS)} 중 하나입니다.\n"
    '답은 JSON 하나만: {"candidates": [{"service": "...", "kind": "...", "reason": "40자 이내 한 문장", '
    '"evidence": ["근거 줄 하나 그대로"]}]}'
)
MAX_TOKENS = 700


def diagnostics(result: BaselineResult, ticket_text: str | None, max_changes: int = 15) -> str:
    parts = []
    if ticket_text:
        parts.append(f"[신고 티켓]\n{ticket_text}")
    if result.changes:
        rows = [f"- {c.service} {c.level} 기준 {c.before}줄 → 분석 {c.during}줄: {c.example[:240]}"
                for c in result.changes[:max_changes]]
        parts.append("[분석 구간에 늘어난 로그(서비스, 수준, 기준→분석 줄 수, 예시)]\n" + "\n".join(rows))
    else:
        parts.append("[분석 구간에 늘어난 로그] 없음")
    if result.similar:
        rows = [f"- 유사도 {s.similarity}: \"{s.ticket.text[:120]}\" → 원인 {s.ticket.root_service}({s.ticket.kind})"
                for s in result.similar]
        parts.append("[비슷한 과거 티켓과 밝혀진 원인]\n" + "\n".join(rows))
    return "\n\n".join(parts)


@dataclass(frozen=True)
class Candidate:
    service: str
    kind: str | None
    reason: str
    evidence: list[str]


@dataclass(frozen=True)
class LlmResult:
    candidates: list[Candidate]
    latency_ms: int
    raw: str


def parse(content: str) -> list[Candidate]:
    """모델 답에서 후보 객체를 하나씩 꺼냅니다. 답이 길이 제한으로 잘려 전체 JSON이 깨져도 온전한 후보는 씁니다.
    목록 밖 서비스는 버리고, 같은 서비스는 처음 것만 둡니다."""
    decoder = json.JSONDecoder()
    objs: list[Any] = []
    # 키 순서와 상관없이 "service"가 든 객체를 찾습니다. 바깥 {"candidates": ...}도 풀리지만 service가 없어 걸러집니다.
    for m in re.finditer(r"\{", content):
        try:
            obj, _ = decoder.raw_decode(content, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "service" in obj:
            objs.append(obj)
    out: list[Candidate] = []
    seen: set[str] = set()
    for c in objs:
        service = str(c.get("service", "")).strip().lower()
        if service not in SERVICES or service in seen:
            continue
        seen.add(service)
        kind = c.get("kind") if c.get("kind") in KINDS else None
        ev_raw = c.get("evidence", [])
        ev_list = [ev_raw] if isinstance(ev_raw, str) else ev_raw if isinstance(ev_raw, list) else []
        ev = [str(x) for x in ev_list if isinstance(x, (str, int, float))][:3]
        out.append(Candidate(service, kind, str(c.get("reason", ""))[:300], ev))
    return out[:3]


# ---------- 모델 프로필(결정 0009, gateway GET /v1/model-profiles) ----------

log = logging.getLogger("incident.llm")

# 프로필 thinking 값 → reasoning_effort(default면 보내지 않음, 모델 기본값)
EFFORT: dict[str, str | None] = {"on": "low", "off": "none", "default": None}


@dataclass(frozen=True)
class CallSettings:
    """장애 분석 호출 한 번의 설정. source: profile(gateway 프로필) | fallback(프로필을 못 읽음) | +env(환경 변수로 덮음)."""
    thinking: str
    timeout_s: float
    source: str
    model: str | None = None

    @property
    def reasoning_effort(self) -> str | None:
        return EFFORT[self.thinking]


# 프로필을 못 읽을 때(프로필 경로가 없는 gateway 등): 프로필 전의 동작(생각 끔, 90초) 그대로
FALLBACK = CallSettings("off", 90.0, "fallback")


def read_profile(gateway_url: str, alias: str = "local", transport: httpx.BaseTransport | None = None,
                 timeout: float = 5.0) -> CallSettings:
    """별칭의 profile.thinking.incident와 timeoutSeconds를 읽습니다. 연결·형식이 틀리면 예외입니다."""
    with httpx.Client(timeout=timeout, transport=transport) as c:
        r = c.get(gateway_url.rstrip("/") + "/v1/model-profiles")
    r.raise_for_status()
    entry = next(a for a in r.json()["aliases"] if a["alias"] == alias)  # 없으면 StopIteration
    thinking = entry["profile"]["thinking"]["incident"]
    seconds = entry["profile"]["timeoutSeconds"]
    if thinking not in EFFORT or not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 1:
        raise ValueError(f"프로필 값이 계약과 다릅니다: thinking={thinking!r} timeoutSeconds={seconds!r}")
    return CallSettings(thinking, float(seconds), "profile", entry.get("model"))


def with_env(s: CallSettings, env: Mapping[str, str]) -> CallSettings:
    """INCIDENT_LLM_THINKING(on·off·default), INCIDENT_LLM_TIMEOUT_SECONDS(1 이상 정수)는 값이 있을 때만 덮습니다."""
    thinking = env.get("INCIDENT_LLM_THINKING", "").strip().lower()
    seconds = env.get("INCIDENT_LLM_TIMEOUT_SECONDS", "").strip()
    out = s
    if thinking:
        if thinking not in EFFORT:
            raise ValueError("INCIDENT_LLM_THINKING은 on, off, default 중 하나입니다")
        out = replace(out, thinking=thinking)
    if seconds:
        if not seconds.isdigit() or int(seconds) < 1:
            raise ValueError("INCIDENT_LLM_TIMEOUT_SECONDS는 1 이상 정수입니다")
        out = replace(out, timeout_s=float(seconds))
    return out if out == s else replace(out, source=s.source + "+env")


def resolve(gateway_url: str, alias: str = "local", env: Mapping[str, str] | None = None,
            transport: httpx.BaseTransport | None = None) -> CallSettings:
    """프로필 → 환경 변수 덮어쓰기. 프로필을 못 읽으면 FALLBACK에서 시작합니다."""
    try:
        base = read_profile(gateway_url, alias, transport)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as e:
        log.warning("모델 프로필을 읽지 못해 기본값(생각 끔, 90초)을 씁니다: %s", type(e).__name__)
        base = FALLBACK
    return with_env(base, os.environ if env is None else env)


class ProfileCache:
    """프로필을 읽어 둡니다. 읽기에 성공한 값만 두고, 못 읽었으면 다음 호출에서 다시 읽습니다(gateway가 늦게 떠도 됨).
    프로필은 gateway를 다시 띄워야 바뀌므로(계약) 성공한 값은 다시 읽지 않습니다."""

    def __init__(self, gateway_url: str, alias: str = "local", env: Mapping[str, str] | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.gateway_url, self.alias, self.env, self.transport = gateway_url, alias, env, transport
        self._value: CallSettings | None = None
        self._lock = threading.Lock()

    def get(self) -> CallSettings:
        with self._lock:
            if self._value is not None:
                return self._value
            s = resolve(self.gateway_url, self.alias, self.env, self.transport)
            if s.source.startswith("profile"):
                self._value = s
                log.info("장애 분석 모델 프로필: %s, 생각 %s, %.0f초(%s)", s.model, s.thinking, s.timeout_s, s.source)
            return s


def analyze(gateway_url: str, text: str, model: str = "local", settings: CallSettings = FALLBACK,
            transport: httpx.BaseTransport | None = None) -> LlmResult:
    """gateway 출구(/v1/chat/completions, local 별칭)로 부릅니다. 생각 단계·시간 제한은 settings(모델 프로필)를 따릅니다."""
    body: dict[str, Any] = {"model": model, "temperature": 0, "max_tokens": MAX_TOKENS,
                            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]}
    if settings.reasoning_effort is not None:
        body["reasoning_effort"] = settings.reasoning_effort
    started = time.monotonic()
    with httpx.Client(timeout=settings.timeout_s, transport=transport) as c:
        r = c.post(gateway_url.rstrip("/") + "/v1/chat/completions", json=body)
    ms = round((time.monotonic() - started) * 1000)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"] or ""
    return LlmResult(parse(content), ms, content)
