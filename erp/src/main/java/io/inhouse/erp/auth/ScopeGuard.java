package io.inhouse.erp.auth;

import io.inhouse.erp.common.ApiException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * 위임 토큰 요청의 scope와 사람 화면 전용 여부를 확인합니다. 최종 권한 판단(토큰 주인의 권한)은 각 업무 규칙이 합니다.
 * 여기서 난 거절은 읽기 경로라도 {@link io.inhouse.erp.audit.DeniedRequestAuditor}가 erp.denied로 남깁니다.
 */
@Component
public class ScopeGuard implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) {
        if (!(handler instanceof HandlerMethod hm)) {
            return true;
        }
        ErpPrincipal p = current();
        if (p == null || hm.hasMethodAnnotation(PublicEndpoint.class)) {
            return true;
        }
        RequiredScope rs = hm.getMethodAnnotation(RequiredScope.class);
        if (p.viaServiceLogin() && rs != null && rs.humanOnly()) {
            throw new ApiException(403, "service-login-not-allowed", "웹 화면에서 하세요.")
                    .auditedOnReads();
        }
        if (!p.viaDelegationToken()) {
            return true;
        }
        if (rs == null) {
            // scope 표시가 빠진 경로는 위임 토큰으로 열지 않습니다(실패 시 닫힘).
            throw new ApiException(403, "forbidden", "scope가 정해지지 않은 경로입니다").auditedOnReads();
        }
        if (rs.humanOnly()) {
            throw new ApiException(403, "delegation-token-not-allowed", "위임 토큰으로 부를 수 없는 기능입니다")
                    .auditedOnReads();
        }
        if (!rs.perForm()) {
            require(p, rs.value());
        }
        return true;
    }

    /** {@code approval:request}이거나 {@code approval:request:<formId>}가 있어야 합니다. */
    public void requireForForm(ErpPrincipal p, String scope, String formId) {
        if (p.viaDelegationToken() && !p.scopes().contains(scope) && !p.scopes().contains(scope + ":" + formId)) {
            throw scopeMissing(scope + ":" + formId);
        }
    }

    private static void require(ErpPrincipal p, String scope) {
        if (!p.scopes().contains(scope)) {
            throw scopeMissing(scope);
        }
    }

    private static ApiException scopeMissing(String scope) {
        return new ApiException(403, "scope-missing", "필요한 scope: " + scope).auditedOnReads();
    }

    private static ErpPrincipal current() {
        Authentication a = SecurityContextHolder.getContext().getAuthentication();
        return a != null && a.getPrincipal() instanceof ErpPrincipal p ? p : null;
    }
}
