package io.inhouse.erp.auth;

import java.util.Set;

/**
 * 요청한 사람. 직원 JWT면 직원 본인, 위임 토큰이면 토큰 주인(sub)과 토큰 ID(jti)·에이전트·대화·scope를 함께 갖습니다.
 * viaServiceLogin은 서비스 로그인(슬랙 입구, amr slack)으로 받은 직원 JWT이고, 사람 전용 기능을 부를 수 없습니다.
 */
public record ErpPrincipal(String employeeId, boolean viaDelegationToken, String delegationTokenId, String agentId,
                           String conversationId, Set<String> scopes, boolean viaServiceLogin) {

    public static ErpPrincipal employee(String employeeId) {
        return new ErpPrincipal(employeeId, false, null, null, null, Set.of(), false);
    }

    /** 감사 이벤트 actor.channel: 위임 토큰이면 agent, 서비스 로그인(amr slack)이면 slack, 그 밖에는 web. */
    public String channel() {
        return viaDelegationToken ? "agent" : viaServiceLogin ? "slack" : "web";
    }

    public static ErpPrincipal serviceLogin(String employeeId) {
        return new ErpPrincipal(employeeId, false, null, null, null, Set.of(), true);
    }
}
