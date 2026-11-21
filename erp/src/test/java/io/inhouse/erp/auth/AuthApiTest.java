package io.inhouse.erp.auth;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jwt.JWTClaimsSet;
import io.inhouse.erp.PostgresTestBase;
import java.security.KeyPairGenerator;
import java.security.spec.ECGenParameterSpec;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

@AutoConfigureMockMvc
class AuthApiTest extends PostgresTestBase {

    static final String EMP = "E0010";

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;

    private ResultActions login(String employeeNo, String password) throws Exception {
        return mvc.perform(post("/auth/login").contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(new LoginController.LoginRequest(employeeNo, password))));
    }

    private ResultActions me(String token) throws Exception {
        return mvc.perform(get("/me").header("Authorization", "Bearer " + token));
    }

    private void expect401(ResultActions r) throws Exception {
        r.andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith("application/problem+json"))
                .andExpect(jsonPath("$.type").value("urn:problem:unauthorized"));
    }

    private static JWTClaimsSet.Builder employeeClaims(String sub, Instant exp) {
        return new JWTClaimsSet.Builder().issuer("erp").audience("erp").subject(sub)
                .issueTime(new Date()).expirationTime(Date.from(exp));
    }

    @Test
    void loginIssuesEmployeeJwtThatWorks() throws Exception {
        String body = login(EMP, DEMO_PASSWORD)
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.expiresIn").value(3600))
                .andExpect(jsonPath("$.employee.id").value(EMP))
                .andExpect(jsonPath("$.employee.roles").isArray())
                .andReturn().getResponse().getContentAsString();
        JsonNode json = mapper.readTree(body);
        me(json.get("accessToken").asText()).andExpect(status().isOk()).andExpect(jsonPath("$.id").value(EMP));
    }

    @Test
    void wrongPasswordOrUnknownEmployeeIs401() throws Exception {
        expect401(login(EMP, "wrong-password"));
        expect401(login("E9999", DEMO_PASSWORD));
        expect401(login(null, null));
    }

    @Test
    void badEmployeeJwtIs401() throws Exception {
        Instant later = Instant.now().plusSeconds(600);
        expect401(me(Tokens.hs256(employeeClaims(EMP, Instant.now().minusSeconds(1)).build(), JWT_SECRET)));
        expect401(me(Tokens.hs256(employeeClaims(EMP, later).build(), "another-secret-0123456789abcdef0123")));
        expect401(me(Tokens.hs256(employeeClaims(EMP, later).audience("rag").build(), JWT_SECRET)));
        expect401(me(Tokens.hs256(employeeClaims(EMP, later).issuer("gateway").build(), JWT_SECRET)));
        expect401(me(Tokens.hs256(employeeClaims("E9999", later).build(), JWT_SECRET)));
        expect401(me("not-a-jwt"));
        me(Tokens.hs256(employeeClaims(EMP, later).build(), JWT_SECRET)).andExpect(status().isOk());
    }

    @Test
    void delegationTokenNeedsScope() throws Exception {
        me(Tokens.delegation(EMP, List.of("profile:read"))).andExpect(status().isOk());
        mvc.perform(get("/org/units").header("Authorization", "Bearer " + Tokens.delegation(EMP, List.of("profile:read"))))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith("application/problem+json"))
                .andExpect(jsonPath("$.type").value("urn:problem:scope-missing"));
    }

    @Test
    void badDelegationTokenIs401() throws Exception {
        List<String> s = List.of("profile:read");
        expect401(me(Tokens.delegation(EMP, s, b -> b.expirationTime(Date.from(Instant.now().minusSeconds(10))))));
        expect401(me(Tokens.delegation(EMP, s, b -> b.issuer("erp"))));
        expect401(me(Tokens.delegation(EMP, s, b -> b.audience(List.of("rag", "mcp")))));
        expect401(me(Tokens.delegation("E9999", s)));
        for (String claim : List.of("agt", "cid", "scopes", "iat", "jti")) {
            expect401(me(Tokens.delegation(EMP, s, b -> b.claim(claim, null))));
        }
        expect401(me(Tokens.delegation(EMP, java.util.Arrays.asList("profile:read", null))));
        String good = Tokens.delegation(EMP, s);
        expect401(me(good.substring(0, good.length() - 4) + (good.endsWith("AAAA") ? "BBBB" : "AAAA")));
        KeyPairGenerator g = KeyPairGenerator.getInstance("EC");
        g.initialize(new ECGenParameterSpec("secp256r1"));
        JWTClaimsSet claims = com.nimbusds.jwt.SignedJWT.parse(good).getJWTClaimsSet();
        expect401(me(Tokens.sign(claims, g.generateKeyPair().getPrivate())));
    }

    @Test
    void humanOnlyRejectsDelegationTokenButAllowsEmployee() throws Exception {
        String path = GuardProbeController.PREFIX + "/human-only";
        mvc.perform(get(path).header("Authorization", "Bearer " + Tokens.delegation(EMP, List.of("approval:decide"))))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.type").value("urn:problem:delegation-token-not-allowed"));
        String jwt = Tokens.hs256(employeeClaims(EMP, Instant.now().plusSeconds(60)).build(), JWT_SECRET);
        mvc.perform(get(path).header("Authorization", "Bearer " + jwt)).andExpect(status().isOk());
    }

    @Test
    void pathWithoutScopeIsClosedToDelegationTokens() throws Exception {
        String path = GuardProbeController.PREFIX + "/unmarked";
        mvc.perform(get(path).header("Authorization", "Bearer " + Tokens.delegation(EMP, List.of("profile:read"))))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.type").value("urn:problem:forbidden"));
        String jwt = Tokens.hs256(employeeClaims(EMP, Instant.now().plusSeconds(60)).build(), JWT_SECRET);
        mvc.perform(get(path).header("Authorization", "Bearer " + jwt)).andExpect(status().isOk());
        mvc.perform(get("/health").header("Authorization", "Bearer " + Tokens.delegation(EMP, List.of())))
                .andExpect(status().isOk());
    }

    @Test
    void blankDemoPasswordStopsStartup() {
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> new LoginController(null, null, null,
                        new AuthProperties(JWT_SECRET, 3600, " ", null, null), null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void formScopedRequestScope() throws Exception {
        String narrow = Tokens.delegation(EMP, List.of("approval:request:leave"));
        String wide = Tokens.delegation(EMP, List.of("approval:request"));
        String path = GuardProbeController.PREFIX + "/form/";
        mvc.perform(get(path + "leave").header("Authorization", "Bearer " + narrow)).andExpect(status().isOk());
        mvc.perform(get(path + "expense").header("Authorization", "Bearer " + narrow))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.type").value("urn:problem:scope-missing"));
        mvc.perform(get(path + "expense").header("Authorization", "Bearer " + wide)).andExpect(status().isOk());
    }
}
