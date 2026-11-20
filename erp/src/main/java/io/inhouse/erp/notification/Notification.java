package io.inhouse.erp.notification;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

@Entity
@Table(name = "notification")
public class Notification {

    @Id
    private String id;
    @Column(name = "recipient_id")
    private String recipientId;
    private String kind;
    private String message;
    @Column(name = "document_id")
    private String documentId;
    @Column(name = "delegation_id")
    private String delegationId;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;
    private boolean read;

    protected Notification() {}

    Notification(String id, String recipientId, String kind, String message, String documentId,
                 String delegationId, OffsetDateTime createdAt) {
        this.id = id;
        this.recipientId = recipientId;
        this.kind = kind;
        this.message = message;
        this.documentId = documentId;
        this.delegationId = delegationId;
        this.createdAt = createdAt;
    }

    public String getId() { return id; }
    public String getKind() { return kind; }
    public String getMessage() { return message; }
    public String getDocumentId() { return documentId; }
    public String getDelegationId() { return delegationId; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public boolean isRead() { return read; }
}
