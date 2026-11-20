package io.inhouse.erp.common;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** 요청 본문 검사(계약의 required·additionalProperties: false·maxLength). 어기면 422 validation입니다. */
public final class Bodies {

    private Bodies() {}

    public static void check(JsonNode body, Set<String> allowed, Set<String> required) {
        if (body == null || !body.isObject()) {
            throw new ApiException(422, "validation", "JSON 객체 본문이 필요합니다");
        }
        List<ApiException.FieldError> errors = new ArrayList<>();
        body.fieldNames().forEachRemaining(f -> {
            if (!allowed.contains(f)) {
                errors.add(new ApiException.FieldError(f, "unknown field"));
            }
        });
        for (String r : required) {
            if (!body.hasNonNull(r)) {
                errors.add(new ApiException.FieldError(r, "required"));
            }
        }
        if (!errors.isEmpty()) {
            throw new ApiException(422, "validation", "입력이 올바르지 않습니다", errors);
        }
    }

    public static String text(JsonNode body, String field, int maxLength) {
        JsonNode v = body.get(field);
        if (v == null || v.isNull()) {
            return null;
        }
        if (!v.isTextual()) {
            throw ApiException.validation(field, "string required");
        }
        if (v.asText().length() > maxLength) {
            throw ApiException.validation(field, "maxLength " + maxLength);
        }
        return v.asText();
    }

    public static int integer(JsonNode body, String field) {
        JsonNode v = body.get(field);
        if (v == null || !v.canConvertToInt() || !v.isIntegralNumber()) {
            throw ApiException.validation(field, "integer required");
        }
        return v.asInt();
    }
}
