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
        if (!org.isAuditor(p.employeeId())) {
            throw ApiException.forbidden("감사 기록은 감사 조회 역할이 있어야 볼 수 있습니다.");
        }
        return new Items<>(audit.list(actorId, actionId, since, limit));
    }
}
