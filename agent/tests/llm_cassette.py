"""LLM 응답 녹화·재생.

기본은 재생입니다. 녹화본에 없는 요청이 오면 시험이 실패합니다. 녹화본을 새로 만들려면
AGENT_LLM_RECORD=1로 돌립니다. 이때 실제 LLM은 LLMSettings.from_env()의 경로(로컬 개발은
AGENT_LLM_BACKEND=ollama)로 부르고, 시험 세션 하나에서 AGENT_LLM_CALL_BUDGET(기본 40)번까지만 부릅니다.
로컬 모델은 모든 세션이 같이 쓰므로 실제 호출을 줄이려는 것입니다.

녹화 키는 (model, messages)의 SHA-256입니다. 프롬프트나 등록부가 바뀌면 키가 바뀌어 다시 녹화해야 합니다.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx


class CassetteMiss(AssertionError):
    pass


class BudgetExceeded(AssertionError):
    pass


def request_key(body: dict[str, Any]) -> str:
    raw = json.dumps({"model": body["model"], "messages": body["messages"]}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cassette(httpx.BaseTransport):
    def __init__(self, path: Path, record: bool, budget: int) -> None:
        self.path = path
        self.record = record
        self.budget = budget
        self.real_calls = 0
        self.dirty = False
        self.entries: dict[str, Any] = json.loads(path.read_text("utf-8")) if path.exists() else {}
        self._real = httpx.HTTPTransport() if record else None

    @classmethod
    def from_env(cls, path: Path) -> Cassette:
        return cls(path, os.environ.get("AGENT_LLM_RECORD") == "1", int(os.environ.get("AGENT_LLM_CALL_BUDGET", "40")))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        key = request_key(body)
        if key in self.entries:
            return _response(self.entries[key]["content"])
        if not self.record:
            user = body["messages"][-1]["content"]
            raise CassetteMiss(f"녹화본에 없는 LLM 요청입니다(AGENT_LLM_RECORD=1로 다시 녹화): {user!r}")
        if self.real_calls >= self.budget:
            raise BudgetExceeded(f"이 시험 세션의 실제 LLM 호출 예산 {self.budget}번을 다 썼습니다")
        self.real_calls += 1
        resp = self._real.handle_request(request)
        resp.read()
        if resp.status_code != 200:
            return resp
        content = resp.json()["choices"][0]["message"]["content"]
        self.entries[key] = {"model": body["model"], "user": body["messages"][-1]["content"], "content": content}
        self.dirty = True
        return _response(content)

    def save(self) -> None:
        if self.dirty:
            self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")


def _response(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    })
