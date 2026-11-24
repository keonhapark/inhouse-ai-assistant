package io.inhouse.erp.approval;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.pack.Pack;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ApprovalViewsTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private static List<String> names(JsonNode n) {
        List<String> out = new ArrayList<>();
        n.fieldNames().forEachRemaining(out::add);
        return out;
    }

    @Test
    void ordersByFormThenKeepsUnknownFieldsAfter() throws Exception {
        JsonNode schema = mapper.readTree("""
                {"properties": {"amount": {}, "spent_on": {}, "merchant": {}, "purpose": {}}}""");
        Pack.FormDef form = new Pack.FormDef("expense", "경비 정산", 2, schema, "amount", List.of(), Map.of(), List.of());
        // jsonb가 돌려주는 순서(키 길이 순)와 양식에서 빠진 옛 칸
        JsonNode stored = mapper.readTree("""
                {"amount": 1, "legacy": "x", "purpose": "p", "merchant": "m", "spent_on": "d"}""");
        JsonNode out = ApprovalViews.ordered(stored, form);
        assertThat(names(out)).containsExactly("amount", "spent_on", "merchant", "purpose", "legacy");
        assertThat(out).isEqualTo(stored);
        assertThat(names(ApprovalViews.ordered(stored, null))).isEqualTo(names(stored));
    }
}
