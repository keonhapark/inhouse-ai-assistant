package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.inhouse.erp.audit.AuditService;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import jakarta.persistence.OptimisticLockException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;
import java.util.function.Supplier;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 모든 erp 쓰기의 공통 처리(계약 erp.yaml 머리말).
 * <ul>
 *   <li>dryRun: 같은 명령을 트랜잭션 안에서 돌리고 되돌립니다. 그래서 검사 규칙이 실행과 같고 상태는 바뀌지 않습니다.</li>
 *   <li>실행: Idempotency-Key가 필요합니다. 같은 사람·같은 키면 24시간 동안 처음 응답을 그대로 돌려주고,
 *       본문이 다르면 422입니다. 명령, 행동 기록, 감사 이벤트, 멱등 기록을 한 트랜잭션에 씁니다.</li>
 *   <li>거절·충돌은 업무 트랜잭션이 되돌려지므로 감사 이벤트(erp.denied)만 따로 남깁니다. 이보다 앞에서 난 거절
 *       (scope, 본문 검사, Idempotency-Key 없음)은 {@link io.inhouse.erp.audit.DeniedRequestAuditor}가 남깁니다.</li>
 * </ul>
 */
@Service
public class WriteExecutor {

    static final Duration KEY_TTL = Duration.ofHours(24);

    private final TransactionTemplate tx;
    private final ActionRepository actions;
    private final IdempotencyRecordRepository idempotency;
    private final AuditService audit;
    private final ObjectMapper mapper;
    private final Clock clock;

    public WriteExecutor(PlatformTransactionManager txm, ActionRepository actions,
                         IdempotencyRecordRepository idempotency, AuditService audit, ObjectMapper mapper,
                         Clock clock) {
        this.tx = new TransactionTemplate(txm);
        this.actions = actions;
        this.idempotency = idempotency;
        this.audit = audit;
        this.mapper = mapper;
        this.clock = clock;
    }

    public ResponseEntity<Object> run(WriteRequest req, Supplier<WriteOutcome> command) {
        return req.dryRun() ? preview(req, command) : execute(req, command);
    }

    private ResponseEntity<Object> preview(WriteRequest req, Supplier<WriteOutcome> command) {
        ObjectNode body = inTx(() -> tx.execute(status -> {
            status.setRollbackOnly();
            WriteOutcome out = command.get();
            actions.flush();
            ObjectNode preview = mapper.createObjectNode();
            preview.put("dryRun", true);
            preview.put("operation", req.operation());
            preview.put("summary", out.summary());
            ArrayNode changes = preview.putArray("changes");
            out.changes().forEach(c -> changes.add(mapper.valueToTree("create".equals(c.op()) ? c.withoutId() : c)));
            preview.put("undoable", out.undoable());
            preview.putArray("warnings");
            return preview;
        }));
        return ResponseEntity.ok(body);
    }

    private ResponseEntity<Object> execute(WriteRequest req, Supplier<WriteOutcome> command) {
        String key = req.idempotencyKey();
        if (key == null || key.length() < 8 || key.length() > 128) {
            throw new ApiException(400, "idempotency-key-required", "Idempotency-Key(8~128자)가 필요합니다");
        }
        ErpPrincipal p = req.principal();
        IdempotencyRecord.Key recordKey = new IdempotencyRecord.Key(p.employeeId(), key);
        String hash = requestHash(req);
        try {
            Optional<ResponseEntity<Object>> replay = replay(recordKey, hash);
            if (replay.isPresent()) {
                return replay.get();
            }
            JsonNode body = inTx(() -> tx.execute(status -> {
                IdempotencyRecord claim = claim(recordKey, hash);
                WriteOutcome out = command.get();
                actions.flush();
                return record(req, out, claim);
            }));
            return ResponseEntity.status(201).body(body);
        } catch (AlreadyClaimed e) {
            // 같은 키의 다른 요청이 먼저 커밋했습니다. 그 응답(또는 본문이 다르면 422)을 돌려줍니다.
            try {
                return replay(recordKey, hash).orElseThrow();
            } catch (ApiException denied) {
                auditDenied(req, denied);
                throw denied;
            }
        } catch (ApiException e) {
            auditDenied(req, e);
            throw e;
        }
    }

    /**
     * 멱등 키를 먼저 차지합니다. 기록 행을 업무보다 먼저 INSERT하므로 같은 키의 요청은 기본 키에서 줄을 서고,
     * 먼저 온 요청이 커밋하면 뒤 요청은 충돌로 끝나 그 응답을 돌려받습니다. 먼저 온 요청이 실패해 되돌려지면
     * 뒤 요청이 이어서 실행합니다. 보관 기간이 지난 같은 키는 지우고 새로 씁니다.
     */
    private IdempotencyRecord claim(IdempotencyRecord.Key recordKey, String hash) {
        OffsetDateTime now = OffsetDateTime.now(clock);
        idempotency.deleteExpired(recordKey.ownerId(), recordKey.idemKey(), now.minus(KEY_TTL));
        IdempotencyRecord claim = IdempotencyRecord.claim(recordKey, hash, now, mapper.createObjectNode());
        try {
            idempotency.saveAndFlush(claim);
        } catch (DataIntegrityViolationException e) {
            throw new AlreadyClaimed();
        }
        return claim;
    }

    private JsonNode record(WriteRequest req, WriteOutcome out, IdempotencyRecord claim) {
        ErpPrincipal p = req.principal();
        OffsetDateTime now = OffsetDateTime.now(clock);
        Action action = new Action(Ids.next("act"), req.operation(), p.employeeId(), p.viaDelegationToken(),
                p.agentId(), p.conversationId(), req.resourceType(), out.resourceId(), out.undoable(), now);
        actions.save(action);
        if (req.undoOf() != null) {
            actions.findById(req.undoOf()).orElseThrow().markUndone(action.getId());
        }
        audit.record(p, req.undoOf() != null ? "erp.undo" : "erp.write", req.operation(), "ok",
                new AuditService.Extra(out.onBehalfOf(), out.delegationId(), action.getId(), req.undoOf()),
                null, null);
        ObjectNode body = mapper.createObjectNode();
        body.put("actionId", action.getId());
        body.put("operation", req.operation());
        body.put("summary", out.summary());
        body.set("changes", mapper.valueToTree(out.changes()));
        body.put("undoable", out.undoable());
        body.set("resource", mapper.valueToTree(out.resource()));
        body.put("undoOf", req.undoOf());
        claim.complete(201, body);
        actions.flush();
        return body;
    }

    private void auditDenied(WriteRequest req, ApiException e) {
        e.markAudited();
        audit.recordSeparately(req.principal(), "erp.denied", req.operation(),
                e.status() == 409 ? "conflict" : "denied", new AuditService.Extra(null, null, null, req.undoOf()),
                e.code(), e.detail());
    }

    private Optional<ResponseEntity<Object>> replay(IdempotencyRecord.Key recordKey, String hash) {
        return idempotency.findById(recordKey)
                .filter(r -> !expired(r))
                .map(r -> {
                    if (!r.getRequestHash().equals(hash)) {
                        throw new ApiException(422, "idempotency-key-reused",
                                "같은 Idempotency-Key로 다른 요청을 보냈습니다");
                    }
                    return ResponseEntity.status(r.getStatus()).body(r.getResponse());
                });
    }

    private boolean expired(IdempotencyRecord r) {
        return !r.getCreatedAt().isAfter(OffsetDateTime.now(clock).minus(KEY_TTL));
    }

    /** 같은 키를 다른 요청이 먼저 차지했을 때 업무를 되돌리고 그 응답을 돌려주기 위한 신호입니다. */
    private static final class AlreadyClaimed extends RuntimeException {
        AlreadyClaimed() {
            super(null, null, false, false);
        }
    }

    /** 낙관적 락 충돌(같은 문서를 동시에 결재 등)은 409 version-conflict, 그 밖의 제약 위반은 409 invalid-state입니다. */
    private <T> T inTx(Supplier<T> body) {
        try {
            return body.get();
        } catch (ObjectOptimisticLockingFailureException | OptimisticLockException e) {
            throw new ApiException(409, "version-conflict", "그사이 다른 요청이 같은 리소스를 바꿨습니다");
        } catch (DataIntegrityViolationException e) {
            // 업무 테이블의 제약 위반. 각 명령이 먼저 검사하지만, 동시 요청이 검사를 함께 지나면 여기로 옵니다.
            throw new ApiException(409, "invalid-state", "같은 상태를 바꾸는 요청이 겹쳤습니다");
        }
    }

    String requestHash(WriteRequest req) {
        ObjectNode n = mapper.createObjectNode();
        n.put("op", req.operation());
        n.put("path", req.path());
        n.set("body", req.body());
        try {
            byte[] raw = mapper.writeValueAsBytes(canonical(n));
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));
        } catch (NoSuchAlgorithmException | com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    /** 객체 키를 정렬한 사본. 키 순서만 다른 같은 본문은 같은 해시가 됩니다. */
    private JsonNode canonical(JsonNode n) {
        if (n.isObject()) {
            Map<String, JsonNode> sorted = new TreeMap<>();
            for (Map.Entry<String, JsonNode> e : n.properties()) {
                sorted.put(e.getKey(), canonical(e.getValue()));
            }
            ObjectNode out = mapper.createObjectNode();
            sorted.forEach(out::set);
            return out;
        }
        if (n.isArray()) {
            ArrayNode out = mapper.createArrayNode();
            n.forEach(x -> out.add(canonical(x)));
            return out;
        }
        return n;
    }

    /** 보관 기간(24시간)이 지난 멱등 기록을 지웁니다. */
    @Scheduled(fixedDelayString = "PT1H", initialDelayString = "PT1M")
    public void purgeExpiredKeys() {
        tx.executeWithoutResult(s -> idempotency.deleteOlderThan(OffsetDateTime.now(clock).minus(KEY_TTL)));
    }
}
