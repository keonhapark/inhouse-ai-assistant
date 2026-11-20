package io.inhouse.erp.auth;

import java.util.Map;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/** 시험 전용. 사람 화면 전용·양식별 scope 검사를 실제 기능 없이 확인합니다. 계약 경로가 아닙니다. */
@RestController
class GuardProbeController {

    static final String PREFIX = "/test-probe";

    private final ScopeGuard guard;

    GuardProbeController(ScopeGuard guard) {
        this.guard = guard;
    }

    @GetMapping(PREFIX + "/human-only")
    @RequiredScope(value = "approval:decide", humanOnly = true)
    Map<String, String> humanOnly() {
        return Map.of("ok", "true");
    }

    @GetMapping(PREFIX + "/unmarked")
    Map<String, String> unmarked() {
        return Map.of("ok", "true");
    }

    @GetMapping(PREFIX + "/form/{formId}")
    @RequiredScope(value = "approval:request", perForm = true)
    Map<String, String> perForm(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String formId) {
        guard.requireForForm(p, "approval:request", formId);
        return Map.of("ok", formId);
    }
}
