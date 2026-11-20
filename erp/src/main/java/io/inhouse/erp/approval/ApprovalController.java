package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.approval.ApprovalViews.DocumentView;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.auth.ScopeGuard;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.write.WriteExecutor;
import io.inhouse.erp.write.WriteRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ApprovalController {

    private static final String RESOURCE = "approval_document";

    private final ApprovalService approvals;
    private final WriteExecutor writes;
    private final ScopeGuard scopes;

    public ApprovalController(ApprovalService approvals, WriteExecutor writes, ScopeGuard scopes) {
        this.approvals = approvals;
        this.writes = writes;
        this.scopes = scopes;
    }

    @GetMapping("/approval-documents")
    @RequiredScope("approval:read")
    public Items<DocumentView> list(@AuthenticationPrincipal ErpPrincipal p, @RequestParam String box,
                                    @RequestParam(required = false) String status,
                                    @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(approvals.list(p.employeeId(), box, status, limit));
    }

    @GetMapping("/approval-documents/{documentId}")
    @RequiredScope("approval:read")
    public DocumentView get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String documentId) {
        return ApprovalViews.of(approvals.visible(p.employeeId(), documentId));
    }

    /** 상신. 위임 토큰은 approval:request나 approval:request:&lt;formId&gt;가 있어야 합니다. */
    @PostMapping("/approval-documents")
    @RequiredScope(value = "approval:request", perForm = true)
    public ResponseEntity<Object> create(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Bodies.check(body, Set.of("formId", "title", "fields"), Set.of("formId", "fields"));
        String formId = Bodies.text(body, "formId", 64);
        scopes.requireForForm(p, "approval:request", formId);
        String title = Bodies.text(body, "title", 100);
        WriteRequest req = WriteRequest.of(p, "createApprovalDocument", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(req, () -> approvals.create(p, formId, title, body.get("fields")));
    }

    @PostMapping("/approval-documents/{documentId}/approve")
    @RequiredScope(value = "approval:decide", humanOnly = true)
    public ResponseEntity<Object> approve(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String documentId,
                                          @RequestParam(defaultValue = "false") boolean dryRun,
                                          @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                          @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        return decide(p, documentId, dryRun, key, body, http, true);
    }

    @PostMapping("/approval-documents/{documentId}/reject")
    @RequiredScope(value = "approval:decide", humanOnly = true)
    public ResponseEntity<Object> reject(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String documentId,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        return decide(p, documentId, dryRun, key, body, http, false);
    }

    private ResponseEntity<Object> decide(ErpPrincipal p, String documentId, boolean dryRun, String key,
                                          JsonNode body, HttpServletRequest http, boolean approve) {
        Bodies.check(body, Set.of("version", "comment"), Set.of("version"));
        int version = Bodies.integer(body, "version");
        String comment = Bodies.text(body, "comment", 200);
        String op = approve ? "approveApprovalDocument" : "rejectApprovalDocument";
        WriteRequest req = WriteRequest.of(p, op, RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(req, () -> approvals.decide(p, documentId, version, comment, approve));
    }

    @PostMapping("/approval-documents/{documentId}/withdraw")
    @RequiredScope("approval:withdraw")
    public ResponseEntity<Object> withdraw(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String documentId,
                                           @RequestParam(defaultValue = "false") boolean dryRun,
                                           @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                           @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        if (body != null && !body.isNull()) {
            Bodies.check(body, Set.of("reason"), Set.of());
            Bodies.text(body, "reason", 200);
        }
        WriteRequest req = WriteRequest.of(p, "withdrawApprovalDocument", RESOURCE, http.getRequestURI(), body,
                dryRun, key);
        return writes.run(req, () -> approvals.withdraw(p, documentId));
    }
}
