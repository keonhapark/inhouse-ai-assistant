package io.inhouse.erp.ticket;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.Set;
import org.hibernate.annotations.Formula;

/** IT 티켓. version은 상태가 바뀔 때마다 1씩 오릅니다(댓글은 올리지 않음). */
@Entity
@Table(name = "ticket")
public class Ticket {

    public static final Set<String> CATEGORIES = Set.of("incident", "access_request", "other");
    public static final Set<String> PRIORITIES = Set.of("low", "normal", "high");
    public static final Set<String> STATUSES = Set.of("open", "in_progress", "resolved", "closed", "cancelled");
    /** 바꿀 수 있는 상태(계약 changeTicketStatus). closed·cancelled에서는 바꿀 수 없습니다. */
    static final Map<String, Set<String>> TRANSITIONS = Map.of(
            "open", Set.of("in_progress", "resolved"),
            "in_progress", Set.of("open", "resolved"),
            "resolved", Set.of("in_progress", "closed"));

    @Id
    private String id;
    @Column(name = "requester_id")
    private String requesterId;
    private String category;
    private String priority;
    private String title;
    private String description;
    private String status;
    private int version;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;
    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;
    @Formula("(select count(*) from ticket_comment c where c.ticket_id = id)")
    private int commentCount;

    protected Ticket() {}

    Ticket(String id, String requesterId, String category, String priority, String title, String description,
           String status, OffsetDateTime createdAt) {
        this.id = id;
        this.requesterId = requesterId;
        this.category = category;
        this.priority = priority;
        this.title = title;
        this.description = description;
        this.status = status;
        this.createdAt = createdAt;
        this.updatedAt = createdAt;
    }

    void changeStatus(String status, OffsetDateTime at) {
        this.status = status;
        this.version++;
        this.updatedAt = at;
    }

    void touch(OffsetDateTime at) {
        if (at.isAfter(updatedAt)) {
            this.updatedAt = at;
        }
    }

    boolean isFinished() {
        return "closed".equals(status) || "cancelled".equals(status);
    }

    public String getId() { return id; }
    public String getRequesterId() { return requesterId; }
    public String getCategory() { return category; }
    public String getPriority() { return priority; }
    public String getTitle() { return title; }
    public String getDescription() { return description; }
    public String getStatus() { return status; }
    public int getVersion() { return version; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
    public int getCommentCount() { return commentCount; }
}
