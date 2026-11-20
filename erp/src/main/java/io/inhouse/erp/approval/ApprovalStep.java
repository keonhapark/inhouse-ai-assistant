package io.inhouse.erp.approval;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import java.time.OffsetDateTime;

/** 결재선의 한 단계. approverId는 결재선의 원 결재자, actedBy는 실제로 결재한 사람(대결이면 대리인)입니다. */
@Embeddable
public class ApprovalStep {

    @Column(name = "step_order")
    private int stepOrder;
    @Column(name = "approver_id")
    private String approverId;
    private String status;
    @Column(name = "acted_by")
    private String actedBy;
    @Column(name = "on_behalf_of")
    private String onBehalfOf;
    @Column(name = "delegation_id")
    private String delegationId;
    @Column(name = "acted_at")
    private OffsetDateTime actedAt;
    private String comment;

    protected ApprovalStep() {}

    ApprovalStep(int stepOrder, String approverId, String status) {
        this.stepOrder = stepOrder;
        this.approverId = approverId;
        this.status = status;
    }

    void act(String status, String actedBy, String onBehalfOf, String delegationId, OffsetDateTime at,
             String comment) {
        this.status = status;
        this.actedBy = actedBy;
        this.onBehalfOf = onBehalfOf;
        this.delegationId = delegationId;
        this.actedAt = at;
        this.comment = comment;
    }

    void setStatus(String status) {
        this.status = status;
    }

    public int getStepOrder() { return stepOrder; }
    public String getApproverId() { return approverId; }
    public String getStatus() { return status; }
    public String getActedBy() { return actedBy; }
    public String getOnBehalfOf() { return onBehalfOf; }
    public String getDelegationId() { return delegationId; }
    public OffsetDateTime getActedAt() { return actedAt; }
    public String getComment() { return comment; }
}
