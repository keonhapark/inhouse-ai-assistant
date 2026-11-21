package io.inhouse.erp.auth;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.audit.AuditService;
import io.inhouse.erp.auth.LoginController.LoginResponse;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.EmployeeRepository;
import io.inhouse.erp.org.OrgService;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * 서비스 로그인(gateway 전용, 슬랙 입구 #273·#291). gateway가 슬랙 사용자를 직원으로 확인한 뒤 그 직원의 짧은
 * 직원 JWT(amr slack)를 받습니다. 이 토큰으로는 사람 전용 기능을 부를 수 없습니다(ScopeGuard).
 * 비밀값(ERP_SERVICE_LOGIN_SECRET)이 비어 있으면 빈을 만들지 않아 경로가 없습니다(404).
 */
@RestController
@ConditionalOnExpression("'${erp.service-login-secret:}'.trim().length() > 0")
public class ServiceLoginController {

    static final int MIN_SECRET_BYTES = 32;
    private static final Logger log = LoggerFactory.getLogger(ServiceLoginController.class);

    private final EmployeeRepository employees;
    private final OrgService org;
    private final TokenService tokens;
    private final AuditService audit;
    private final byte[] secret;

    public ServiceLoginController(EmployeeRepository employees, OrgService org, TokenService tokens,
                                  AuthProperties props, AuditService audit) {
        this.employees = employees;
        this.org = org;
        this.tokens = tokens;
        this.audit = audit;
        String s = props.serviceLoginSecret();
        this.secret = s == null || s.isBlank() ? null : s.getBytes(StandardCharsets.UTF_8);
        if (secret != null && secret.length < MIN_SECRET_BYTES) {
            log.warn("ERP_SERVICE_LOGIN_SECRET이 {}바이트보다 짧습니다. 길고 무작위인 값을 쓰세요", MIN_SECRET_BYTES);
        }
    }

    /** 비밀값이 설정되지 않았으면 경로가 없는 것과 같이 404, 비밀값이 없거나 틀리면 401, 없는 직원이면 422입니다. */
    @PostMapping("/auth/service-login")
    @OperationId("serviceLogin")
    @PublicEndpoint
    public LoginResponse serviceLogin(@RequestHeader(value = "X-Service-Login-Secret", required = false) String given,
                                      @RequestBody(required = false) JsonNode body) {
        if (secret == null) {
            throw ApiException.notFound("없는 경로입니다");
        }
        byte[] g = given == null ? new byte[0] : given.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(secret, g)) {
            // 비밀값은 남기지 않습니다. 시도가 잦으면 이 줄로 알아봅니다.
            log.warn("서비스 로그인 비밀값 불일치(헤더 {})", given == null ? "없음" : "다름");
            throw new ApiException(401, "unauthorized", "서비스 비밀값이 틀렸습니다");
        }
        Bodies.check(body, Set.of("employeeId"), Set.of("employeeId"));
        String id = Bodies.text(body, "employeeId", 32);
        Employee e = employees.findById(id).orElseThrow(() -> ApiException.validation("employeeId", "unknown"));
        audit.recordSeparately(ErpPrincipal.serviceLogin(e.getId()), "auth.login", "serviceLogin", "ok",
                AuditService.Extra.NONE, null, null);
        return new LoginResponse(tokens.issueServiceLogin(e.getId()), "Bearer", TokenService.SERVICE_LOGIN_TTL_SECONDS,
                org.full(e));
    }
}
