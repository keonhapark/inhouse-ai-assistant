package io.inhouse.erp.common;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/** 계약(erp.yaml)의 operationId. 컨트롤러 앞단에서 난 거절을 감사 이벤트에 남길 때 operation으로 씁니다. */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface OperationId {
    String value();
}
