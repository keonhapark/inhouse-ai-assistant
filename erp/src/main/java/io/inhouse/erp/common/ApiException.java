package io.inhouse.erp.common;

import java.util.List;

/** 계약의 ProblemCode로 끝나는 오류. 응답은 RFC 9457 problem+json, type은 urn:problem:&lt;code&gt;입니다. */
public class ApiException extends RuntimeException {

    public record FieldError(String field, String message) {}

    private final int status;
    private final String code;
    private final String detail;
    private final List<FieldError> errors;
    private boolean alwaysAudited;
    private boolean audited;

    public ApiException(int status, String code) {
        this(status, code, null, List.of());
    }

    public ApiException(int status, String code, String detail) {
        this(status, code, detail, List.of());
    }

    public ApiException(int status, String code, String detail, List<FieldError> errors) {
        super(detail == null ? code : detail);
        this.status = status;
        this.code = code;
        this.detail = detail;
        this.errors = errors;
    }

    public static ApiException notFound(String detail) {
        return new ApiException(404, "not-found", detail);
    }

    public static ApiException forbidden(String detail) {
        return new ApiException(403, "forbidden", detail);
    }

    public static ApiException validation(String field, String message) {
        return new ApiException(422, "validation", field + ": " + message, List.of(new FieldError(field, message)));
    }

    /** 읽기 경로에서 나도 감사 이벤트로 남길 거절(위임 토큰의 scope·사람 전용 거절)로 표시합니다. */
    public ApiException auditedOnReads() {
        this.alwaysAudited = true;
        return this;
    }

    /** 이미 erp.denied로 남겼다고 표시합니다. 응답 처리에서 다시 남기지 않습니다. */
    public void markAudited() {
        this.audited = true;
    }

    public boolean isAuditedOnReads() { return alwaysAudited; }
    public boolean isAudited() { return audited; }
    public int status() { return status; }
    public String code() { return code; }
    public String detail() { return detail; }
    public List<FieldError> errors() { return errors; }
}
