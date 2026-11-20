"""팩의 에이전트 등록부와 MCP 도구 계약을 읽어, 에이전트별로 위임 토큰에 넣을 범위를 계산합니다.

업종 용어는 코드에 두지 않고 팩(agents.yaml)과 계약(tools.json, scopes.json)에서만 읽습니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentEntry:
    id: str
    name: str
    description: str
    callable_by: Any
    tools: tuple[str, ...]
    doc_scopes: tuple[str, ...]
    model_policy: dict[str, Any]
    scopes: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class Requester:
    """erp `/me`와 `/me/access-tags`에서 얻은 요청자 정보."""

    id: str
    unit_id: str
    grade: str
    roles: tuple[str, ...]
    access_tags: tuple[str, ...]


def grant_matches(grant: Any, who: Requester) -> bool:
    """팩의 grant(`all` 또는 units·grades·roles 중 하나라도 맞으면 허용)를 요청자에 맞춰 봅니다."""
    if grant == "all":
        return True
    if not isinstance(grant, dict):
        return False
    return (
        who.unit_id in grant.get("units", [])
        or who.grade in grant.get("grades", [])
        or bool(set(who.roles) & set(grant.get("roles", [])))
    )


class Registry:
    def __init__(self, agents_doc: dict[str, Any], tools_doc: dict[str, Any], scopes_doc: dict[str, Any],
                 access_tags: tuple[str, ...] = ()):
        human_only = {s["id"] for s in scopes_doc["scopes"] if s.get("human_only")}
        # 평가 조건 no_guard·baseline_tools의 공용 계정 범위: 사람 전용을 뺀 모든 scope, 팩의 모든 문서 태그
        self.wide_scopes = tuple(s["id"] for s in scopes_doc["scopes"] if not s.get("human_only"))
        self.all_access_tags = tuple(access_tags)
        tool_scope = {t["name"]: t["required_scope"] for t in tools_doc["tools"]}
        self.fallback_agent: str | None = agents_doc.get("fallback_agent")
        self._agents: dict[str, AgentEntry] = {}
        for a in agents_doc["agents"]:
            missing = [t for t in a["tools"] if t not in tool_scope]
            if missing:
                raise ValueError(f"에이전트 {a['id']}의 도구가 tools.json에 없습니다: {missing}")
            scopes = sorted({tool_scope[t] for t in a["tools"]} - human_only)
            self._agents[a["id"]] = AgentEntry(
                id=a["id"],
                name=a["name"],
                description=a.get("description", ""),
                callable_by=a["callable_by"],
                tools=tuple(a["tools"]),
                doc_scopes=tuple(a.get("doc_scopes", [])),
                model_policy=dict(a.get("model_policy", {})),
                scopes=tuple(scopes),
                raw=a,
            )

    @classmethod
    def load(cls, pack_dir: Path, contracts_dir: Path) -> Registry:
        def read(p: Path) -> Any:
            text = p.read_text(encoding="utf-8")
            return yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)

        org = read(pack_dir / "org.yaml")
        return cls(
            read(pack_dir / "agents.yaml"),
            read(contracts_dir / "mcp/tools.json"),
            read(contracts_dir / "auth/scopes.json"),
            tuple(t["id"] for t in org.get("access_tags", [])),
        )

    def get(self, agent_id: str) -> AgentEntry | None:
        return self._agents.get(agent_id)

    def all(self) -> list[AgentEntry]:
        return list(self._agents.values())

    def callable_for(self, who: Requester) -> list[AgentEntry]:
        return [a for a in self._agents.values() if grant_matches(a.callable_by, who)]
