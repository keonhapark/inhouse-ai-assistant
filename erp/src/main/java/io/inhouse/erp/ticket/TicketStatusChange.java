package io.inhouse.erp.ticket;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

/** 상태 변경 한 번. 되돌리기는 티켓 version이 versionAfter 그대로일 때만 fromStatus로 돌립니다. */
@Entity
@Table(name = "ticket_status_change")
public class TicketStatusChange {

    @Id
    private String id;
    @Column(name = "ticket_id")
    private String ticketId;
    @Column(name = "from_status")
    private String fromStatus;
    @Column(name = "to_status")
    private String toStatus;
    @Column(name = "version_after")
    private int versionAfter;
    @Column(name = "changed_by")
    private String changedBy;
    @Column(name = "changed_at")
    private OffsetDateTime changedAt;

    protected TicketStatusChange() {}

    TicketStatusChange(String id, String ticketId, String fromStatus, String toStatus, int versionAfter,
                       String changedBy, OffsetDateTime changedAt) {
        this.id = id;
        this.ticketId = ticketId;
        this.fromStatus = fromStatus;
        this.toStatus = toStatus;
        this.versionAfter = versionAfter;
        this.changedBy = changedBy;
        this.changedAt = changedAt;
    }

    public String getId() { return id; }
    public String getTicketId() { return ticketId; }
    public String getFromStatus() { return fromStatus; }
    public String getToStatus() { return toStatus; }
    public int getVersionAfter() { return versionAfter; }
}
