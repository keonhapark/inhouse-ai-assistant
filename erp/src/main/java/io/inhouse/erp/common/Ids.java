package io.inhouse.erp.common;

import java.util.UUID;

/** 리소스 ID. 접두사 + 무작위 12자(16진수)입니다. 예: act_1a2b3c4d5e6f */
public final class Ids {

    private Ids() {}

    public static String next(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }
}
