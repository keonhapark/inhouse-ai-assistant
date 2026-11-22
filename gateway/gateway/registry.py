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


FORM_SCOPE_PREFIX = "approval:request:"


def _strip_x(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_x(v) for k, v in node.items() if not str(k).startswith("x-")}
    if isinstance(node, list):
        return [_strip_x(v) for v in node]
    return node


def form_tools(forms_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """팩 양식 도구(#397·#403): forms.yaml 양식의 `tool`에서 tools.json 형식의 도구를 만듭니다.

    규칙은 contracts/mcp/README.md '팩 양식 도구'와 참조 구현 contracts/tools/pack_tools.py와 같습니다(시험이 둘을 견줍니다).
    agent MCP 카탈로그도 같은 규칙으로 같은 도구를 만들어, 위임 토큰의 tools·scopes와 실제 도구가 맞습니다.
    """
    out = []
    for f in forms_doc.get("forms", []):
        t = f.get("tool")
        if not t:
            continue
        out.append({
            "name": t["name"],
            "displayName": t.get("displayName") or f"{f['name']} 상신",  # 도구 표시 이름(#575, 계약 참조 구현과 같게)
            "description": t["description"],
            "inputSchema": _strip_x(f["fields"]),
            "risk": t.get("risk", "reversible_write"),
            "trust_required": t.get("trust_required", "user_direct"),
            "required_scope": f"{FORM_SCOPE_PREFIX}{f['id']}",
            "backend": {"service": "erp", "operationId": "createApprovalDocument", "fixed": {"formId": f["id"]}},
            "stage": t.get("stage", f["stage"]),
        })
    return out


PACK_LOCAL_REASON = "팩 단위 외부 LLM 금지(pack.yaml model_policy_override)"


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
                 unit_names: dict[str, str] | None = None, model_policy_override: str | None = None):
        """stage를 주면 그 단계 이하 에이전트만 싣습니다(#170). None이면 모두 싣습니다.

        model_policy_override가 local_only면(pack.yaml, #384) 모든 에이전트의 모델 정책을 local_only로 봅니다.
        """
        self.pack_local_only = model_policy_override == "local_only"
        self.stage = stage
        self.unit_names = dict(unit_names or {})
        self.tool_meta = {t["name"]: t for t in tools_doc["tools"]}
        human_only = {s["id"] for s in scopes_doc["scopes"] if s.get("human_only")}
        # 평가 조건 no_guard·baseline_tools의 공용 계정 범위: 사람 전용을 뺀 모든 scope, 팩의 모든 문서 태그
        # 양식별 범위(approval:request:<양식>)는 scopes.json의 approval:request가 덮으므로 공용 계정 범위는 그대로입니다
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
                model_policy=({"mode": "local_only", "reason": PACK_LOCAL_REASON} if self.pack_local_only
                              else dict(a.get("model_policy", {}))),
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
        shared = read(contracts_dir / "mcp/tools.json")
        forms = read(pack_dir / "forms.yaml") if (pack_dir / "forms.yaml").exists() else {}
        pack_tools = form_tools(forms)
        clash = {t["name"] for t in shared["tools"]} & {t["name"] for t in pack_tools}
        if clash:
            raise ValueError(f"팩 양식 도구 이름이 공용 tools.json과 겹칩니다: {sorted(clash)}")
        return cls(
            read(pack_dir / "agents.yaml"),
            {**shared, "tools": shared["tools"] + pack_tools},
            read(contracts_dir / "auth/scopes.json"),
            tuple(t["id"] for t in org.get("access_tags", [])),
            stage,
            {u["id"]: u["name"] for u in org.get("units", [])},
            pack.get("model_policy_override"),
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
