package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;

/** 계약의 Change. 미리보기에서 새로 만들 것은 resourceId가 null입니다. */
public record Change(String op, String resource, String resourceId, JsonNode before, JsonNode after) {

    public Change withoutId() {
        return new Change(op, resource, null, before, after);
    }
}
