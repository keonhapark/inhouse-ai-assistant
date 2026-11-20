package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.PostLoad;
import jakarta.persistence.PostPersist;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
import java.io.Serializable;
import java.time.OffsetDateTime;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import org.springframework.data.domain.Persistable;

/** 멱등 키 하나와 처음 응답. 키는 요청한 사람(토큰 주인)마다 따로입니다. */
@Entity
@Table(name = "idempotency_record")
@IdClass(IdempotencyRecord.Key.class)
public class IdempotencyRecord implements Persistable<IdempotencyRecord.Key> {

    public record Key(String ownerId, String idemKey) implements Serializable {
        public Key() {
            this(null, null);
        }
    }

    @Id
    @Column(name = "owner_id")
    private String ownerId;
    @Id
    @Column(name = "idem_key")
    private String idemKey;
    @Column(name = "request_hash")
    private String requestHash;
    private int status;
    @JdbcTypeCode(SqlTypes.JSON)
    private JsonNode response;
    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    /** 새 기록은 merge가 아니라 INSERT로 저장합니다. 같은 키가 동시에 들어오면 기본 키 충돌로 하나만 남습니다. */
    @Transient
    private boolean fresh = true;

    protected IdempotencyRecord() {}

    public IdempotencyRecord(String ownerId, String idemKey, String requestHash, int status, JsonNode response,
                             OffsetDateTime createdAt) {
        this.ownerId = ownerId;
        this.idemKey = idemKey;
        this.requestHash = requestHash;
        this.status = status;
        this.response = response;
        this.createdAt = createdAt;
    }

    @Override
    public Key getId() {
        return new Key(ownerId, idemKey);
    }

    @Override
    public boolean isNew() {
        return fresh;
    }

    @PostLoad
    @PostPersist
    void markStored() {
        fresh = false;
    }

    public String getRequestHash() { return requestHash; }
    public int getStatus() { return status; }
    public JsonNode getResponse() { return response; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
