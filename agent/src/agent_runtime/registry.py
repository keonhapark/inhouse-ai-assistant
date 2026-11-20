"""팩의 에이전트 등록부(agents.yaml)를 읽고, 요청자가 에이전트를 부를 수 있는지 판단합니다.

업종 용어는 코드에 두지 않고 모두 팩에서 읽습니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Requester:
    employee_id: str
    unit_id: str
    grade: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    description: str
    stage: int
    model_policy: str
    callable_by: Any
    tools: tuple[str, ...]
    keywords: tuple[str, ...]
    examples: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False, compare=False)

    def callable_for(self, requester: Requester) -> bool:
        return grant_matches(self.callable_by, requester)


def grant_matches(grant: Any, requester: Requester) -> bool:
    """팩 스키마의 grant: all, 또는 units·roles·grades 중 하나라도 맞으면 부여합니다.

    units는 소속 단위가 정확히 같을 때만 맞습니다(하위 단위로 퍼지지 않음). 가짜 erp와 같은 규칙입니다.
    """
    if grant == "all":
        return True
    if not isinstance(grant, dict):
        return False
    if requester.unit_id in grant.get("units", []):
        return True
    if requester.grade in grant.get("grades", []):
        return True
    return bool(set(requester.roles) & set(grant.get("roles", [])))


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Registry:
    pack_id: str
    pack_stage: int
    fallback_agent_id: str
    agents: tuple[Agent, ...]

    @property
    def fallback(self) -> Agent:
        return self.get(self.fallback_agent_id)

    def get(self, agent_id: str) -> Agent:
        for a in self.agents:
            if a.id == agent_id:
                return a
        raise KeyError(agent_id)

    def has(self, agent_id: str) -> bool:
        return any(a.id == agent_id for a in self.agents)

    @classmethod
    def load(cls, pack_dir: Path) -> Registry:
        pack = _read_yaml(pack_dir / "pack.yaml")
        doc = _read_yaml(pack_dir / "agents.yaml")
        pack_stage = int(pack["stage"])
        enabled = tuple(_to_agent(a) for a in doc["agents"] if int(a["stage"]) <= pack_stage)
        if not enabled:
            raise RegistryError(f"{pack_dir}: 단계 {pack_stage}에서 켜진 에이전트가 없습니다")
        reg = cls(
            pack_id=pack["id"],
            pack_stage=pack_stage,
            fallback_agent_id=doc["fallback_agent"],
            agents=enabled,
        )
        if not reg.has(reg.fallback_agent_id):
            raise RegistryError(f"{pack_dir}: fallback_agent '{reg.fallback_agent_id}'가 켜진 에이전트에 없습니다")
        return reg


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"{path}가 없습니다")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _to_agent(a: dict[str, Any]) -> Agent:
    routing = a.get("routing", {})
    return Agent(
        id=a["id"],
        name=a["name"],
        description=a["description"],
        stage=int(a["stage"]),
        model_policy=a["model_policy"]["mode"],
        callable_by=a["callable_by"],
        tools=tuple(a.get("tools", [])),
        keywords=tuple(routing.get("keywords", [])),
        examples=tuple(routing.get("examples", [])),
        raw=a,
    )
