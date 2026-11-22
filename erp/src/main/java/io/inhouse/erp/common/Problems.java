package io.inhouse.erp.common;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

/**
 * problem+json 본문을 만듭니다. 제목은 코드마다 고정입니다(문구 기준 ux/copy-guide.md).
 * 웹은 제목과 detail을 이어 보여 주므로, detail이 제목과 같으면 detail을 뺍니다.
 */
public final class Problems {

    public static final MediaType PROBLEM_JSON = MediaType.APPLICATION_PROBLEM_JSON;

    private static final Map<String, String> TITLES = Map.ofEntries(
            Map.entry("unauthorized", "로그인이 필요합니다"),
            Map.entry("forbidden", "권한이 없습니다"),
            Map.entry("scope-missing", "위임 토큰에 필요한 scope가 없습니다"),
            Map.entry("delegation-token-not-allowed", "사람 화면 전용 기능입니다"),
            Map.entry("service-login-not-allowed", "슬랙에서는 쓸 수 없는 기능입니다"),
            Map.entry("not-found", "찾을 수 없습니다"),
            Map.entry("validation", "입력이 올바르지 않습니다"),
            Map.entry("form-validation-failed", "양식 입력이 올바르지 않습니다"),
            Map.entry("idempotency-key-required", "Idempotency-Key가 필요합니다"),
            Map.entry("idempotency-key-reused", "같은 Idempotency-Key로 다른 요청을 보냈습니다"),
            Map.entry("version-conflict", "그사이 다른 사람이 먼저 바꿨습니다"),
            Map.entry("invalid-state", "지금 상태에서는 할 수 없습니다"),
            Map.entry("not-current-approver", "지금 결재 대기 중인 문서가 아닙니다"),
            Map.entry("self-approval-forbidden", "본인이 기안한 문서는 결재할 수 없습니다"),
            Map.entry("delegation-not-found", "이 문서를 대결할 수 있는 대결 지정이 없습니다"),
            Map.entry("delegation-out-of-period", "대결 기간이 아닙니다"),
            Map.entry("delegation-out-of-scope", "대결 범위 밖의 문서입니다"),
            Map.entry("delegation-revoked", "해제된 대결입니다"),
            Map.entry("redelegation-not-allowed", "대결자는 맡은 결재를 다른 사람에게 다시 맡길 수 없습니다"),
            Map.entry("delegation-self", "본인을 대결자로 지정할 수 없습니다"),
            Map.entry("delegation-period-too-long", "대결 기간이 너무 깁니다"),
            Map.entry("delegation-registrar-forbidden", "대결을 지정할 권한이 없습니다"),
            Map.entry("leave-balance-insufficient", "남은 연차가 부족합니다"),
            Map.entry("room-conflict", "이미 예약된 시간입니다"),
            Map.entry("not-undoable", "실행 취소할 수 없는 작업입니다"),
            Map.entry("already-undone", "이미 실행 취소한 작업입니다"),
            Map.entry("undo-conflict", "그사이 상태가 바뀌어 실행 취소할 수 없습니다"),
            Map.entry("internal", "서버에서 요청을 처리하지 못했습니다"));

    private Problems() {}

    public static Map<String, Object> body(int status, String code, String detail, List<ApiException.FieldError> errors) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("type", "urn:problem:" + code);
        String title = TITLES.getOrDefault(code, code);
        body.put("title", title);
        body.put("status", status);
        if (detail != null && !detail.isBlank() && !sameSentence(detail, title)) {
            body.put("detail", detail);
        }
        if (errors != null && !errors.isEmpty()) {
            body.put("errors", errors);
        }
        return body;
    }

    private static boolean sameSentence(String a, String b) {
        return a.strip().replaceAll("\\.$", "").equals(b.strip().replaceAll("\\.$", ""));
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
