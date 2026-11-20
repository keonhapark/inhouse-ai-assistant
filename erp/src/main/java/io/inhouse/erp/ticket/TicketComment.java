package io.inhouse.erp.ticket;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

@Entity
@Table(name = "ticket_comment")
public class TicketComment {

    @Id
    private String id;
    @Column(name = "ticket_id")
    private String ticketId;
    @Column(name = "author_id")
    private String authorId;
    private String body;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    protected TicketComment() {}

    TicketComment(String id, String ticketId, String authorId, String body, OffsetDateTime createdAt) {
        this.id = id;
        this.ticketId = ticketId;
        this.authorId = authorId;
        this.body = body;
        this.createdAt = createdAt;
    }

    public String getId() { return id; }
    public String getTicketId() { return ticketId; }
    public String getAuthorId() { return authorId; }
    public String getBody() { return body; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
