package io.inhouse.erp.audit;

import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.OperationId;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.convert.ConversionException;
import org.springframework.core.convert.support.DefaultConversionService;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerMapping;

/**
 * 업무 명령({@code WriteExecutor}) 앞에서 끝난 거절을 erp.denied로 남깁니다.
 * <ul>
 *   <li>위임 토큰의 scope·사람 전용 거절({@link ApiException#isAuditedOnReads()}): 읽기 경로도 남깁니다.</li>
 *   <li>쓰기 경로(GET 아닌 경로)의 사전 검사 거절(본문 검사, 양식별 scope, Idempotency-Key 없음 등): 실행 요청만
 *       남깁니다. dryRun은 미리보기라 {@code WriteExecutor}처럼 남기지 않습니다.</li>
 * </ul>
 * 로그인하지 않은 요청(401)과 경로를 못 찾은 요청은 누가 무엇을 했는지 알 수 없어 남기지 않습니다.
 */
@Component
public class DeniedRequestAuditor {

    private static final Logger log = LoggerFactory.getLogger(DeniedRequestAuditor.class);

    private final AuditService audit;

    public DeniedRequestAuditor(AuditService audit) {
        this.audit = audit;
    }

    public void recordIfNeeded(HttpServletRequest req, ApiException e) {
        if (e.isAudited()) {
            return;
        }
        ErpPrincipal p = principal();
        if (p == null || !(req.getAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE) instanceof HandlerMethod hm)) {
            return;
        }
        boolean write = !"GET".equals(req.getMethod());
        boolean dryRun = dryRun(req.getParameter("dryRun"));
        if (!e.isAuditedOnReads() && !(write && !dryRun)) {
            return;
        }
        OperationId op = hm.getMethodAnnotation(OperationId.class);
        try {
            audit.recordSeparately(p, "erp.denied", op == null ? null : op.value(),
                    e.status() == 409 ? "conflict" : "denied", AuditService.Extra.NONE, e.code(), e.detail());
            e.markAudited();
        } catch (RuntimeException ex) {
            // 감사 저장이 실패해도 거절 응답은 그대로 돌려줍니다. 원래 응답을 500으로 바꾸지 않습니다.
            log.error("거절 감사 이벤트를 남기지 못했습니다: {} {}", op == null ? hm : op.value(), e.code(), ex);
        }
    }

    /** 컨트롤러의 {@code boolean dryRun} 바인딩과 같은 규칙(true·on·yes·1)으로 읽습니다. */
    static boolean dryRun(String value) {
        if (value == null) {
            return false;
        }
        try {
            return Boolean.TRUE.equals(DefaultConversionService.getSharedInstance().convert(value, Boolean.class));
        } catch (ConversionException e) {
            return false;
        }
    }

    private static ErpPrincipal principal() {
        Authentication a = SecurityContextHolder.getContext().getAuthentication();
        return a != null && a.getPrincipal() instanceof ErpPrincipal p ? p : null;
    }
}
