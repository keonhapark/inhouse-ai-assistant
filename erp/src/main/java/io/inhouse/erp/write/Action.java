package io.inhouse.erp.write;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.OffsetDateTime;

/** 실행된 쓰기 하나. 되돌리기와 감사의 기준입니다. */
@Entity
@Table(name = "action")
public class Action {

    @Id
    private String id;
    private String operation;
    @Column(name = "actor_id")
    private String actorId;
    @Column(name = "via_delegation_token")
    private boolean viaDelegationToken;
    @Column(name = "agent_id")
    private String agentId;
    @Column(name = "conversation_id")
    private String conversationId;
    @Column(name = "resource_type")
    private String resourceType;
    @Column(name = "resource_id")
    private String resourceId;
    private String status;
    private boolean undoable;
    @Column(name = "undo_action_id")
    private String undoActionId;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    protected Action() {}

    public Action(String id, String operation, String actorId, boolean viaDelegationToken, String agentId,
                  String conversationId, String resourceType, String resourceId, boolean undoable,
                  OffsetDateTime createdAt) {
        this.id = id;
        this.operation = operation;
        this.actorId = actorId;
        this.viaDelegationToken = viaDelegationToken;
        this.agentId = agentId;
        this.conversationId = conversationId;
        this.resourceType = resourceType;
        this.resourceId = resourceId;
        this.status = "done";
        this.undoable = undoable;
        this.createdAt = createdAt;
    }

    public void markUndone(String undoActionId) {
        this.status = "undone";
        this.undoActionId = undoActionId;
    }

    public boolean isUndone() { return "undone".equals(status); }

    public String getId() { return id; }
    public String getOperation() { return operation; }
    public String getActorId() { return actorId; }
    public boolean isViaDelegationToken() { return viaDelegationToken; }
    public String getAgentId() { return agentId; }
    public String getConversationId() { return conversationId; }
    public String getResourceType() { return resourceType; }
    public String getResourceId() { return resourceId; }
    public String getStatus() { return status; }
    public boolean isUndoable() { return undoable; }
    public String getUndoActionId() { return undoActionId; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
