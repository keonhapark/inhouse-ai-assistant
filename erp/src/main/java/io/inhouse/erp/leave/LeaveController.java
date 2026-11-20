package io.inhouse.erp.leave;

import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.OrgService;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class LeaveController {

    private final LeaveService leave;
    private final OrgService org;

    public LeaveController(LeaveService leave, OrgService org) {
        this.leave = leave;
        this.org = org;
    }

    /** 본인 잔여. 다른 사람 것은 인사 담당(팩 erp_roles.hr)만 봅니다. */
    @GetMapping("/leave/balance")
    @OperationId("getLeaveBalance")
    @RequiredScope("leave:read")
    public LeaveService.BalanceView balance(@AuthenticationPrincipal ErpPrincipal p,
                                            @RequestParam(required = false) String employeeId) {
        String target = employeeId == null || employeeId.isBlank() ? p.employeeId() : employeeId;
        if (!target.equals(p.employeeId()) && !org.isHr(p.employeeId())) {
            throw ApiException.forbidden("본인 잔여만 봅니다");
        }
        org.employee(target);
        return leave.view(target);
    }
}
