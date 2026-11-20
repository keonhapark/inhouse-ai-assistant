package io.inhouse.erp.auth;

import java.util.Set;

/**
 * 요청한 사람. 직원 JWT면 직원 본인, 위임 토큰이면 토큰 주인(sub)과 에이전트·대화·scope를 함께 갖습니다.
 */
public record ErpPrincipal(String employeeId, boolean viaDelegationToken, String agentId, String conversationId,
                           Set<String> scopes) {

    public static ErpPrincipal employee(String employeeId) {
        return new ErpPrincipal(employeeId, false, null, null, Set.of());
    }
}
