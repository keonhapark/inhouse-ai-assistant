package io.inhouse.erp.auth;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 계약의 {@code x-required-scope}와 {@code x-human-only}. 위임 토큰으로 부를 때만 검사합니다(직원 JWT는 모든 scope).
 * {@code perForm}이면 양식 ID를 본문에서 알아야 하므로 컨트롤러가 {@link ScopeGuard#requireForForm}를 부릅니다.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequiredScope {
    String value();

    boolean humanOnly() default false;

    boolean perForm() default false;
}
