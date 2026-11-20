"""대화마다 위임 토큰을 발급합니다(요청자 확인 → 에이전트 호출 자격 확인 → 범위 계산 → 서명)."""

from __future__ import annotations

from gateway.erp_client import ErpClient
from gateway.problems import ProblemError
from gateway.registry import Registry, Requester, grant_matches
from gateway.tokens import DelegationTokenIssuer, IssuedToken


async def load_requester(erp: ErpClient, employee_jwt: str) -> Requester:
    me = await erp.get_json("/me", employee_jwt)
    tags = await erp.get_json("/me/access-tags", employee_jwt)
    return Requester(id=me["id"], unit_id=me["unitId"], grade=me["grade"], roles=tuple(me.get("roles", [])),
                     access_tags=tuple(tags.get("tags", [])))


class DelegationService:
    def __init__(self, erp: ErpClient, registry: Registry, issuer: DelegationTokenIssuer):
        self.erp, self.registry, self.issuer = erp, registry, issuer

    async def issue(self, employee_jwt: str, agent_id: str, conversation_id: str) -> IssuedToken:
        agent = self.registry.get(agent_id)
        if agent is None:
            raise ProblemError(404, "not-found", "없는 에이전트입니다", agent_id)
        who = await load_requester(self.erp, employee_jwt)
        if not grant_matches(agent.callable_by, who):
            raise ProblemError(403, "forbidden", "이 에이전트를 부를 수 없습니다", agent_id)
        return self.issuer.issue(who, agent, conversation_id)
