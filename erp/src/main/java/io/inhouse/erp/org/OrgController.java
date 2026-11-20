package io.inhouse.erp.org;

import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.org.OrgViews.AccessTags;
import io.inhouse.erp.org.OrgViews.EmployeeFull;
import io.inhouse.erp.org.OrgViews.EmployeeSummary;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.org.OrgViews.UnitView;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrgController {

    private final OrgService org;

    public OrgController(OrgService org) {
        this.org = org;
    }

    @GetMapping("/me")
    @RequiredScope("profile:read")
    public EmployeeFull me(@AuthenticationPrincipal ErpPrincipal p) {
        return org.full(org.employee(p.employeeId()));
    }

    @GetMapping("/me/access-tags")
    @RequiredScope("profile:read")
    public AccessTags myAccessTags(@AuthenticationPrincipal ErpPrincipal p) {
        return new AccessTags(p.employeeId(), org.accessTags(p.employeeId()));
    }

    @GetMapping("/org/units")
    @RequiredScope("org:read")
    public Items<UnitView> units() {
        return new Items<>(org.units());
    }

    @GetMapping("/employees")
    @RequiredScope("org:read")
    public Items<EmployeeSummary> search(@RequestParam(required = false) String q,
                                         @RequestParam(required = false) String unitId,
                                         @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(org.search(q, unitId, limit));
    }

    @GetMapping("/employees/{employeeId}")
    @RequiredScope("org:read")
    public Object employee(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String employeeId) {
        return org.view(p.employeeId(), employeeId);
    }
}
