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
        return self.issue_for(await load_requester(self.erp, employee_jwt), agent_id, conversation_id)

    def issue_for(self, who: Requester, agent_id: str, conversation_id: str, wide: bool = False) -> IssuedToken:
        """요청자 정보를 이미 읽었을 때 씁니다(대화 흐름에서 erp를 두 번 부르지 않게)."""
        agent = self.registry.get(agent_id)
        if agent is None:
            raise ProblemError(404, "not-found", "없는 에이전트입니다", agent_id)
        if not grant_matches(agent.callable_by, who):
            raise ProblemError(403, "forbidden", "이 에이전트를 부를 수 없습니다", agent_id)
        if wide:  # 평가 조건 no_guard·baseline_tools: 공용 계정 범위(contracts/eval/conditions.md)
            return self.issuer.issue(who, agent, conversation_id, scopes=self.registry.wide_scopes,
                                     doc_scopes=self.registry.all_access_tags)
        return self.issuer.issue(who, agent, conversation_id)
