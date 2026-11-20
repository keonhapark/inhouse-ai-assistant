package io.inhouse.erp.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

/** problem+json 본문을 만듭니다. 제목은 코드마다 고정입니다(가짜 erp와 같은 문구). */
public final class Problems {

    public static final MediaType PROBLEM_JSON = MediaType.APPLICATION_PROBLEM_JSON;

    private static final Map<String, String> TITLES = Map.ofEntries(
            Map.entry("unauthorized", "인증이 필요합니다"),
            Map.entry("forbidden", "권한이 없습니다"),
            Map.entry("scope-missing", "위임 토큰에 필요한 scope가 없습니다"),
            Map.entry("delegation-token-not-allowed", "사람 화면 전용 기능입니다"),
            Map.entry("not-found", "찾을 수 없습니다"),
            Map.entry("validation", "입력이 올바르지 않습니다"),
            Map.entry("form-validation-failed", "양식 입력이 올바르지 않습니다"),
            Map.entry("idempotency-key-required", "Idempotency-Key가 필요합니다"),
            Map.entry("idempotency-key-reused", "같은 Idempotency-Key로 다른 요청을 보냈습니다"),
            Map.entry("version-conflict", "문서가 그사이 바뀌었습니다"),
            Map.entry("invalid-state", "지금 상태에서는 할 수 없습니다"),
            Map.entry("not-current-approver", "현재 결재 차례가 아닙니다"),
            Map.entry("self-approval-forbidden", "본인이 올린 문서는 결재할 수 없습니다"),
            Map.entry("delegation-not-found", "유효한 대결 위임이 없습니다"),
            Map.entry("delegation-out-of-period", "대결 위임 기간이 아닙니다"),
            Map.entry("delegation-out-of-scope", "대결 위임 범위 밖입니다"),
            Map.entry("delegation-revoked", "해지된 대결 위임입니다"),
            Map.entry("redelegation-not-allowed", "재위임은 허용하지 않습니다"),
            Map.entry("delegation-self", "본인에게 위임할 수 없습니다"),
            Map.entry("delegation-period-too-long", "위임 기간이 너무 깁니다"),
            Map.entry("delegation-registrar-forbidden", "대결을 등록할 권한이 없습니다"),
            Map.entry("leave-balance-insufficient", "연차 잔여가 부족합니다"),
            Map.entry("room-conflict", "같은 시간에 예약이 있습니다"),
            Map.entry("not-undoable", "되돌릴 수 없는 행동입니다"),
            Map.entry("already-undone", "이미 되돌린 행동입니다"),
            Map.entry("undo-conflict", "상태가 바뀌어 되돌릴 수 없습니다"));

    private Problems() {}

    public static Map<String, Object> body(int status, String code, String detail, List<ApiException.FieldError> errors) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("type", "urn:problem:" + code);
        body.put("title", TITLES.getOrDefault(code, code));
        body.put("status", status);
        if (detail != null && !detail.isBlank()) {
            body.put("detail", detail);
        }
        if (errors != null && !errors.isEmpty()) {
            body.put("errors", errors);
        }
        return body;
    }

    public static ResponseEntity<Object> response(ApiException e) {
        return ResponseEntity.status(e.status()).contentType(PROBLEM_JSON)
                .body(body(e.status(), e.code(), e.detail(), e.errors()));
    }

    public static void write(HttpServletResponse res, ObjectMapper mapper, int status, String code, String detail)
            throws IOException {
        res.setStatus(status);
        res.setContentType(PROBLEM_JSON.toString());
        res.setCharacterEncoding("UTF-8");
        mapper.writeValue(res.getOutputStream(), body(status, code, detail, null));
    }
}
