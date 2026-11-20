package io.inhouse.erp.common;

import io.inhouse.erp.audit.DeniedRequestAuditor;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/** 오류를 problem+json으로 바꿉니다. 업무 명령 앞에서 끝난 거절은 {@link DeniedRequestAuditor}가 감사에 남깁니다. */
@RestControllerAdvice
public class ProblemHandler {

    private static final Logger log = LoggerFactory.getLogger(ProblemHandler.class);

    private final DeniedRequestAuditor denied;

    public ProblemHandler(DeniedRequestAuditor denied) {
        this.denied = denied;
    }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Object> api(ApiException e, HttpServletRequest req) {
        return respond(req, e);
    }

    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Object> missingParam(MissingServletRequestParameterException e, HttpServletRequest req) {
        return respond(req, ApiException.validation(e.getParameterName(), "required"));
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<Object> typeMismatch(MethodArgumentTypeMismatchException e, HttpServletRequest req) {
        return respond(req, ApiException.validation(e.getName(), "invalid value"));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Object> unreadable(HttpMessageNotReadableException e, HttpServletRequest req) {
        return respond(req, new ApiException(422, "validation", "JSON 본문이 아닙니다"));
    }

    /** JSON이 아닌 Content-Type도 본문을 못 읽은 것과 같이 422입니다(예전에는 500). */
    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<Object> mediaType(HttpMediaTypeNotSupportedException e, HttpServletRequest req) {
        return respond(req, new ApiException(422, "validation", "JSON 본문이 아닙니다"));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Object> noResource(NoResourceFoundException e) {
        return Problems.response(ApiException.notFound("없는 경로입니다"));
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<Object> method(HttpRequestMethodNotSupportedException e) {
        return Problems.response(new ApiException(405, "validation", "지원하지 않는 메서드입니다"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Object> unknown(Exception e) {
        log.error("처리하지 못한 오류", e);
        return ResponseEntity.status(500).contentType(Problems.PROBLEM_JSON)
                .body(Problems.body(500, "internal", "서버 오류", List.of()));
    }

    private ResponseEntity<Object> respond(HttpServletRequest req, ApiException e) {
        denied.recordIfNeeded(req, e);
        return Problems.response(e);
    }
}
