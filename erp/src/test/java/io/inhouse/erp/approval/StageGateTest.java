package io.inhouse.erp.approval;

import static org.assertj.core.api.Assertions.assertThat;

import io.inhouse.erp.ApiTestBase;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;

/** ERP_STAGE=1이면 2단계 양식(지출·구매)은 꺼집니다. */
@TestPropertySource(properties = "erp.stage=1")
class StageGateTest extends ApiTestBase {

    @Test
    void stage2FormsAreOffInStage1() throws Exception {
        String member = members("quality").get(0);
        assertThat(json(get("/approval-forms", member)).path("items").findValuesAsText("id")).containsExactly("leave");
        var r = post("/approval-documents", member, Map.of("formId", "expense", "fields", Map.of("amount", 1000,
                "spent_on", "2026-11-02", "merchant", "가상상회", "purpose", "x")));
        assertThat(r.getStatus()).isEqualTo(422);
        assertThat(problem(r)).isEqualTo("validation");
        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.ofHours(9));
        var d = post("/delegations", leader("quality"), Map.of("delegateId", member, "startsAt", now.toString(),
                "endsAt", now.plusDays(1).toString(), "scope", Map.of("formTypes", List.of("expense")), "reason", "x"));
        assertThat(problem(d)).isEqualTo("validation");
    }
}
