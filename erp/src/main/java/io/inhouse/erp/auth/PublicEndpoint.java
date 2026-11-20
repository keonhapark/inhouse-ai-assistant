package io.inhouse.erp.auth;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/** 계약에서 {@code security: []}인 경로(건강 확인, 로그인). 그 밖의 경로는 {@link RequiredScope}가 있어야 합니다. */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface PublicEndpoint {}
