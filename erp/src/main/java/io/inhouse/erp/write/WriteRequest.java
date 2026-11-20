package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import io.inhouse.erp.auth.ErpPrincipal;

/**
 * 쓰기 요청의 공통 부분.
 *
 * @param operation      계약의 operationId
 * @param resourceType   행동이 가리킬 리소스 종류(예: approval_document)
 * @param path           요청 경로(멱등 키 해시에 들어감)
 * @param body           요청 본문(없으면 빈 객체)
 * @param idempotencyKey Idempotency-Key 헤더(dryRun이면 쓰지 않음)
 * @param undoOf         되돌리기 요청이면 원래 actionId
 */
public record WriteRequest(ErpPrincipal principal, String operation, String resourceType, String path, JsonNode body,
                           boolean dryRun, String idempotencyKey, String undoOf) {

    public static WriteRequest of(ErpPrincipal principal, String operation, String resourceType, String path,
                                  JsonNode body, boolean dryRun, String idempotencyKey) {
        return new WriteRequest(principal, operation, resourceType, path,
                body == null || body.isNull() ? JsonNodeFactory.instance.objectNode() : body, dryRun,
                idempotencyKey, null);
    }

    public WriteRequest asUndoOf(String actionId) {
        return new WriteRequest(principal, operation, resourceType, path, body, dryRun, idempotencyKey, actionId);
    }
}
