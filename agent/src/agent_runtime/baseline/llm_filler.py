"""같은 입력을 LLM 도구 호출 한 번으로 채웁니다. RuleSlotFiller와 같은 SlotResult를 돌려줘 비교에 씁니다."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from agent_runtime.baseline.slots import WEEKDAYS, SlotResult
from agent_runtime.llm import ChatClient, LLMError

SLOT_TOOLS = ("leave_request", "room_list_availability", "room_reserve")
INTENT = {"leave_request": "leave", "room_list_availability": "room", "room_reserve": "room"}


def load_slot_tools(tools_file: Path) -> list[dict[str, Any]]:
    doc = json.loads(tools_file.read_text("utf-8"))
    return [t for t in doc["tools"] if t["name"] in SLOT_TOOLS]


class LlmSlotFiller:
    def __init__(self, llm: ChatClient, tools: list[dict[str, Any]], headers: dict[str, str] | None = None) -> None:
        self.llm = llm
        self.tools = tools
        self.headers = headers or {}

    def fill(self, message: str, today: date, rooms: list[dict[str, Any]] | None = None) -> SlotResult:
        lines = [
            f"오늘은 {today.isoformat()}({WEEKDAYS[today.weekday()]})이고 시간대는 +09:00입니다.",
            "직원의 요청에 맞는 도구 하나를 골라 인자를 채웁니다. 맞는 도구가 없으면 도구를 부르지 않습니다.",
            "회의실 예약 요청인데 회의실을 특정할 수 없으면 room_list_availability를 고릅니다.",
        ]
        if rooms:
            lines.append("회의실: " + ", ".join(f"{r['name']}(id {r['id']})" for r in rooms))
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["inputSchema"]}} for t in self.tools]
        try:
            msg = self.llm.chat([{"role": "system", "content": "\n".join(lines)},
                                 {"role": "user", "content": message}], tools, self.headers)
        except LLMError:
            return SlotResult(None, None, {}, ("llm_error",))
        calls = msg.get("tool_calls") or []
        if not calls:
            return SlotResult(None, None, {}, ())
        fn = calls[0].get("function") or {}
        name = fn.get("name")
        if name not in INTENT:
            return SlotResult(None, None, {}, ())
        try:
            args = fn.get("arguments")
            args = json.loads(args) if isinstance(args, str) else dict(args or {})
        except (ValueError, TypeError):
            return SlotResult(INTENT[name], name, {}, ("arguments",))
        schema = next(t["inputSchema"] for t in self.tools if t["name"] == name)
        missing = tuple(k for k in schema.get("required", []) if k not in args)
        return SlotResult(INTENT[name], name, args, missing)
