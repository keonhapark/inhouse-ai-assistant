package io.inhouse.erp.sales;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Set;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** 견적. 품목 줄(lines)은 만들 때의 단가·금액을 그대로 담아 둡니다(품목 단가가 바뀌어도 견적은 그대로). */
@Entity
@Table(name = "quote")
public class Quote {

    public static final Set<String> STATUSES = Set.of("draft", "issued", "cancelled");

    @Id
    private String id;
    @Column(name = "created_by")
    private String createdBy;
    @Column(name = "customer_id")
    private String customerId;
    @Column(name = "customer_name")
    private String customerName;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode lines;
    @Column(name = "total_amount")
    private long totalAmount;
    @Column(name = "valid_until")
    private LocalDate validUntil;
    private String note;
    private String status;
    private int version;
    @Column(name = "issued_by")
    private String issuedBy;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;
    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    protected Quote() {}

    Quote(String id, String createdBy, String customerId, String customerName, JsonNode lines, long totalAmount,
          LocalDate validUntil, String note, OffsetDateTime createdAt) {
        this.id = id;
        this.createdBy = createdBy;
        this.customerId = customerId;
        this.customerName = customerName;
        this.lines = lines;
        this.totalAmount = totalAmount;
        this.validUntil = validUntil;
        this.note = note;
        this.status = "draft";
        this.createdAt = createdAt;
        this.updatedAt = createdAt;
    }

    void changeStatus(String status, String by, OffsetDateTime at) {
        this.status = status;
        if ("issued".equals(status)) {
            this.issuedBy = by;
        }
        this.version++;
        this.updatedAt = at;
    }

    public String getId() { return id; }
    public String getCreatedBy() { return createdBy; }
    public String getCustomerId() { return customerId; }
    public String getCustomerName() { return customerName; }
    public JsonNode getLines() { return lines; }
    public long getTotalAmount() { return totalAmount; }
    public LocalDate getValidUntil() { return validUntil; }
    public String getNote() { return note; }
    public String getStatus() { return status; }
    public int getVersion() { return version; }
    public String getIssuedBy() { return issuedBy; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
}
