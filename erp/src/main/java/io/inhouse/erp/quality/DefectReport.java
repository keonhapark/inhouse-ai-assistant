package io.inhouse.erp.quality;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import java.util.Set;

/** 불량 보고서. version은 상태가 바뀔 때마다 1씩 오릅니다. */
@Entity
@Table(name = "defect_report")
public class DefectReport {

    public static final Set<String> SEVERITIES = Set.of("minor", "major", "critical");
    public static final Set<String> STATUSES = Set.of("draft", "confirmed", "cancelled");

    @Id
    private String id;
    @Column(name = "created_by")
    private String createdBy;
    @Column(name = "item_code")
    private String itemCode;
    @Column(name = "item_name")
    private String itemName;
    @Column(name = "defect_type")
    private String defectType;
    private String severity;
    private int quantity;
    private String location;
    @Column(name = "lot_no")
    private String lotNo;
    private String description;
    private String status;
    private int version;
    @Column(name = "confirmed_by")
    private String confirmedBy;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;
    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    protected DefectReport() {}

    DefectReport(String id, String createdBy, String itemCode, String itemName, String defectType, String severity,
                 int quantity, String location, String lotNo, String description, String status, String confirmedBy,
                 OffsetDateTime createdAt) {
        this.id = id;
        this.createdBy = createdBy;
        this.itemCode = itemCode;
        this.itemName = itemName;
        this.defectType = defectType;
        this.severity = severity;
        this.quantity = quantity;
        this.location = location;
        this.lotNo = lotNo;
        this.description = description;
        this.status = status;
        this.confirmedBy = confirmedBy;
        this.createdAt = createdAt;
        this.updatedAt = createdAt;
    }

    void changeStatus(String status, String by, OffsetDateTime at) {
        this.status = status;
        if ("confirmed".equals(status)) {
            this.confirmedBy = by;
        }
        this.version++;
        this.updatedAt = at;
    }

    public String getId() { return id; }
    public String getCreatedBy() { return createdBy; }
    public String getItemCode() { return itemCode; }
    public String getItemName() { return itemName; }
    public String getDefectType() { return defectType; }
    public String getSeverity() { return severity; }
    public int getQuantity() { return quantity; }
    public String getLocation() { return location; }
    public String getLotNo() { return lotNo; }
    public String getDescription() { return description; }
    public String getStatus() { return status; }
    public int getVersion() { return version; }
    public String getConfirmedBy() { return confirmedBy; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
}
