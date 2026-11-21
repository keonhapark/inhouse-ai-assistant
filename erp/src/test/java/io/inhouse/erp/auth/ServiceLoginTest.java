package io.inhouse.erp.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.nimbusds.jwt.SignedJWT;
import io.inhouse.erp.ApiTestBase;
import io.inhouse.erp.common.ApiException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

/** 서비스 로그인(슬랙 입구): 짧은 amr slack 토큰, 사람 전용 기능 403, 감사 이벤트. */
@TestPropertySource(properties = "erp.service-login-secret=" + ServiceLoginTest.SECRET)
class ServiceLoginTest extends ApiTestBase {

    static final String SECRET = "module-test-service-login-secret";

    private MockHttpServletResponse login(String secret, Object body) throws Exception {
        var b = MockMvcRequestBuilders.post("/auth/service-login").contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(body));
        if (secret != null) {
            b.header("X-Service-Login-Secret", secret);
        }
        return mvc.perform(b).andReturn().getResponse();
    }

    private String token(String emp) throws Exception {
        MockHttpServletResponse r = login(SECRET, Map.of("employeeId", emp));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(200);
        return json(r).path("accessToken").asText();
    }

    private MockHttpServletResponse call(String method, String path, String token, Object body) throws Exception {
        var b = MockMvcRequestBuilders.request(org.springframework.http.HttpMethod.valueOf(method), path)
                .header("Authorization", "Bearer " + token).header("Idempotency-Key", java.util.UUID.randomUUID().toString());
        if (body != null) {
            b.contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(body));
        }
        return mvc.perform(b).andReturn().getResponse();
    }

    @Test
    void issuesShortSlackTokenAndAudits() throws Exception {
        String emp = members("sales").get(0);
        MockHttpServletResponse r = login(SECRET, Map.of("employeeId", emp));
        JsonNode body = json(r);
        assertThat(body.path("expiresIn").asLong()).isEqualTo(900);
        assertThat(body.path("employee").path("id").asText()).isEqualTo(emp);
        var claims = SignedJWT.parse(body.path("accessToken").asText()).getJWTClaimsSet();
        assertThat(claims.getStringListClaim("amr")).containsExactly("slack");
        assertThat(claims.getExpirationTime().getTime() - claims.getIssueTime().getTime()).isEqualTo(900_000L);
        assertThat(call("GET", "/me", body.path("accessToken").asText(), null).getStatus()).isEqualTo(200);

        String auditor = pack.employees().stream().filter(e -> e.grade().equals("ceo")).findFirst().orElseThrow().id();
        JsonNode events = json(get("/audit-events", auditor, "actorId", emp, "limit", "500")).path("items");
        assertThat(events.findValuesAsText("operation")).contains("serviceLogin");
        assertThat(events.toString()).doesNotContain(SECRET).doesNotContain(body.path("accessToken").asText());
    }

    @Test
    void rejectsMissingOrWrongSecretAndUnknownEmployee() throws Exception {
        assertThat(problem(login(null, Map.of("employeeId", "E0010")))).isEqualTo("unauthorized");
        assertThat(problem(login("wrong", Map.of("employeeId", "E0010")))).isEqualTo("unauthorized");
        MockHttpServletResponse r = login(SECRET, Map.of("employeeId", "E9999"));
        assertThat(r.getStatus()).isEqualTo(422);
        assertThat(problem(r)).isEqualTo("validation");
        assertThat(problem(login(SECRET, Map.of("employeeId", "E0010", "role", "admin")))).isEqualTo("validation");
    }

    @Test
    void humanOnlyFeaturesAreClosedToServiceLoginTokens() throws Exception {
        String auditor = pack.employees().stream().filter(e -> e.grade().equals("ceo")).findFirst().orElseThrow().id();
        MockHttpServletResponse r = call("GET", "/audit-events", token(auditor), null);
        assertThat(r.getStatus()).isEqualTo(403);
        assertThat(problem(r)).isEqualTo("service-login-not-allowed");
        r = call("POST", "/approval-documents/apd_none/approve", token(leader("sales")), Map.of("version", 1));
        assertThat(problem(r)).isEqualTo("service-login-not-allowed");
        // 사람 전용이 아닌 일은 직원 JWT와 같습니다
        assertThat(call("GET", "/approval-documents?box=inbox", token(leader("sales")), null).getStatus())
                .isEqualTo(200);
        // 같은 사람의 데모 로그인 토큰은 사람 전용 기능을 부를 수 있습니다
        assertThat(get("/audit-events", auditor).getStatus()).isEqualTo(200);
    }

    @Test
    void shortSecretStopsStartup() {
        assertThatThrownBy(() -> new ServiceLoginController(null, null, null,
                new AuthProperties("x".repeat(32), 3600, "demo", null, "short"), null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void pathIsOffWithoutSecret() {
        ServiceLoginController off = new ServiceLoginController(null, null, null,
                new AuthProperties("x".repeat(32), 3600, "demo", null, " "), null);
        assertThatThrownBy(() -> off.serviceLogin(SECRET, null))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(404));
    }
}
