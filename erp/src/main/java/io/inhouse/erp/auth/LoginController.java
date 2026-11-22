package io.inhouse.erp.auth;

import io.inhouse.erp.audit.AuditService;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.EmployeeRepository;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.org.OrgViews.EmployeeFull;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class LoginController {

    public record LoginRequest(String employeeNo, String password) {}

    public record LoginResponse(String accessToken, String tokenType, long expiresIn, EmployeeFull employee) {}

    private final EmployeeRepository employees;
    private final OrgService org;
    private final TokenService tokens;
    private final AuditService audit;
    private final byte[] password;

    public LoginController(EmployeeRepository employees, OrgService org, TokenService tokens, AuthProperties props,
                           AuditService audit) {
        this.audit = audit;
        this.employees = employees;
        this.org = org;
        this.tokens = tokens;
        if (props.demoPassword() == null || props.demoPassword().isBlank()) {
            throw new IllegalStateException("ERP_DEMO_PASSWORD가 비어 있습니다. 빈 비밀번호로 로그인되지 않게 시작을 멈춥니다");
        }
        this.password = props.demoPassword().getBytes(StandardCharsets.UTF_8);
    }

    /** 데모 로그인: 사번과 공통 비밀번호(ERP_DEMO_PASSWORD). 틀리면 사번이 있는지 알려 주지 않고 401입니다. */
    @PostMapping("/auth/login")
    @OperationId("login")
    @PublicEndpoint
    public LoginResponse login(@RequestBody LoginRequest req) {
        String given = req.password() == null ? "" : req.password();
        boolean passwordOk = MessageDigest.isEqual(password, given.getBytes(StandardCharsets.UTF_8));
        Employee e = req.employeeNo() == null ? null : employees.findByEmployeeNo(req.employeeNo()).orElse(null);
        if (e == null || !passwordOk) {
            throw new ApiException(401, "unauthorized", "사번이나 비밀번호가 틀렸습니다. 다시 입력하세요.");
        }
        audit.recordSeparately(ErpPrincipal.employee(e.getId()), "auth.login", "login", "ok",
                AuditService.Extra.NONE, null, null);
        return new LoginResponse(tokens.issue(e.getId()), "Bearer", tokens.ttlSeconds(), org.full(e));
    }
}
