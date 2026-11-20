"""슬롯 채우기를 명령줄에서 비교합니다.

사용: uv run python -m agent_runtime.baseline [--method rule|llm|both] [--today YYYY-MM-DD]
      [--rooms rooms.json] "문장" ...
출력: 문장마다 JSON 한 줄({"message", "method", "intent", "tool", "arguments", "missing"})
llm은 LLMSettings.from_env()의 경로(기본 gateway, 개발용 AGENT_LLM_BACKEND=ollama)로 부릅니다.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path

from agent_runtime.baseline.llm_filler import LlmSlotFiller, load_slot_tools
from agent_runtime.baseline.slots import KST, RuleSlotFiller, SlotFiller


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_runtime.baseline")
    p.add_argument("messages", nargs="+")
    p.add_argument("--method", choices=["rule", "llm", "both"], default="rule")
    p.add_argument("--today", type=date.fromisoformat, default=datetime.now(KST).date())
    p.add_argument("--rooms", type=Path, help='[{"id", "name"}] 또는 {"rooms": [...]} JSON')
    a = p.parse_args(argv)
    rooms = None
    if a.rooms:
        raw = json.loads(a.rooms.read_text("utf-8"))
        rooms = raw["rooms"] if isinstance(raw, dict) else raw
    fillers: dict[str, SlotFiller] = {}
    if a.method in ("rule", "both"):
        fillers["rule"] = RuleSlotFiller()
    if a.method in ("llm", "both"):
        from agent_runtime.llm import ChatClient, LLMSettings

        contracts = Path(os.environ.get("CONTRACTS_DIR", "../contracts"))
        fillers["llm"] = LlmSlotFiller(ChatClient(LLMSettings.from_env()), load_slot_tools(contracts / "mcp" / "tools.json"))
    for message in a.messages:
        for method, filler in fillers.items():
            out = {"message": message, "method": method, **filler.fill(message, a.today, rooms).to_dict()}
            print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
