package io.inhouse.erp.audit;

import java.time.OffsetDateTime;

/** contracts/events/audit.schema.json 중 erp가 쓰는 필드입니다. 토큰 문자열·비밀값은 넣지 않습니다. */
public record AuditEvent(
        String eventId,
        OffsetDateTime occurredAt,
        String source,
        String kind,
        Actor actor,
        String onBehalfOf,
        String delegationId,
        String conversationId,
        String actionId,
        String undoOf,
        String operation,
        String result,
        String problemType,
        String detail) {

    /** delegationTokenId는 위임 토큰으로 한 일이면 그 토큰의 jti입니다(gateway 발급 이벤트와 잇는 값). */
    public record Actor(String employeeId, boolean viaDelegationToken, String delegationTokenId, String agentId) {}
}
