"""팩의 에이전트 등록부와 MCP 도구 계약을 읽어, 에이전트별로 위임 토큰에 넣을 범위를 계산합니다.

업종 용어는 코드에 두지 않고 팩(agents.yaml)과 계약(tools.json, scopes.json)에서만 읽습니다.
"""

from __future__ import annotations

import json
import re
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
    channel: str = "web"   # 요청이 들어온 입구(web·slack). 감사 actor.channel(#338)


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
                 access_tags: tuple[str, ...] = (), stage: int | None = None,
                 unit_names: dict[str, str] | None = None):
        """stage를 주면 그 단계 이하 에이전트만 싣습니다(#170). None이면 모두 싣습니다."""
        self.stage = stage
        self.unit_names = dict(unit_names or {})
        self.tool_meta = {t["name"]: t for t in tools_doc["tools"]}
        human_only = {s["id"] for s in scopes_doc["scopes"] if s.get("human_only")}
        # 평가 조건 no_guard·baseline_tools의 공용 계정 범위: 사람 전용을 뺀 모든 scope, 팩의 모든 문서 태그
        self.wide_scopes = tuple(s["id"] for s in scopes_doc["scopes"] if not s.get("human_only"))
        self.all_access_tags = tuple(access_tags)
        tool_scope = {t["name"]: t["required_scope"] for t in tools_doc["tools"]}
        self.fallback_agent: str | None = agents_doc.get("fallback_agent")
        self._agents: dict[str, AgentEntry] = {}
        for a in agents_doc["agents"]:
            if stage is not None and a.get("stage", 1) > stage:
                continue  # 이 단계에서 켜지지 않은 에이전트: /agents에 보이지 않고 위임 토큰도 발급하지 않습니다
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
    def load(cls, pack_dir: Path, contracts_dir: Path, stage: int | None = None) -> Registry:
        """팩 단계는 pack.yaml의 stage 하나가 기준이고, stage 인자(GATEWAY_PACK_STAGE)는 덮어쓰기만 합니다."""
        def read(p: Path) -> Any:
            text = p.read_text(encoding="utf-8")
            return yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)

        org = read(pack_dir / "org.yaml")
        pack = read(pack_dir / "pack.yaml")
        stage = stage if stage is not None else pack.get("stage")
        return cls(
            read(pack_dir / "agents.yaml"),
            read(contracts_dir / "mcp/tools.json"),
            read(contracts_dir / "auth/scopes.json"),
            tuple(t["id"] for t in org.get("access_tags", [])),
            stage,
            {u["id"]: u["name"] for u in org.get("units", [])},
        )

    def get(self, agent_id: str) -> AgentEntry | None:
        return self._agents.get(agent_id)

    def all(self) -> list[AgentEntry]:
        return list(self._agents.values())

    def callable_for(self, who: Requester) -> list[AgentEntry]:
        return [a for a in self._agents.values() if grant_matches(a.callable_by, who)]

    def registry_entry(self, a: AgentEntry, who: Requester) -> dict[str, Any]:
        """등록부 화면용 항목(계약 AgentRegistryEntry). 라우팅 예문은 넣지 않습니다."""
        raw = a.raw
        tools = []
        for name in a.tools:
            meta = self.tool_meta[name]
            tool = {"name": name}
            if title := _first_sentence(meta.get("description", "")):
                tool["title"] = title
            tool["risk"] = meta["risk"]
            tools.append(tool)
        rp = raw.get("risk_policy", {})
        risk_policy: dict[str, Any] = {"read": rp.get("read"), "reversibleWrite": rp.get("reversible_write"),
                                       "irreversible": rp.get("irreversible")}
        if "overrides" in rp:
            risk_policy["overrides"] = [_override(o) for o in rp["overrides"]]
        cb = a.callable_by
        entry: dict[str, Any] = {
            "id": a.id, "name": a.name, "version": raw["version"], "stage": raw.get("stage", 1),
            "ownerUnitId": raw["owner_unit"], "ownerUnitName": self.unit_names.get(raw["owner_unit"]),
            "description": a.description, "callable": grant_matches(cb, who),
            "callableBy": cb if cb == "all" else {k: list(cb[k]) for k in ("units", "roles", "grades") if k in cb},
            "tools": tools, "allowedRisk": list(raw.get("allowed_risk", [])), "docScopes": list(a.doc_scopes),
            "modelPolicy": {k: a.model_policy[k] for k in ("mode", "reason") if k in a.model_policy},
            "riskPolicy": risk_policy,
        }
        if (keywords := raw.get("routing", {}).get("keywords")) is not None:
            entry["routingKeywords"] = list(keywords)
        return entry


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return m.group(1) if m else text.strip()


def _override(o: dict[str, Any]) -> dict[str, Any]:
    """팩의 인자 조건 `when: {arg, gt}`는 계약대로 `when: arg_gt`와 `arg`·`gt`로 씁니다."""
    when = o["when"]
    if isinstance(when, dict):
        return {"tool": o["tool"], "when": "arg_gt", "arg": when["arg"], "gt": when["gt"], "action": o["action"]}
    return {"tool": o["tool"], "when": when, "action": o["action"]}
