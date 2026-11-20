"""평가 경로 POST /eval/tool-call(contracts/openapi/agent.yaml, #103).

업무 실행의 첫 계획 호출만 하고 도구를 실행하지 않습니다. 변형(ToolCallVariant)
- 모두 끔(S0): 업무 실행과 같은 시스템 프롬프트(full 조건)와 그 에이전트의 도구 목록
- grammar: 첫 호출로 도구를 고르고, 둘째 호출에서 그 도구의 입력 스키마를 response_format(json_schema)으로 걸어 인자를 받습니다
- toolFilterK: 요청 문장과 도구 설명의 글자 두 개 묶음(bigram) 겹침으로 후보를 k개로 줄입니다(같으면 tools.json 순서)
- fewShot: 개발 묶음(eval_dev/tool_calls.jsonl, contracts/eval/toolcall 형식)에서 후보 도구마다 도구를 부르는 예시
  하나를 시스템 프롬프트에 넣습니다.
  평가하는 요청과 문장이 같은 예시는 뺍니다
- thinking: reasoning_effort를 low(켬)·none(끔)으로 보냅니다. null이면 보내지 않습니다
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agent_runtime.llm import ChatClient, ChatReply, LLMError
from agent_runtime.registry import Agent, Registry, Requester
from agent_runtime.run.graph import asks_user, system_prompt

KST_OFFSET = "+09:00"
UNSUPPORTED = "urn:problem:unsupported-parameter"


class EvalBadRequest(Exception):
    """400: 모르는·꺼진 에이전트, 지원하지 않는 변형."""


class EvalUpstreamError(Exception):
    """502: gateway·모델 호출 실패."""


@dataclass(frozen=True)
class Variant:
    grammar: bool = False
    tool_filter_k: int | None = None
    few_shot: bool = False
    thinking: bool | None = None


def load_tools(tools_file: Path) -> dict[str, dict[str, Any]]:
    doc = json.loads(tools_file.read_text("utf-8"))
    return {t["name"]: t for t in doc["tools"]}


def load_examples(path: Path) -> list[dict[str, Any]]:
    """개발 묶음에서 정답이 도구 호출(expected.type=call)인 항목만 읽습니다. 파일이 없으면 빈 목록입니다(fewShot을 쓰면 400)."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if (item.get("expected") or {}).get("type") == "call":
                out.append(item)
    return out


def bigrams(text: str) -> set[str]:
    s = "".join(ch for ch in text.lower() if not ch.isspace())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def filter_tools(message: str, tools: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """요청과 도구 설명의 bigram 겹침이 큰 순서로 k개. 같으면 주어진 순서(tools.json)를 따릅니다."""
    words = bigrams(message)
    scored = [(len(words & bigrams(t["description"])), -i, t) for i, t in enumerate(tools)]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    keep = {id(t) for _, _, t in scored[:k]}
    return [t for t in tools if id(t) in keep]


def few_shot_lines(examples: list[dict[str, Any]], tool_names: list[str], message: str) -> list[str]:
    lines = ["예시(괄호 안은 그 예시의 기준일):"]
    for name in tool_names:
        ex = next((e for e in examples if e["expected"]["tool"] == name and e["utterance"] != message), None)
        if ex:
            args = json.dumps(ex["expected"].get("args", {}), ensure_ascii=False)
            lines.append(f"- 요청 \"{ex['utterance']}\" ({ex['referenceDate']}) → {name} {args}")
    return lines if len(lines) > 1 else []


class EvalToolCaller:
    def __init__(self, registry: Registry, llm: ChatClient, tools: dict[str, dict[str, Any]],
                 examples: list[dict[str, Any]]) -> None:
        self.registry = registry
        self.llm = llm
        self.tools = tools
        self.examples = examples

    async def run(self, message: str, agent_id: str, requester: Requester, today: date, model: str | None,
                  variant: Variant) -> dict:
        if not self.registry.has(agent_id):
            raise EvalBadRequest(f"모르는 에이전트이거나 이 단계에서 꺼진 에이전트입니다: {agent_id}")
        if variant.few_shot and not self.examples:
            raise EvalBadRequest("few-shot 예시(개발 묶음)를 읽지 못했습니다")
        agent = self.registry.get(agent_id)
        model = model or self.llm.settings.model_for(agent.model_policy)
        # 업무 실행과 같이, 요청자가 부를 수 없는 에이전트는 도구 없이 안내만 합니다.
        # 도구 순서는 업무 실행과 같게 tools.json(MCP 카탈로그) 순서입니다.
        defs = [t for n, t in self.tools.items() if n in agent.tools] if agent.callable_for(requester) else []
        if variant.tool_filter_k is not None:
            defs = filter_tools(message, defs, variant.tool_filter_k)
        names = [t["name"] for t in defs]
        messages = [{"role": "system", "content": self._prompt(agent, today, names, message, variant)},
                    {"role": "user", "content": message}]
        extra = _thinking(variant.thinking)
        openai_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                          "parameters": t["inputSchema"]}} for t in defs]
        replies = [await self._call(messages, openai_tools or None, model, extra)]
        first = replies[0].message
        calls = first.get("tool_calls") or []
        tool, raw = None, None
        if calls:
            fn = calls[0].get("function") or {}
            tool = fn.get("name")
            raw = fn.get("arguments")
            if raw is not None and not isinstance(raw, str):
                raw = json.dumps(raw, ensure_ascii=False)
        if variant.grammar and tool in names:
            schema = self.tools[tool]["inputSchema"]
            arg_messages = [*messages, {"role": "assistant", "content": first.get("content") or ""},
                            {"role": "user", "content": f"{tool} 도구의 인자를 JSON 객체 하나로만 답합니다."}]
            fmt = {"response_format": {"type": "json_schema",
                                       "json_schema": {"name": tool, "schema": schema, "strict": True}}}
            replies.append(await self._call(arg_messages, None, model, {**extra, **fmt}))
            raw = replies[-1].message.get("content") or ""
        content = first.get("content") or ""
        last = replies[-1]
        return {
            "tool": tool,
            "arguments": _parse(raw),
            "rawArguments": raw,
            "content": content,
            "asked": tool is None and asks_user(content),
            "candidates": names,
            "model": {"requested": model, "egress": last.egress_model,
                      "location": last.egress_location if last.egress_location in ("local", "external") else None},
            "latencyMs": sum(r.latency_ms for r in replies),
            "llmCalls": len(replies),
            "usage": _sum_usage(replies),
        }

    def _prompt(self, agent: Agent, today: date, names: list[str], message: str, variant: Variant) -> str:
        now = datetime.fromisoformat(f"{today.isoformat()}T09:00:00{KST_OFFSET}")
        text = system_prompt(agent, "full", now, bool(names))
        if variant.few_shot:
            lines = few_shot_lines(self.examples, names, message)
            if lines:
                text = "\n".join([text, *lines])
        return text

    async def _call(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, model: str,
                    extra: dict[str, Any]) -> ChatReply:
        try:
            return await asyncio.to_thread(self.llm.chat_detail, messages, tools, None, model, extra)
        except LLMError as e:
            # gateway는 모델이 지원하지 않는 요청 기능(response_format, reasoning_effort 등)을 400 unsupported-parameter로 줍니다.
            if e.status == 400 and e.problem_type == UNSUPPORTED:
                what = "구조화 출력(grammar)" if "response_format" in extra else "요청한 변형"
                raise EvalBadRequest(f"이 별칭은 {what}을 지원하지 않습니다: {model}") from None
            raise EvalUpstreamError(str(e)) from None


def _thinking(value: bool | None) -> dict[str, Any]:
    if value is None:
        return {}
    return {"reasoning_effort": "low" if value else "none"}


def _parse(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _sum_usage(replies: list[ChatReply]) -> dict[str, int] | None:
    if any(r.usage is None for r in replies):
        return None
    return {"promptTokens": sum(r.usage["promptTokens"] for r in replies),
            "completionTokens": sum(r.usage["completionTokens"] for r in replies)}
