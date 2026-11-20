package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.OffsetDateTime;
import java.util.List;

/** 계약 erp.yaml의 ApprovalDocument·ApprovalStep 응답 형태입니다. */
public final class ApprovalViews {

    private ApprovalViews() {}

    public record StepView(int order, String approverId, String status, String actedBy, String onBehalfOf,
                           String delegationId, OffsetDateTime actedAt, String comment) {}

    public record DocumentView(String id, String formId, String title, String requesterId, String status,
                               JsonNode fields, Long amount, List<StepView> steps, Integer currentStep, int version,
                               OffsetDateTime createdAt, OffsetDateTime updatedAt) {}

    public static DocumentView of(ApprovalDocument d) {
        return new DocumentView(d.getId(), d.getFormId(), d.getTitle(), d.getRequesterId(), d.getStatus(),
                d.getFields().deepCopy(), d.getAmount(),
                d.getSteps().stream().map(s -> new StepView(s.getStepOrder(), s.getApproverId(), s.getStatus(),
                        s.getActedBy(), s.getOnBehalfOf(), s.getDelegationId(), s.getActedAt(), s.getComment()))
                        .toList(),
                d.getCurrentStep(), d.getVersion(), d.getCreatedAt(), d.getUpdatedAt());
    }
}
