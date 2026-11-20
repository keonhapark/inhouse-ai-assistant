package io.inhouse.erp.delegation;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.approval.ApprovalDocumentRepository;
import io.inhouse.erp.approval.ApprovalViews;
import io.inhouse.erp.approval.ApprovalViews.DocumentView;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.delegation.DelegationService.DelegationView;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.write.WriteExecutor;
import io.inhouse.erp.write.WriteRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DelegationController {

    private static final String RESOURCE = "delegation";

    private final DelegationService delegations;
    private final ApprovalDocumentRepository docs;
    private final WriteExecutor writes;

    public DelegationController(DelegationService delegations, ApprovalDocumentRepository docs, WriteExecutor writes) {
        this.delegations = delegations;
        this.docs = docs;
        this.writes = writes;
    }

    @GetMapping("/delegations")
    @RequiredScope("delegation:read")
    public Items<DelegationView> list(@AuthenticationPrincipal ErpPrincipal p, @RequestParam String role,
                                      @RequestParam(required = false) String activeAt) {
        return new Items<>(delegations.list(p.employeeId(), role, activeAt == null ? null : time("activeAt", activeAt)));
    }

    @GetMapping("/delegations/{delegationId}")
    @RequiredScope("delegation:read")
    public DelegationView get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String delegationId) {
        return delegations.view(delegations.visible(p.employeeId(), delegationId));
    }

    /** 이 위임으로 대리인이 결재한 문서(후열 확인용). */
    @GetMapping("/delegations/{delegationId}/acted-documents")
    @RequiredScope("delegation:read")
    @Transactional(readOnly = true)
    public Items<DocumentView> acted(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String delegationId) {
        delegations.visible(p.employeeId(), delegationId);
        return new Items<>(docs.findActedUnderDelegation(delegationId).stream().map(ApprovalViews::of).toList());
    }

    @PostMapping("/delegations")
    @RequiredScope("delegation:write")
    public ResponseEntity<Object> create(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        DelegationService.CreateRequest req = parse(body);
        WriteRequest w = WriteRequest.of(p, "createDelegation", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> delegations.create(p, req));
    }

    @PostMapping("/delegations/{delegationId}/revoke")
    @RequiredScope("delegation:write")
    public ResponseEntity<Object> revoke(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String delegationId,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        WriteRequest w = WriteRequest.of(p, "revokeDelegation", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> delegations.revoke(p, delegationId));
    }

    /** 계약 DelegationCreate: 필수 필드, 모르는 필드 금지, 시각은 오프셋이 있는 RFC 3339. */
    private static DelegationService.CreateRequest parse(JsonNode body) {
        Bodies.check(body, Set.of("delegatorId", "delegateId", "startsAt", "endsAt", "scope", "reason"),
                Set.of("delegateId", "startsAt", "endsAt", "scope", "reason"));
        JsonNode scope = body.get("scope");
        Bodies.check(scope, Set.of("formTypes", "maxAmount"), Set.of("formTypes"));
        JsonNode types = scope.get("formTypes");
        if (!types.isArray() || types.isEmpty()) {
            throw ApiException.validation("scope.formTypes", "non-empty array required");
        }
        List<String> formTypes = new ArrayList<>();
        types.forEach(t -> {
            if (!t.isTextual()) {
                throw ApiException.validation("scope.formTypes", "string items required");
            }
            formTypes.add(t.asText());
        });
        Long maxAmount = null;
        JsonNode max = scope.get("maxAmount");
        if (max != null && !max.isNull()) {
            if (!max.isIntegralNumber() || max.asLong() < 0) {
                throw ApiException.validation("scope.maxAmount", "integer >= 0 required");
            }
            maxAmount = max.asLong();
        }
        return new DelegationService.CreateRequest(Bodies.text(body, "delegatorId", 32),
                Bodies.text(body, "delegateId", 32), time("startsAt", Bodies.text(body, "startsAt", 64)),
                time("endsAt", Bodies.text(body, "endsAt", 64)), formTypes, maxAmount,
                Bodies.text(body, "reason", 200));
    }

    private static OffsetDateTime time(String field, String value) {
        try {
            return OffsetDateTime.parse(value);
        } catch (DateTimeParseException e) {
            throw ApiException.validation(field, "RFC 3339(오프셋 포함)");
        }
    }
}
