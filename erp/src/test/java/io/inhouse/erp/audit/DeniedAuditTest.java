package io.inhouse.erp.audit;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.ApiTestBase;
import io.inhouse.erp.auth.Tokens;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

/** 업무 명령 앞에서 끝난 거절(scope·사람 전용·본문 검사·Idempotency-Key 없음)도 erp.denied로 남는지 봅니다. */
class DeniedAuditTest extends ApiTestBase {

    static final String EMP = "E0031";

    @Autowired JdbcTemplate jdbc;

    private int denied(String operation, String problem) {
        Integer n = jdbc.queryForObject("select count(*) from audit_event where actor_id = ? and kind = 'erp.denied'"
                + " and event->>'operation' = ? and event->>'problemType' = ?", Integer.class, EMP, operation,
                "urn:problem:" + problem);
        return n == null ? 0 : n;
    }

    private JsonNode lastDenied(String operation) throws Exception {
        String event = jdbc.queryForObject("select event::text from audit_event where actor_id = ?"
                + " and kind = 'erp.denied' and event->>'operation' = ? order by seq desc limit 1", String.class, EMP,
                operation);
        return mapper.readTree(event);
    }

    private MockHttpServletResponse send(MockHttpServletRequestBuilder b, String token, Object body, boolean key)
            throws Exception {
        b.header("Authorization", "Bearer " + token);
        if (key) {
            b.header("Idempotency-Key", UUID.randomUUID().toString());
        }
        if (body != null) {
            b.contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(body));
        }
        return mvc.perform(b).andReturn().getResponse();
    }

    @Test
    void delegationTokenApproveIsAudited() throws Exception {
        String token = Tokens.delegation(EMP, List.of("approval:decide"));
        int before = denied("approveApprovalDocument", "delegation-token-not-allowed");
        MockHttpServletResponse r = send(MockMvcRequestBuilders.post("/approval-documents/apd_x/approve"), token,
                Map.of("version", 1), true);
        assertThat(r.getStatus()).isEqualTo(403);
        assertThat(problem(r)).isEqualTo("delegation-token-not-allowed");
        // 미리보기로 시도해도 사람 전용 기능을 위임 토큰으로 부른 것이므로 남깁니다.
        send(MockMvcRequestBuilders.post("/approval-documents/apd_x/approve").param("dryRun", "true"), token,
                Map.of("version", 1), false);
        assertThat(denied("approveApprovalDocument", "delegation-token-not-allowed")).isEqualTo(before + 2);

        JsonNode e = lastDenied("approveApprovalDocument");
        assertThat(e.path("source").asText()).isEqualTo("erp");
        assertThat(e.path("result").asText()).isEqualTo("denied");
        assertThat(e.path("actor").path("viaDelegationToken").asBoolean()).isTrue();
        assertThat(e.path("actor").path("agentId").asText()).isEqualTo("hr");
        assertThat(e.path("conversationId").asText()).isEqualTo("cnv_test");
    }

    @Test
    void scopeMissingOnReadIsAudited() throws Exception {
        int before = denied("listUnits", "scope-missing");
        MockHttpServletResponse r = send(MockMvcRequestBuilders.get("/org/units"),
                Tokens.delegation(EMP, List.of("profile:read")), null, false);
        assertThat(r.getStatus()).isEqualTo(403);
        assertThat(denied("listUnits", "scope-missing")).isEqualTo(before + 1);
    }

    @Test
    void formScopeMissingOnCreateIsAudited() throws Exception {
        int before = denied("createApprovalDocument", "scope-missing");
        MockHttpServletResponse r = send(MockMvcRequestBuilders.post("/approval-documents"),
                Tokens.delegation(EMP, List.of("approval:request:leave")),
                Map.of("formId", "expense", "fields", Map.of()), true);
        assertThat(problem(r)).isEqualTo("scope-missing");
        assertThat(denied("createApprovalDocument", "scope-missing")).isEqualTo(before + 1);
    }

    @Test
    void writePrecheckIsAuditedButDryRunIsNot() throws Exception {
        String jwt = jwt(EMP);
        int validation = denied("createApprovalDocument", "validation");
        MockHttpServletResponse r = send(MockMvcRequestBuilders.post("/approval-documents"), jwt,
                Map.of("formId", "leave"), true);
        assertThat(problem(r)).isEqualTo("validation");
        assertThat(denied("createApprovalDocument", "validation")).isEqualTo(validation + 1);

        // dryRun은 미리보기라 사전 검사 거절을 남기지 않습니다(WriteExecutor의 미리보기와 같음).
        r = send(MockMvcRequestBuilders.post("/approval-documents").param("dryRun", "true"), jwt,
                Map.of("formId", "leave"), false);
        assertThat(problem(r)).isEqualTo("validation");
        assertThat(denied("createApprovalDocument", "validation")).isEqualTo(validation + 1);
        // 컨트롤러 바인딩처럼 1도 dryRun입니다.
        send(MockMvcRequestBuilders.post("/approval-documents").param("dryRun", "1"), jwt, Map.of("formId", "leave"),
                false);
        assertThat(denied("createApprovalDocument", "validation")).isEqualTo(validation + 1);

        // JSON이 아닌 본문도 사전 검사 거절(422)로 남습니다.
        r = mvc.perform(MockMvcRequestBuilders.post("/approval-documents").header("Authorization", "Bearer " + jwt)
                .header("Idempotency-Key", UUID.randomUUID().toString()).contentType(MediaType.TEXT_PLAIN)
                .content("leave")).andReturn().getResponse();
        assertThat(r.getStatus()).isEqualTo(422);
        assertThat(denied("createApprovalDocument", "validation")).isEqualTo(validation + 2);

        int noKey = denied("withdrawApprovalDocument", "idempotency-key-required");
        r = send(MockMvcRequestBuilders.post("/approval-documents/apd_x/withdraw"), jwt, null, false);
        assertThat(problem(r)).isEqualTo("idempotency-key-required");
        assertThat(denied("withdrawApprovalDocument", "idempotency-key-required")).isEqualTo(noKey + 1);
    }

    @Test
    void denialInsideWriteIsAuditedOnce() throws Exception {
        int before = denied("withdrawApprovalDocument", "not-found");
        MockHttpServletResponse r = send(MockMvcRequestBuilders.post("/approval-documents/apd_none/withdraw"),
                jwt(EMP), null, true);
        assertThat(r.getStatus()).isEqualTo(404);
        assertThat(denied("withdrawApprovalDocument", "not-found")).isEqualTo(before + 1);
    }

    @Test
    void readDenialByEmployeeIsNotAudited() throws Exception {
        int before = denied("getApprovalDocument", "not-found");
        MockHttpServletResponse r = get("/approval-documents/apd_none", EMP);
        assertThat(r.getStatus()).isEqualTo(404);
        assertThat(denied("getApprovalDocument", "not-found")).isEqualTo(before);
    }
}
