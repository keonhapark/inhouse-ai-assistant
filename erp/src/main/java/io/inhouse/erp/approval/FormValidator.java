package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ko;
import io.inhouse.erp.pack.Pack;
import java.math.BigInteger;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/**
 * 양식 입력(fields)을 팩 forms.yaml의 JSON Schema(2020-12)로 검사합니다. 양식에 amount_product_of가 있으면
 * 금액 필드가 그 필드들의 곱과 같은지도 봅니다. 어기면 422 form-validation-failed입니다.
 */
@Component
public class FormValidator {

    /** format(date 등)도 검사합니다. 2020-12 기본값은 format을 주석으로만 봅니다. */
    private static final SchemaValidatorsConfig CONFIG = SchemaValidatorsConfig.builder()
            .formatAssertionsEnabled(true).build();

    private final JsonSchemaFactory factory = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
    private final Map<String, JsonSchema> cache = new ConcurrentHashMap<>();

    public void validate(Pack.FormDef form, JsonNode fields) {
        if (fields == null || !fields.isObject()) {
            throw new ApiException(422, "form-validation-failed", "fields는 객체여야 합니다",
                    List.of(new ApiException.FieldError("fields", "object required")));
        }
        JsonSchema schema = cache.computeIfAbsent(form.id(), id -> factory.getSchema(form.fields(), CONFIG));
        List<ApiException.FieldError> errors = schema.validate(fields).stream()
                .sorted(Comparator.comparing(ValidationMessage::getMessage))
                .map(m -> new ApiException.FieldError(field(m), m.getMessage()))
                .toList();
        if (!errors.isEmpty()) {
            throw new ApiException(422, "form-validation-failed", "양식 입력이 올바르지 않습니다", errors);
        }
        checkProduct(form, fields);
    }

    /** 스키마 검사를 지난 뒤라 곱할 필드는 모두 있는 정수입니다(팩 검사가 필수 정수 필드인지 봅니다). */
    private static void checkProduct(Pack.FormDef form, JsonNode fields) {
        if (form.amountProductOf().isEmpty() || form.amountField() == null) {
            return;
        }
        BigInteger want = BigInteger.ONE;
        for (String name : form.amountProductOf()) {
            want = want.multiply(fields.path(name).bigIntegerValue());
        }
        BigInteger amount = fields.path(form.amountField()).bigIntegerValue();
        if (!amount.equals(want)) {
            String detail = Ko.i(label(form, form.amountField())) + " "
                    + String.join(" × ", form.amountProductOf().stream().map(n -> label(form, n)).toList())
                    + "(" + String.format("%,d", want) + "원)과 다릅니다. " + Ko.eul(label(form, form.amountField()))
                    + " 다시 확인하세요.";
            throw new ApiException(422, "form-validation-failed", detail,
                    List.of(new ApiException.FieldError(form.amountField(), "mismatch")));
        }
    }

    /** 팩 양식 스키마의 칸 표시 이름(title). 없으면 칸 이름 그대로입니다. */
    private static String label(Pack.FormDef form, String name) {
        return form.fields().path("properties").path(name).path("title").asText(name);
    }

    private static String field(ValidationMessage m) {
        if ("required".equals(m.getType()) && m.getProperty() != null) {
            return m.getProperty();
        }
        String loc = m.getInstanceLocation().toString();
        String f = loc.startsWith("$.") ? loc.substring(2) : loc.startsWith("/") ? loc.substring(1)
                : loc.equals("$") ? "" : loc;
        if (f.isEmpty() && m.getProperty() != null) {
            return m.getProperty();
        }
        return f.isEmpty() ? m.getType() : f;
    }
}
