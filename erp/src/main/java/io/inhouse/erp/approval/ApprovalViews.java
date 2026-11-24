package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.inhouse.erp.pack.Pack;
import java.time.OffsetDateTime;
import java.util.Iterator;
import java.util.List;

/** 계약 erp.yaml의 ApprovalDocument·ApprovalStep 응답 형태입니다. */
public final class ApprovalViews {

    private ApprovalViews() {}

    public record StepView(int order, String approverId, String status, String actedBy, String onBehalfOf,
                           String delegationId, OffsetDateTime actedAt, String comment) {}

    public record DocumentView(String id, String formId, String title, String requesterId, String status,
                               JsonNode fields, Long amount, List<StepView> steps, Integer currentStep, int version,
                               OffsetDateTime createdAt, OffsetDateTime updatedAt) {}

    /** form이 있으면 fields를 양식 정의(팩 forms의 properties) 순서로 둡니다. 저장(jsonb)은 키 순서를 지키지 않습니다. */
    public static DocumentView of(ApprovalDocument d, Pack.FormDef form) {
        return new DocumentView(d.getId(), d.getFormId(), d.getTitle(), d.getRequesterId(), d.getStatus(),
                ordered(d.getFields(), form), d.getAmount(),
                d.getSteps().stream().map(s -> new StepView(s.getStepOrder(), s.getApproverId(), s.getStatus(),
                        s.getActedBy(), s.getOnBehalfOf(), s.getDelegationId(), s.getActedAt(), s.getComment()))
                        .toList(),
                d.getCurrentStep(), d.getVersion(), d.getCreatedAt(), d.getUpdatedAt());
    }

    /** 양식에 있는 칸은 양식 순서로, 양식에 없는 칸(양식이 바뀐 뒤의 옛 문서 등)은 그 뒤에 원래 순서로 둡니다. */
    static JsonNode ordered(JsonNode fields, Pack.FormDef form) {
        if (form == null || !fields.isObject()) {
            return fields.deepCopy();
        }
        ObjectNode out = ((ObjectNode) fields).objectNode();
        for (Iterator<String> it = form.fields().path("properties").fieldNames(); it.hasNext(); ) {
            String name = it.next();
            if (fields.has(name)) {
                out.set(name, fields.get(name).deepCopy());
            }
        }
        for (Iterator<String> it = fields.fieldNames(); it.hasNext(); ) {
            String name = it.next();
            if (!out.has(name)) {
                out.set(name, fields.get(name).deepCopy());
            }
        }
        return out;
    }
}
