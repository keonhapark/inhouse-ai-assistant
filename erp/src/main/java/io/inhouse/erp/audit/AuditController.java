package io.inhouse.erp.audit;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.org.OrgViews.Items;
import java.time.OffsetDateTime;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuditController {

    static final String AUDITOR_ROLE = "auditor";

    private final AuditService audit;
    private final OrgService org;

    public AuditController(AuditService audit, OrgService org) {
        this.audit = audit;
        this.org = org;
    }

    @GetMapping("/audit-events")
    @OperationId("listAuditEvents")
    @RequiredScope(value = "audit:read", humanOnly = true)
    public Items<JsonNode> list(@AuthenticationPrincipal ErpPrincipal p,
                                @RequestParam(required = false) String actorId,
                                @RequestParam(required = false) String actionId,
                                @RequestParam(required = false)
                                @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime since,
                                @RequestParam(defaultValue = "100") int limit) {
        if (!org.hasRole(p.employeeId(), AUDITOR_ROLE)) {
            throw ApiException.forbidden("감사 조회 역할만 봅니다");
        }
        return new Items<>(audit.list(actorId, actionId, since, limit));
    }
}
