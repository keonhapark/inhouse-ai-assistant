package io.inhouse.erp.audit;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "audit_event")
public class AuditEventEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long seq;
    @Column(name = "event_id")
    private String eventId;
    @Column(name = "occurred_at")
    private OffsetDateTime occurredAt;
    @Column(name = "actor_id")
    private String actorId;
    @Column(name = "action_id")
    private String actionId;
    private String kind;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode event;

    protected AuditEventEntity() {}

    public AuditEventEntity(AuditEvent e, JsonNode json) {
        this.eventId = e.eventId();
        this.occurredAt = e.occurredAt();
        this.actorId = e.actor().employeeId();
        this.actionId = e.actionId();
        this.kind = e.kind();
        this.event = json;
    }

    public JsonNode getEvent() { return event; }
}
