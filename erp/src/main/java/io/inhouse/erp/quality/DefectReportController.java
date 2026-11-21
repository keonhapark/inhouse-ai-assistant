package io.inhouse.erp.quality;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.common.OperationId;
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
public class DefectReportController {

    private static final String RESOURCE = "defect_report";

    private final DefectReportService reports;
    private final WriteExecutor writes;

    public DefectReportController(DefectReportService reports, WriteExecutor writes) {
        this.reports = reports;
        this.writes = writes;
    }

    @GetMapping("/quality/defect-reports")
    @OperationId("listDefectReports")
    @RequiredScope("quality:read")
    public Items<DefectReportService.View> list(@AuthenticationPrincipal ErpPrincipal p,
                                                @RequestParam(defaultValue = "mine") String box,
                                                @RequestParam(required = false) String status,
                                                @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(reports.list(p.employeeId(), box, status, limit));
    }

    @GetMapping("/quality/defect-reports/{reportId}")
    @OperationId("getDefectReport")
    @RequiredScope("quality:read")
    public DefectReportService.View get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String reportId) {
        return reports.get(p.employeeId(), reportId);
    }

    @PostMapping("/quality/defect-reports")
    @OperationId("createDefectReport")
    @RequiredScope("quality:write")
    public ResponseEntity<Object> create(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        reports.requireFeature();
        Bodies.check(body, Set.of("itemCode", "defectType", "severity", "quantity", "location", "lotNo", "description"),
                Set.of("itemCode", "defectType", "severity", "quantity", "description"));
        String severity = Bodies.text(body, "severity", 16);
        if (!DefectReport.SEVERITIES.contains(severity)) {
            throw ApiException.validation("severity", "minor, major, critical 중 하나");
        }
        int quantity = Bodies.integer(body, "quantity");
        if (quantity < 1 || quantity > 1_000_000) {
            throw ApiException.validation("quantity", "1~1000000");
        }
        DefectReportService.CreateRequest req = new DefectReportService.CreateRequest(
                nonBlank(body, "itemCode", 32), nonBlank(body, "defectType", 50), severity, quantity,
                Bodies.text(body, "location", 100), Bodies.text(body, "lotNo", 50), nonBlank(body, "description", 1000));
        WriteRequest w = WriteRequest.of(p, "createDefectReport", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> reports.create(p, req));
    }

    @PostMapping("/quality/defect-reports/{reportId}/confirm")
    @OperationId("confirmDefectReport")
    @RequiredScope(value = "quality:confirm", humanOnly = true)
    public ResponseEntity<Object> confirm(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String reportId,
                                          @RequestParam(defaultValue = "false") boolean dryRun,
                                          @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                          @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        reports.requireFeature();
        Bodies.check(body, Set.of("version"), Set.of("version"));
        int version = Bodies.integer(body, "version");
        WriteRequest w = WriteRequest.of(p, "confirmDefectReport", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> reports.confirm(p, reportId, version));
    }

    static String nonBlank(JsonNode body, String field, int maxLength) {
        String v = Bodies.text(body, field, maxLength);
        if (v == null || v.isBlank()) {
            throw ApiException.validation(field, "1~" + maxLength + "자");
        }
        return v;
    }
}
