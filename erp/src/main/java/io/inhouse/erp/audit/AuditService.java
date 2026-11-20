package io.inhouse.erp.audit;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.Ids;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * erp 감사 이벤트를 DB에 저장합니다. {@code erp.audit-log}(ERP_AUDIT_LOG)가 있으면 커밋 뒤 JSON Lines로도 씁니다.
 */
@Service
public class AuditService {

    private static final Logger log = LoggerFactory.getLogger(AuditService.class);

    /** 감사 이벤트에 붙일 대결 정보(결재 대결이면 원 결재자와 위임 ID). */
    public record Extra(String onBehalfOf, String delegationId, String actionId, String undoOf) {
        public static final Extra NONE = new Extra(null, null, null, null);
    }

    private final AuditEventRepository repo;
    private final ObjectMapper mapper;
    private final Clock clock;
    private final Path logFile;

    public AuditService(AuditEventRepository repo, ObjectMapper mapper, Clock clock,
                        @Value("${erp.audit-log:}") String logFile) {
        this.repo = repo;
        this.mapper = mapper;
        this.clock = clock;
        this.logFile = logFile == null || logFile.isBlank() ? null : Path.of(logFile);
    }

    /** 지금 트랜잭션에 함께 저장합니다. 트랜잭션이 되돌려지면 이벤트도 남지 않습니다. */
    @Transactional(propagation = Propagation.MANDATORY)
    public AuditEvent record(ErpPrincipal p, String kind, String operation, String result, Extra extra,
                             String problemCode, String detail) {
        AuditEvent e = new AuditEvent(Ids.next("evt"), OffsetDateTime.now(clock), "erp", kind,
                new AuditEvent.Actor(p.employeeId(), p.viaDelegationToken(), p.delegationTokenId(),
                        p.agentId()),
                extra.onBehalfOf(), extra.delegationId(), p.conversationId(), extra.actionId(), extra.undoOf(),
                operation, result, problemCode == null ? null : "urn:problem:" + problemCode, detail);
        JsonNode json = mapper.valueToTree(e);
        repo.save(new AuditEventEntity(e, json));
        appendAfterCommit(json);
        return e;
    }

    /** 거절·충돌처럼 업무 트랜잭션이 되돌려지는 경우에 따로 저장합니다. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordSeparately(ErpPrincipal p, String kind, String operation, String result, Extra extra,
                                 String problemCode, String detail) {
        record(p, kind, operation, result, extra, problemCode, detail);
    }

    @Transactional(readOnly = true)
    public List<JsonNode> list(String actorId, String actionId, OffsetDateTime since, int limit) {
        List<JsonNode> out = new ArrayList<>();
        repo.latest(actorId, actionId, since, Limit.of(Math.max(1, Math.min(limit, 500))))
                .forEach(a -> out.add(a.getEvent()));
        Collections.reverse(out);
        return out;
    }

    private void appendAfterCommit(JsonNode json) {
        if (logFile == null || !TransactionSynchronizationManager.isSynchronizationActive()) {
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                try {
                    Files.writeString(logFile, mapper.writeValueAsString(json) + "\n", StandardCharsets.UTF_8,
                            StandardOpenOption.CREATE, StandardOpenOption.APPEND);
                } catch (IOException ex) {
                    log.error("감사 JSON Lines를 쓰지 못했습니다: {}", logFile, ex);
                }
            }
        });
    }
}
