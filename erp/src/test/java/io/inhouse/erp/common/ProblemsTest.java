package io.inhouse.erp.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ProblemsTest {

    @Test
    void detailSameAsTitleIsDropped() {
        // 웹은 제목과 detail을 이어 보여 주므로 같은 말이 두 번 나오지 않게 합니다.
        Map<String, Object> b = Problems.body(403, "self-approval-forbidden", "본인이 기안한 문서는 결재할 수 없습니다.",
                List.of());
        assertThat(b.get("title")).isEqualTo("본인이 기안한 문서는 결재할 수 없습니다");
        assertThat(b).doesNotContainKey("detail");
        assertThat(Problems.body(422, "validation", "입력이 올바르지 않습니다", List.of())).doesNotContainKey("detail");
        assertThat(Problems.body(409, "version-conflict", "새로 고친 뒤 다시 확인하세요.", List.of()).get("detail"))
                .isEqualTo("새로 고친 뒤 다시 확인하세요.");
    }

    @Test
    void internalHasKoreanTitle() {
        assertThat(Problems.body(500, "internal", null, List.of()).get("title")).isEqualTo("서버에서 요청을 처리하지 못했습니다");
    }

    @Test
    void invalidKeepsFieldOutOfDetail() {
        ApiException e = ApiException.invalid("endsAt", "끝나는 시각은 시작 시각보다 늦어야 합니다.");
        assertThat(e.detail()).isEqualTo("끝나는 시각은 시작 시각보다 늦어야 합니다.");
        assertThat(e.errors()).extracting(ApiException.FieldError::field).containsExactly("endsAt");
    }
}
