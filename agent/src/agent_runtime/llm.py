"""OpenAI 호환 채팅 엔드포인트 클라이언트.

기본 경로는 gateway(LiteLLM)입니다. gateway가 없을 때만 개발용으로 Ollama의 OpenAI 호환 엔드포인트를
직접 부릅니다(AGENT_LLM_BACKEND=ollama). 시험은 httpx transport를 바꿔 녹화한 응답으로 돕니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    timeout_s: float = 60.0
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMSettings:
        env = dict(os.environ if env is None else env)
        backend = env.get("AGENT_LLM_BACKEND", "gateway")
        model = env.get("AGENT_LLM_MODEL") or env.get("LOCAL_MODEL") or "qwen3.5:9b"
        timeout = float(env.get("AGENT_LLM_TIMEOUT_S", "60"))
        if backend == "ollama":
            base = env.get("AGENT_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"
            # 로컬 개발에서 생각 단계를 끄면 라우팅 한 번이 몇 초 안에 끝납니다.
            return cls(base_url=base, model=model, timeout_s=timeout, extra_body={"reasoning_effort": "none"})
        if backend != "gateway":
            raise ValueError(f"AGENT_LLM_BACKEND는 gateway 또는 ollama입니다: {backend}")
        default_gw = f"http://localhost:{env.get('PORT_GATEWAY', '8010')}/v1"
        return cls(base_url=env.get("GATEWAY_LLM_URL", default_gw).rstrip("/"), model=model, timeout_s=timeout)


class ChatClient:
    def __init__(self, settings: LLMSettings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._http = httpx.Client(base_url=settings.base_url, timeout=settings.timeout_s, transport=transport)

    def complete(self, messages: list[dict[str, str]], headers: dict[str, str] | None = None) -> str:
        return self.chat(messages, headers=headers).get("content") or ""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             headers: dict[str, str] | None = None) -> dict[str, Any]:
        """assistant 메시지(content, tool_calls)를 돌려줍니다."""
        body: dict[str, Any] = {"model": self.settings.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        body.update(self.settings.extra_body)
        try:
            resp = self._http.post("/chat/completions", json=body, headers=headers or {})
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 호출 실패: {type(e).__name__}") from e
        if resp.status_code != 200:
            raise LLMError(f"LLM 응답 {resp.status_code}")
        try:
            message = resp.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError("LLM 응답 형식이 OpenAI 호환이 아닙니다") from e
        if not isinstance(message, dict):
            raise LLMError("LLM 응답 형식이 OpenAI 호환이 아닙니다")
        return message

    def close(self) -> None:
        self._http.close()
