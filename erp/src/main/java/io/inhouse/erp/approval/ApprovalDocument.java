package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OrderBy;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * 결재 문서. 상태는 in_progress에서 approved·rejected·withdrawn 중 하나로 끝납니다.
 * version은 낙관적 락입니다. 결재할 때 화면이 본 version과 다르면 409이고, 동시에 두 결재가 커밋되면 하나만 남습니다.
 */
@Entity
@Table(name = "approval_document")
public class ApprovalDocument {

    public static final String IN_PROGRESS = "in_progress";
    public static final String APPROVED = "approved";
    public static final String REJECTED = "rejected";
    public static final String WITHDRAWN = "withdrawn";

    @Id
    private String id;
    @Column(name = "form_id")
    private String formId;
    private String title;
    @Column(name = "requester_id")
    private String requesterId;
    private String status;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode fields;
    private Long amount;
    @Column(name = "current_step")
    private Integer currentStep;
    @Column(name = "leave_days")
    private BigDecimal leaveDays;
    @Version
    private int version;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;
    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "approval_step", joinColumns = @JoinColumn(name = "document_id"))
    @OrderBy("stepOrder")
    private List<ApprovalStep> steps = new ArrayList<>();

    protected ApprovalDocument() {}

    ApprovalDocument(String id, String formId, String title, String requesterId, JsonNode fields, Long amount,
                     BigDecimal leaveDays, List<String> approvers, OffsetDateTime now) {
        this.id = id;
        this.formId = formId;
        this.title = title;
        this.requesterId = requesterId;
        this.fields = fields;
        this.amount = amount;
        this.leaveDays = leaveDays;
        for (int i = 0; i < approvers.size(); i++) {
            steps.add(new ApprovalStep(i + 1, approvers.get(i), i == 0 ? "pending" : "waiting"));
        }
        this.status = approvers.isEmpty() ? APPROVED : IN_PROGRESS;
        this.currentStep = approvers.isEmpty() ? null : 1;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public ApprovalStep current() {
        return currentStep == null ? null : steps.get(currentStep - 1);
    }

    public boolean isLastStep() {
        return currentStep != null && currentStep == steps.size();
    }

    public boolean nobodyActed() {
        return steps.stream().allMatch(s -> "pending".equals(s.getStatus()) || "waiting".equals(s.getStatus()));
    }

    /** 다음 단계로 넘깁니다. */
    void advance(OffsetDateTime now) {
        currentStep++;
        current().setStatus("pending");
        updatedAt = now;
    }

    /** 결재를 끝냅니다(승인·반려·회수). 남은 단계는 그대로 둡니다. */
    void close(String newStatus, OffsetDateTime now) {
        status = newStatus;
        currentStep = null;
        updatedAt = now;
    }

    public boolean involves(String employeeId) {
        return requesterId.equals(employeeId)
                || steps.stream().anyMatch(s -> s.getApproverId().equals(employeeId)
                || employeeId.equals(s.getActedBy()));
    }

    public String getId() { return id; }
    public String getFormId() { return formId; }
    public String getTitle() { return title; }
    public String getRequesterId() { return requesterId; }
    public String getStatus() { return status; }
    public JsonNode getFields() { return fields; }
    public Long getAmount() { return amount; }
    public Integer getCurrentStep() { return currentStep; }
    public BigDecimal getLeaveDays() { return leaveDays; }
    public int getVersion() { return version; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
    public List<ApprovalStep> getSteps() { return steps; }
}
