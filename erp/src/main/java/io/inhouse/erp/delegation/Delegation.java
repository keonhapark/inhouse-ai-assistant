package io.inhouse.erp.delegation;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import java.util.List;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/**
 * 결재 대결 위임. 위임자(delegator)가 자리를 비운 기간에 대리인(delegate)이 범위(양식·금액) 안의 결재를 대신합니다.
 * 상태(scheduled·active·expired·revoked)는 저장하지 않고 조회 시각으로 계산합니다.
 */
@Entity
@Table(name = "delegation")
public class Delegation {

    public static final String ALL_FORMS = "*";

    @Id
    private String id;
    @Column(name = "delegator_id")
    private String delegatorId;
    @Column(name = "delegate_id")
    private String delegateId;
    @Column(name = "starts_at")
    private OffsetDateTime startsAt;
    @Column(name = "ends_at")
    private OffsetDateTime endsAt;
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "form_types")
    private List<String> formTypes;
    @Column(name = "max_amount")
    private Long maxAmount;
    private String reason;
    @Column(name = "registered_by")
    private String registeredBy;
    @Column(name = "revoked_at")
    private OffsetDateTime revokedAt;
    @Column(name = "revoked_by")
    private String revokedBy;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    protected Delegation() {}

    Delegation(String id, String delegatorId, String delegateId, OffsetDateTime startsAt, OffsetDateTime endsAt,
               List<String> formTypes, Long maxAmount, String reason, String registeredBy, OffsetDateTime createdAt) {
        this.id = id;
        this.delegatorId = delegatorId;
        this.delegateId = delegateId;
        this.startsAt = startsAt;
        this.endsAt = endsAt;
        this.formTypes = List.copyOf(formTypes);
        this.maxAmount = maxAmount;
        this.reason = reason;
        this.registeredBy = registeredBy;
        this.createdAt = createdAt;
    }

    public String status(OffsetDateTime at) {
        if (revokedAt != null) {
            return "revoked";
        }
        if (at.isBefore(startsAt)) {
            return "scheduled";
        }
        return at.isAfter(endsAt) ? "expired" : "active";
    }

    /**
     * 이 위임으로 at 시각에 그 문서를 대신 결재할 수 없는 이유. 되면 null입니다.
     * 금액 한도는 금액이 있는 양식에만 씁니다.
     */
    public String problemFor(String formId, Long amount, OffsetDateTime at) {
        if (revokedAt != null) {
            return "delegation-revoked";
        }
        if (at.isBefore(startsAt) || at.isAfter(endsAt)) {
            return "delegation-out-of-period";
        }
        if (!formTypes.contains(ALL_FORMS) && !formTypes.contains(formId)) {
            return "delegation-out-of-scope";
        }
        if (maxAmount != null && amount != null && amount > maxAmount) {
            return "delegation-out-of-scope";
        }
        return null;
    }

    void revoke(String by, OffsetDateTime at) {
        this.revokedBy = by;
        this.revokedAt = at;
    }

    public String getId() { return id; }
    public String getDelegatorId() { return delegatorId; }
    public String getDelegateId() { return delegateId; }
    public OffsetDateTime getStartsAt() { return startsAt; }
    public OffsetDateTime getEndsAt() { return endsAt; }
    public List<String> getFormTypes() { return formTypes; }
    public Long getMaxAmount() { return maxAmount; }
    public String getReason() { return reason; }
    public String getRegisteredBy() { return registeredBy; }
    public OffsetDateTime getRevokedAt() { return revokedAt; }
    public String getRevokedBy() { return revokedBy; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
