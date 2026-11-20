package io.inhouse.erp.write;

import java.util.List;

/**
 * 쓰기 명령 하나의 결과.
 *
 * @param resource     실행 뒤 대상 리소스(응답 resource)
 * @param resourceId   행동이 가리킬 리소스 ID
 * @param onBehalfOf   결재 대결이면 원 결재자(감사 이벤트)
 * @param delegationId 결재 대결 위임 ID(감사 이벤트)
 */
public record WriteOutcome(String summary, List<Change> changes, boolean undoable, Object resource,
                           String resourceId, String onBehalfOf, String delegationId) {

    public static WriteOutcome of(String summary, Change change, boolean undoable, Object resource, String resourceId) {
        return new WriteOutcome(summary, List.of(change), undoable, resource, resourceId, null, null);
    }

    public WriteOutcome withDelegation(String onBehalfOf, String delegationId) {
        return new WriteOutcome(summary, changes, undoable, resource, resourceId, onBehalfOf, delegationId);
    }
}
