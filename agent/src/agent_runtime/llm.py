"""OpenAI 호환 채팅 엔드포인트 클라이언트.

기본 경로는 gateway(LiteLLM)입니다. gateway가 없을 때만 개발용으로 Ollama의 OpenAI 호환 엔드포인트를
직접 부릅니다(AGENT_LLM_BACKEND=ollama). 시험은 httpx transport를 바꿔 녹화한 응답으로 돕니다.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


GATEWAY_DEFAULT_ALIAS = "local"
# 에이전트 model_policy.mode → gateway 출구 별칭. 기밀 판정으로 로컬로 돌리는 것은 gateway가 합니다.
POLICY_ALIASES = {"external_allowed": "external", "local_only": "local"}


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, problem_type: str | None = None) -> None:
        super().__init__(message)
        self.status = status  # 응답을 받았으면 HTTP 상태
        self.problem_type = problem_type  # gateway 문제 응답의 type(예 urn:problem:unsupported-parameter)


@dataclass(frozen=True)
class ChatReply:
    """평가 경로용 상세 응답. gateway 출구 헤더와 usage, 지연을 함께 돌려줍니다."""

    message: dict[str, Any]
    egress_model: str | None
    egress_location: str | None
    usage: dict[str, int] | None
    latency_ms: int


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    timeout_s: float = 60.0
    extra_body: dict[str, Any] = field(default_factory=dict)
    # gateway 경로에서만 씁니다. 비어 있으면 정책과 관계없이 model을 씁니다(Ollama 개발 경로).
    policy_aliases: dict[str, str] = field(default_factory=dict)

    def model_for(self, model_policy: str | None) -> str:
        """에이전트 정책에 맞는 모델. 정책이 없거나(라우터·슬롯 기준선) 모르는 값이면 model(기본 local)입니다."""
        if model_policy and self.policy_aliases:
            return self.policy_aliases.get(model_policy, GATEWAY_DEFAULT_ALIAS)
        return self.model

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMSettings:
        env = dict(os.environ if env is None else env)
        backend = env.get("AGENT_LLM_BACKEND", "gateway")
        # 생각을 켠 로컬 계획 호출이 여러 턴 대화에서 60초를 넘길 수 있어 120초로 둡니다(결정 0008, #535).
        timeout = float(env.get("AGENT_LLM_TIMEOUT_S", "120"))
        if backend == "ollama":
            # Ollama는 모델 이름 그대로 받습니다.
            model = env.get("AGENT_LLM_MODEL") or env.get("LOCAL_MODEL") or "qwen3.5:9b"
            base = env.get("AGENT_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"
            # 생각 단계는 업무 경로의 계획 호출과 같은 설정(AGENT_PLAN_REASONING_EFFORT)을 따릅니다. 빈 값이면 보내지 않습니다.
            effort = env.get("AGENT_PLAN_REASONING_EFFORT", "")
            return cls(base_url=base, model=model, timeout_s=timeout,
                       extra_body={"reasoning_effort": effort} if effort else {})
        if backend != "gateway":
            raise ValueError(f"AGENT_LLM_BACKEND는 gateway 또는 ollama입니다: {backend}")
        default_gw = f"http://localhost:{env.get('PORT_GATEWAY', '8010')}/v1"
        # gateway는 LiteLLM 별칭(gateway/litellm/config.yaml의 model_name)만 받습니다. 로컬 모델 이름을 보내면 422입니다.
        model = env.get("AGENT_LLM_MODEL") or GATEWAY_DEFAULT_ALIAS
        return cls(base_url=env.get("GATEWAY_LLM_URL", default_gw).rstrip("/"), model=model, timeout_s=timeout,
                   policy_aliases=dict(POLICY_ALIASES))


class ChatClient:
    def __init__(self, settings: LLMSettings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.Client(base_url=settings.base_url, timeout=settings.timeout_s, transport=transport)

    def complete(self, messages: list[dict[str, str]], headers: dict[str, str] | None = None) -> str:
        return self.chat(messages, headers=headers).get("content") or ""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             headers: dict[str, str] | None = None, model_policy: str | None = None,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """assistant 메시지(content, tool_calls)를 돌려줍니다. model_policy는 에이전트 등록부 model_policy.mode입니다."""
        return self.chat_detail(messages, tools, headers, self.settings.model_for(model_policy), extra).message

    def chat_detail(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                    headers: dict[str, str] | None = None, model: str | None = None,
                    extra: dict[str, Any] | None = None) -> ChatReply:
        """chat과 같은 호출에 모델 별칭·추가 본문 필드(response_format, reasoning_effort)를 넣고 상세를 돌려줍니다."""
        body: dict[str, Any] = {"model": model or self.settings.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        body.update(self.settings.extra_body)
        body.update(extra or {})
        started = time.perf_counter()
        try:
            resp = self._http.post("/chat/completions", json=body, headers=headers or {})
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 호출 실패: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            raise LLMError(f"LLM 응답 {resp.status_code}", resp.status_code, _problem_type(resp))
        try:
            data = resp.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError("LLM 응답 형식이 OpenAI 호환이 아닙니다") from e
        if not isinstance(message, dict):
            raise LLMError("LLM 응답 형식이 OpenAI 호환이 아닙니다")
        return ChatReply(message, resp.headers.get("X-Egress-Model"), resp.headers.get("X-Egress-Location"),
                         _usage(data.get("usage")), latency_ms)

    def close(self) -> None:
        self._http.close()


def _usage(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    p, c = raw.get("prompt_tokens"), raw.get("completion_tokens")
    if not isinstance(p, int) or not isinstance(c, int):
        return None
    return {"promptTokens": p, "completionTokens": c}


def _problem_type(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    value = body.get("type") if isinstance(body, dict) else None
    return value if isinstance(value, str) else None
